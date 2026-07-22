"""Generic in-region streaming extractor for large (requester-pays) S3 archives.

Fetch each object, decompress it in memory, keep only the rows a predicate selects,
discard the rest. Peak disk stays at O(one object), so the archive can be arbitrarily
larger than the machine -- 211 GB streams through a 30 GB box without trouble. Results
append to local disk as they are found and upload once at the end.

Run this ON an instance in the SAME REGION as the bucket: S3 -> EC2 same-region transfer
is free, so the only real cost is instance time. Pulling the same data to a laptop pays
egress on every byte you were going to throw away anyway.

Two failure modes this is deliberately shaped around, both learned the hard way:

1. **Do not submit every task up front.** `{executor.submit(...): k for k in keys}` keeps
   each completed Future -- and therefore its *result* -- alive until the pool exits. On
   a 10k-object archive that OOMs long before the work finishes, even though results are
   being written to disk. Process in bounded batches and drop each Future as it is
   consumed.
2. **Do not assume one schema.** Long-lived archives change shape mid-life. Sample the
   oldest and newest object before writing a parser, and make the parser handle both.
"""
from __future__ import annotations

import gzip
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Iterable, Iterator

import boto3
import lz4.frame

DEFAULT_WORKERS = 4      # each worker holds one decompressed object in memory
DEFAULT_BATCH = 200      # bounded so completed Futures are freed as we go


def list_keys(s3, bucket: str, prefixes: Iterable[str], *,
              suffix: str = ".lz4", requester_pays: bool = True) -> list[str]:
    """Every object under `prefixes` ending in `suffix`, sorted."""
    extra = {"RequestPayer": "requester"} if requester_pays else {}
    keys: list[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for pref in prefixes:
        for page in paginator.paginate(Bucket=bucket, Prefix=pref, **extra):
            keys.extend(o["Key"] for o in page.get("Contents", [])
                        if o["Key"].endswith(suffix))
    return sorted(keys)


def iter_lines(s3, bucket: str, key: str, *,
               requester_pays: bool = True,
               contains: bytes | None = None) -> Iterator[bytes]:
    """Yield the lines of one lz4 object, streaming.

    `contains` is a cheap whole-file reject: if the needle is absent from the raw bytes,
    the object is skipped without touching JSON at all. On a sparse predicate (ours kept
    ~0.1% of rows) this is most of the speedup.
    """
    extra = {"RequestPayer": "requester"} if requester_pays else {}
    body = s3.get_object(Bucket=bucket, Key=key, **extra)["Body"].read()
    raw = lz4.frame.decompress(body)
    del body
    if contains is not None and contains not in raw:
        return
    # BytesIO rather than raw.split(b"\n"): a ~1 GB object should not also materialise a
    # list of every line in it.
    for line in io.BytesIO(raw):
        if contains is None or contains in line:
            yield line


def extract(
    *,
    bucket: str,
    prefixes: Iterable[str],
    parse: Callable[[str, bytes], list[dict]],
    out_path: str,
    prefilter: bytes | None = None,
    workers: int = DEFAULT_WORKERS,
    batch: int = DEFAULT_BATCH,
    requester_pays: bool = True,
    region: str | None = None,
    log=print,
) -> int:
    """Stream every object, apply `parse(key, line) -> [row, ...]`, write rows to
    `out_path` (gzipped JSONL). Returns the row count.

    `parse` receives raw bytes so it can decide cheaply; return `[]` to skip a line.
    One bad object never kills the run -- it is logged and skipped.
    """
    s3 = boto3.client("s3", region_name=region)
    keys = list_keys(s3, bucket, prefixes, requester_pays=requester_pays)
    log(f"objects: {len(keys):,}")

    done = total = 0
    with gzip.open(out_path, "wt") as fh:
        for i in range(0, len(keys), batch):
            chunk = keys[i:i + batch]
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {
                    ex.submit(_parse_one, s3, bucket, k, parse, prefilter,
                              requester_pays): k
                    for k in chunk
                }
                for f in as_completed(futs):
                    key = futs[f]
                    done += 1
                    try:
                        rows = f.result()
                    except Exception as e:                  # noqa: BLE001
                        log(f"FAIL {key}: {type(e).__name__}: {e}")
                        continue
                    for r in rows:
                        fh.write(json.dumps(r) + "\n")
                    total += len(rows)
                    del rows
                    f._result = None       # release the Future's payload immediately
                futs.clear()
            fh.flush()
            log(f"  {done:,}/{len(keys):,} objects | {total:,} rows")

    log(f"extracted {total:,} rows from {len(keys):,} objects "
        f"-> {out_path} ({os.path.getsize(out_path) / 1e6:.0f} MB)")
    return total


def _parse_one(s3, bucket, key, parse, prefilter, requester_pays) -> list[dict]:
    out: list[dict] = []
    for line in iter_lines(s3, bucket, key, requester_pays=requester_pays,
                           contains=prefilter):
        out.extend(parse(key, line))
    return out


def upload(out_path: str, bucket: str, key: str, region: str | None = None) -> None:
    """Ship the (small) result somewhere durable before the instance terminates."""
    boto3.client("s3", region_name=region).upload_file(out_path, bucket, key)
