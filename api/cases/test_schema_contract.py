"""代表性稳定接口的 JSON Schema 契约校验示例

仅覆盖 3 个稳定接口（登录、商品列表、采购单详情），不做全接口 Schema 覆盖。
采购单详情校验复用采购业务场景中已创建的 AUTO_API_BSPO_ 采购入库单（smoke
套件中业务场景先于本文件执行，fixed_timestamp() 在同一会话返回相同时间戳）。
"""
import allure
import pytest

from api.framework.runner import run_case
from api.framework.assertions import validate_schema
from api.framework.yaml_loader import load_case_pairs


@pytest.mark.smoke
@allure.feature('接口契约校验')
class TestSchemaContract:

    @allure.story('登录接口 Schema')
    def test_login_schema(self, system_login):
        allure.dynamic.title('登录接口响应符合 JSON Schema')
        validate_schema(system_login, './api/schemas/auth/login_response.json')

    @allure.story('商品列表接口 Schema')
    def test_goods_list_schema(self):
        allure.dynamic.title('商品列表接口响应符合 JSON Schema')
        base_info, testcase = load_case_pairs('./api/cases/goods/goods_read.yaml')[0]
        response = run_case(base_info, testcase, yaml_file='./api/cases/goods/goods_read.yaml')
        validate_schema(response, './api/schemas/inventory/goods_list_response.json')

    @allure.story('采购单详情接口 Schema')
    def test_purchase_detail_schema(self):
        """依赖当前会话中采购业务场景已创建 AUTO_API_BSPO_ 采购入库单"""
        allure.dynamic.title('采购单详情接口响应符合 JSON Schema')
        steps = load_case_pairs('./api/cases/scenarios/PurchaseScenario.yml')
        query_step = None
        for base_info, testcase in steps:
            if '查询采购入库单' in base_info['api_name']:
                query_step = (base_info, testcase)
                break
        assert query_step is not None, 'PurchaseScenario.yml 中未找到采购单查询步骤'
        base_info, testcase = query_step
        response = run_case(base_info, testcase, yaml_file='./api/cases/scenarios/PurchaseScenario.yml')
        validate_schema(response, './api/schemas/documents/purchase_detail_response.json')
