# Not fooling yourself with archive data

Cheap access to hundreds of GB of history is a good way to generate confident nonsense.
These are the practices that survived contact with real data — method only, no findings.

## Preregister, then look once

Write the hypothesis, the exact rule, the outcome metric, the horizon, **and the pass
bar** to a file and commit it *before* running anything. Then run it once.

A preregistration is worth writing only if it can fail. Ours look like:

> PASS requires mean-centered forward return t-stat ≥ 2.0 at the primary horizon AND
> mean net return > 0 after costs. Power floor: ≥ 200 events — below that the verdict is
> NO-EVIDENCE, not PASS, regardless of point estimate. One spec, one primary horizon. No
> re-parameterising after seeing results. A fail is recorded as a fail.

The power floor matters as much as the t-stat. Without it, a "pass" on 12 events reads
the same as a pass on 12,000.

## Declare the universe before you see it

Two failure modes, both easy and both fatal:

- **Survivorship.** Testing on the symbols that exist *today* silently conditions on
  survival. An edge that only appears on a long-history subset is usually an edge that
  only appears on things that didn't die.
- **Lookahead in universe construction.** Filtering by "average daily volume over the
  last 30 days" and then backtesting years of history uses the future to pick the past.
  Use a point-in-time universe or accept the result is inflated.

## Mean-center cross-sectionally

For anything cross-sectional, subtract the per-timestamp mean before measuring. Otherwise
you are largely measuring market beta and will "discover" that things go up in bull
markets.

## Watch the median, not just the mean

A strategy with a positive mean and a **negative median** is a lottery, not an edge: the
typical trade loses and a few outliers carry the average. That distribution is fragile —
it depends on the tail repeating, which is exactly what a survivor-biased or
regime-limited sample over-promises. Report mean, median, win rate, and t-stat together.

## Collinear filters don't stack

Stacking seven confirming conditions feels rigorous and usually isn't: if they all say
"price went up on volume", you have one filter and a smaller sample. Check the hit rate
of each condition alone. If three of them fire ~50% of the time, they are coin flips
contributing nothing but a shrunken N.

## Count every test you run

Every variant — a new horizon, a threshold tweak, an ablation, a different mapping —
raises the multiple-testing burden. Track the lineage count explicitly and raise the
bar as it grows (deflated Sharpe or equivalent). A spec that passes at t=2.0 after
twenty undeclared variants has not passed.

## Split occupancy from outcome

Check that the data can even support the test **before** looking at any outcome: event
counts, symbol coverage, per-period balance, control availability. This is label-only —
the outcome variable is never constructed — so a failed occupancy check costs you
nothing and tells you the instrument is unsuitable rather than the idea is wrong.

Distinguish the two verdicts in writing. "The instrument cannot answer this" is a
completely different fact from "the idea is dead", and conflating them either burns a
good idea or resurrects a dead one.

## Beware floors no instrument can meet

If you write "≥ N observations in every year from 2020" for a venue that launched in
2023, you have written an unsatisfiable spec. Waiting will never fix it. When a
requirement cannot be met by any reachable source, record it as an **instrument** outcome
and close it honestly — and resist the temptation to relax the floor after seeing that
nothing clears it. That is goalpost-moving; recognising the spec was impossible is not.

## Have something adversarial review the result

Self-review finds the bugs you already thought about. On live-money code especially, get
an independent pass whose brief is *find the bug*, not *approve this*. In our experience
the useful findings were consistently the ones the author's own tests couldn't have
caught — including a case where the fix introduced a new failure mode that the existing
regression suite, not the new tests, exposed.

## Bank perishable data immediately, analyse later

Some sources are irreplaceable (rolling retention windows, third-party free tiers that
may vanish). Collection is not analysis: bank it now, keep it sealed, and preregister
before you look. Confusing "I have the data" with "I may now go fishing in it" is how
the discipline above gets quietly abandoned.
