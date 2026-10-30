# -*- coding: utf-8 -*-
"""统一 API 执行器：单接口 run_case 与多步骤业务场景 run_scenario

合并旧单接口执行器与多步骤场景执行器的重复能力：
- YAML 模板变量解析（api/framework/template.py）
- HTTP 请求发送（复用 api/framework/http_client.py）
- Token 过期自动重新登录（登录凭据来自 config/settings.py 环境变量，不写死账号密码）
- 响应字段提取，写入会话运行上下文（api/framework/yaml_loader.py）
- 响应与数据库断言（api/framework/assertions.py）

失败信息可定位到：YAML 文件、用例名称、执行步骤、请求地址、失败断言、期望值、实际值、变量来源。
"""
import json
import re
import time
from json.decoder import JSONDecodeError

import allure
import jsonpath
import requests

from shared.debugtalk import DebugTalk
from shared.logger import logs
from api.framework.http_client import (
    SendRequest,
    _mask_response_text,
    _mask_sensitive,
    _response_output,
    _safe_ci_logs,
    _SENSITIVE_KEYS,
)
from config.settings import ERP_PASSWORD, ERP_USERNAME, get_api_url
from api.framework.assertions import Assertions
from api.framework.template import TemplateResolver
from api.framework.yaml_loader import get_run_context

_EXTRACT_PATTERNS = ['(.+?)', '(.*?)', r'(\d+)', r'(\d*)']


def _mask_extract_log(key, value):
    """提取变量日志脱敏：token/password/loginName 等敏感字段只展示 ***，上下文仍保存原值"""
    if str(key).lower() in _SENSITIVE_KEYS:
        return '***'
    return value


class ApiRunner:
    """统一执行器：登录、提取、重试和断言逻辑只维护一份"""

    def __init__(self, context=None):
        self.context = context or get_run_context()
        self.template = TemplateResolver(self.context)
        self.asserts = Assertions()
        self.send = SendRequest()

    # ---------- 对外接口 ----------

    def run_case(self, base_info, testcase, yaml_file=None, step_index=None):
        """执行一条接口用例，返回解析后的响应 JSON"""
        case = dict(testcase)
        base = dict(base_info)
        api_name = base.get('api_name', '')
        url = get_api_url() + base.get('url', '')
        case_name = case.pop('case_name', api_name)
        header = self._context_header(yaml_file, case_name, step_index, url)
        try:
            return self._execute_case(base, case, api_name, url, case_name, yaml_file, step_index)
        except AssertionError:
            raise  # 断言错误已包含完整定位信息
        except Exception as e:
            vars_info = ''
            if self.template.used:
                vars_info = f'\n变量来源: {list(self.template.used)}'
            raise RuntimeError(f'{header}{vars_info}\n执行异常: {e}') from e

    def run_scenario(self, steps, yaml_file=None):
        """顺序执行多步骤业务场景，任一步失败即终止并定位到具体步骤"""
        results = []
        for index, (base_info, testcase) in enumerate(steps, start=1):
            logs.info('--- 场景步骤 %s: %s ---', index, base_info.get('api_name'))
            results.append(self.run_case(base_info, testcase, yaml_file=yaml_file, step_index=index))
        return results

    # ---------- 内部实现 ----------

    def _execute_case(self, base, case, api_name, url, case_name, yaml_file, step_index):
        allure.attach(api_name, '接口名称', allure.attachment_type.TEXT)
        allure.attach(url, '接口地址', allure.attachment_type.TEXT)
        method = base.get('method')
        allure.attach(method, '请求方法', allure.attachment_type.TEXT)
        allure.attach(case_name, '测试用例名称', allure.attachment_type.TEXT)

        # 模板变量记录（失败定位变量来源用）
        self.template.used = []

        if base.get('url') == '/user/login':
            DebugTalk._captcha_data = None

        header = self.template.resolve(base.get('header') or {})
        # 附件仅展示脱敏副本（X-Access-Token 等不写入报告），实际请求不受影响
        allure.attach(str(_mask_sensitive(header)), '请求头信息', allure.attachment_type.TEXT)
        cookies = None
        if base.get('cookies') is not None:
            cookies = json.loads(self.template.resolve(base['cookies']))
        validation = self.template.resolve(case.pop('validation', []))
        extract = self.template.resolve(case.pop('extract', None))
        extract_list = self.template.resolve(case.pop('extract_list', None))
        request_params = {}
        for key in ('params', 'data', 'json'):
            if key in case:
                request_params[key] = self.template.resolve(case[key])

        # 文件上传（当前用例未使用，保留旧能力兼容）
        file_spec = case.pop('files', None)
        files = {fk: open(fv, 'rb') for fk, fv in file_spec.items()} if file_spec else None
        try:
            res = self._send_with_relogin(api_name, url, case_name, method, header, cookies, files, request_params)
        finally:
            if files:
                for f in files.values():
                    f.close()

        status_code = res.status_code
        res_text = res.text
        # 附件仅展示脱敏副本（登录响应含 token），提取与断言仍使用原始文本
        allure.attach(_response_output(res), '接口响应信息', allure.attachment_type.TEXT)
        res_json = self._parse_response(res_text, api_name, url, case_name, method, header, cookies, files,
                                        request_params)

        # 响应字段提取，写入会话运行上下文
        self._extract(extract, extract_list, res_text, case_name)

        # 响应与数据库断言
        ctx = {
            'yaml_file': yaml_file,
            'case_name': case_name,
            'step': step_index,
            'url': url,
            'template_vars': list(self.template.used),
        }
        self.asserts.bind_context(**ctx).assert_result(validation, res_json, status_code)
        return res_json

    def _send_with_relogin(self, api_name, url, case_name, method, header, cookies, files, request_params):
        """发送请求，检测到 Token 过期（loginOut）时重新登录并重试一次"""
        for attempt in range(2):
            res = self.send.run_main(name=api_name, url=url, case_name=case_name, header=header,
                                     method=method, cookies=cookies, file=files, **request_params)
            if res is None:
                raise RuntimeError(f'接口请求失败: {method} {url}')
            if res.text and res.text.strip() == 'loginOut':
                logs.warning(f'【{api_name}】Token 过期（loginOut），重新登录并重试')
                header['X-Access-Token'] = self._relogin()
                continue
            return res
        raise RuntimeError(f'【{api_name}】Token 过期重试后仍然失败: {url}')

    def _parse_response(self, res_text, api_name, url, case_name, method, header, cookies, files, request_params):
        """解析响应 JSON；Token 过期时重新登录后重发一次"""
        try:
            return json.loads(res_text)
        except JSONDecodeError:
            if 'loginOut' in res_text:
                logs.warning(f'【{api_name}】响应包含 loginOut，正在重新登录并重试...')
                header['X-Access-Token'] = self._relogin()
                res = self.send.run_main(name=api_name, url=url, case_name=case_name, header=header,
                                         method=method, cookies=cookies, file=files, **request_params)
                allure.attach(_response_output(res), '接口响应信息', allure.attachment_type.TEXT)
                return json.loads(res.text)
            if _safe_ci_logs():
                raise RuntimeError('接口响应不是合法 JSON，响应内容已隐藏') from None
            raise RuntimeError(f'接口响应不是合法 JSON，响应内容: {res_text[:200]}')

    def _extract(self, extract, extract_list, res_text, case_name):
        if extract is not None:
            self._extract_data(extract, res_text)
        if extract_list is not None:
            self._extract_data_list(extract_list, res_text)

    def _extract_data(self, extract_map, response_text):
        """提取单个变量（支持正则和 JSONPath），写入运行上下文"""
        response_json = None
        for key, value in extract_map.items():
            for pattern in _EXTRACT_PATTERNS:
                if pattern in value:
                    match = re.search(value, response_text)
                    if match is None:
                        continue
                    extracted = int(match.group(1)) if pattern in (r'(\d+)', r'(\d*)') else match.group(1)
                    self.context.set(key, extracted)
                    logs.info('提取变量 %s=%s（正则）', key, _mask_extract_log(key, extracted))
            if '$' in value:
                if response_json is None:
                    response_json = json.loads(response_text)
                values = jsonpath.jsonpath(response_json, value)
                if not values:
                    logs.warning('提取变量 %s 失败（JSONPath: %s），保留上下文原值', key, value)
                    continue
                extracted = values[0]
                self.context.set(key, extracted)
                logs.info('提取变量 %s=%s（JSONPath）', key, _mask_extract_log(key, extracted))

    def _extract_data_list(self, extract_map, response_text):
        """提取多个变量为列表（支持正则和 JSONPath），写入运行上下文"""
        response_json = None
        for key, value in extract_map.items():
            if '(.+?)' in value or '(.*?)' in value:
                matches = re.findall(value, response_text, re.S)
                if matches:
                    self.context.set(key, matches)
                    logs.info('提取列表 %s=%s（正则）', key, _mask_extract_log(key, matches))
            if '$' in value:
                if response_json is None:
                    response_json = json.loads(response_text)
                values = jsonpath.jsonpath(response_json, value)
                if not values:
                    logs.warning('提取列表 %s 失败（JSONPath: %s），保留上下文原值', key, value)
                    continue
                extracted = values
                self.context.set(key, extracted)
                logs.info('提取列表 %s=%s（JSONPath）', key, _mask_extract_log(key, extracted))

    def _relogin(self):
        """Token 过期后重新登录（凭据来自 config/settings.py 环境变量）"""
        if not ERP_USERNAME or not ERP_PASSWORD:
            raise RuntimeError('登录凭据未配置：请通过环境变量 ERP_USERNAME / ERP_PASSWORD 提供测试账号密码，'
                               '不要写入代码或 YAML')
        dt = DebugTalk()
        max_retries = 5
        for attempt in range(max_retries):
            DebugTalk._captcha_data = None
            time.sleep(1)
            try:
                payload = {
                    'loginName': ERP_USERNAME,
                    'password': dt.md5_encryption(ERP_PASSWORD),
                    'code': dt.get_captcha_code(),
                    'uuid': dt.get_captcha_uuid(),
                }
                headers = {'Content-Type': 'application/json;charset=UTF-8'}
                r = requests.post(get_api_url() + '/user/login', json=payload, headers=headers,
                                  verify=False, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    new_token = data.get('data', {}).get('token')
                    if new_token:
                        self.context.set('token', new_token)
                        logs.info('重新登录成功（第%s次）', attempt + 1)
                        return new_token
                    if _safe_ci_logs():
                        logs.warning('登录返回无 token（第%s次），响应内容已隐藏', attempt + 1)
                    else:
                        logs.warning('登录返回无 token（第%s次）: %s', attempt + 1, _mask_sensitive(data))
                else:
                    logs.warning('登录状态码异常（第%s次）: %s', attempt + 1, r.status_code)
            except Exception as e:
                logs.warning('登录异常（第%s次）: %s', attempt + 1, e)
        raise RuntimeError(f'重新登录失败，已重试{max_retries}次')

    @staticmethod
    def _context_header(yaml_file, case_name, step_index, url):
        lines = []
        if yaml_file:
            lines.append(f'YAML 文件: {yaml_file}')
        if case_name:
            lines.append(f'用例名称: {case_name}')
        if step_index:
            lines.append(f'执行步骤: 第 {step_index} 步')
        if url:
            lines.append(f'请求地址: {url}')
        return '\n'.join(lines)


_runner = None


def get_runner():
    """获取当前会话的统一执行器（与运行上下文同为会话内单例）"""
    global _runner
    if _runner is None:
        _runner = ApiRunner(get_run_context())
    return _runner


def run_case(base_info, testcase, yaml_file=None, step_index=None):
    """执行一条接口用例"""
    return get_runner().run_case(base_info, testcase, yaml_file=yaml_file, step_index=step_index)


def run_scenario(steps, yaml_file=None):
    """顺序执行多步骤业务场景"""
    return get_runner().run_scenario(steps, yaml_file=yaml_file)


def run_scenario_file(yaml_file):
    """加载业务场景 YAML 并顺序执行全部步骤"""
    from api.framework.yaml_loader import load_case_pairs
    steps = load_case_pairs(yaml_file)
    return get_runner().run_scenario(steps, yaml_file=yaml_file)
