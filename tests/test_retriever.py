"""app.rag.retriever 单元测试：pgvector 检索、降级行为、get_retriever 接线。

全程离线：假 embedder + 假连接（构造器注入），不打 psycopg / 真实数据库 / 网络。
"""

import logging

import pytest

from app.api import deps
from app.config import Settings
from app.rag import NullRetriever, PgVectorRetriever


@pytest.fixture(autouse=True)
def _clear_retriever_cache():
    """get_retriever 的 id 键缓存不得在测试间串扰。"""
    deps._RETRIEVERS.clear()
    yield
    deps._RETRIEVERS.clear()


class FakeEmbedder:
    """返回固定 1024 维零向量，不联网；fail=True 时模拟向量化 API 故障。"""

    def __init__(self, dims=1024, fail=False):
        self.dims = dims
        self.fail = fail
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding api down")
        return [[0.0] * self.dims for _ in texts]


class _FakeCursor:
    """模拟 psycopg 游标：上下文管理器 + execute/fetchall。"""

    def __init__(self, rows, executed, fail=False):
        self._rows = rows
        self._executed = executed
        self._fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._executed.append((sql, params))
        if self._fail:
            raise RuntimeError("query failed")

    def fetchall(self):
        return self._rows


class _FakeConnection:
    """模拟 psycopg 连接：cursor() 返回假游标，close() 记标记。"""

    def __init__(self, rows=(), fail_query=False):
        self.rows = rows
        self.fail_query = fail_query
        self.closed = False
        self.executed = []

    def cursor(self):
        return _FakeCursor(self.rows, self.executed, fail=self.fail_query)

    def close(self):
        self.closed = True


def _connect_ok(conn):
    return lambda dsn: conn


def _connect_fail(dsn):
    raise RuntimeError("db down")


def _settings(database_url=""):
    return Settings(deepseek_api_key="k", database_url=database_url, _env_file=None)


def test_null_retriever_returns_empty_list():
    """占位实现契约不变：恒返回空引用。"""
    assert NullRetriever().search("布洛芬怎么吃") == []
    assert NullRetriever().search("x", limit=3) == []


def test_search_returns_citations():
    rows = [
        ("泰诺", "用法用量", "口服。成人一次1-2片，一日3次。", 0.12),
        ("芬必得", "禁忌", "对布洛芬过敏者禁用。", 0.40),
    ]
    conn = _FakeConnection(rows=rows)
    embedder = FakeEmbedder()
    retriever = PgVectorRetriever(
        embedder=embedder, dsn="postgresql://fake", connect=_connect_ok(conn)
    )

    citations = retriever.search("布洛芬怎么吃")

    assert [c.brand_name for c in citations] == ["泰诺", "芬必得"]
    assert [c.section for c in citations] == ["用法用量", "禁忌"]
    assert citations[0].excerpt == "口服。成人一次1-2片，一日3次。"
    assert embedder.calls == [["布洛芬怎么吃"]]


def test_excerpt_is_first_200_chars_and_exact_substring():
    """铁律：excerpt 必须是 chunk 原文的精确子串（取前 200 字符）。"""
    content = "长" * 300
    conn = _FakeConnection(rows=[("泰诺", "注意事项", content, 0.5)])
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(), dsn="postgresql://fake", connect=_connect_ok(conn)
    )

    (citation,) = retriever.search("q")

    assert citation.excerpt == content[:200]
    assert citation.excerpt in content


def test_search_sends_cosine_sql_with_limit():
    """铁律：检索必须走 pgvector 余弦相似度（<=>），limit 参数生效。"""
    conn = _FakeConnection(rows=())
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(), dsn="postgresql://fake", connect=_connect_ok(conn)
    )

    retriever.search("q", limit=3)

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    vector = [0.0] * 1024
    assert params == (vector, vector, 3)
    assert "<=>" in sql
    assert "ORDER BY" in sql
    assert "LIMIT %s" in sql
    assert "brand_name" in sql and "section" in sql and "content" in sql


def test_empty_result_returns_empty_list():
    conn = _FakeConnection(rows=())
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(), dsn="postgresql://fake", connect=_connect_ok(conn)
    )

    assert retriever.search("没有匹配的问题") == []


def test_connect_failure_returns_empty_and_logs(caplog):
    """数据库连接失败 → 降级为空引用，不抛异常、不炸 /chat。"""
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(), dsn="postgresql://fake", connect=_connect_fail
    )

    with caplog.at_level(logging.WARNING, logger="app.rag"):
        assert retriever.search("q") == []

    assert any("降级" in r.message for r in caplog.records)


def test_query_failure_returns_empty_and_logs(caplog):
    """查询失败 → 降级 + 关闭并复位连接（下次 search 自动重连）。"""
    conn = _FakeConnection(rows=(), fail_query=True)
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(), dsn="postgresql://fake", connect=_connect_ok(conn)
    )

    with caplog.at_level(logging.WARNING, logger="app.rag"):
        assert retriever.search("q") == []

    assert conn.closed is True
    assert retriever._conn is None
    assert any("降级" in r.message for r in caplog.records)


def test_search_retries_connection_after_failure():
    class _Switchable:
        def __init__(self):
            self.calls = 0
            self.fail = True

        def __call__(self, dsn):
            self.calls += 1
            if self.fail:
                raise RuntimeError("db down")
            return _FakeConnection(rows=[("泰诺", "用法用量", "口服", 0.1)])

    connect = _Switchable()
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(), dsn="postgresql://fake", connect=connect
    )

    assert retriever.search("q") == []
    connect.fail = False
    citations = retriever.search("q")

    assert len(citations) == 1
    assert connect.calls == 2  # 失败后确实重连了


def test_embedder_failure_returns_empty_and_logs(caplog):
    """向量化失败 → 降级为空引用，且不丢弃健康的数据库连接。"""
    conn = _FakeConnection(rows=[("泰诺", "用法用量", "口服", 0.1)])
    retriever = PgVectorRetriever(
        embedder=FakeEmbedder(fail=True),
        dsn="postgresql://fake",
        connect=_connect_ok(conn),
    )

    with caplog.at_level(logging.WARNING, logger="app.rag"):
        assert retriever.search("q") == []

    assert conn.closed is False
    assert conn.executed == []  # SQL 压根没发出去
    assert any("向量化" in r.message for r in caplog.records)


def test_get_retriever_without_database_url_returns_null():
    """未配置 DATABASE_URL → NullRetriever 占位（向后兼容）。"""
    retriever = deps.get_retriever(_settings(database_url=""))

    assert isinstance(retriever, NullRetriever)


def test_get_retriever_with_database_url_returns_pgvector():
    """配置了 DATABASE_URL → PgVectorRetriever；构造不触网（无需真实数据库）。"""
    retriever = deps.get_retriever(
        _settings(database_url="postgresql://u:p@localhost:5432/db")
    )

    assert isinstance(retriever, PgVectorRetriever)


def test_get_retriever_caches_per_settings_instance():
    s1 = _settings(database_url="postgresql://a")
    s2 = _settings(database_url="postgresql://a")

    assert deps.get_retriever(s1) is deps.get_retriever(s1)
    assert deps.get_retriever(s2) is not deps.get_retriever(s1)
