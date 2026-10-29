# -*- coding: utf-8 -*-
"""UI 自动化 conftest（基于官方 pytest-playwright，不再使用本地插件副本）

- browser/context/page 全部使用官方 pytest-playwright fixture：
  - browser 为 session 级，默认 Chromium headless，--headed 时切换有头模式
  - context 由官方插件为每条用例创建并关闭独立 BrowserContext，用例间互不污染
- 登录状态复用（storage_state）：
  - session 内登录一次并保存到 .runtime/auth/（Git 忽略，不进入报告/Allure/日志）
  - 业务用例的 context 自动加载登录状态；登录冒烟用例使用不加载状态的新 context
  - 状态文件不自动清理：只依赖 .gitignore 保证不提交，不做任何删除操作
- 调试产物：截图、视频、Trace 由官方插件写入 --output（run.py ui 默认
  reports/playwright）；失败时把非敏感截图与 Trace 附加到 Allure，
  storage_state 永不进入 reports/ 或 Allure 附件
- session 后置定向清理：只清理本轮从真实接口响应中记录 ID 的单据数据，
  不清理 AUTO_API_* 数据，不删除任何基础数据，不执行任何文件删除操作
- 真实 jshERP 页面资料/配置缺失时，在启动浏览器前整体跳过并给出具体原因，
  不使用猜测的定位器冒充真实用例
"""
import time
from pathlib import Path
from typing import Dict, List

import allure
import pytest

from config.settings import (
    ERP_PASSWORD,
    ERP_UI_URL,
    ERP_USERNAME,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_USERNAME,
)
from ui.pages.login_page import LoginPage

_AUTH_DIR = Path(__file__).resolve().parent.parent / ".runtime" / "auth"

# 浏览器上下文统一参数：固定视口 + 忽略 HTTPS 证书错误
_CONTEXT_ARGS: Dict = {
    "viewport": {"width": 1920, "height": 1080},
    "ignore_https_errors": True,
}


def pytest_runtest_call(item):
    """动态添加 Allure feature/title，保持报告分类清晰"""
    if item.parent._obj.__doc__:
        allure.dynamic.feature(item.parent._obj.__doc__)
    if item.function.__doc__:
        allure.dynamic.title(item.function.__doc__)


def _ui_missing_issues() -> List[str]:
    """列出当前无法真实运行 ERP UI 用例的原因（配置或真实页面资料缺失项）"""
    issues = []
    if not ERP_UI_URL:
        issues.append("ERP UI 地址未配置（ERP_UI_URL 环境变量或 config/local.ini [api_envi] ui_host）")
    if not (ERP_USERNAME and ERP_PASSWORD):
        issues.append("测试账号未配置（ERP_USERNAME/ERP_PASSWORD 环境变量或 config/local.ini [LOGIN]）")
    login_missing = LoginPage.missing_materials()
    if login_missing:
        issues.append("登录页真实资料未齐：" + "、".join(login_missing)
                     + "（需人工提供真实 jshERP 登录页 DOM/codegen/截图/录屏后补充）")
    return issues


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Chromium 启动参数：默认 headless（官方插件处理 --headed）。

    真实页面资料/配置缺失时，在启动浏览器前跳过整个会话并说明原因，
    避免无意义地拉起浏览器或使用猜测的登录判断。
    """
    issues = _ui_missing_issues()
    if issues:
        pytest.skip("无法真实运行 ERP UI 用例：" + "；".join(issues))
    return {"args": ["--no-sandbox"], **browser_type_launch_args}


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, login_state_path):
    """Context 参数：固定视口、忽略 HTTPS 证书错误；存在登录状态时自动加载"""
    args = {**_CONTEXT_ARGS, **browser_context_args}
    if login_state_path:
        args["storage_state"] = str(login_state_path)
    return args


@pytest.fixture(scope="session")
def login_state_path(browser):
    """session 内登录一次，把 storage_state 保存到 .runtime/auth/。

    状态文件只写入 Git 忽略目录，由 .gitignore 保证不提交；
    文件内容不进入报告、Allure 或日志。
    """
    _AUTH_DIR.mkdir(parents=True, exist_ok=True)
    state_file = _AUTH_DIR / f"ui-login-{time.strftime('%Y%m%d-%H%M%S')}.json"
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


@pytest.fixture
def fresh_page(browser):
    """不加载登录状态的独立 Context + Page：登录用例专用，避免被已登录状态干扰。

    直接从 browser 创建，不加载 browser_context_args 中的 storage_state。
    """
    context = browser.new_context(**_CONTEXT_ARGS)
    yield context.new_page()
    context.close()


@pytest.fixture(scope="session")
def ui_run_id() -> str:
    """本轮 UI 运行 ID（YYYYMMDDHHMMSS）。

    UI 本轮主动填写的订单编号包含该 run_id，命名约定：
    - AUTO_UI_PO_<run_id>：采购订单
    - AUTO_UI_SO_<run_id>：销售订单
    - 转单后的采购入库、销售出库由系统自动编号，通过接口响应获取
    - 如需要新建商品：AUTO_UI_GOODS_<run_id>（第一版优先复用固定商品，不清理商品表）
    """
    return time.strftime("%Y%m%d%H%M%S")


@pytest.fixture(scope="session")
def ui_created_document_ids() -> set:
    """记录本轮 UI 精确查询响应中返回的 jsh_depot_head.id。"""
    return set()


def _cleanup_ui_run_data(document_ids) -> None:
    """session 结束后在一个事务中按已记录 ID 定向清理本轮 UI 数据。

    只删除本轮 UI 创建并从接口响应精确记录的订单、出入库单及对应明细；
    不清理 AUTO_API_* 与接口自动化数据，不删除供应商/客户/仓库/结算账户/
    固定商品等基础数据。清理失败会抛出异常，使 teardown 明确失败。
    """
    ids = sorted({int(document_id) for document_id in document_ids})
    if not ids:
        print('[UI 后置清理] 无已登记的本轮业务单据 ID，不执行数据库清理')
        return
    if not all([MYSQL_HOST, MYSQL_PORT, MYSQL_USERNAME, MYSQL_PASSWORD, MYSQL_DATABASE]):
        raise RuntimeError(
            '[UI 后置清理] 失败：存在已登记业务单据，但 MySQL 配置缺失'
        )

    # 延迟导入：仅清理执行时加载，collect-only 时不产生任何副作用
    from shared.database import ConnectMysql

    conn = None
    try:
        conn = ConnectMysql()
        cursor = conn.cursor
        placeholders = ', '.join(['%s'] * len(ids))
        statements = [
            ('收付款明细-按业务单据',
             f"DELETE FROM jsh_account_item WHERE bill_id IN ({placeholders})"),
            ('出入库明细',
             f"DELETE FROM jsh_depot_item WHERE header_id IN ({placeholders})"),
            ('出入库单',
             f"DELETE FROM jsh_depot_head WHERE id IN ({placeholders})"),
        ]
        for label, sql in statements:
            cursor.execute(sql, tuple(ids))
            print(f'[UI 后置清理] {label} 影响行数: {cursor.rowcount}')
        conn.conn.commit()
        print(f'[UI 后置清理] 完成：事务已提交，业务单据 ID={ids}')
    except Exception as exc:
        if conn and conn.conn:
            try:
                conn.conn.rollback()
            except Exception as rollback_exc:
                raise RuntimeError(
                    f'[UI 后置清理] 失败且回滚失败: {rollback_exc}'
                ) from exc
            raise RuntimeError('[UI 后置清理] 失败，事务已回滚') from exc
        raise RuntimeError('[UI 后置清理] 失败：数据库连接未建立') from exc
    finally:
        if conn:
            conn.close()


@pytest.fixture(scope="session", autouse=True)
def ui_run_data_cleanup(ui_created_document_ids):
    """session 后置定向清理：只清理本轮已登记 ID 对应的数据。

    不清理 AUTO_API_* 数据，不删除供应商/客户/仓库/结算账户/固定商品等基础数据。
    """
    yield
    _cleanup_ui_run_data(ui_created_document_ids)


@pytest.fixture(autouse=True)
def _attach_ui_artifacts(request, output_path):
    """失败时把官方插件保存的截图与 Trace 附加到 Allure。

    只附加非敏感的截图与 Trace，不附加视频与任何登录状态文件。
    """
    yield
    failed = getattr(request.node, "rep_call", None)
    if failed is None or not failed.failed:
        return
    artifact_dir = Path(output_path)
    for png in sorted(artifact_dir.glob("test-failed-*.png")):
        allure.attach.file(str(png), name=png.name, attachment_type=allure.attachment_type.PNG)
    for trace in sorted(artifact_dir.glob("trace*.zip")):
        allure.attach.file(str(trace), name=trace.name, attachment_type=allure.attachment_type.ZIP)
