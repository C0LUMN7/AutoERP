# -*- coding: utf-8 -*-
"""销售管理页面对象

定位器来自云端 jshERP 销售页面真实 DOM 与只读式页面资料收集：
销售管理 > 销售订单，前端路由 /bill/sale_order；
销售管理 > 销售出库，前端路由 /bill/sale_out。
"""
import json

from playwright.sync_api import expect

from config.settings import BUSINESS_IDS, ERP_UI_URL
from ui.pages.base_page import BasePage


class SalesPage(BasePage):
    """销售页面：销售订单新增、审核并转未审核销售出库"""

    SALES_ORDER_ROUTE = "/bill/sale_order"
    SALES_OUT_ROUTE = "/bill/sale_out"
    CUSTOMER_NAME = "自动化测试专用客户"
    WAREHOUSE_NAME = "自动化测试专属仓库3"
    SETTLEMENT_ACCOUNT_NAME = "自动化测试专用结算账户"
    PRODUCT_NAME = "请购单测试商品C"
    QUANTITY = "1"
    UNIT_PRICE = "70"

    def open_sales_order(self) -> None:
        """进入销售订单列表页"""
        self._push_route(self.SALES_ORDER_ROUTE)
        expect(self.page.get_by_role("button", name="新增")).to_be_visible(timeout=15000)

    def create_unapproved_order(self, order_no: str, record_document_id=None) -> dict:
        """新增销售订单并保存为未审核状态"""
        self.open_sales_order()
        with self.page.expect_response(
            lambda response: "/sequence/buildNumber" in response.url
            and response.request.method == "GET",
            timeout=15000,
        ) as number_response_info:
            self.page.get_by_role("button", name="新增").click()
        number_response = number_response_info.value
        if number_response.status != 200:
            raise RuntimeError(
                f"销售订单自动编号请求失败: HTTP {number_response.status}"
            )
        number_response_data = number_response.json()
        if number_response_data.get("code") != 200:
            raise RuntimeError(f"销售订单自动编号请求失败: {number_response_data}")

        self._close_intro()
        expect(self.page.get_by_text("客户").last).to_be_visible(timeout=10000)

        self._select_ant_option("请选择客户", self.CUSTOMER_NAME)
        self._select_ant_option("输入条码或名称", self.PRODUCT_NAME)
        self._overwrite_input(self.page.locator("[id^='operNumber_']").first, self.QUANTITY)
        self._overwrite_input(self.page.locator("[id^='unitPrice_']").first, self.UNIT_PRICE)

        number_input = self.page.locator("#number")
        number_input.fill(order_no)
        expect(number_input).to_have_value(order_no, timeout=5000)

        with self.page.expect_response(
            lambda response: "/depotHead/addDepotHeadAndDetail" in response.url
            and response.request.method == "POST",
            timeout=15000,
        ) as save_response_info:
            self.page.get_by_role("button", name="保存（Ctrl+S）").click()
        save_response = save_response_info.value
        request_info = self._request_info(save_response.request.post_data_json)
        actual_order_no = request_info.get("number")

        if save_response.status != 200:
            raise RuntimeError(f"销售订单保存失败: HTTP {save_response.status}")
        response_data = save_response.json()
        if response_data.get("code") != 200:
            raise RuntimeError(f"销售订单保存失败: {response_data}")
        if not actual_order_no:
            raise RuntimeError("销售订单保存请求缺少实际单号，无法安全定位已创建单据")

        self.open_sales_order()
        self.page.get_by_placeholder("请输入单据编号").first.fill(actual_order_no)
        query_response = self._query_list_response(actual_order_no)
        document = self._exact_document(query_response, actual_order_no)
        if record_document_id:
            record_document_id(int(document["id"]))
        if actual_order_no != order_no:
            raise RuntimeError(
                f"销售订单实际提交单号与预期不一致: expected={order_no}, "
                f"actual={actual_order_no}, document_id={document['id']}"
            )

        row = self.page.locator(".ant-table-tbody tr").filter(
            has_text=actual_order_no
        ).first
        expect(row).to_be_visible(timeout=15000)
        return document

    def assert_order_unapproved(self, order_no: str) -> None:
        """按单号查询并断言销售订单为未审核"""
        self.assert_order_status(order_no, "未审核")

    def audit_order(self, order_no: str) -> None:
        """审核销售订单，并断言状态变为已审核"""
        self._select_order(order_no)
        self._click_toolbar_button("审核")
        self._confirm_operation()
        self.assert_order_status(order_no, "已审核")

    def reverse_audit_order(self, order_no: str) -> None:
        """反审核销售订单，并断言状态恢复为未审核"""
        self._select_order(order_no)
        self._click_toolbar_button("反审核")
        self._confirm_operation()
        self.assert_order_status(order_no, "未审核")

    def transfer_to_sales_out(
        self, order_no: str, requested_outbound_no: str, record_document_id=None
    ) -> dict:
        """转销售出库，并返回系统实际生成编号对应的列表响应记录。"""
        self._select_order(order_no)
        self._click_toolbar_button("转销售出库")
        dialog = self._transfer_dialog("转销售出库")
        dialog.locator("#number").fill(requested_outbound_no)
        self._select_dialog_warehouse(dialog)
        self._select_dialog_settlement_account(dialog)
        self._overwrite_input(dialog.locator("#changeAmount"), "0")
        with self.page.expect_response(
            lambda response: "/depotHead/addDepotHeadAndDetail" in response.url
            and response.request.method == "POST",
            timeout=15000,
        ) as response_info:
            dialog.get_by_role("button", name="保存（Ctrl+S）").click()
        save_response = response_info.value
        response_data = save_response.json()
        if response_data.get("code") != 200:
            raise RuntimeError(f"销售出库转单保存失败: {response_data}")

        request_payload = save_response.request.post_data_json
        request_info = self._request_info(request_payload)
        actual_outbound_no = request_info.get("number")
        if not actual_outbound_no or request_info.get("linkNumber") != order_no:
            raise RuntimeError(
                f"销售出库转单响应对应请求不完整: number={actual_outbound_no}, "
                f"linkNumber={request_info.get('linkNumber')}"
            )

        expect(dialog).to_be_hidden(timeout=15000)
        document = self.assert_sales_out_status(
            actual_outbound_no, "未审核", record_document_id
        )
        request_rows = self._request_rows(request_payload)
        expected_depot_id = str(BUSINESS_IDS["depot_id"])
        actual_depot_ids = [str(row.get("depotId")) for row in request_rows]
        if not request_rows or any(
            depot_id != expected_depot_id for depot_id in actual_depot_ids
        ):
            raise RuntimeError(
                "销售出库转单明细仓库不一致，已阻止后续审核: "
                f"number={actual_outbound_no}, document_id={document['id']}, "
                f"expected_depot_id={expected_depot_id}, "
                f"actual_depot_ids={actual_depot_ids}"
            )
        self.assert_order_status(order_no, "完成销售")
        return document

    def assert_sales_out_unapproved(self, outbound_no: str) -> dict:
        """按单号查询并断言销售出库单为未审核"""
        return self.assert_sales_out_status(outbound_no, "未审核")

    def audit_sales_out(self, outbound_no: str) -> str:
        """审核销售出库单，并断言状态变为已审核"""
        self._select_sales_out(outbound_no)
        self._click_toolbar_button("审核")
        self._confirm_operation()
        self.assert_sales_out_status(outbound_no, "已审核")
        return outbound_no

    def assert_sales_out_status(
        self, outbound_no: str, status: str, record_document_id=None
    ) -> dict:
        """按单号查询并断言销售出库单状态"""
        row, document = self._query_sales_out(outbound_no, record_document_id)
        expect(row).to_contain_text(self.CUSTOMER_NAME)
        expect(row).to_contain_text(self.PRODUCT_NAME)
        expect(row).to_contain_text(status)
        return document

    def assert_order_status(self, order_no: str, status: str) -> None:
        """按单号查询并断言销售订单状态"""
        row, _ = self._query_order(order_no)
        expect(row).to_contain_text(self.CUSTOMER_NAME)
        expect(row).to_contain_text(self.PRODUCT_NAME)
        expect(row).to_contain_text(status)

    def _query_order(self, order_no: str, record_document_id=None):
        self.open_sales_order()
        self.page.get_by_placeholder("请输入单据编号").first.fill(order_no)
        response = self._query_list_response(order_no)
        document = self._exact_document(response, order_no)
        if record_document_id:
            record_document_id(int(document["id"]))
        row = self.page.locator(".ant-table-tbody tr").filter(has_text=order_no).first
        expect(row).to_be_visible(timeout=15000)
        return row, document

    def _query_sales_out(self, outbound_no: str, record_document_id=None):
        self._push_route(self.SALES_OUT_ROUTE)
        expect(self.page.get_by_role("button", name="新增")).to_be_visible(timeout=15000)
        self.page.get_by_placeholder("请输入单据编号").first.fill(outbound_no)
        response = self._query_list_response(outbound_no)
        document = self._exact_document(response, outbound_no)
        if record_document_id:
            record_document_id(int(document["id"]))
        row = self.page.locator(".ant-table-tbody tr").filter(has_text=outbound_no).first
        expect(row).to_be_visible(timeout=15000)
        return row, document

    def _select_order(self, order_no: str) -> None:
        row, _ = self._query_order(order_no)
        checkbox = row.locator(".ant-checkbox-input").first
        if not checkbox.is_checked():
            checkbox.click()

    def _select_sales_out(self, outbound_no: str) -> None:
        row, _ = self._query_sales_out(outbound_no)
        checkbox = row.locator(".ant-checkbox-input").first
        if not checkbox.is_checked():
            checkbox.click()

    def _click_toolbar_button(self, name: str) -> None:
        buttons = self.page.locator("button:visible")
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if button.inner_text().strip() == name:
                button.click()
                return
        raise RuntimeError(f"未找到工具栏按钮: {name}")

    def _confirm_operation(self) -> None:
        confirm = self.page.locator(".ant-modal:visible").filter(has_text="确认操作").first
        expect(confirm).to_be_visible(timeout=10000)
        confirm.get_by_role("button", name="确 定").click()

    def _transfer_dialog(self, title: str):
        dialog = self.page.get_by_role("dialog").filter(has_text=title).first
        expect(dialog).to_be_visible(timeout=10000)
        self._close_intro()
        return dialog

    def _select_dialog_warehouse(self, dialog) -> None:
        warehouse_header = dialog.locator(".thead .td").filter(
            has_text="仓库名称"
        ).first
        batch_switch = warehouse_header.locator(".anticon-down").first
        expect(batch_switch).to_be_visible(timeout=10000)
        batch_switch.click()

        batch_dialog = self.page.get_by_role(
            "dialog", name="批量切换仓库", exact=True
        )
        expect(batch_dialog).to_be_visible(timeout=10000)
        warehouse_select = batch_dialog.locator("#batchSetDepot").get_by_role(
            "combobox"
        )
        expect(warehouse_select).to_be_visible(timeout=10000)
        warehouse_select.click(force=True)
        self.page.keyboard.type(self.WAREHOUSE_NAME)
        option = self.page.locator(
            ".ant-select-dropdown:visible .ant-select-dropdown-menu-item"
        ).filter(has_text=self.WAREHOUSE_NAME).first
        expect(option).to_be_visible(timeout=10000)
        option.click()

        expected_depot_id = str(BUSINESS_IDS["depot_id"])
        with self.page.expect_response(
            lambda response: "/material/getMaterialByBarCode?" in response.url
            and f"depotId={expected_depot_id}" in response.url
            and response.request.method == "GET",
            timeout=15000,
        ):
            batch_dialog.get_by_role("button", name="确 定").click()
        expect(batch_dialog).to_be_hidden(timeout=10000)

        selected_depots = dialog.locator(
            "[id^='depotId_'] .ant-select-selection-selected-value"
        )
        if selected_depots.count() == 0:
            raise RuntimeError("销售出库转单未找到商品明细仓库控件")
        for index in range(selected_depots.count()):
            expect(selected_depots.nth(index)).to_have_attribute(
                "title", self.WAREHOUSE_NAME, timeout=10000
            )

    def _select_dialog_settlement_account(self, dialog) -> None:
        account = dialog.locator("#accountId")
        expect(account).to_be_visible(timeout=10000)
        account.get_by_role("combobox").click(force=True)
        option = self.page.locator(
            ".ant-select-dropdown:visible .ant-select-dropdown-menu-item"
        ).filter(has_text=self.SETTLEMENT_ACCOUNT_NAME).first
        expect(option).to_be_visible(timeout=10000)
        option.click()

        selected = account.locator(".ant-select-selection-selected-value")
        expect(selected).to_have_attribute(
            "title", self.SETTLEMENT_ACCOUNT_NAME, timeout=5000
        )
        expect(selected).to_contain_text(
            self.SETTLEMENT_ACCOUNT_NAME, timeout=5000
        )

    def _push_route(self, route: str) -> None:
        if self.page.url == "about:blank":
            self.page.goto(ERP_UI_URL.rstrip("/") + "/")
            self.page.wait_for_load_state("domcontentloaded")
            self.page.wait_for_timeout(1200)
        self.page.evaluate(
            """async (path) => {
                const root = document.querySelector('#app') || document.querySelector('#root');
                const router = (window.app && window.app.$router)
                    || (root && root.__vue__ && root.__vue__.$router);
                if (!router) throw new Error('Vue router not found');
                await router.push(path);
            }""",
            route,
        )
        self.page.wait_for_timeout(1200)
        self._close_intro()

    def _select_ant_option(self, placeholder: str, option_text: str) -> None:
        self.page.get_by_text(placeholder).last.click()
        self.page.keyboard.type(option_text)
        option = self.page.locator(
            ".ant-select-dropdown:visible .ant-select-dropdown-menu-item"
        ).filter(has_text=option_text).first
        expect(option).to_be_visible(timeout=10000)
        option.click()

    def _overwrite_input(self, locator, value: str) -> None:
        expect(locator).to_be_visible(timeout=10000)
        locator.fill(value)
        expect(locator).to_have_value(value, timeout=5000)

    def _close_intro(self) -> None:
        skip = self.page.locator(".introjs-skipbutton")
        if skip.count():
            try:
                skip.first.click(timeout=1000)
            except Exception:
                pass

    def _wait_saved_row(self, order_no: str) -> None:
        row = self.page.locator(".ant-table-tbody tr").filter(has_text=order_no).first
        expect(row).to_be_visible(timeout=15000)

    def _query_list_response(self, number: str) -> dict:
        with self.page.expect_response(
            lambda response: "/depotHead/list?" in response.url
            and number in response.url
            and response.request.method == "GET",
            timeout=15000,
        ) as response_info:
            self.page.get_by_role("button", name="查 询").click()
        response_data = response_info.value.json()
        if response_data.get("code") != 200:
            raise RuntimeError(f"单据列表查询失败: {response_data}")
        return response_data

    @staticmethod
    def _exact_document(response_data: dict, number: str) -> dict:
        rows = (response_data.get("data") or {}).get("rows") or []
        matches = [row for row in rows if row.get("number") == number]
        if len(matches) != 1 or not matches[0].get("id"):
            raise RuntimeError(f"未从单据列表响应唯一定位单据: number={number}")
        return matches[0]

    @staticmethod
    def _request_info(payload) -> dict:
        if isinstance(payload, str):
            payload = json.loads(payload)
        info = payload.get("info") if isinstance(payload, dict) else None
        if isinstance(info, str):
            info = json.loads(info)
        return info if isinstance(info, dict) else {}

    @staticmethod
    def _request_rows(payload) -> list:
        if isinstance(payload, str):
            payload = json.loads(payload)
        rows = payload.get("rows") if isinstance(payload, dict) else None
        if isinstance(rows, str):
            rows = json.loads(rows)
        return rows if isinstance(rows, list) else []
