# -*- coding: utf-8 -*-
"""API 测试 conftest

- start_test_and_end: 用例级日志标记
- api_run_context: session 级运行上下文，替代全局 extract.yaml（收集阶段不执行）
- system_login: session 级自动登录，提取 Token 写入运行上下文
- datadb_init: session 后置数据清理，防止 ERP 环境残留脏数据

fixture 仅对 api/ 目录下用例生效；pytest 收集阶段不执行任何 fixture，
因此 collect-only 不会触发自动登录和数据库清理。
"""
import time

import pytest

from shared.logger import logs
from shared.debugtalk import DebugTalk
from shared.database import ConnectMysql
from api.framework.yaml_loader import load_case_pairs, reset_run_context
from api.framework.runner import run_case


def _short_run_id(run_id):
    value = int(run_id)
    chars = '0123456789abcdefghijklmnopqrstuvwxyz'
    result = ''
    while value:
        value, remainder = divmod(value, 36)
        result = chars[remainder] + result
    return result or '0'


def _cleanup_sql(cursor, label, sql, params):
    cursor.execute(sql, params)
    affected = cursor.rowcount
    logs.info('后置清理%s已执行（待事务提交），影响行数: %s', label, affected)
    return affected


def _cleanup_run_data():
    run_id = DebugTalk._fixed_ts
    if not run_id:
        logs.info('本次会话未生成运行ID，跳过后置数据清理')
        return {}

    run_id = str(run_id)
    if len(run_id) != 13 or not run_id.isdigit():
        raise RuntimeError(f'后置数据清理中止：运行ID格式无效: {run_id!r}')

    depot_run_id = _short_run_id(run_id)
    conn = ConnectMysql()
    if not conn.conn or not conn.cursor:
        conn.close()
        raise RuntimeError('后置数据清理失败：MySQL 未连接')

    try:
        cursor = conn.cursor
        run_suffix = "REGEXP CONCAT('_', %s, '($|_(EMPTY|INVALID)$)')"
        head_ids = ("SELECT id FROM jsh_depot_head WHERE LEFT(number, 9) = 'AUTO_API_' "
                    f"AND number {run_suffix} AND delete_flag = '0'")
        account_ids = ("SELECT id FROM jsh_account_head WHERE LEFT(bill_no, 9) = 'AUTO_API_' "
                       f"AND bill_no {run_suffix} AND delete_flag = '0'")
        material_ids = ("SELECT id FROM jsh_material WHERE LEFT(name, 9) = 'AUTO_API_' "
                        f"AND name {run_suffix} AND delete_flag = '0'")
        statements = [
            ('收付款明细-按业务单据', f"DELETE FROM jsh_account_item WHERE bill_id IN ({head_ids})", (run_id,)),
            ('收付款明细-按收付款单', f"DELETE FROM jsh_account_item WHERE header_id IN ({account_ids})", (run_id,)),
            ('出入库明细', f"DELETE FROM jsh_depot_item WHERE header_id IN ({head_ids})", (run_id,)),
            ('收付款单', "DELETE FROM jsh_account_head WHERE LEFT(bill_no, 9) = 'AUTO_API_' "
                     f"AND bill_no {run_suffix} AND delete_flag = '0'", (run_id,)),
            ('出入库单', "DELETE FROM jsh_depot_head WHERE LEFT(number, 9) = 'AUTO_API_' "
                    f"AND number {run_suffix} AND delete_flag = '0'", (run_id,)),
            ('初始库存', f"DELETE FROM jsh_material_initial_stock WHERE material_id IN ({material_ids})", (run_id,)),
            ('当前库存', f"DELETE FROM jsh_material_current_stock WHERE material_id IN ({material_ids})", (run_id,)),
            ('商品扩展', f"DELETE FROM jsh_material_extend WHERE material_id IN ({material_ids})", (run_id,)),
            ('商品', "DELETE FROM jsh_material WHERE LEFT(name, 9) = 'AUTO_API_' "
                   f"AND name {run_suffix} AND delete_flag = '0'", (run_id,)),
            ('新增仓库', "DELETE FROM jsh_depot WHERE name = %s AND delete_flag = '0'",
             (f'AUTO_API_D_{depot_run_id}',)),
            ('更新仓库', "DELETE FROM jsh_depot WHERE name = %s AND delete_flag = '0'",
             (f'AUTO_API_U_{depot_run_id}',)),
        ]
        affected = {}
        for label, sql, params in statements:
            affected[label] = _cleanup_sql(cursor, label, sql, params)
        conn.conn.commit()
        logs.info('后置定向清理事务已提交，运行ID: %s，影响行数: %s', run_id, affected)
        return affected
    except Exception as exc:
        conn.conn.rollback()
        logs.error('后置定向清理失败并已回滚，运行ID: %s，原因: %s', run_id, exc)
        raise RuntimeError(f'后置数据清理失败并已回滚，运行ID: {run_id}') from exc
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def start_test_and_end():
    logs.info('-------------接口测试开始--------------')
    yield
    logs.info('-------------接口测试结束--------------')


@pytest.fixture(scope='session', autouse=True)
def api_run_context():
    """每次测试会话独立的运行上下文：替代全局 extract.yaml，避免并发和失败重跑相互污染"""
    context = reset_run_context()
    yield context


@pytest.fixture(scope='session', autouse=True)
def system_login(api_run_context):
    max_retries = 5
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                DebugTalk._captcha_data = None
                time.sleep(1)
            base_info, testcase = load_case_pairs('./api/login.yaml')[0]
            run_case(base_info, testcase, yaml_file='./api/login.yaml')
            return
        except Exception as e:
            logs.error(f'登录接口异常 (第{attempt+1}次/共{max_retries}次): {e}')
            if attempt == max_retries - 1:
                logs.error(f'登录重试{max_retries}次均失败，退出测试')
                exit()


@pytest.fixture(scope='session', autouse=True)
def datadb_init():
    """
    后置定向清理：只清理本次会话创建且带 AUTO_API_ 前缀与本次运行 ID 的测试数据。

    单据按单号前缀 + 运行 ID 匹配，商品/仓库按名称前缀 + 运行 ID 匹配，
    不模糊删除共享环境中的历史数据；本次创建数据的精确业务 ID 优先在用例内
    通过创建响应/数据库精确查询获取，这里只作为失败重跑后的兜底清理。
    """
    yield
    _cleanup_run_data()
