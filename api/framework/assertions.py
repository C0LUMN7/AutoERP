# -*- coding: utf-8 -*-
"""响应与数据库断言

支持既有 YAML 断言类型：
- contains: 响应字段包含断言（支持 status_code）
- eq / ne: 响应相等 / 不相等断言
- rv: 响应任意值断言
- db: 数据库查询结果非空断言
- db_eq: 数据库查询结果与期望值比较断言

失败时抛出 AssertionError，信息包含：YAML 文件、用例名称、执行步骤、
请求地址、失败断言、期望值、实际值和变量来源。
"""
import json
import os

import allure
import jsonpath

from shared.database import ConnectMysql
from shared.logger import logs
from api.framework.http_client import _safe_ci_logs


def _actual_output(value):
    """CI 安全模式不展示断言实际值，避免失败 traceback 泄露业务响应。"""
    if _safe_ci_logs():
        return f'<{type(value).__name__}，实际值已隐藏>'
    return repr(value)


class Assertions:
    """响应与数据库断言，失败信息可精确定位到用例和断言项"""

    def __init__(self):
        self._ctx = {}

    def bind_context(self, **kwargs):
        """绑定定位上下文：yaml_file / case_name / step / url / template_vars"""
        self._ctx.update(kwargs)
        return self

    def assert_result(self, validation, response, status_code):
        """执行 YAML validation 列表，收集全部失败后统一抛出"""
        failures = []
        for assertion in validation:
            for key, value in assertion.items():
                try:
                    self._check(key, value, response, status_code)
                except AssertionError as e:
                    failures.append(str(e))
        if failures:
            self._attach_failure(failures)
            raise AssertionError(self._format_failure(failures))

    def _check(self, key, value, response, status_code):
        if key == 'contains':
            self._check_contains(value, response, status_code)
        elif key == 'eq':
            self._check_eq(value, response, 'eq')
        elif key == 'ne':
            self._check_eq(value, response, 'ne')
        elif key == 'rv':
            self._check_rv(value, response)
        elif key == 'db':
            self._check_db(value)
        elif key == 'db_eq':
            self._check_db_eq(value)
        else:
            raise AssertionError(f'不支持的断言类型: {key}')

    # ---------- 响应断言 ----------

    def _check_contains(self, value, response, status_code):
        failures = []
        for key, expected in value.items():
            if key == 'status_code':
                if expected != status_code:
                    failures.append(f'状态码断言: 期望 {expected}，实际 {status_code}')
                continue
            resp_list = jsonpath.jsonpath(response, '$..%s' % key)
            if not resp_list:
                failures.append(f'响应中未找到字段 {key}')
                continue
            if isinstance(resp_list[0], str):
                resp_list = ''.join(resp_list)
            if isinstance(expected, str) and expected.upper() == 'NONE':
                expected = None
            if expected not in resp_list:
                failures.append(f'字段 {key} 期望包含 {expected!r}，实际 {_actual_output(resp_list)}')
        if failures:
            raise AssertionError('；'.join(failures))

    def _check_eq(self, expected, response, mode):
        """eq: 期望的每个字段与实际相等；ne: 期望的每个字段与实际不相等"""
        failures = []
        for key, expected_value in expected.items():
            if key not in response:
                failures.append(f'响应中未找到字段 {key}')
                continue
            actual_value = response[key]
            equal = actual_value == expected_value
            if mode == 'eq' and not equal:
                failures.append(f'字段 {key} 期望 {expected_value!r}，实际 {_actual_output(actual_value)}')
            if mode == 'ne' and equal:
                failures.append(f'字段 {key} 不应等于 {expected_value!r}，实际 {_actual_output(actual_value)}')
        if failures:
            raise AssertionError('；'.join(failures))

    def _check_rv(self, expected, response):
        key = list(expected.keys())[0]
        if key not in response:
            raise AssertionError(f'响应中未找到字段 {key}')
        if response[key] != list(expected.values())[0]:
            raise AssertionError(f'字段 {key} 期望 {expected[key]!r}，实际 {_actual_output(response[key])}')

    # ---------- 数据库断言 ----------

    def _check_db(self, sql):
        conn = ConnectMysql()
        try:
            rows = conn.query_all(sql)
        finally:
            conn.close()
        if not rows:
            raise AssertionError(f'数据库断言失败，SQL 查询结果为空: {sql}')
        logs.info('数据库断言成功')

    def _check_db_eq(self, value):
        sql = value.get('sql')
        expect = value.get('expect')
        if not sql:
            raise AssertionError('db_eq 断言缺少 sql 字段')
        conn = ConnectMysql()
        try:
            rows = conn.query_all(sql)
        finally:
            conn.close()
        if not rows or len(rows[0]) == 0:
            raise AssertionError(f'db_eq 断言失败，SQL 查询结果为空: {sql}，期望值 {expect!r}')
        actual = rows[0][0]
        if actual != expect:
            raise AssertionError(f'db_eq 断言失败: 期望值 {expect!r}，实际值 {actual!r}，SQL: {sql}')
        logs.info(f'db_eq 断言成功: 期望值 {expect!r}，实际值 {actual!r}')

    # ---------- 失败信息 ----------

    def _attach_failure(self, failures):
        message = '\n'.join(failures)
        allure.attach(message, '断言失败详情', allure.attachment_type.TEXT)
        logs.error('断言失败: %s' % message)

    def _format_failure(self, failures):
        lines = []
        ctx = self._ctx
        if ctx.get('yaml_file'):
            lines.append(f'YAML 文件: {ctx["yaml_file"]}')
        if ctx.get('case_name'):
            lines.append(f'用例名称: {ctx["case_name"]}')
        if ctx.get('step'):
            lines.append(f'执行步骤: 第 {ctx["step"]} 步')
        if ctx.get('url'):
            lines.append(f'请求地址: {ctx["url"]}')
        if ctx.get('template_vars'):
            lines.append(f'变量来源: {ctx["template_vars"]}')
        lines.append('失败断言:')
        lines.extend('  - %s' % f for f in failures)
        return '\n'.join(lines)


def validate_schema(response, schema_file):
    """校验接口响应是否符合 JSON Schema 契约，失败抛出带定位信息的 AssertionError"""
    import jsonschema
    with open(schema_file, 'r', encoding='utf-8') as f:
        schema = json.load(f)
    try:
        jsonschema.validate(response, schema)
    except jsonschema.ValidationError as e:
        path = '.'.join(str(p) for p in e.absolute_path) or '(根节点)'
        if _safe_ci_logs():
            detail = e.message if e.validator == 'required' else f'实际类型 {type(e.instance).__name__}'
            raise AssertionError(
                f'Schema 契约校验失败: {os.path.basename(schema_file)}，'
                f'字段 {path} 不符合约束 {e.validator}: {detail}，实际值已隐藏'
            ) from None
        raise AssertionError(
            f'Schema 契约校验失败: {os.path.basename(schema_file)}，'
            f'字段 {path} 不符合约束 {e.validator}: {e.message}，实际 {e.instance!r}'
        ) from e
