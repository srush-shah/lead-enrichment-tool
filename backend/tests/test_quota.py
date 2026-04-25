from __future__ import annotations

import os
import tempfile

import pytest

from backend import cache, quota
from backend.config import NEWSAPI_BATCH_CEILING, NEWSAPI_DAILY_CAP


@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr("backend.cache.settings.cache_db_path", tmp.name)
    cache.init_db()
    yield
    os.unlink(tmp.name)


SPEC = quota.QuotaSpec(
    api="newsapi",
    hard_cap=NEWSAPI_DAILY_CAP,
    batch_ceiling=NEWSAPI_BATCH_CEILING,
    reserved_for_realtime=NEWSAPI_DAILY_CAP - NEWSAPI_BATCH_CEILING,
)


def test_reserve_increments_counter():
    assert cache.usage_today("newsapi") == 0
    quota.reserve(SPEC, batch_mode=True)
    assert cache.usage_today("newsapi") == 1


def test_batch_ceiling_blocks_before_hard_cap():
    for _ in range(NEWSAPI_BATCH_CEILING):
        quota.reserve(SPEC, batch_mode=True)
    with pytest.raises(quota.QuotaExhausted) as exc:
        quota.reserve(SPEC, batch_mode=True)
    assert exc.value.reason == "quota_reserved_for_realtime"
    assert exc.value.used == NEWSAPI_BATCH_CEILING
    assert exc.value.ceiling == NEWSAPI_BATCH_CEILING


def test_realtime_can_use_reserved_pool():
    # Fill batch ceiling.
    for _ in range(NEWSAPI_BATCH_CEILING):
        quota.reserve(SPEC, batch_mode=True)
    # Batch blocked, realtime still works.
    quota.reserve(SPEC, batch_mode=False)
    assert cache.usage_today("newsapi") == NEWSAPI_BATCH_CEILING + 1


def test_hard_cap_blocks_everything():
    for _ in range(NEWSAPI_DAILY_CAP):
        quota.reserve(SPEC, batch_mode=False)
    with pytest.raises(quota.QuotaExhausted) as exc:
        quota.reserve(SPEC, batch_mode=False)
    assert exc.value.reason == "daily_cap_reached"


def test_release_decrements():
    quota.reserve(SPEC, batch_mode=True)
    quota.release(SPEC)
    assert cache.usage_today("newsapi") == 0


def test_release_floor_at_zero():
    quota.release(SPEC)
    assert cache.usage_today("newsapi") == 0
