import json
import os
import allure
import pytest
import requests
import urllib3
import time

from config.settings import API_TIMEOUT
from shared.logger import logs
from requests import utils
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# 日志/Allure 附件脱敏：命中以下字段名的值一律不展示真实内容
_SENSITIVE_KEYS = ('loginname', 'password', 'token', 'x-access-token')


def _safe_ci_logs():
    """只读冒烟 CI 开关：隐藏响应和请求值，本地默认日志与 Allure 行为不变。"""
    return os.getenv('ERP_SAFE_CI_LOGS', '').lower() == 'true'


def _mask_sensitive(data, mask='***'):
    """递归脱敏敏感字段（loginName/password/token/X-Access-Token 等）

    只影响日志与 Allure 附件的展示副本，不影响实际请求内容。
    """
    if isinstance(data, dict):
        return {
            key: (mask if str(key).lower() in _SENSITIVE_KEYS else _mask_sensitive(value))
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [_mask_sensitive(item) for item in data]
    return data


def _mask_response_text(text):
    """脱敏响应 JSON 文本中的敏感字段（登录响应包含 token），非 JSON 原样返回"""
    if not text:
        return text
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return text
    return json.dumps(_mask_sensitive(data), ensure_ascii=False)


def _response_output(response):
    """返回适合日志/Allure 的响应文本；CI 安全模式只保留 HTTP 状态码。"""
    if _safe_ci_logs():
        return f'HTTP status={response.status_code}，响应内容已隐藏'
    return _mask_response_text(response.text) if response.text else str(response)


def _request_output(kwargs):
    """CI 安全模式不展示请求值或字段名。"""
    if not _safe_ci_logs():
        return json.dumps(_mask_sensitive(kwargs), ensure_ascii=False)
    return '请求参数已隐藏'


class SendRequest:
    """发送接口请求，暂时只写了get和post方法的请求"""

    def __init__(self, cookie=None):
        self.cookie = cookie

    @staticmethod
    def _write_context(values):
        """运行期数据写入当前会话运行上下文，不再写全局 extract.yaml"""
        from api.framework.yaml_loader import get_run_context
        get_run_context().update(values)

    def get(self, url, data, header):
        """
        :param url: 接口地址
        :param data: 请求参数
        :param header: 请求头
        :return:
        """
        requests.packages.urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            if data is None:
                response = requests.get(url, headers=header, cookies=self.cookie, verify=False)
            else:
                response = requests.get(url, data, headers=header, cookies=self.cookie, verify=False)
        except requests.RequestException as e:
            logs.error(e)
            return None
        except Exception as e:
            logs.error(e)
            return None
        # 响应时间/毫秒
        res_ms = response.elapsed.microseconds / 1000
        # 响应时间/秒
        res_second = response.elapsed.total_seconds()
        response_dict = dict()

        # 接口响应状态码
        response_dict['code'] = response.status_code
        # 接口响应文本
        response_dict['text'] = response.text
        try:
            response_dict['body'] = response.json().get('body')
        except Exception:
            response_dict['body'] = ''
        response_dict['res_ms'] = res_ms
        response_dict['res_second'] = res_second
        return response_dict

    def post(self, url, data, header):
        """
        :param url:
        :param data: verify=False忽略SSL证书验证
        :param header:
        :return:
        """
        # 控制台输出InsecureRequestWarning错误
        requests.packages.urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        try:
            if data is None:
                response = requests.post(url, header, cookies=self.cookie, verify=False)
            else:
                response = requests.post(url, data, headers=header, cookies=self.cookie, verify=False)
        except requests.RequestException as e:
            logs.error(e)
            return None
        except Exception as e:
            logs.error(e)
            return None
        # 响应时间/毫秒
        res_ms = response.elapsed.microseconds / 1000
        # 响应时间/秒
        res_second = response.elapsed.total_seconds()
        response_dict = dict()
        # 接口响应状态码
        response_dict['code'] = response.status_code
        # 接口响应文本
        response_dict['text'] = response.text
        try:
            response_dict['body'] = response.json().get('body')
        except Exception:
            response_dict['body'] = ''
        response_dict['res_ms'] = res_ms
        response_dict['res_second'] = res_second
        return response_dict

    def _relogin(self):
        """重新登录获取新token（登录凭据从 config/settings.py 环境变量读取）"""
        from config.settings import ERP_USERNAME, ERP_PASSWORD, get_api_url
        from shared.debugtalk import DebugTalk
        if not ERP_USERNAME or not ERP_PASSWORD:
            logs.error('登录凭据未配置：请通过环境变量 ERP_USERNAME / ERP_PASSWORD 提供测试账号密码')
            return None
        host = get_api_url()
        dt = DebugTalk()
        for attempt in range(5):
            DebugTalk._captcha_data = None
            time.sleep(1)
            try:
                payload = {
                    'loginName': ERP_USERNAME,
                    'password': dt.md5_encryption(ERP_PASSWORD),
                    'code': dt.get_captcha_code(),
                    'uuid': dt.get_captcha_uuid()
                }
                headers = {'Content-Type': 'application/json;charset=UTF-8'}
                r = requests.post(host + '/user/login', json=payload, headers=headers, verify=False, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    new_token = data.get('data', {}).get('token')
                    if new_token:
                        self._write_context({'token': new_token})
                        logs.info('[send_request] 重新登录成功，新token已写入运行上下文，不在日志中展示')
                        return new_token
            except Exception as e:
                logs.warning(f'[send_request] 登录异常 (第{attempt+1}次): {e}')
        return None

    def send_request(self, **kwargs):

        session = requests.session()
        result = None
        cookie = {}
        try:
            result = session.request(**kwargs)
            set_cookie = requests.utils.dict_from_cookiejar(result.cookies)
            if set_cookie:
                cookie['Cookie'] = set_cookie
                self._write_context(cookie)
                if not _safe_ci_logs():
                    logs.info("cookie：%s" % {k: '***' for k in cookie})
            logs.info("接口返回信息：%s", _response_output(result))

            # 自动重新登录：检测到loginOut时循环重试（最多3次）
            max_relogin_retries = 3
            for rl_attempt in range(max_relogin_retries):
                if result and result.text and result.text.strip() == 'loginOut':
                    logs.warning(f'[send_request] 检测到loginOut，正在重新登录并重试 (第{rl_attempt+1}次)...')
                    new_token = self._relogin()
                    if new_token:
                        if 'headers' in kwargs:
                            kwargs['headers']['X-Access-Token'] = new_token
                        result = session.request(**kwargs)
                        logs.info("接口返回信息(重试)：%s", _response_output(result))
                    else:
                        break
                else:
                    break

        except requests.exceptions.ConnectionError:
            logs.error("ConnectionError--连接异常")
            pytest.fail("接口请求异常，可能是request的连接数过多或请求速度过快导致程序报错！")
        except requests.exceptions.HTTPError:
            logs.error("HTTPError--http异常")
        except requests.exceptions.RequestException as e:
            logs.error(e)
            pytest.fail("请求异常，请检查系统或数据是否正常！")
        return result

    def run_main(self, name, url, case_name, header, method, cookies=None, file=None, **kwargs):
        """
        接口请求
        :param name: 接口名
        :param url: 接口地址
        :param case_name: 测试用例
        :param header:请求头
        :param method:请求方法
        :param cookies：默认为空
        :param file: 上传文件接口
        :param kwargs: 请求参数，根据yaml文件的参数类型
        :return:
        """

        try:
            # 收集报告日志
            logs.info('接口名称：%s' % name)
            logs.info('请求地址：%s' % url)
            logs.info('请求方式：%s' % method)
            logs.info('测试用例名称：%s' % case_name)
            if not _safe_ci_logs():
                logs.info('请求头：%s' % _mask_sensitive(header))
                logs.info('Cookie：%s' % ({k: '***' for k in cookies} if cookies else cookies))
            req_params = _request_output(kwargs)
            log_params = req_params if _safe_ci_logs() else _mask_sensitive(kwargs)
            if "data" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s", log_params)
            elif "json" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s", log_params)
            elif "params" in kwargs.keys():
                allure.attach(req_params, '请求参数', allure.attachment_type.TEXT)
                logs.info("请求参数：%s", log_params)
        except Exception as e:
            logs.error(e)
        # time.sleep(0.5)
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
        response = self.send_request(method=method,
                                     url=url,
                                     headers=header,
                                     cookies=cookies,
                                     files=file,
                                     timeout=API_TIMEOUT,
                                     verify=False,
                                     **kwargs)
        return response
