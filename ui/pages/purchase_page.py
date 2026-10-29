# -*- coding: utf-8 -*-
"""采购管理页面对象

定位器来自云端 jshERP 采购页面真实 DOM 与只读式页面资料收集：
采购管理 > 采购订单，前端路由 /bill/purchase_order；
采购管理 > 采购入库，前端路由 /bill/purchase_in。
"""
import json

from playwright.sync_api import expect

from config.settings import ERP_UI_URL
from ui.pages.base_page import BasePage


class PurchasePage(BasePage):
    """采购页面：采购订单新增、审核并转未审核采购入库"""

    PURCHASE_ORDER_ROUTE = "/bill/purchase_order"
    PURCHASE_IN_ROUTE = "/bill/purchase_in"
    SUPPLIER_NAME = "自动化测试专用供应商"
    WAREHOUSE_NAME = "自动化测试专属仓库3"
    PRODUCT_NAME = "请购单测试商品C"
    QUANTITY = "1"
    UNIT_PRICE = "30"

    def open_purchase_order(self) -> None:
        """进入采购订单列表页"""
        self._push_route(self.PURCHASE_ORDER_ROUTE)
        expect(self.page.get_by_role("button", name="新增")).to_be_visible(timeout=15000)

    def create_unapproved_order(self, order_no: str, record_document_id=None) -> dict:
        """新增采购订单并保存为未审核状态"""
        self.open_purchase_order()
        self.page.get_by_role("button", name="新增").click()
        self._close_intro()
        expect(self.page.get_by_text("供应商").last).to_be_visible(timeout=10000)

        self._select_ant_option("请选择供应商", self.SUPPLIER_NAME)
        self._select_ant_option("输入条码或名称", self.PRODUCT_NAME)
        self._overwrite_input(self.page.locator("[id^='operNumber_']").first, self.QUANTITY)
        self._overwrite_input(self.page.locator("[id^='unitPrice_']").first, self.UNIT_PRICE)

        # 最后填写单号，避免后续表单操作覆盖
        number_input = self.page.locator("#number")
        number_input.fill(order_no)
        expect(number_input).to_have_value(order_no)

        # 保存前检查真实接口请求，防止系统编号覆盖测试单号
        submitted_numbers = []

        def guard_save(route):
            try:
                payload = route.request.post_data_json
                if isinstance(payload, str):
                    payload = json.loads(payload)

                info = payload.get("info") if isinstance(payload, dict) else None
                if isinstance(info, str):
                    info = json.loads(info)

                actual = info.get("number") if isinstance(info, dict) else None
            except Exception:
                actual = None

            submitted_numbers.append(actual)

            if actual == order_no:
                route.continue_()
            else:
                route.abort("blockedbyclient")

        pattern = "**/depotHead/addDepotHeadAndDetail*"
        self.page.route(pattern, guard_save)

        try:
            with self.page.expect_response(pattern, timeout=15000):
                self.page.get_by_role("button", name="保存（Ctrl+S）").click()
        finally:
            self.page.unroute(pattern, guard_save)

        if submitted_numbers != [order_no]:
            raise RuntimeError(
                f"采购订单保存已拦截：期望单号={order_no}，"
                f"实际提交={submitted_numbers}"
            )

        self._wait_saved_row(order_no)
        _, document = self._query_order(order_no, record_document_id)
        return document

    def assert_order_unapproved(self, order_no: str) -> None:
        """按单号查询并断言采购订单为未审核"""
        self.assert_order_status(order_no, "未审核")

    def audit_order(self, order_no: str) -> None:
        """审核采购订单，并断言状态变为已审核"""
        self._select_order(order_no)
        self._click_toolbar_button("审核")
        self._confirm_operation()
        self.assert_order_status(order_no, "已审核")

    def reverse_audit_order(self, order_no: str) -> None:
        """反审核采购订单，并断言状态恢复为未审核"""
        self._select_order(order_no)
        self._click_toolbar_button("反审核")
        self._confirm_operation()
        self.assert_order_status(order_no, "未审核")

    def transfer_to_purchase_in(
        self, order_no: str, requested_inbound_no: str, record_document_id=None
    ) -> dict:
        """转采购入库，并返回系统实际生成编号对应的列表响应记录。"""
        self._select_order(order_no)
        self._click_toolbar_button("转采购入库")
        dialog = self._transfer_dialog("转采购入库")
        dialog.locator("#number").fill(requested_inbound_no)
        self._select_dialog_warehouse(dialog)
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
            raise RuntimeError(f"采购入库转单保存失败: {response_data}")

        request_info = self._request_info(save_response.request.post_data_json)
        actual_inbound_no = request_info.get("number")
        if not actual_inbound_no or request_info.get("linkNumber") != order_no:
            raise RuntimeError(
                f"采购入库转单响应对应请求不完整: number={actual_inbound_no}, "
                f"linkNumber={request_info.get('linkNumber')}"
            )

        expect(dialog).to_be_hidden(timeout=15000)
        document = self.assert_purchase_in_status(
            actual_inbound_no, "未审核", record_document_id
        )
        self.assert_order_status(order_no, "完成采购")
        return document

    def assert_purchase_in_unapproved(self, inbound_no: str) -> dict:
        """按单号查询并断言采购入库单为未审核"""
        return self.assert_purchase_in_status(inbound_no, "未审核")

    def audit_purchase_in(self, inbound_no: str) -> str:
        """审核采购入库单，并断言状态变为已审核"""
        self._select_purchase_in(inbound_no)
        self._click_toolbar_button("审核")
        self._confirm_operation()
        self.assert_purchase_in_status(inbound_no, "已审核")
        return inbound_no

    def assert_purchase_in_status(
        self, inbound_no: str, status: str, record_document_id=None
    ) -> dict:
        """按单号查询并断言采购入库单状态"""
        row, document = self._query_purchase_in(inbound_no, record_document_id)
        expect(row).to_contain_text(self.SUPPLIER_NAME)
        expect(row).to_contain_text(self.PRODUCT_NAME)
        expect(row).to_contain_text(status)
        return document

    def assert_order_status(self, order_no: str, status: str) -> None:
        """按单号查询并断言采购订单状态"""
        row, _ = self._query_order(order_no)
        expect(row).to_contain_text(self.SUPPLIER_NAME)
        expect(row).to_contain_text(self.PRODUCT_NAME)
        expect(row).to_contain_text(status)

    def _query_order(self, order_no: str, record_document_id=None):
        self.open_purchase_order()
        self.page.get_by_placeholder("请输入单据编号").first.fill(order_no)
        response = self._query_list_response(order_no)
        document = self._exact_document(response, order_no)
        if record_document_id:
            record_document_id(int(document["id"]))
        row = self.page.locator(".ant-table-tbody tr").filter(has_text=order_no).first
        expect(row).to_be_visible(timeout=15000)
        return row, document

    def _query_purchase_in(self, inbound_no: str, record_document_id=None):
        self._push_route(self.PURCHASE_IN_ROUTE)
        expect(self.page.get_by_role("button", name="新增")).to_be_visible(timeout=15000)
        self.page.get_by_placeholder("请输入单据编号").first.fill(inbound_no)
        response = self._query_list_response(inbound_no)
        document = self._exact_document(response, inbound_no)
        if record_document_id:
            record_document_id(int(document["id"]))
        row = self.page.locator(".ant-table-tbody tr").filter(has_text=inbound_no).first
        expect(row).to_be_visible(timeout=15000)
        return row, document

    def _select_order(self, order_no: str) -> None:
        row, _ = self._query_order(order_no)
        checkbox = row.locator(".ant-checkbox-input").first
        if not checkbox.is_checked():
            checkbox.click()

    def _select_purchase_in(self, inbound_no: str) -> None:
        row, _ = self._query_purchase_in(inbound_no)
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
        warehouse_select = dialog.get_by_role("combobox").nth(1)
        expect(warehouse_select).to_be_visible(timeout=10000)
        warehouse_select.click(force=True)
        self.page.keyboard.type(self.WAREHOUSE_NAME)
        option = self.page.locator(
            ".ant-select-dropdown:visible .ant-select-dropdown-menu-item"
        ).filter(has_text=self.WAREHOUSE_NAME).first
        expect(option).to_be_visible(timeout=10000)
        option.click()

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
