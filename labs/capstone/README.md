# Capstone — Acme Change Proposal (exec-facing)

## Purpose & objectives

Integrate the whole day into one defensible, executive-quality change
proposal with evidence, risk, and rollback.

| Objective | Coverage |
|---|---|
| **TO-1 … TO-7** integrated | Architecture, evidence-based tuning, HA, observability, safe change, security posture, exec communication |
| Direct rubric | 4 dimensions x 4 levels — see `assessments/` (instructor copy in `assessments/instructor-only/`) |

## Scenario — the Acme change brief

Acme Retail (illustrative: 40M objects, 768-dim, 1.2k tenants, 450 QPS
peak, p95 ≤ 120 ms, recall@10 ≥ 0.97, 99.9% availability, RPO 1h / RTO 4h,
SOC 2, cost program in flight) currently runs **Weaviate 1.36.x**. The
platform team proposes, in one change window this quarter:

1. **Upgrade 1.36 → 1.38** (through 1.37 — one minor at a time, latest patch
   per hop; no documented breaking changes on this path, but verify),
2. **Migrate the support-docs collection (28M of the 40M objects) from HNSW
   to HFresh** to cut memory cost (HFresh GA in 1.38; RQ built-in;
   `searchProbe` must be set explicitly — the default is contradicted
   between docs and release notes, C-1),
3. **under live traffic**, with a **rollback path** at every stage.

Leadership asks your team for a GO / NO-GO / GO-WITH-CONDITIONS
recommendation.

## Prerequisites & preflight

Your artifacts from the day: Lab 1 sizing sheet, Lab 2 benchmark JSONs +
recommendation, Lab 3 prediction matrix + boundary paragraph, Lab 4 incident
record. No new cluster work is required (evidence reuse); the lab cluster
stays available for spot checks:

```bash
make verify    # expected: All 7 checks passed.
```

## Timebox — 16 minutes in class: 14 min team work + 2 min share-out (+ assessment follows)

| Checkpoint | At minute |
|---|---|
| T1 decision + upgrade sequencing outline | 4 |
| T2 evidence table cited (labs 1–4) | 8 |
| T3 risk register + rollback criteria | 11 |
| T4 executive summary (≤ 150 words) done | 14 |
| Share-out (one decision + one risk per team) | 14–16 |

## Deliverable spec (one page + appendix)

1. **Decision** — GO / NO-GO / GO-WITH-CONDITIONS, one sentence.
2. **Plan** — upgrade sequence (1.36.x → 1.37.latest → 1.38.3; backup +
   health gate before each hop; canary node/collection; rolling restart
   preconditions: RF ≥ 2, `maxUnavailable: 0`), then HFresh migration as
   **blue-green behind a collection alias** (new collection, dual-write or
   re-ingest, measure, atomic alias repoint) — never in-place.
3. **Evidence** — cite at least: your Lab 2 recall/latency deltas (with the
   dataset-scale caveat verbatim), Lab 3 consistency/convergence
   observations, Lab 4 signals you would watch during the change
   (queue depth, batch shape, p95, config hash).
4. **Risk & rollback** — top 3 risks with detection signal + rollback
   trigger + rollback action each (e.g., alias repoint back; downgrade
   floor caveat; searchProbe misconfiguration symptom).
5. **Security/compliance note** — what the change does NOT alter (authN/Z,
   backup schedule), and the restore-test you'll run before the window.
6. **Executive summary** — ≤ 150 words, no jargon, cost + risk + customer
   impact.

## Hints (progressive)

<details><summary>Hint 1</summary>
The rubric rewards NAMING uncertainty ("our recall evidence is from a 50k
proxy dataset; we gate on a 1M-object canary re-measurement") over false
confidence.
</details>

<details><summary>Hint 2</summary>
Rollback for a migration behind an alias is an alias repoint — seconds, no
data loss, as long as you kept the old collection. Rollback for a version
upgrade is NOT symmetric (multi-node downgrade floor) — say what you'd do
instead (restore from the pre-hop backup).
</details>

## Verify your work

Self-check against the public rubric dimensions (decision quality, evidence
use, risk/rollback rigor, communication). Exemplar: instructor-only, at

## Reset & cleanup

None required. If you ran spot checks: `make reset`.

## Recovery path if environment fails

The capstone is evidence-reuse by design. If your own Lab 2/3 artifacts are
missing, use the labeled-simulated fallbacks:
`../lab-02-benchmark-tuning/fallback/*.json` and
`../lab-03-failure-recovery/fallback/failure-drill-transcript.md`, and say
in the brief that the evidence is simulated.

## Safety boundary

This is a fictional customer scenario. Do not import real customer numbers
unless the instructor has activated a customer overlay
(`customer/customer-profile.yaml`); never mix other customers' data in.
Estimates are not vendor sizing guarantees.
