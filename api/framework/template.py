# -*- coding: utf-8 -*-
"""模板变量解析：解析 YAML 中的 ${function(args)} 动态表达式

- 表达式函数来自 shared/debugtalk.py（DebugTalk）
- get_extract_data() 优先读取当前会话运行上下文，缺失时兼容旧 extract.yaml
- 循环、复杂计算、签名、业务校验等逻辑由 Python 实现，不进入 YAML
- 记录本次解析使用过的表达式，供失败时定位变量来源
"""
import re

from shared.debugtalk import DebugTalk

_EXPR_PATTERN = re.compile(r'\$\{([^}]*)\}')

# 失败定位信息脱敏：命中以下字段名的提取变量值不展示真实内容
_SENSITIVE_KEYS = ('token', 'password', 'loginname', 'x-access-token')
# 直接返回凭据的模板函数，解析值一律不进入失败定位信息
_SENSITIVE_FUNCS = (
    'get_login_name',
    'get_login_password',
    'get_captcha_code',
    'get_captcha_uuid',
)


class TemplateResolver:
    """解析 ${function(args)} 表达式，支持 str / dict / list 递归"""

    def __init__(self, context=None):
        self._dt = DebugTalk()
        self._context = context
        # 本次解析使用过的表达式，格式: (表达式, 解析结果截断值)
        self.used = []

    def resolve(self, data):
        """递归解析模板，返回解析后的数据（不修改原数据）"""
        if isinstance(data, str):
            return self._resolve_string(data)
        if isinstance(data, dict):
            return {key: self.resolve(value) for key, value in data.items()}
        if isinstance(data, list):
            return [self.resolve(item) for item in data]
        return data

    def _resolve_string(self, text):
        """替换字符串中的全部 ${function(args)} 表达式"""
        if '${' not in text:
            return text
        result = text
        while '${' in result:
            match = _EXPR_PATTERN.search(result)
            if not match:
                break
            expression = match.group(1)
            value = self._call_expression(expression)
            self.used.append((expression, self._display_value(expression, value)))
            result = result[:match.start()] + str(value) + result[match.end():]
        return result

    @staticmethod
    def _display_value(expression, value):
        """记录变量来源时脱敏敏感值：token/password 等不写入失败定位信息和报告附件

        只影响展示副本，不影响 self.used 之外的任何逻辑。
        """
        func_name = expression.split('(')[0]
        if func_name in _SENSITIVE_FUNCS:
            return '***'
        if func_name == 'get_extract_data':
            arg = expression[expression.index('(') + 1:expression.index(')')].strip()
            if arg.lower() in _SENSITIVE_KEYS:
                return '***'
        return str(value)[:40]

    def _call_expression(self, expression):
        """执行一个表达式，返回解析后的值"""
        func_name = expression[:expression.index('(')]
        args_text = expression[expression.index('(') + 1:expression.index(')')]
        args = [a.strip() for a in args_text.split(',')] if args_text else []
        value = getattr(self._dt, func_name)(*args)
        if isinstance(value, list):
            value = ','.join(str(item) for item in value)
        return value
