# Lab 2 — Benchmark & Tune (one variable at a time)

## Purpose & objectives

Measure a baseline, change exactly ONE thing, re-measure, and write a
recommendation that names its own limits.

| Objective | Coverage |
|---|---|
| **TO-2** Index/compression/ingestion/query engineering | Primary |
| EO-2.1 | Index family consequences (HNSW vs HFresh preset) |
| EO-2.2 | Quantization trade-off measured (RQ-8 preset), rescoring effect |
| EO-2.3 | Server-side batching already used by seed; failed-object discipline |
| EO-2.4 | ef / filter-strategy tuned one variable at a time vs recall@10 + p95/p99 |

## Scenario

Acme's cost program wants quantization or a cheaper index; product wants
recall ≥ 0.97 and no latency regressions. You have 40 minutes to produce
evidence, not opinions. The harness (`acme.bench`) enforces the
methodology: warm-up, repeated trials, exact ground truth, machine-readable
output.

## Prerequisites & preflight

```bash
make verify
```
Expected: table with **7/7 PASS** ending `All 7 checks passed.`
(If counts FAIL: `make reset`. If cluster down: `make up && make seed`.)

## Timebox — 40 minutes

| Checkpoint | At minute |
|---|---|
| T1 baseline measured & saved | 10 |
| T2 team's ONE change chosen + justified in writing | 14 |
| T3 change measured | 28 |
| T4 before/after table + recommendation w/ caveat | 35 |
| Micro-debrief | 35–40 |

## Participant tasks

1. **Baseline.**
   ```bash
   PYTHONPATH=src python -m acme.bench --preset baseline
   ```
   Record recall@10, p50/p95/p99, throughput from the printed table; the
   JSON lands in `labs/results/`. *Prompt: before running — write down your
   predicted recall@10 for HNSW defaults on this dataset.*
2. **Choose ONE variable** (per team, assigned or negotiated):
   `rq8` | `ef-sweep` | `hfresh` | `filter-strategy`. Write ONE sentence:
   what will improve, what might pay for it.
3. **Measure it.**
   ```bash
   PYTHONPATH=src python -m acme.bench --preset <your-preset>
   ```
   (`rq8` builds + seeds its collection on first run, ~1–2 min extra;
   `ef-sweep` and `filter-strategy` mutate ONLY hot-mutable settings and
   restore them afterwards.)
4. **Compare.** Build a before/after table from the two JSON files
   (`config_fingerprint` identifies each run). *Prompts: is the recall delta
   worth the cost delta? Which percentiles moved — median or tail? Why might
   tail latency move when median doesn't?*
5. **Recommend.** 5 sentences max: decision, evidence (cite numbers), risk,
   rollback, and the **dataset-scale caveat** (mandatory — the harness
   prints it; 50k x 256 ≠ 40M x 768).

## Hints (progressive)

<details><summary>Hint 1</summary>
The JSON files are the source of truth; the console table rounds. `jq` is
your friend: <code>jq '.results[] | {variant, recall_at_10, p95_ms}' labs/results/*.json</code>
</details>

<details><summary>Hint 2</summary>
ef-sweep: recall should rise monotonically with ef while p95 climbs — find
the knee. filter-strategy: brand filters are UNcorrelated with vector
clusters; that is ACORN's best case, so expect sweeping to pay a visible
latency price at similar recall.
</details>

<details><summary>Hint 3</summary>
rq8: expect recall within ~1–2 points of baseline (rescoring recovers most
loss) — the win is memory (~4x on vector residency), which this small
dataset cannot show you directly. Say so in the recommendation: what you
measured (recall/latency) vs what you inferred (memory).
</details>

## Verify your work

```bash
ls labs/results/bench-*.json | wc -l    # >= 2 (baseline + your change)
PYTHONPATH=src python -m acme.verify
```
Expected: ≥2 result files; verify still **7/7 PASS** (proves your run left
the cluster in baseline state — presets restore mutated settings).

Done means: baseline JSON + change JSON + before/after table + 5-sentence
recommendation including the scale caveat.

## Reset & cleanup

```bash
make reset          # drops AcmeProductRQ8 etc., re-seeds baseline
```
Idempotent; run it if anything looks off. Result JSONs are yours — keep them
for the capstone.

## Recovery path if environment fails (5-minute fallback)

Use the prepared evidence in `fallback/`:
`bench-baseline.json`, `bench-rq8.json`, `bench-ef-sweep.json`,
`bench-hfresh.json`, `bench-filter-strategy.json` — same schema the harness
writes, **clearly labeled `"simulated": true`** with plausible values.
Do tasks 4–5 (comparison + recommendation) from those files. The analysis
and the caveat discipline — not the button-pressing — are the assessed
skills.

## Safety boundary

* Presets only mutate hot-mutable settings (`ef`, `filterStrategy`) and
  always restore them; immutable knobs (efConstruction, maxConnections,
  quantization on an existing collection) are exercised via SEPARATE
  collections, never in-place.
* Do not run two presets concurrently (you'd be measuring each other).
* Numbers from this lab NEVER go into customer sizing docs — mechanism and
  method transfer; absolute values do not.
