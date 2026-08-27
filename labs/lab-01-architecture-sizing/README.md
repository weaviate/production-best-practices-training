# Lab 1 — Architecture & Sizing (paper + workbook)

## Purpose & objectives

Design a defensible Weaviate architecture and capacity estimate from a
workload card, labeling every assumption and its uncertainty.

| Objective | Coverage |
|---|---|
| **TO-1** Architecture & capacity (Create/Evaluate) | Primary — full sizing + topology decision record |
| EO-1.1 | 12-input workload characterization + estimator arithmetic with uncertainty |
| EO-1.2 | Source-of-truth decision, idempotent ingestion (deterministic IDs, DLQ) |
| EO-1.3 | WCD shared/dedicated vs BYOC responsibility allocation |

**No cluster needed.** This lab is deliberately paper + workbook: sizing is
a thinking discipline, not a command.

## Scenario

You are the platform team for one of three *Acme-adjacent* workloads
(cards below — illustrative, fully fictional). Leadership wants a deployment
recommendation this week: deployment model, topology, tenancy, shard/replica
plan, index family, and a memory/disk estimate they can budget against.

## Prerequisites & preflight

Nothing to install. Preflight = you can open the estimator sheet:

```bash
ls ../../course/participant-workbook.md && echo "workbook found"
```
Expected output: `... participant-workbook.md` then `workbook found`.

## Timebox — 30 minutes

| Checkpoint | At minute |
|---|---|
| T1 workload profile filled (12 inputs) | 8 |
| T2 memory/disk estimate with ranges | 16 |
| T3 topology + index/tenancy decisions | 22 |
| T4 unknowns + validation plan logged | 25 |
| Team debrief (defend one decision) | 25–30 |

## Participant tasks

Your team is assigned **one** card (A, B, or C).

1. **Characterize** the workload into the 12 sizing inputs (workbook sheet).
   Mark each input `given` / `derived` / `assumed`. *Prompt: which single
   input, if wrong by 2x, hurts you most?*
2. **Estimate memory** using the course estimator: raw vector bytes =
   `objects x dims x 4B`; rule of thumb memory ≈ `2 x vector bytes`; graph
   overhead ≈ `objects x maxConnections x ~10B`. Then apply your chosen
   quantization (RQ-8 ≈ /4 on the vector residency; caveat: rescoring reads
   originals from disk). Write LOW / EXPECTED / HIGH — not one number.
3. **Estimate disk** (objects + vectors + indexes ≈ 2–3x raw payload+vectors;
   plus backup space) and growth runway to 18 months.
4. **Decide topology**: deployment model (WCD shared / WCD dedicated /
   BYOC), node count, replication factor, shard count, single vs
   multi-tenant collections, index family (HNSW / flat / HFresh — note
   maturity labels), quantization. One sentence of trade-off per choice.
   *Prompt: which of these choices are effectively immutable (shards,
   distance metric, efConstruction/maxConnections, enabled quantization) and
   what is your rebuild path if wrong?*
5. **Ingestion contract**: source of truth (Weaviate or upstream?),
   deterministic IDs, retry/DLQ behavior, backpressure. Three bullet points.
6. **Log unknowns + validation plan**: what you'd measure in week 1 to
   correct this estimate (the Lab 2 harness is exactly that tool).
7. **Debrief**: defend ONE decision in 60 seconds; name the assumption that
   would flip it.

## Workload cards (12-input profiles)

### Card A — "Atlas" : read-heavy single-tenant catalog
| # | Input | Value |
|---|---|---|
| 1 | Objects | 120M (single collection) |
| 2 | Vectors | 1 named vector, 768-dim float32 |
| 3 | Avg object payload | 2.0 KB (title/desc/attrs) |
| 4 | Tenants | 1 (internal product search) |
| 5 | Peak read QPS | 900 (filtered vector + hybrid) |
| 6 | Ingest | 250k objects/day steady; 5M/day during quarterly re-embeds |
| 7 | Growth | +25%/yr objects |
| 8 | Latency SLO | p95 ≤ 100 ms |
| 9 | Recall target | ≥ 0.98 @10 |
| 10 | Availability | 99.95% |
| 11 | RPO / RTO | 24 h / 8 h |
| 12 | Compliance & budget | SOC 2; active cloud cost-reduction program |

### Card B — "Bazaar" : 5,000-tenant B2B SaaS
| # | Input | Value |
|---|---|---|
| 1 | Objects | ~150M total (avg 30k/tenant, p99 tenant 2M) |
| 2 | Vectors | 1 named vector, 512-dim float32 |
| 3 | Avg object payload | 1.5 KB |
| 4 | Tenants | 5,000 (B2B storefronts), +40%/yr; ~20% inactive >30 days |
| 5 | Peak read QPS | 600 aggregate (business-hours peaks, per-tenant spiky) |
| 6 | Ingest | 5M objects/day across tenants (onboarding bursts) |
| 7 | Growth | tenant-count led; object count +60%/yr |
| 8 | Latency SLO | p95 ≤ 150 ms per tenant |
| 9 | Recall target | ≥ 0.95 @10 |
| 10 | Availability | 99.9% |
| 11 | RPO / RTO | 1 h / 4 h |
| 12 | Compliance & budget | ISO 27001; per-tenant cost must stay flat as tenants grow |

### Card C — "Chronicle" : high-ingest logs + semantic search
| # | Input | Value |
|---|---|---|
| 1 | Objects | 2B rolling (30-day retention window) |
| 2 | Vectors | 1 named vector, 256-dim float32 |
| 3 | Avg object payload | 0.5 KB |
| 4 | Tenants | 12 internal teams (one collection each is acceptable) |
| 5 | Peak read QPS | 80 (investigations; bursty) |
| 6 | Ingest | 800 obj/s sustained (~69M/day); bursts to 5,000 obj/s |
| 7 | Growth | 2x volume/yr |
| 8 | Latency SLO | p95 ≤ 300 ms |
| 9 | Recall target | ≥ 0.90 @10 |
| 10 | Availability | 99.5% |
| 11 | RPO / RTO | 4 h / 12 h |
| 12 | Compliance & budget | none strict; HARD infra budget cap (memory is the enemy) |

## Hints (progressive — try before peeking)

<details><summary>Hint 1 (gentle)</summary>
Start from memory: it dominates cost for HNSW. 768-dim = 3,072 B/vector.
Multiply before you philosophize.
</details>

<details><summary>Hint 2 (directional)</summary>
Card A: 120M x 3,072 B ≈ 369 GB raw vectors — the x2 rule says ~740 GB
before you even discuss node counts. What does RQ-8 do to that? Card B:
per-tenant shards mean the hash-tree + shard overheads and INACTIVE/OFFLOAD
states matter more than raw math. Card C: 2B x 1,024 B = 2 TB of vectors —
pure in-memory HNSW is the wrong opening bid; which index family was built
for exactly this (and what maturity label does it carry)?
</details>

<details><summary>Hint 3 (nearly the answer)</summary>
A: HNSW + RQ-8, RF3, single-digit shard count, WCD dedicated or BYOC —
justify with the 99.95% + SOC2 + cost program. B: multi-tenancy with tenant
states + offloading for dormant tenants; autoTenantCreation OFF; watch
PROMETHEUS_MONITORING_GROUP cardinality. C: HFresh (GA in 1.38, RQ built-in,
searchProbe set explicitly) or aggressive quantization + async indexing;
retention via scheduled deletes/TTL and shard planning for churn.
</details>

## Verify your work

Paper lab — verification is the rubric, not a script:

- [ ] all 12 inputs filled, each labeled given/derived/assumed
- [ ] memory & disk shown as LOW/EXPECTED/HIGH with arithmetic visible
- [ ] every topology choice has a stated trade-off
- [ ] immutable-at-creation choices explicitly flagged with a rebuild path
- [ ] ≥ 3 unknowns with a concrete validation step each

(worked arithmetic for all three cards).

## Reset & cleanup

None (paper). Keep the sheet — the capstone reuses your Card outputs.

## Recovery path if environment fails

Not applicable in the usual sense (no environment). If the *workbook* is
unavailable: `fallback/sizing-worksheet.md` contains a standalone copy of
the 12-input sheet and estimator formulas, plus a fully worked example for a
fourth card so no team is blocked waiting for a facilitator.

## Safety boundary

No cluster access, no customer data. The estimator teaches estimation
discipline — **never present its output as an official Weaviate sizing
guarantee** (CLAUDE.md rule 9); ranges + validation plan are mandatory parts
of a "done" answer.
