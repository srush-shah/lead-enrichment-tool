from __future__ import annotations

from dataclasses import dataclass

from . import cache


class QuotaExhausted(Exception):
    def __init__(self, api: str, used: int, ceiling: int, reason: str):
        self.api = api
        self.used = used
        self.ceiling = ceiling
        self.reason = reason
        super().__init__(f"{api} quota exhausted: {used}/{ceiling} ({reason})")


@dataclass
class QuotaSpec:
    api: str
    hard_cap: int
    batch_ceiling: int
    reserved_for_realtime: int


def check_budget(spec: QuotaSpec, batch_mode: bool) -> None:
    used = cache.usage_today(spec.api)
    ceiling = spec.batch_ceiling if batch_mode else spec.hard_cap
    if used >= ceiling:
        reason = (
            "quota_reserved_for_realtime"
            if batch_mode and used < spec.hard_cap
            else "daily_cap_reached"
        )
        raise QuotaExhausted(spec.api, used, ceiling, reason)


def reserve(spec: QuotaSpec, batch_mode: bool) -> int:
    check_budget(spec, batch_mode)
    return cache.increment_usage(spec.api)


def release(spec: QuotaSpec) -> None:
    cache.decrement_usage(spec.api)
