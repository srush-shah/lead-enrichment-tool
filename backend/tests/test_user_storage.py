from __future__ import annotations

import os
import tempfile

import pytest

from backend import cache


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("backend.cache.settings.cache_db_path", tmp.name)
    cache.init_db()
    yield
    os.unlink(tmp.name)


def test_init_db_is_idempotent():
    # Running init twice on the same file must not raise (CREATE IF NOT EXISTS).
    cache.init_db()
    cache.init_db()
    uid = cache.upsert_user("a@example.com")
    assert uid == 1


def test_upsert_user_is_idempotent_and_lowercases():
    a = cache.upsert_user("Foo@Example.com")
    b = cache.upsert_user("foo@example.com")
    c = cache.upsert_user("  FOO@example.com  ")
    assert a == b == c


def test_save_and_list_lead_roundtrip():
    uid = cache.upsert_user("sdr@example.com")
    lid = cache.save_lead(uid, "hash1", '{"input":{"name":"X"}}', "A", 87.5)
    assert lid > 0
    leads, total = cache.list_leads(uid)
    assert total == 1
    assert leads[0]["id"] == lid
    assert leads[0]["tier"] == "A"
    assert leads[0]["score"] == 87.5


def test_list_leads_pagination_and_ordering():
    uid = cache.upsert_user("sdr@example.com")
    ids = [cache.save_lead(uid, f"h{i}", "{}", "B", float(i)) for i in range(5)]
    page1, total = cache.list_leads(uid, limit=2, offset=0)
    page2, _ = cache.list_leads(uid, limit=2, offset=2)
    assert total == 5
    # Newest first.
    assert page1[0]["id"] == ids[-1]
    assert page1[1]["id"] == ids[-2]
    assert page2[0]["id"] == ids[-3]


def test_get_lead_user_isolation():
    a = cache.upsert_user("a@example.com")
    b = cache.upsert_user("b@example.com")
    lid = cache.save_lead(a, "h", "{}", "A", 90.0)
    assert cache.get_lead(a, lid) is not None
    assert cache.get_lead(b, lid) is None  # cross-user lookup returns nothing


def test_update_lead_scoped_to_owner():
    a = cache.upsert_user("a@example.com")
    b = cache.upsert_user("b@example.com")
    lid = cache.save_lead(a, "h", "{}", "A", 90.0)
    assert cache.update_lead(lid, b, "{}", "C", 30.0) is False  # wrong owner
    assert cache.update_lead(lid, a, '{"v":2}', "C", 30.0) is True
    assert cache.get_lead(a, lid)["tier"] == "C"
