# -*- coding: utf-8 -*-
"""跨层用例使用的数据库查询与本轮数据清理工具。"""
from decimal import Decimal

from shared.database import ConnectMysql
from config.settings import BUSINESS_IDS


def fetch_one(sql: str, params=()):
    conn = ConnectMysql()
    try:
        if not conn.conn or not conn.cursor:
            raise RuntimeError("MySQL 连接失败")
        conn.cursor.execute(sql, params)
        return conn.cursor.fetchone()
    finally:
        conn.close()


def fetch_all(sql: str, params=()):
    conn = ConnectMysql()
    try:
        if not conn.conn or not conn.cursor:
            raise RuntimeError("MySQL 连接失败")
        conn.cursor.execute(sql, params)
        return conn.cursor.fetchall()
    finally:
        conn.close()


def get_material(product_name: str) -> dict:
    row = fetch_one(
        "SELECT id, name FROM jsh_material WHERE name = %s AND delete_flag = '0'",
        (product_name,),
    )
    if not row:
        raise RuntimeError(f"数据库未找到商品: {product_name}")
    return row


def get_material_stock(product_name: str, depot_id=None) -> Decimal:
    depot = depot_id or BUSINESS_IDS["depot_id"]
    row = fetch_one(
        """
        SELECT current_number
        FROM jsh_material_current_stock
        WHERE material_id = (
            SELECT id FROM jsh_material WHERE name = %s AND delete_flag = '0' LIMIT 1
        )
        AND depot_id = %s
        AND delete_flag = '0'
        """,
        (product_name, depot),
    )
    if not row:
        raise RuntimeError(f"数据库未找到商品库存: {product_name}, depot_id={depot}")
    return Decimal(str(row["current_number"]))


def get_depot_head(number: str) -> dict:
    row = fetch_one(
        """
        SELECT id, number, type, sub_type, status, total_price, discount_last_money,
               change_amount, organ_id, account_id
        FROM jsh_depot_head
        WHERE number = %s AND delete_flag = '0'
        """,
        (number,),
    )
    if not row:
        raise RuntimeError(f"数据库未找到单据: {number}")
    return row


def get_depot_item(header_id, product_name: str, depot_id=None) -> dict:
    depot = depot_id or BUSINESS_IDS["depot_id"]
    row = fetch_one(
        """
        SELECT id, header_id, material_id, depot_id, oper_number, unit_price, all_price,
               tax_last_money
        FROM jsh_depot_item
        WHERE header_id = %s
          AND material_id = (
              SELECT id FROM jsh_material WHERE name = %s AND delete_flag = '0' LIMIT 1
          )
          AND depot_id = %s
          AND delete_flag = '0'
        """,
        (header_id, product_name, depot),
    )
    if not row:
        raise RuntimeError(f"数据库未找到单据明细: header_id={header_id}, 商品={product_name}")
    return row


def list_depot_heads(document_ids):
    ids = sorted({int(document_id) for document_id in document_ids})
    if not ids:
        return []
    placeholders = ", ".join(["%s"] * len(ids))
    return fetch_all(
        f"""
        SELECT id, number, type, sub_type, status
        FROM jsh_depot_head
        WHERE id IN ({placeholders}) AND delete_flag = '0'
        ORDER BY id
        """,
        tuple(ids),
    )


def cleanup_depot_documents(document_ids) -> dict:
    """在一个事务中按本轮登记 ID 删除单据与明细。"""
    ids = sorted({int(document_id) for document_id in document_ids})
    if not ids:
        return {}
    placeholders = ", ".join(["%s"] * len(ids))
    params = tuple(ids)
    statements = [
        ("收付款明细-按业务单据",
         f"DELETE FROM jsh_account_item WHERE bill_id IN ({placeholders})", params),
        ("出入库明细",
         f"DELETE FROM jsh_depot_item WHERE header_id IN ({placeholders})", params),
        (
            "出入库单",
            f"DELETE FROM jsh_depot_head WHERE id IN ({placeholders})",
            params,
        ),
    ]

    conn = ConnectMysql()
    affected = {}
    try:
        if not conn.conn or not conn.cursor:
            raise RuntimeError("MySQL 连接失败")
        for label, sql, sql_params in statements:
            conn.cursor.execute(sql, sql_params)
            affected[label] = conn.cursor.rowcount
        conn.conn.commit()
        return affected
    except Exception:
        if conn.conn:
            conn.conn.rollback()
        raise
    finally:
        conn.close()


def count_run_residue(document_ids) -> dict:
    ids = sorted({int(document_id) for document_id in document_ids})
    if not ids:
        return {"jsh_depot_head": 0, "jsh_depot_item": 0, "jsh_account_item": 0}
    placeholders = ", ".join(["%s"] * len(ids))
    params = tuple(ids)
    head_count = fetch_one(
        f"""
        SELECT COUNT(*) AS c
        FROM jsh_depot_head
        WHERE id IN ({placeholders})
        """,
        params,
    )["c"]
    item_count = fetch_one(
        f"""
        SELECT COUNT(*) AS c
        FROM jsh_depot_item
        WHERE header_id IN ({placeholders})
        """,
        params,
    )["c"]
    account_item_count = fetch_one(
        f"""
        SELECT COUNT(*) AS c
        FROM jsh_account_item
        WHERE bill_id IN ({placeholders})
        """,
        params,
    )["c"]
    return {
        "jsh_depot_head": head_count,
        "jsh_depot_item": item_count,
        "jsh_account_item": account_item_count,
    }
