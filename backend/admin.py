"""Operational helpers. Not exposed via the API.

Primary use: pin today's local quota counter to the cap when the
external API state is already exhausted but this app's counter doesn't
know yet (e.g., quota burned outside this process, or before the
Postgres-backed counters were deployed).

Usage:
    DATABASE_URL="..." python -m backend.admin mark-exhausted gemini
    DATABASE_URL="..." python -m backend.admin mark-exhausted newsapi

Run from the deploy environment (or with DATABASE_URL pointed at the
production Postgres) so it writes to the same store the FastAPI
service reads from.
"""
from __future__ import annotations

import argparse
import sys

from . import quota_store
from .config import GEMINI_DAILY_CAP, NEWSAPI_DAILY_CAP


CAPS = {"gemini": GEMINI_DAILY_CAP, "newsapi": NEWSAPI_DAILY_CAP}


def main() -> None:
    ap = argparse.ArgumentParser(description="EliseAI GTM admin helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)

    mark = sub.add_parser(
        "mark-exhausted",
        help="Pin today's local counter to the daily cap so further calls gate locally.",
    )
    mark.add_argument("api", choices=list(CAPS))

    show = sub.add_parser(
        "show",
        help="Print today's counter for an API.",
    )
    show.add_argument("api", choices=list(CAPS))

    args = ap.parse_args()

    if args.cmd == "mark-exhausted":
        cap = CAPS[args.api]
        quota_store.set_usage(args.api, cap)
        print(f"{args.api}: usage_today set to {cap}", file=sys.stderr)
    elif args.cmd == "show":
        used = quota_store.usage_today(args.api)
        print(f"{args.api}: {used}/{CAPS[args.api]}")
    else:
        ap.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
