# -*- coding: utf-8 -*-
"""采购/销售 UI 转单冒烟

验证真实页面新增、审核并转未审核出入库单：
- 复用接口自动化基础数据：供应商、客户、仓库、结算账户
- 固定商品使用“请购单测试商品C”
- 不保存并审核、不审核采购入库、不审核销售出库
- 转单生成的入库/出库单保持未审核，避免触发库存和财务实际变更
- 订单编号包含 AUTO_UI_ 前缀与本轮 ui_run_id；转单使用系统实际生成编号
- session teardown 仅按本轮接口响应中记录的数据库 ID 定向清理
"""
import pytest

from ui.pages.purchase_page import PurchasePage
from ui.pages.sales_page import SalesPage


@pytest.mark.smoke
@pytest.mark.destructive
def test_purchase_order_transfer_to_unapproved_purchase_in(
    page, ui_run_id, ui_created_document_ids
):
    """新增采购订单，审核后转未审核采购入库"""
    order_no = f"AUTO_UI_PO_{ui_run_id}"
    requested_inbound_no = f"AUTO_UI_PI_{ui_run_id}"
    purchase_page = PurchasePage(page)
    purchase_page.create_unapproved_order(order_no, ui_created_document_ids.add)
    purchase_page.assert_order_unapproved(order_no)
    purchase_page.audit_order(order_no)
    purchase_page.transfer_to_purchase_in(
        order_no, requested_inbound_no, ui_created_document_ids.add
    )


@pytest.mark.smoke
@pytest.mark.destructive
def test_sales_order_transfer_to_unapproved_sales_out(
    page, ui_run_id, ui_created_document_ids
):
    """新增销售订单，审核后转未审核销售出库"""
    order_no = f"AUTO_UI_SO_{ui_run_id}"
    requested_outbound_no = f"AUTO_UI_SOUT_{ui_run_id}"
    sales_page = SalesPage(page)
    sales_page.create_unapproved_order(order_no, ui_created_document_ids.add)
    sales_page.assert_order_unapproved(order_no)
    sales_page.audit_order(order_no)
    sales_page.transfer_to_sales_out(
        order_no, requested_outbound_no, ui_created_document_ids.add
    )
