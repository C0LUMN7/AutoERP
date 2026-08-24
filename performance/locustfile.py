"""Locust performance scenarios for jshERP."""

from decimal import Decimal
import itertools
import json
import os
import threading
import time

from locust import HttpUser, between, task
from locust.exception import StopUser
import urllib3

from config.settings import BUSINESS_IDS, ERP_PASSWORD, ERP_USERNAME, get_api_url
from shared.database import ConnectMysql
from shared.debugtalk import DebugTalk


READONLY_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
}
PERF_PREFIX = "AUTO_PERF_"
PURCHASE_DOC_PREFIX = "AUTO_PERF_PI"
PURCHASE_MATERIAL_NAME = "请购单测试商品C"
SALES_DOC_PREFIX = "AUTO_PERF_SOUT"
SALES_MATERIAL_NAMES = ("请购单测试商品A", "请购单测试商品B", "洗脸巾")
SALES_RUN_LOCK = threading.Lock()
SALES_RUN_BASELINE_STOCKS = {}
SALES_RUN_STARTED_USERS = 0
SALES_RUN_COMPLETED_USERS = 0
SALES_RUN_ABORTED = False
SALES_RUN_QUIT_SCHEDULED = False


def _open_mysql() -> ConnectMysql:
    conn = ConnectMysql()
    if not conn.conn or not conn.cursor:
        conn.close()
        raise RuntimeError("MySQL connection failed")
    return conn


def _placeholders(values) -> str:
    return ",".join(["%s"] * len(values))


def _known_doc_filters(run_id: str, docs: list[dict]) -> tuple[list, list]:
    ids = [doc["id"] for doc in docs if doc.get("id")]
    numbers = [doc["number"] for doc in docs if doc.get("number")]
    if not ids and not numbers:
        raise RuntimeError("no recorded performance document id or number")
    return ids, numbers


def _list_perf_depot_heads(run_id: str, docs: list[dict]) -> list[dict]:
    ids, numbers = _known_doc_filters(run_id, docs)
    filters = ["number LIKE %s", "number LIKE %s", "delete_flag = '0'"]
    params = [f"{PERF_PREFIX}%", f"%{run_id}%"]
    recorded_filters = []
    if ids:
        recorded_filters.append(f"id IN ({_placeholders(ids)})")
        params.extend(ids)
    if numbers:
        recorded_filters.append(f"number IN ({_placeholders(numbers)})")
        params.extend(numbers)
    filters.append("(" + " OR ".join(recorded_filters) + ")")

    conn = _open_mysql()
    try:
        conn.cursor.execute(
            f"""
            SELECT id, number, type, sub_type, status
            FROM jsh_depot_head
            WHERE {' AND '.join(filters)}
            ORDER BY id
            """,
            params,
        )
        return list(conn.cursor.fetchall())
    finally:
        conn.close()


def _remember_depot_head_ids(docs: list[dict], heads: list[dict]) -> None:
    ids_by_number = {row["number"]: row["id"] for row in heads}
    for doc in docs:
        if not doc.get("id") and doc.get("number") in ids_by_number:
            doc["id"] = ids_by_number[doc["number"]]


def _cleanup_perf_depot_docs(run_id: str, docs: list[dict]) -> dict:
    heads = _list_perf_depot_heads(run_id, docs)
    if not heads:
        return {"出入库明细": 0, "出入库单": 0}
    _remember_depot_head_ids(docs, heads)

    head_ids = [row["id"] for row in heads]
    placeholders = _placeholders(head_ids)
    params = head_ids + [f"{PERF_PREFIX}%", f"%{run_id}%"]
    statements = [
        (
            "出入库明细",
            f"""
            DELETE FROM jsh_depot_item
            WHERE header_id IN ({placeholders})
              AND delete_flag = '0'
            """,
            head_ids,
        ),
        (
            "出入库单",
            f"""
            DELETE FROM jsh_depot_head
            WHERE id IN ({placeholders})
              AND number LIKE %s
              AND number LIKE %s
              AND delete_flag = '0'
            """,
            params,
        ),
    ]

    conn = _open_mysql()
    affected = {}
    try:
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


def _count_perf_depot_residue(run_id: str, docs: list[dict]) -> dict:
    ids, numbers = _known_doc_filters(run_id, docs)
    head_filters = ["number LIKE %s", "number LIKE %s", "delete_flag = '0'"]
    head_params = [f"{PERF_PREFIX}%", f"%{run_id}%"]
    recorded_filters = []
    if ids:
        recorded_filters.append(f"id IN ({_placeholders(ids)})")
        head_params.extend(ids)
    if numbers:
        recorded_filters.append(f"number IN ({_placeholders(numbers)})")
        head_params.extend(numbers)
    head_filters.append("(" + " OR ".join(recorded_filters) + ")")

    conn = _open_mysql()
    try:
        conn.cursor.execute(
            f"SELECT COUNT(*) AS c FROM jsh_depot_head WHERE {' AND '.join(head_filters)}",
            head_params,
        )
        head_count = conn.cursor.fetchone()["c"]

        item_count = 0
        if ids:
            conn.cursor.execute(
                f"""
                SELECT COUNT(*) AS c
                FROM jsh_depot_item
                WHERE header_id IN ({_placeholders(ids)})
                  AND delete_flag = '0'
                """,
                ids,
            )
            item_count = conn.cursor.fetchone()["c"]

        return {
            "jsh_depot_head": head_count,
            "jsh_depot_item": item_count,
        }
    finally:
        conn.close()


class ErpBaseUser(HttpUser):
    """Common ERP login and response helpers."""

    abstract = True
    host = get_api_url()

    def on_start(self) -> None:
        self.token = ""
        self._login()

    def _login(self) -> None:
        if not self.host:
            raise StopUser("ERP API address is not configured")
        if not ERP_USERNAME or not ERP_PASSWORD:
            raise StopUser("ERP login credentials are not configured")

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        helper = DebugTalk()
        for attempt in range(5):
            DebugTalk._captcha_data = None
            payload = {
                "loginName": ERP_USERNAME,
                "password": helper.md5_encryption(ERP_PASSWORD),
                "code": helper.get_captcha_code(),
                "uuid": helper.get_captcha_uuid(),
            }
            with self.client.post(
                "/user/login",
                json=payload,
                headers=READONLY_HEADERS,
                name="/user/login",
                catch_response=True,
                verify=False,
                timeout=15,
            ) as response:
                token = self._extract_token(response)
                if token:
                    self.token = token
                    response.success()
                    return
                if attempt == 4:
                    response.failure("ERP login failed")
                else:
                    response.success()
            time.sleep(1)
        raise StopUser("ERP login failed after retries")

    def _login_or_record_failure(self, name: str) -> bool:
        try:
            self._login()
            return True
        except StopUser as exc:
            self._record_failure(name, str(exc))
            return False
        except Exception as exc:
            self._record_failure(name, f"ERP login failed: {type(exc).__name__}: {exc}")
            return False

    def _headers(self) -> dict:
        headers = dict(READONLY_HEADERS)
        headers["X-Access-Token"] = self.token
        return headers

    @staticmethod
    def _extract_token(response) -> str:
        if response.status_code != 200:
            return ""
        try:
            data = response.json()
        except ValueError:
            return ""
        if data.get("code") != 200:
            return ""
        token = data.get("data", {}).get("token")
        return token or ""

    @staticmethod
    def _response_summary(response) -> str:
        text = (response.text or "").strip().replace("\r", " ").replace("\n", " ")
        if len(text) > 300:
            text = text[:300] + "..."
        return f"status={response.status_code}, body={text or '<empty>'}"

    @staticmethod
    def _validate_response(response, required_data_keys=(), require_data_object=True):
        if response.status_code != 200:
            response.failure("HTTP response failed: " + ErpBaseUser._response_summary(response))
            return None
        if response.text and response.text.strip() == "loginOut":
            response.failure("ERP token expired")
            return None
        try:
            data = response.json()
        except ValueError:
            response.failure("response is not JSON: " + ErpBaseUser._response_summary(response))
            return None
        if data.get("code") != 200:
            response.failure(f"business code is not 200: {data}; {ErpBaseUser._response_summary(response)}")
            return None
        payload = data.get("data")
        if require_data_object and not isinstance(payload, dict):
            response.failure("response data is not an object: " + ErpBaseUser._response_summary(response))
            return None
        for key in required_data_keys:
            if key not in payload:
                response.failure(f"response data missing key: {key}; {ErpBaseUser._response_summary(response)}")
                return None
        response.success()
        return data

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        name: str,
        required_data_keys=(),
        require_data_object=True,
        **kwargs,
    ):
        for attempt in range(2):
            if not self.token:
                if not self._login_or_record_failure(f"{name} login"):
                    return None
            with self.client.request(
                method,
                path,
                headers=self._headers(),
                name=name,
                catch_response=True,
                verify=False,
                timeout=15,
                **kwargs,
            ) as response:
                if response.text and response.text.strip() == "loginOut":
                    self.token = ""
                    if attempt == 0:
                        response.success()
                        continue
                    response.failure("ERP token expired after retry: " + self._response_summary(response))
                    return None
                return self._validate_response(
                    response,
                    required_data_keys=required_data_keys,
                    require_data_object=require_data_object,
                )
        return None

    def _record_failure(self, name: str, message: str) -> None:
        self.environment.events.request.fire(
            request_type="ERP",
            name=name,
            response_time=0,
            response_length=0,
            exception=RuntimeError(message),
        )

class ErpReadOnlyUser(ErpBaseUser):
    """Read-only Locust user for product, stock and document list queries."""

    wait_time = between(1, 3)

    def _get_readonly(self, path: str, *, name: str, params: dict, required_data_keys=()) -> None:
        self._request_json(
            "GET",
            path,
            name=name,
            params=params,
            required_data_keys=required_data_keys,
        )

    @task(5)
    def query_material_list(self) -> None:
        self._get_readonly(
            "/material/list",
            name="/material/list",
            params={"currentPage": 1, "pageSize": 10},
            required_data_keys=("rows",),
        )

    @task(4)
    def query_material_stock(self) -> None:
        self._get_readonly(
            "/material/getListWithStock",
            name="/material/getListWithStock",
            params={
                "currentPage": 1,
                "pageSize": 10,
                "materialParam": "",
                "zeroStock": "0",
            },
            required_data_keys=("rows", "total"),
        )

    @task(3)
    def query_depot_head_list(self) -> None:
        search = {
            "type": "入库",
            "subType": "采购订单",
            "roleType": "全部数据",
            "status": "",
            "number": "",
            "beginTime": "",
            "endTime": "",
            "materialParam": "",
            "depotIds": "",
        }
        self._get_readonly(
            "/depotHead/list",
            name="/depotHead/list",
            params={
                "search": json.dumps(search, ensure_ascii=False),
                "currentPage": 1,
                "pageSize": 10,
            },
            required_data_keys=("rows", "total"),
        )


class ErpPurchaseWriteUser(ErpBaseUser):
    """Controlled purchase write flow: create, audit, reverse audit and clean."""

    wait_time = between(1, 2)
    purchase_sequence = itertools.count(1)

    def on_start(self) -> None:
        self.run_id = os.getenv("ERP_PERF_RUN_ID") or time.strftime("%Y%m%d%H%M%S")
        self.created_docs = []
        self.purchase_material = None
        self.flow_finished = False
        super().on_start()

    def on_stop(self) -> None:
        if self.created_docs:
            self._cleanup_purchase_docs(list(self.created_docs))

    @staticmethod
    def _business_id(key: str):
        value = BUSINESS_IDS.get(key)
        if not value:
            raise StopUser(f"ERP business id is not configured: {key}")
        if str(value).isdigit():
            return int(value)
        return value

    @staticmethod
    def _purchase_material() -> dict:
        conn = _open_mysql()
        try:
            conn.cursor.execute(
                """
                SELECT m.name, COALESCE(e.bar_code, '') AS bar_code,
                       COALESCE(e.commodity_unit, m.unit, '支') AS unit
                FROM jsh_material m
                LEFT JOIN jsh_material_extend e
                  ON e.material_id = m.id AND e.delete_flag = '0'
                WHERE m.name = %s AND m.delete_flag = '0'
                ORDER BY e.id
                LIMIT 1
                """,
                (PURCHASE_MATERIAL_NAME,),
            )
            row = conn.cursor.fetchone()
        finally:
            conn.close()
        if not row:
            raise RuntimeError(f"purchase material not found: {PURCHASE_MATERIAL_NAME}")
        if not row.get("bar_code"):
            raise RuntimeError(f"purchase material barcode not found: {PURCHASE_MATERIAL_NAME}")
        return row

    def _get_purchase_material(self) -> dict:
        if not self.purchase_material:
            self.purchase_material = self._purchase_material()
        return self.purchase_material

    def _next_purchase_number(self) -> str:
        sequence = next(self.purchase_sequence)
        return f"{PURCHASE_DOC_PREFIX}_{self.run_id}_{sequence:04d}"

    def _add_purchase_receipt(self, number: str, material: dict) -> None:
        unit_price = 30
        quantity = 1
        amount = unit_price * quantity
        info = {
            "number": number,
            "type": "入库",
            "subType": "采购",
            "organId": self._business_id("supplier_organ_id"),
            "accountId": self._business_id("settle_account_id"),
            "totalPrice": -amount,
            "changeAmount": 0,
            "debt": amount,
            "discount": 0,
            "discountMoney": 0,
            "discountLastMoney": amount,
            "otherMoney": 0,
            "operTime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "0",
        }
        rows = [
            {
                "name": material["name"],
                "barCode": material["bar_code"],
                "depotId": self._business_id("depot_id"),
                "operNumber": quantity,
                "unitPrice": unit_price,
                "allPrice": amount,
                "unit": material.get("unit") or "支",
                "taxRate": 0,
                "taxMoney": 0,
                "taxLastMoney": amount,
            }
        ]
        data = self._request_json(
            "POST",
            "/depotHead/addDepotHeadAndDetail",
            name="/depotHead/addDepotHeadAndDetail purchase_write",
            json={
                "info": json.dumps(info, ensure_ascii=False),
                "rows": json.dumps(rows, ensure_ascii=False),
            },
            require_data_object=False,
        )
        if data is None:
            raise RuntimeError(f"failed to create purchase receipt: {number}")

    def _get_depot_detail(self, number: str) -> dict:
        data = self._request_json(
            "GET",
            "/depotHead/getDetailByNumber",
            name="/depotHead/getDetailByNumber purchase_write",
            params={"number": number},
            required_data_keys=("id", "number", "type"),
        )
        if data is None:
            raise RuntimeError(f"failed to query purchase receipt: {number}")
        detail = data.get("data") or {}
        if detail.get("number") != number or detail.get("type") != "入库":
            raise RuntimeError(f"purchase receipt detail mismatch: {detail}")
        return detail

    def _set_depot_status(self, doc_id, status: str, *, name: str) -> None:
        data = self._request_json(
            "POST",
            "/depotHead/batchSetStatus",
            name=name,
            json={"ids": str(doc_id), "status": str(status)},
            require_data_object=False,
        )
        if data is None:
            raise RuntimeError(f"failed to set purchase receipt status={status}, id={doc_id}")

    def _reverse_audited_docs(self, docs: list[dict]) -> None:
        for row in _list_perf_depot_heads(self.run_id, docs):
            if str(row.get("status")) == "1" and row.get("type") == "入库" and row.get("sub_type") == "采购":
                self._set_depot_status(
                    row["id"],
                    "0",
                    name="/depotHead/batchSetStatus purchase_write reverse_cleanup",
                )

    def _cleanup_purchase_docs(self, docs: list[dict]) -> None:
        self._reverse_audited_docs(docs)
        affected = _cleanup_perf_depot_docs(self.run_id, docs)
        residue = _count_perf_depot_residue(self.run_id, docs)
        print(
            f"[purchase_write cleanup] run_id={self.run_id}, affected={affected}, residue={residue}"
        )
        if any(residue.values()):
            raise RuntimeError(f"purchase_write residue exists: {residue}")
        for doc in docs:
            if doc in self.created_docs:
                self.created_docs.remove(doc)

    @task
    def purchase_write_flow(self) -> None:
        if self.flow_finished:
            raise StopUser("purchase_write flow already completed")
        material = self._get_purchase_material()
        doc = {"number": self._next_purchase_number(), "id": None}
        self.created_docs.append(doc)
        success = False
        try:
            self._add_purchase_receipt(doc["number"], material)
            detail = self._get_depot_detail(doc["number"])
            doc["id"] = detail["id"]

            self._set_depot_status(
                doc["id"],
                "1",
                name="/depotHead/batchSetStatus purchase_write audit",
            )
            audited_detail = self._get_depot_detail(doc["number"])
            if str(audited_detail.get("status")) != "1":
                raise RuntimeError(f"purchase receipt is not audited: {audited_detail}")

            self._set_depot_status(
                doc["id"],
                "0",
                name="/depotHead/batchSetStatus purchase_write reverse",
            )
            reversed_detail = self._get_depot_detail(doc["number"])
            if str(reversed_detail.get("status")) != "0":
                raise RuntimeError(f"purchase receipt is not reversed: {reversed_detail}")
            success = True
        finally:
            self._cleanup_purchase_docs([doc])
        if success:
            self.flow_finished = True
            raise StopUser("purchase_write flow completed once")


class ErpSalesWriteUser(ErpBaseUser):
    """Controlled sales write flow: create, audit, reverse audit and clean."""

    wait_time = between(1, 2)
    sales_sequence = itertools.count(1)

    def on_start(self) -> None:
        self.run_id = os.getenv("ERP_PERF_RUN_ID") or time.strftime("%Y%m%d%H%M%S")
        self.token = ""
        self.created_docs = []
        self.sales_materials = None
        self.flow_finished = False

    def on_stop(self) -> None:
        if self.created_docs:
            try:
                self._cleanup_sales_docs(list(self.created_docs))
            except Exception as exc:
                self._record_failure(
                    "sales_write cleanup",
                    f"{type(exc).__name__}: {exc}",
                )
                print(f"[sales_write cleanup failed] run_id={self.run_id}, error={exc}")

    @staticmethod
    def _business_id(key: str):
        value = BUSINESS_IDS.get(key)
        if not value:
            raise StopUser(f"ERP business id is not configured: {key}")
        if str(value).isdigit():
            return int(value)
        return value

    @staticmethod
    def _sales_materials_for_depot(depot_id) -> list[dict]:
        conn = _open_mysql()
        try:
            conn.cursor.execute(
                """
                SELECT m.id, m.name, COALESCE(e.bar_code, '') AS bar_code,
                       COALESCE(e.commodity_unit, m.unit, '支') AS unit,
                       s.depot_id
                FROM jsh_material m
                JOIN jsh_material_current_stock s
                  ON s.material_id = m.id
                 AND s.depot_id = %s
                 AND s.delete_flag = '0'
                LEFT JOIN jsh_material_extend e
                  ON e.material_id = m.id AND e.delete_flag = '0'
                WHERE m.name IN (%s, %s, %s)
                  AND m.delete_flag = '0'
                  AND COALESCE(e.bar_code, '') != ''
                ORDER BY m.id, e.id
                """,
                (depot_id, *SALES_MATERIAL_NAMES),
            )
            rows = list(conn.cursor.fetchall())
        finally:
            conn.close()
        rows_by_name = {}
        for row in rows:
            rows_by_name.setdefault(row["name"], row)
        materials = [rows_by_name.get(name) for name in SALES_MATERIAL_NAMES]
        missing = [name for name, row in zip(SALES_MATERIAL_NAMES, materials) if not row]
        if missing:
            raise RuntimeError(f"sales material pool is incomplete: {missing}")
        return materials

    def _get_sales_material(self, sequence: int, target_users: int) -> dict:
        if not self.sales_materials:
            self.sales_materials = self._sales_materials_for_depot(self._business_id("depot_id"))
        if target_users > len(self.sales_materials):
            raise RuntimeError(
                f"sales material pool is smaller than target users: materials={len(self.sales_materials)}, "
                f"users={target_users}"
            )
        return self.sales_materials[(sequence - 1) % target_users]

    def _material_stock(self, material_id, depot_id=None) -> Decimal:
        depot = depot_id or self._business_id("depot_id")
        conn = _open_mysql()
        try:
            conn.cursor.execute(
                """
                SELECT current_number
                FROM jsh_material_current_stock
                WHERE material_id = %s
                  AND depot_id = %s
                  AND delete_flag = '0'
                """,
                (material_id, depot),
            )
            row = conn.cursor.fetchone()
        finally:
            conn.close()
        if not row:
            raise RuntimeError(
                f"sales material stock not found: material_id={material_id}, depot_id={depot}"
            )
        return Decimal(str(row["current_number"]))

    def _target_user_count(self) -> int:
        value = os.getenv("ERP_PERF_USERS") or "1"
        if str(value).isdigit():
            return int(value)
        return 1

    def _sales_run_baseline_stock(self, material: dict) -> Decimal:
        with SALES_RUN_LOCK:
            key = (material["id"], material["depot_id"])
            if key not in SALES_RUN_BASELINE_STOCKS:
                SALES_RUN_BASELINE_STOCKS[key] = self._material_stock(
                    material["id"],
                    material["depot_id"],
                )
            return SALES_RUN_BASELINE_STOCKS[key]

    def _reserve_sales_user_slot(self) -> int | None:
        global SALES_RUN_STARTED_USERS
        target_users = self._target_user_count()
        with SALES_RUN_LOCK:
            if SALES_RUN_STARTED_USERS >= target_users:
                return None
            SALES_RUN_STARTED_USERS += 1
            return SALES_RUN_STARTED_USERS

    def _record_sales_user_completed(self) -> bool:
        global SALES_RUN_COMPLETED_USERS
        target_users = self._target_user_count()
        with SALES_RUN_LOCK:
            SALES_RUN_COMPLETED_USERS += 1
            completed_users = SALES_RUN_COMPLETED_USERS
            baseline_stocks = dict(SALES_RUN_BASELINE_STOCKS)
        if not baseline_stocks or completed_users < target_users:
            return False
        for (material_id, depot_id), baseline_stock in baseline_stocks.items():
            final_stock = self._material_stock(material_id, depot_id)
            if final_stock != baseline_stock:
                raise RuntimeError(
                    f"sales stock final restore mismatch: material_id={material_id}, "
                    f"depot_id={depot_id}, initial={baseline_stock}, current={final_stock}"
                )
        return True

    @staticmethod
    def _sales_run_aborted() -> bool:
        with SALES_RUN_LOCK:
            return SALES_RUN_ABORTED

    def _schedule_sales_run_stop(self, delay: int) -> None:
        global SALES_RUN_QUIT_SCHEDULED
        with SALES_RUN_LOCK:
            if SALES_RUN_QUIT_SCHEDULED:
                return
            SALES_RUN_QUIT_SCHEDULED = True
        runner = getattr(self.environment, "runner", None)
        if runner:
            import gevent
            gevent.spawn_later(delay, runner.quit)

    def _abort_sales_run(self) -> None:
        global SALES_RUN_ABORTED
        with SALES_RUN_LOCK:
            SALES_RUN_ABORTED = True
        self._schedule_sales_run_stop(3)

    def _next_sales_number(self) -> str:
        sequence = next(self.sales_sequence)
        return f"{SALES_DOC_PREFIX}_{self.run_id}_{sequence:04d}"

    def _add_sales_shipment(self, number: str, material: dict) -> None:
        unit_price = 70
        quantity = 1
        amount = unit_price * quantity
        info = {
            "number": number,
            "type": "出库",
            "subType": "销售",
            "organId": self._business_id("customer_organ_id"),
            "accountId": self._business_id("settle_account_id"),
            "totalPrice": amount,
            "changeAmount": 0,
            "debt": amount,
            "discount": 0,
            "discountMoney": 0,
            "discountLastMoney": amount,
            "otherMoney": 0,
            "operTime": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "0",
        }
        rows = [
            {
                "name": material["name"],
                "barCode": material["bar_code"],
                "depotId": material["depot_id"],
                "operNumber": quantity,
                "unitPrice": unit_price,
                "allPrice": amount,
                "unit": material.get("unit") or "支",
                "taxRate": 0,
                "taxMoney": 0,
                "taxLastMoney": amount,
            }
        ]
        data = self._request_json(
            "POST",
            "/depotHead/addDepotHeadAndDetail",
            name="/depotHead/addDepotHeadAndDetail sales_write",
            json={
                "info": json.dumps(info, ensure_ascii=False),
                "rows": json.dumps(rows, ensure_ascii=False),
            },
            require_data_object=False,
        )
        if data is None:
            raise RuntimeError(f"failed to create sales shipment: {number}")

    def _get_depot_detail(self, number: str) -> dict:
        data = self._request_json(
            "GET",
            "/depotHead/getDetailByNumber",
            name="/depotHead/getDetailByNumber sales_write",
            params={"number": number},
            required_data_keys=("id", "number", "type"),
        )
        if data is None:
            raise RuntimeError(f"failed to query sales shipment: {number}")
        detail = data.get("data") or {}
        if detail.get("number") != number or detail.get("type") != "出库":
            raise RuntimeError(f"sales shipment detail mismatch: {detail}")
        return detail

    def _set_depot_status(self, doc_id, status: str, *, name: str) -> None:
        data = self._request_json(
            "POST",
            "/depotHead/batchSetStatus",
            name=name,
            json={"ids": str(doc_id), "status": str(status)},
            require_data_object=False,
        )
        if data is None:
            raise RuntimeError(f"failed to set sales shipment status={status}, id={doc_id}")

    def _reverse_audited_docs(self, docs: list[dict]) -> None:
        for row in _list_perf_depot_heads(self.run_id, docs):
            if str(row.get("status")) == "1" and row.get("type") == "出库" and row.get("sub_type") == "销售":
                self._set_depot_status(
                    row["id"],
                    "0",
                    name="/depotHead/batchSetStatus sales_write reverse_cleanup",
                )

    def _cleanup_sales_docs(self, docs: list[dict]) -> None:
        self._reverse_audited_docs(docs)
        affected = _cleanup_perf_depot_docs(self.run_id, docs)
        residue = _count_perf_depot_residue(self.run_id, docs)
        print(
            f"[sales_write cleanup] run_id={self.run_id}, affected={affected}, residue={residue}"
        )
        if any(residue.values()):
            raise RuntimeError(f"sales_write residue exists: {residue}")
        for doc in docs:
            if doc in self.created_docs:
                self.created_docs.remove(doc)

    @task
    def sales_write_flow(self) -> None:
        if self.flow_finished:
            raise StopUser("sales_write flow already completed")
        if self._sales_run_aborted():
            self.flow_finished = True
            raise StopUser("sales_write run already aborted")
        try:
            sequence = self._reserve_sales_user_slot()
            if sequence is None:
                self.flow_finished = True
                raise StopUser("sales_write target user slots already used")
            target_users = self._target_user_count()
            material = self._get_sales_material(sequence, target_users)
            quantity = Decimal("1")
            baseline_stock = self._sales_run_baseline_stock(material)
            initial_stock = self._material_stock(material["id"], material["depot_id"])
        except Exception as exc:
            self._record_failure(
                "sales_write setup",
                f"{type(exc).__name__}: {exc}",
            )
            self.flow_finished = True
            self._abort_sales_run()
            raise StopUser(f"sales_write setup failed: {exc}")
        if initial_stock < quantity:
            self._record_failure(
                "sales_write stock precheck",
                f"sales_write stopped: stock is insufficient for {material['name']}, "
                f"material_id={material['id']}, depot_id={material['depot_id']}, "
                f"stock={initial_stock}, required={quantity}",
            )
            self.flow_finished = True
            self._abort_sales_run()
            raise StopUser(
                f"sales_write stopped: stock is insufficient for {material['name']}, "
                f"material_id={material['id']}, depot_id={material['depot_id']}, "
                f"stock={initial_stock}, required={quantity}"
            )
        if baseline_stock < quantity:
            self._record_failure(
                "sales_write stock precheck",
                f"sales_write stopped: baseline stock is insufficient for selected material, "
                f"material_id={material['id']}, depot_id={material['depot_id']}, "
                f"stock={baseline_stock}, required={quantity}",
            )
            self.flow_finished = True
            self._abort_sales_run()
            raise StopUser(
                f"sales_write stopped: baseline stock is insufficient for selected material, "
                f"material_id={material['id']}, depot_id={material['depot_id']}, "
                f"stock={baseline_stock}, required={quantity}"
            )

        doc = {"number": f"{SALES_DOC_PREFIX}_{self.run_id}_{sequence:04d}", "id": None}
        self.created_docs.append(doc)
        success = False
        flow_error = None
        cleanup_error = None
        try:
            self._add_sales_shipment(doc["number"], material)
            detail = self._get_depot_detail(doc["number"])
            doc["id"] = detail["id"]

            self._set_depot_status(
                doc["id"],
                "1",
                name="/depotHead/batchSetStatus sales_write audit",
            )
            audited_detail = self._get_depot_detail(doc["number"])
            if str(audited_detail.get("status")) != "1":
                raise RuntimeError(f"sales shipment is not audited: {audited_detail}")

            audited_stock = self._material_stock(material["id"], material["depot_id"])
            expected_audited_stock = initial_stock - quantity
            if target_users == 1 and audited_stock != expected_audited_stock:
                raise RuntimeError(
                    f"sales stock after audit mismatch: initial={initial_stock}, "
                    f"current={audited_stock}, expected={expected_audited_stock}"
                )
            if audited_stock < Decimal("0"):
                raise RuntimeError(f"sales stock after audit is negative: current={audited_stock}")

            self._set_depot_status(
                doc["id"],
                "0",
                name="/depotHead/batchSetStatus sales_write reverse",
            )
            reversed_detail = self._get_depot_detail(doc["number"])
            if str(reversed_detail.get("status")) != "0":
                raise RuntimeError(f"sales shipment is not reversed: {reversed_detail}")

            restored_stock = self._material_stock(material["id"], material["depot_id"])
            if target_users == 1 and restored_stock != initial_stock:
                raise RuntimeError(
                    f"sales stock after reverse mismatch: initial={initial_stock}, current={restored_stock}"
                )
            if restored_stock < Decimal("0"):
                raise RuntimeError(f"sales stock after reverse is negative: current={restored_stock}")
            success = True
        except Exception as exc:
            flow_error = exc
        finally:
            try:
                self._cleanup_sales_docs([doc])
            except Exception as exc:
                cleanup_error = exc
        if cleanup_error is not None:
            self._record_failure(
                "sales_write cleanup",
                f"{type(cleanup_error).__name__}: {cleanup_error}",
            )
            self.flow_finished = True
            self._abort_sales_run()
            raise StopUser(f"sales_write cleanup failed: {cleanup_error}")
        if flow_error is not None:
            self._record_failure(
                "sales_write flow",
                f"{type(flow_error).__name__}: {flow_error}",
            )
            self.flow_finished = True
            self._abort_sales_run()
            raise StopUser(f"sales_write flow failed: {flow_error}")
        if success:
            try:
                is_final_user = self._record_sales_user_completed()
            except Exception as exc:
                self._record_failure(
                    "sales_write final stock restore",
                    f"{type(exc).__name__}: {exc}",
                )
                self.flow_finished = True
                self._abort_sales_run()
                raise StopUser(f"sales_write final stock restore failed: {exc}")
            if is_final_user:
                self._schedule_sales_run_stop(1)
            self.flow_finished = True
            raise StopUser("sales_write flow completed once")
