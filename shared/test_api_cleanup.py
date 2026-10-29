# -*- coding: utf-8 -*-
"""API 后置数据清理的离线事务测试。"""
import pytest

from api import conftest as api_conftest
from shared import database


class FakeConnection:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.closed = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed += 1


class FakeCursor:
    def __init__(self, fail_at=None):
        self.calls = []
        self.rowcount = 0
        self.fail_at = fail_at
        self.closed = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.fail_at == len(self.calls):
            raise ValueError('mock SQL failure')
        self.rowcount = len(self.calls)

    def fetchall(self):
        return []

    def close(self):
        self.closed += 1


class FakeMysql:
    def __init__(self, fail_at=None):
        self.conn = FakeConnection()
        self.cursor = FakeCursor(fail_at=fail_at)
        self.closed = 0

    def close(self):
        self.closed += 1


def test_cleanup_is_run_scoped_and_commits_once(monkeypatch):
    fake_mysql = FakeMysql()
    run_id = '1792723046447'
    monkeypatch.setattr(api_conftest.DebugTalk, '_fixed_ts', run_id)
    monkeypatch.setattr(api_conftest, 'ConnectMysql', lambda: fake_mysql)

    affected = api_conftest._cleanup_run_data()

    assert fake_mysql.conn.commits == 1
    assert fake_mysql.conn.rollbacks == 0
    assert fake_mysql.closed == 1
    assert len(fake_mysql.cursor.calls) == 11
    assert '初始库存' in affected
    assert list(affected)[:5] == [
        '收付款明细-按业务单据', '收付款明细-按收付款单', '出入库明细', '收付款单', '出入库单'
    ]
    assert list(affected)[5:9] == ['初始库存', '当前库存', '商品扩展', '商品']
    for sql, params in fake_mysql.cursor.calls[:9]:
        assert "'AUTO_API_'" in sql
        assert "REGEXP CONCAT('_', %s" in sql
        assert params == (run_id,)
        assert run_id not in sql
    assert fake_mysql.cursor.calls[9][1] == ('AUTO_API_D_mvkd0jlb',)
    assert fake_mysql.cursor.calls[10][1] == ('AUTO_API_U_mvkd0jlb',)


def test_cleanup_rolls_back_and_reports_failure(monkeypatch):
    fake_mysql = FakeMysql(fail_at=6)
    monkeypatch.setattr(api_conftest.DebugTalk, '_fixed_ts', '1792723046447')
    monkeypatch.setattr(api_conftest, 'ConnectMysql', lambda: fake_mysql)

    with pytest.raises(RuntimeError, match='后置数据清理失败并已回滚') as exc_info:
        api_conftest._cleanup_run_data()

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert fake_mysql.conn.commits == 0
    assert fake_mysql.conn.rollbacks == 1
    assert fake_mysql.closed == 1


def test_cleanup_connection_failure_is_not_treated_as_skip(monkeypatch):
    monkeypatch.setattr(api_conftest.DebugTalk, '_fixed_ts', '1792723046447')

    def fail_to_connect():
        raise ConnectionError('mock connection failure')

    monkeypatch.setattr(api_conftest, 'ConnectMysql', fail_to_connect)

    with pytest.raises(ConnectionError, match='mock connection failure'):
        api_conftest._cleanup_run_data()


def test_database_connection_error_propagates(monkeypatch):
    def fail_to_connect(**_kwargs):
        raise ConnectionError('mock pymysql failure')

    monkeypatch.setattr(database.pymysql, 'connect', fail_to_connect)

    with pytest.raises(ConnectionError, match='mock pymysql failure'):
        database.ConnectMysql()


def test_database_query_error_propagates_and_closes(monkeypatch):
    fake_conn = FakeConnection()
    fake_cursor = FakeCursor(fail_at=1)
    mysql = database.ConnectMysql.__new__(database.ConnectMysql)
    mysql.conn = fake_conn
    mysql.cursor = fake_cursor

    with pytest.raises(ValueError, match='mock SQL failure'):
        mysql.query_all('SELECT 1')

    assert fake_cursor.closed == 1
    assert fake_conn.closed == 1
