#!/usr/bin/env python3

import ctypes
import ctypes.util
import os
import errno
import shutil
import sys
import time
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# Paste your current OpenAlex institutional API key here.
API_KEY = 

LOG_FILE = Path.home() / "openalex_usage_log" / "openalex_usage_usd.csv"

BOX_FILE = Path(
    "/Users/yanhan/Library/CloudStorage/Box-Box/"
    "RE Department Access/"
    "Scholarly Communication Unit/"
    "Publication-Data-Mining-Analysis/"
    "OpenAlex/"
    "OpenAlex_usage_log/"
    "openalex_usage_usd.csv"
)


def copy_to_box(attempts=6, wait_seconds=20):
    """Copy the full local CSV to Box, retrying if Box Drive is busy."""
    for attempt in range(1, attempts + 1):
        try:
            BOX_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = BOX_FILE.with_name(BOX_FILE.name + ".tmp")
            shutil.copyfile(LOG_FILE, tmp)
            os.replace(tmp, BOX_FILE)
            if BOX_FILE.stat().st_size == LOG_FILE.stat().st_size:
                print(f"Copied to Box on attempt {attempt}: {BOX_FILE}")
                return True
            print(f"Attempt {attempt}: size mismatch after copy", file=sys.stderr)
        except OSError as e:
            print(f"Attempt {attempt}: Box copy failed: {e}", file=sys.stderr)
        time.sleep(wait_seconds)
    print("WARNING: Box copy failed. Local CSV is safe; next run will retry.",
          file=sys.stderr)
    return False


URL = "https://api.openalex.org/rate-limit"

FIELDNAMES = [
    "timestamp_utc",
    "timestamp_arizona",
    "http_status",
    "daily_budget_usd",
    "daily_used_usd",
    "daily_remaining_usd",
    "prepaid_balance_usd",
    "prepaid_remaining_usd",
    "onetime_balance_usd",
    "onetime_remaining_usd",
    "total_available_usd",
    "singleton_cost_usd",
    "list_cost_usd",
    "search_cost_usd",
    "search_rerank_cost_usd",
    "rerank_extra_cost_usd",
    "content_cost_usd",
    "semantic_cost_usd",
    "text_cost_usd",
    "resets_at",
    "resets_in_seconds",
]


def format_usd(value):
    """
    Format a number as a USD amount with four decimal places.

    Examples:
        20     -> $20.0000
        0.01   -> $0.0100
        0.0001 -> $0.0001
        None   -> blank field
    """
    if value is None or value == "":
        return ""

    try:
        amount = Decimal(str(value))
        return f"${amount:.4f}"
    except (InvalidOperation, ValueError, TypeError):
        return ""


def as_decimal(value):
    """Convert a response value to Decimal for calculations."""
    if value is None or value == "":
        return Decimal("0")

    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def allow_dataless_materialization():
    """Let this process download Box Drive 'dataless' files (macOS File Provider)."""
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
        IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES = 3
        IOPOL_SCOPE_PROCESS = 0
        IOPOL_MATERIALIZE_DATALESS_FILES_ON = 2
        rc = libc.setiopolicy_np(
            IOPOL_TYPE_VFS_MATERIALIZE_DATALESS_FILES,
            IOPOL_SCOPE_PROCESS,
            IOPOL_MATERIALIZE_DATALESS_FILES_ON,
        )
        if rc == 0:
            print("Dataless file materialization enabled")
        else:
            print("setiopolicy_np failed, errno", ctypes.get_errno(), file=sys.stderr)
    except Exception as e:
        print("Could not set materialization policy:", e, file=sys.stderr)

def main():
    allow_dataless_materialization()
    response = requests.get(
        URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
        },
        timeout=30,
    )

    print("HTTP status:", response.status_code)
    response.raise_for_status()

    data = response.json()
    rate_limit = data.get("rate_limit", {})
    endpoint_costs = rate_limit.get("endpoint_costs_usd", {})

    now_utc = dt.datetime.now(dt.timezone.utc)
    now_arizona = now_utc.astimezone(
        ZoneInfo("America/Phoenix")
    )

    daily_remaining = as_decimal(
        rate_limit.get("daily_remaining_usd")
    )
    prepaid_remaining = as_decimal(
        rate_limit.get("prepaid_remaining_usd")
    )

    # The current response does not provide one-time balances directly
    # in USD. Convert them using the USD value of one credit as derived
    # from daily_budget_usd divided by credits_limit.
    daily_budget = as_decimal(
        rate_limit.get("daily_budget_usd")
    )
    credits_limit = as_decimal(
        rate_limit.get("credits_limit")
    )

    if credits_limit > 0:
        usd_per_credit = daily_budget / credits_limit
    else:
        usd_per_credit = Decimal("0")

    onetime_balance_usd = (
        as_decimal(rate_limit.get("onetime_credits_balance"))
        * usd_per_credit
    )

    onetime_remaining_usd = (
        as_decimal(rate_limit.get("onetime_credits_remaining"))
        * usd_per_credit
    )

    total_available_usd = (
        daily_remaining
        + prepaid_remaining
        + onetime_remaining_usd
    )

    row = {
        "timestamp_utc": now_utc.isoformat(),
        "timestamp_arizona": now_arizona.isoformat(),
        "http_status": response.status_code,

        # Daily account amounts
        "daily_budget_usd": format_usd(
            rate_limit.get("daily_budget_usd")
        ),
        "daily_used_usd": format_usd(
            rate_limit.get("daily_used_usd")
        ),
        "daily_remaining_usd": format_usd(
            rate_limit.get("daily_remaining_usd")
        ),

        # Prepaid amounts
        "prepaid_balance_usd": format_usd(
            rate_limit.get("prepaid_balance_usd")
        ),
        "prepaid_remaining_usd": format_usd(
            rate_limit.get("prepaid_remaining_usd")
        ),

        # One-time amounts converted from credits to USD
        "onetime_balance_usd": format_usd(
            onetime_balance_usd
        ),
        "onetime_remaining_usd": format_usd(
            onetime_remaining_usd
        ),

        # Combined remaining daily, prepaid, and one-time amount
        "total_available_usd": format_usd(
            total_available_usd
        ),

        # Cost of each API operation
        "singleton_cost_usd": format_usd(
            endpoint_costs.get("singleton")
        ),
        "list_cost_usd": format_usd(
            endpoint_costs.get("list")
        ),
        "search_cost_usd": format_usd(
            endpoint_costs.get("search")
        ),
        "search_rerank_cost_usd": format_usd(
            endpoint_costs.get("search_rerank")
        ),
        "rerank_extra_cost_usd": format_usd(
            endpoint_costs.get("rerank_extra")
        ),
        "content_cost_usd": format_usd(
            endpoint_costs.get("content")
        ),
        "semantic_cost_usd": format_usd(
            endpoint_costs.get("semantic")
        ),
        "text_cost_usd": format_usd(
            endpoint_costs.get("text")
        ),

        # Reset information
        "resets_at": rate_limit.get("resets_at", ""),
        "resets_in_seconds": rate_limit.get(
            "resets_in_seconds", ""
        ),
    }

    LOG_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    new_file = (
        not LOG_FILE.exists()
        or LOG_FILE.stat().st_size == 0
    )

    for attempt in range(1, 7):
        try:
            with LOG_FILE.open("a", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(file, fieldnames=FIELDNAMES, extrasaction="ignore")
                if new_file:
                    writer.writeheader()
                writer.writerow(row)
            break
        except OSError as e:
            if e.errno != errno.EDEADLK or attempt == 6:
                raise
            print(f"Box busy (attempt {attempt}), retrying in 20s...")
            time.sleep(20)

        if new_file:
            writer.writeheader()

        writer.writerow(row)

    print("Logged OpenAlex usage successfully.")
    print("Execution time (MST):", now_arizona.strftime("%Y-%m-%d %H:%M:%S %Z"))
    print("Log file:", LOG_FILE.resolve())
    print("File exists:", LOG_FILE.exists())
    print("File size:", LOG_FILE.stat().st_size, "bytes")
    print("Daily budget:", row["daily_budget_usd"])
    print("Used today:", row["daily_used_usd"])
    print("Remaining today:", row["daily_remaining_usd"])
    print("Total available:", row["total_available_usd"])
    copy_to_box()


if __name__ == "__main__":
    main()
