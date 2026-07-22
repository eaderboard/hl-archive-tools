"""Worked example: extract every liquidation from Hyperliquid's fills archive.

Why this example: liquidations are the one data class you cannot self-collect. The
public tape (`recentTrades`, ws `trades`) has no liquidation flag; only per-user
`userFills` does, and that needs the address up front -- circular for market-wide work.
So the archive is the route, and it is ~211 GB to find the ~0.1% of fills that are
liquidations.

Handles BOTH fill schemas. Sample the oldest and newest object before trusting either:

    node_fills/hourly/YYYYMMDD/H.lz4           line = [user, fill]
    node_fills_by_block/hourly/YYYYMMDD/H.lz4  line = {block_time, events: [[user, fill]]}

Usage (on an in-region instance):

    python -m hlarchive.liquidations --out /tmp/liq.jsonl.gz \
        [--upload-bucket my-bucket --upload-key liq/liquidations.jsonl.gz]
"""
from __future__ import annotations

import argparse
import json

from .stream_extract import extract, upload

BUCKET = "hl-mainnet-node-data"
PREFIXES = ["node_fills/hourly/", "node_fills_by_block/hourly/"]
NEEDLE = b'"liquidation"'
REGION = "ap-northeast-1"


def _row(day: str, block_time, user, fill: dict) -> dict:
    liq = fill.get("liquidation") or {}
    return {
        "day": day,
        "block_time": block_time,
        "time": fill.get("time"),
        "coin": fill.get("coin"),
        "px": fill.get("px"),
        "sz": fill.get("sz"),
        "side": fill.get("side"),
        "dir": fill.get("dir"),
        "closed_pnl": fill.get("closedPnl"),
        "start_position": fill.get("startPosition"),
        "fee": fill.get("fee"),
        # NOTE: `tid` is NOT unique. One liquidation filling against several makers
        # emits one row per counterparty leg, all sharing a tid. Dedupe on tid before
        # any count-based aggregation or counts inflate ~33%.
        "tid": fill.get("tid"),
        "oid": fill.get("oid"),
        "hash": fill.get("hash"),
        "crossed": fill.get("crossed"),
        "counterparty_user": user,
        "liquidated_user": liq.get("liquidatedUser"),
        "mark_px": liq.get("markPx"),
        "method": liq.get("method"),
    }


def parse(key: str, line: bytes) -> list[dict]:
    """Both schemas -> a flat row list."""
    day = key.split("/hourly/")[1].split("/")[0]
    try:
        d = json.loads(line)
    except Exception:            # noqa: BLE001 - a torn line must not kill the object
        return []

    if isinstance(d, list):                       # OLD: [user, fill]
        if len(d) == 2 and isinstance(d[1], dict) and "liquidation" in d[1]:
            return [_row(day, None, d[0], d[1])]
        return []

    if isinstance(d, dict):                       # BY_BLOCK: {..., events: [[user, fill]]}
        bt = d.get("block_time")
        out = []
        for ev in (d.get("events") or []):
            if (isinstance(ev, list) and len(ev) == 2
                    and isinstance(ev[1], dict) and "liquidation" in ev[1]):
                out.append(_row(day, bt, ev[0], ev[1]))
        return out

    return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/liquidations.jsonl.gz")
    ap.add_argument("--upload-bucket")
    ap.add_argument("--upload-key", default="liq/liquidations.jsonl.gz")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    extract(bucket=BUCKET, prefixes=PREFIXES, parse=parse, out_path=args.out,
            prefilter=NEEDLE, workers=args.workers, region=REGION)

    if args.upload_bucket:
        upload(args.out, args.upload_bucket, args.upload_key, region=REGION)
        print(f"uploaded -> s3://{args.upload_bucket}/{args.upload_key}")


if __name__ == "__main__":
    main()
