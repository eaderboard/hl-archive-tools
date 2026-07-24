# hl-archive-tools

Tools and field notes for working with **Hyperliquid's public S3 archives** — plus the
general pattern for mining any large requester-pays archive without paying for bulk
egress or filling a laptop.

Hyperliquid publishes several hundred GB of historical market and chain data as
requester-pays S3. The official docs are thin and explicitly warn that "there is no
guarantee of timely updates and data may be missing." This repo records what is
**actually there** (measured, not assumed) and gives you a way to extract a narrow slice
from a wide archive cheaply.

## The core idea: stream, don't download

**Every size below is a snapshot, not a constant — this archive grows ~0.5 GB/day
(measured 2026-07-22: 211 GB over 422 days). Recompute before trusting a number here;
see `docs/HL_ARCHIVE_MAP.md` for how.**

The naive approach — `aws s3 cp` the archive to your machine — fails twice: the fills
archive alone was ~211 GB as of 2026-07-22 (egress ≈ $19 at that size, and rising ~$0.09
worth per day), and most laptops don't have room for an archive that only grows.

The fix is to put the compute next to the data — this scales with the archive, not
against it:

```
        S3 (ap-northeast-1)  ──free, same-region──▶  small EC2  ──▶  filtered result
          any size, growing                          30 GB disk     ~0.1% of source*
```
*\* observed on the liquidation extract (2026-07-22): 211 GB in → 561 MB out. Your
predicate's selectivity will differ; this is the shape, not a promise.*

Each object is fetched, decompressed **in memory**, filtered, and discarded. Peak disk
stays at O(one file) **regardless of how large the archive becomes** — only time and
bandwidth scale with source size. The instance self-terminates when done.

Measured on a `m7i-flex.large` (2 vCPU, free-tier eligible) against the 2026-07-22
211 GB snapshot: **~4.2 GB/min**, ~50 minutes, **total cost under $1** including EBS.
At ~0.5 GB/day growth, expect run time to grow by roughly 15 seconds per month you
wait — reflow the archive periodically rather than assuming last quarter's numbers.

## What's here

| path | what |
|---|---|
| `src/hlarchive/stream_extract.py` | the generic in-region streaming extractor |
| `src/hlarchive/liquidations.py` | worked example: extract liquidations from the fills archive |
| `docs/HL_ARCHIVE_MAP.md` | **measured** coverage, sizes and gotchas for every prefix |
| `docs/RESEARCH_DISCIPLINE.md` | how to not fool yourself when testing ideas on this data |
| `examples/run_on_ec2.md` | end-to-end: IAM, launch, extract, tear down |

## Quick facts worth knowing before you start

- **Liquidations exist only in the fills archive.** Hyperliquid's public trade tape
  (`recentTrades`, ws `trades`) carries **no liquidation flag**. Only per-user
  `userFills` does, and that requires knowing the address in advance — circular for
  market-wide work. So the archive (or a third-party indexer) is the only route.
- **Two fill schemas.** `node_fills/hourly/` stores each line as `[user, fill]`;
  `node_fills_by_block/hourly/` stores `{block_time, events: [[user, fill], ...]}`.
  Handle both or you will silently lose the earlier period.
- **One row per counterparty leg.** A single liquidation filling against several makers
  appears as several rows sharing one `tid`. **Dedupe on `tid`** before counting or your
  counts inflate ~33%.
- **Coverage is uneven and partly abandoned.** `node_trades/` stops mid-2025.
  `market_data/` (L2 books) has gaps. The fills archive, by contrast, measured complete.
  See the map.

## Install

```bash
uv venv && uv pip install -e .
```

Requires `boto3` and `lz4`. AWS credentials with S3 read; the archives are
**requester-pays**, so you pay for requests and any egress out of region.

## License

MIT. Data belongs to Hyperliquid; this repo only contains tools and measurements.
