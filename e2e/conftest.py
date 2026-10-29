# -*- coding: utf-8 -*-
"""跨层端到端用例 fixture。"""
import time
from pathlib import Path

import allure
import pytest

from config.settings import ERP_PASSWORD, ERP_UI_URL, ERP_USERNAME
from shared.api_client import ErpApiClient
from shared.db_helpers import cleanup_depot_documents, count_run_residue, list_depot_heads
from ui.pages.login_page import LoginPage

_AUTH_DIR = Path(__file__).resolve().parent.parent / ".runtime" / "auth"
_CONTEXT_ARGS = {
    "viewport": {"width": 1920, "height": 1080},
    "ignore_https_errors": True,
}


def pytest_runtest_call(item):
    if item.parent._obj.__doc__:
        allure.dynamic.feature(item.parent._obj.__doc__)
    if item.function.__doc__:
        allure.dynamic.title(item.function.__doc__)


def _missing_issues():
    issues = []
    if not ERP_UI_URL:
        issues.append("ERP UI 地址未配置")
    if not (ERP_USERNAME and ERP_PASSWORD):
        issues.append("测试账号未配置")
    login_missing = LoginPage.missing_materials()
    if login_missing:
        issues.append("登录页真实资料未齐：" + "、".join(login_missing))
    return issues


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    issues = _missing_issues()
    if issues:
        pytest.skip("无法真实运行跨层端到端用例：" + "；".join(issues))
    return {"args": ["--no-sandbox"], **browser_type_launch_args}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, e2e_login_state_path):
    args = {**_CONTEXT_ARGS, **browser_context_args}
    args["storage_state"] = str(e2e_login_state_path)
    return args


@pytest.fixture(scope="session")
def e2e_login_state_path(browser):
    _AUTH_DIR.mkdir(parents=True, exist_ok=True)
    state_file = _AUTH_DIR / f"e2e-login-{time.strftime('%Y%m%d-%H%M%S')}.json"
    context = browser.new_context(**_CONTEXT_ARGS)
    try:
        page = context.new_page()
        login_page = LoginPage(page)
        login_page.open()
        login_page.login(ERP_USERNAME, ERP_PASSWORD)
        login_page.assert_logged_in()
        context.storage_state(path=str(state_file))
    finally:
        context.close()
    yield state_file


@pytest.fixture(scope="session")
def e2e_run_id() -> str:
    return time.strftime("%Y%m%d%H%M%S")


@pytest.fixture(scope="session")
def e2e_api_client():
    return ErpApiClient().login()


@pytest.fixture(scope="session")
def e2e_created_documents():
    """记录本轮精确单据 ID，以及创建流程异常时的人工核查风险。"""
    return {"ids": set(), "unregistered_risks": set()}


def _cleanup_e2e_documents(created_documents):
    document_ids = sorted(created_documents["ids"])
    risks = sorted(created_documents["unregistered_risks"])
    if risks:
        print(
            "[E2E 后置清理] 人工核查风险：以下创建流程可能已成功，但数据库 ID 未登记："
            + "；".join(risks)
        )
    if not document_ids:
        if risks:
            raise AssertionError("E2E 后置清理无法定位可能已创建的单据，禁止猜测 ID 清理")
        print("[E2E 后置清理] 无已登记的本轮业务单据 ID，不执行清理")
        return

    try:
        docs = list_depot_heads(document_ids)
    except Exception as exc:
        raise AssertionError(f"E2E 后置清理按登记 ID 查询失败: {exc}") from exc
    found_ids = {int(row["id"]) for row in docs}
    missing_ids = sorted(set(document_ids) - found_ids)
    if missing_ids:
        raise AssertionError(f"E2E 后置清理无法查询已登记单据 ID: {missing_ids}")

    audited_stock_docs = [
        row for row in docs
        if str(row.get("status")) == "1"
        and row.get("type") in ("入库", "出库")
        and row.get("sub_type") in ("采购", "销售")
    ]
    if audited_stock_docs:
        client = ErpApiClient().login()
        audited_stock_docs.sort(key=lambda row: 0 if row.get("type") == "出库" else 1)
        for row in audited_stock_docs:
            try:
                client.set_depot_head_status(row["id"], "0")
                detail = client.get_depot_head_detail(row["number"])
                if str(detail.get("status")) != "0":
                    raise RuntimeError(f"反审核后状态仍为 {detail.get('status')}")
                print(f"[E2E 后置清理] 反审核并验证成功: {row['number']} id={row['id']}")
            except Exception as exc:
                raise AssertionError(
                    f"E2E 后置清理中止：反审核失败，单据={row['number']} "
                    f"id={row['id']}，原因={exc}"
                ) from exc

    try:
        refreshed_docs = list_depot_heads(document_ids)
    except Exception as exc:
        raise AssertionError(f"E2E 反审核后数据库复核失败: {exc}") from exc
    still_audited = [
        row["id"] for row in refreshed_docs
        if str(row.get("status")) == "1"
        and row.get("type") in ("入库", "出库")
        and row.get("sub_type") in ("采购", "销售")
    ]
    if still_audited:
        raise AssertionError(f"E2E 后置清理中止：反审核复核失败，单据 ID={still_audited}")

    try:
        affected = cleanup_depot_documents(document_ids)
    except Exception as exc:
        raise AssertionError(f"E2E 后置事务清理失败: {exc}") from exc
    for label, count in affected.items():
        print(f"[E2E 后置清理] {label} 影响行数: {count}")
    try:
        residue = count_run_residue(document_ids)
    except Exception as exc:
        raise AssertionError(f"E2E 后置清理残留复核失败: {exc}") from exc
    print(f"[E2E 后置清理] 精确 ID 残留复核: {residue}, ids={document_ids}")
    if any(residue.values()):
        raise AssertionError(f"E2E 后置清理后仍存在本轮 ID 残留: {residue}")
    if risks:
        raise AssertionError("E2E 已登记数据清理完成，但仍存在未登记单据的人工核查风险")


@pytest.fixture(scope="session", autouse=True)
def e2e_run_data_cleanup(e2e_created_documents):
    yield
    _cleanup_e2e_documents(e2e_created_documents)
