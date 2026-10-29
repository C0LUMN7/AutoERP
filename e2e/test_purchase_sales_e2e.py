# -*- coding: utf-8 -*-
"""采购与销售跨层闭环"""
from decimal import Decimal

import allure
import pytest

from config.settings import BUSINESS_IDS
from shared.db_helpers import get_depot_head, get_depot_item, get_material_stock
from ui.pages.purchase_page import PurchasePage
from ui.pages.sales_page import SalesPage


def _decimal(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def _assert_amounts(head: dict, item: dict, quantity: Decimal, unit_price: Decimal) -> None:
    expected_amount = _decimal(quantity * unit_price)
    assert _decimal(item["oper_number"]) == _decimal(quantity)
    assert _decimal(item["unit_price"]) == _decimal(unit_price)
    assert _decimal(item["all_price"]) == expected_amount
    assert abs(_decimal(head["total_price"])) == expected_amount


def _assert_api_audited(api_detail: dict, number: str) -> None:
    assert api_detail.get("number") == number
    assert str(api_detail.get("status")) == "1"


def _record_document_id(created_documents, risk):
    def record(document_id):
        created_documents["ids"].add(int(document_id))
        created_documents["unregistered_risks"].discard(risk)

    return record


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.destructive
def test_purchase_receipt_cross_layer_closed_loop(
    page, e2e_run_id, e2e_api_client, e2e_created_documents
):
    """采购订单到已审核采购入库的跨层闭环"""
    purchase_page = PurchasePage(page)
    order_no = f"AUTO_E2E_PO_{e2e_run_id}"
    requested_inbound_no = f"AUTO_E2E_PI_{e2e_run_id}"
    quantity = _decimal(purchase_page.QUANTITY)
    unit_price = _decimal(purchase_page.UNIT_PRICE)

    initial_stock = get_material_stock(purchase_page.PRODUCT_NAME, BUSINESS_IDS["depot_id"])
    allure.attach(str(initial_stock), "采购闭环-初始库存", allure.attachment_type.TEXT)

    order_risk = f"采购订单 {order_no}"
    e2e_created_documents["unregistered_risks"].add(order_risk)
    order_document = purchase_page.create_unapproved_order(
        order_no, _record_document_id(e2e_created_documents, order_risk)
    )
    assert int(order_document["id"]) in e2e_created_documents["ids"]
    purchase_page.assert_order_unapproved(order_no)
    purchase_page.audit_order(order_no)
    inbound_risk = f"采购入库（来源订单 {order_no}）"
    e2e_created_documents["unregistered_risks"].add(inbound_risk)
    inbound_document = purchase_page.transfer_to_purchase_in(
        order_no,
        requested_inbound_no,
        _record_document_id(e2e_created_documents, inbound_risk),
    )
    inbound_no = inbound_document["number"]
    assert int(inbound_document["id"]) in e2e_created_documents["ids"]
    purchase_page.audit_purchase_in(inbound_no)

    api_detail = e2e_api_client.get_depot_head_detail(inbound_no)
    _assert_api_audited(api_detail, inbound_no)

    head = get_depot_head(inbound_no)
    assert int(head["id"]) == int(inbound_document["id"])
    item = get_depot_item(head["id"], purchase_page.PRODUCT_NAME, BUSINESS_IDS["depot_id"])
    current_stock = get_material_stock(purchase_page.PRODUCT_NAME, BUSINESS_IDS["depot_id"])

    assert str(head["status"]) == "1"
    assert str(item["depot_id"]) == str(BUSINESS_IDS["depot_id"])
    assert current_stock == _decimal(initial_stock + quantity)
    _assert_amounts(head, item, quantity, unit_price)

    allure.attach(
        f"run_id={e2e_run_id}\n单据={inbound_no}\n库存: {initial_stock} -> {current_stock}\n"
        f"状态=已审核\n头金额={head['total_price']}\n明细金额={item['all_price']}",
        "采购闭环校验结果",
        allure.attachment_type.TEXT,
    )


@pytest.mark.e2e
@pytest.mark.smoke
@pytest.mark.destructive
def test_sales_shipment_cross_layer_closed_loop(
    page, e2e_run_id, e2e_api_client, e2e_created_documents
):
    """销售订单到已审核销售出库的跨层闭环"""
    sales_page = SalesPage(page)
    order_no = f"AUTO_E2E_SO_{e2e_run_id}"
    requested_outbound_no = f"AUTO_E2E_SOUT_{e2e_run_id}"
    quantity = _decimal(sales_page.QUANTITY)
    unit_price = _decimal(sales_page.UNIT_PRICE)

    initial_stock = get_material_stock(sales_page.PRODUCT_NAME, BUSINESS_IDS["depot_id"])
    allure.attach(str(initial_stock), "销售闭环-初始库存", allure.attachment_type.TEXT)

    order_risk = f"销售订单 {order_no}"
    e2e_created_documents["unregistered_risks"].add(order_risk)
    order_document = sales_page.create_unapproved_order(
        order_no, _record_document_id(e2e_created_documents, order_risk)
    )
    assert int(order_document["id"]) in e2e_created_documents["ids"]
    sales_page.assert_order_unapproved(order_no)
    sales_page.audit_order(order_no)
    outbound_risk = f"销售出库（来源订单 {order_no}）"
    e2e_created_documents["unregistered_risks"].add(outbound_risk)
    outbound_document = sales_page.transfer_to_sales_out(
        order_no,
        requested_outbound_no,
        _record_document_id(e2e_created_documents, outbound_risk),
    )
    outbound_no = outbound_document["number"]
    assert int(outbound_document["id"]) in e2e_created_documents["ids"]
    sales_page.audit_sales_out(outbound_no)

    api_detail = e2e_api_client.get_depot_head_detail(outbound_no)
    _assert_api_audited(api_detail, outbound_no)

    head = get_depot_head(outbound_no)
    assert int(head["id"]) == int(outbound_document["id"])
    item = get_depot_item(head["id"], sales_page.PRODUCT_NAME, BUSINESS_IDS["depot_id"])
    current_stock = get_material_stock(sales_page.PRODUCT_NAME, BUSINESS_IDS["depot_id"])

    assert str(head["status"]) == "1"
    assert str(item["depot_id"]) == str(BUSINESS_IDS["depot_id"])
    assert current_stock == _decimal(initial_stock - quantity)
    _assert_amounts(head, item, quantity, unit_price)

    allure.attach(
        f"run_id={e2e_run_id}\n单据={outbound_no}\n库存: {initial_stock} -> {current_stock}\n"
        f"状态=已审核\n头金额={head['total_price']}\n明细金额={item['all_price']}",
        "销售闭环校验结果",
        allure.attachment_type.TEXT,
    )
