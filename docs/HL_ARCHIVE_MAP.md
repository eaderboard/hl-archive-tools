# Hyperliquid public archives — measured map

Everything below was **measured**, not read off documentation. Hyperliquid's own docs
warn that "there is no guarantee of timely updates and data may be missing", and that
turns out to be load-bearing: one prefix is abandoned mid-2025, another changed line
schema partway through, and the L2 books have real gaps while the fills do not.

Access: **requester-pays**, region `ap-northeast-1`. Verify bounds yourself before
relying on any range — these were true on 2026-07-22.

## Bucket `hyperliquid-archive` — market data

| prefix | content | coverage | size |
|---|---|---|---|
| `market_data/<YYYYMMDD>/<hour>/l2Book/<COIN>.lz4` | full L2 book snapshots, **~666/hour (~5s cadence)**, price/size/order-count per level | 2023-04-15 → current | **19 MB/hour** all coins · **383 MB/day** · **~330 GB** total · **5.6 MB/day** for one major |
| `asset_ctxs/<YYYYMMDD>.csv.lz4` | per-asset funding, open interest, mark price | 2023-05-20 → current | ~10 MB/day (~4 GB) |
| `Testnet/` | testnet mirror | — | — |

**L2 books are the genuinely unique asset here.** The public API gives you the *current*
book only; this is the sole source of historical depth/spread/imbalance back to 2023.
It is also far smaller than people assume — lz4 compresses order books extremely well,
so a single coin's entire multi-year history is only a few GB.

**`asset_ctxs` is redundant** — funding, OI and mark are all available free from the
live info API. Don't pay egress for it.

**Gaps exist** in `market_data/` (e.g. 2025-10-17→22, 2025-11-18→25 were absent). Check
before assuming a contiguous range.

## Bucket `hl-mainnet-node-data` — chain / execution

| prefix | content | coverage | note |
|---|---|---|---|
| `node_fills_by_block/hourly/` | every fill; line = `{block_time, events: [[user, fill]]}` | 2025-07-27 → current | carries the `liquidation` object |
| `node_fills/hourly/` | every fill; line = `[user, fill]` — **different schema** | 2025-05-25 → 2025-07-27 | handle both or lose this period |
| `node_trades/hourly/` | trade tape | 2025-03-22 → **2025-06-21** | **abandoned** |
| `misc_events_by_block/hourly/` | non-trade L1 events (`time`/`hash`/`inner`) — deposits, withdrawals, transfers, staking | 2025-09-27 → current | ~11 MB/hour |
| `explorer_blocks/<blocknum-bucket>/` | raw blocks | full chain | very raw; expensive to mine |
| `replica_cmds/<restart-ts>/` | node replica command logs | 2025-01 → | infra artifact, not research data |

Combined fills across both schemas: **10,131 objects / ~211 GB / 422 days**, and — unlike
the L2 books — **zero missing days** when measured (360/360 for the by-block prefix).

## Gotchas that will bite you

1. **Liquidations live only in fills.** No liquidation flag on the public tape; only
   per-user `userFills` has one, and that needs the address up front. Market-wide
   liquidation data cannot be self-collected from the free API.
2. **`tid` is not unique.** One liquidation filling against several makers emits one row
   per counterparty leg, all sharing a `tid`. Dedupe before counting (~33% inflation
   otherwise).
3. **Both sides are present.** Fills include the *counterparty* legs (`Open Long` /
   `Open Short`) alongside the liquidated legs (`Close Long` / `Close Short`) — useful
   if you care who absorbed a cascade, noise if you don't. Filter on `dir`.
4. **Coverage metadata can mislead.** A per-symbol "coverage_from" may reflect the
   symbol's *general* data, not the specific data type you want. Check the per-type
   field, and if it is absent do not silently fall back — you will conclude a class of
   data reaches years further back than it does.
5. **Immediately-filled `Ioc` orders are still queryable by cloid** — verified against
   real filled orders; `orderStatus` resolves them rather than returning `unknownOid`.

## Cost model

Never bulk-copy to a laptop: 211 GB of egress is ≈ $19 **and** most machines lack the
space. Run the extraction in-region (S3 → EC2 same-region transfer is free), filter
there, bring home only the result. A full liquidation extract cost **well under $1**.

Note that a new AWS account is restricted to **free-tier instance types**;
`m7i-flex.large` (8 GiB, up to 12.5 Gbps) is the best of those and sustained ~4.2 GB/min
on 2 vCPU. Larger instance types are simply refused until the restriction lifts.
