# Participant Workbook

**Advanced: Production Best Practices with Weaviate** · Instructor: Mila Vernazza · 420 instructional minutes
Workbook version aligned to course baseline **Weaviate v1.38.3 / weaviate-client 4.22.0** (see `VERSION_MATRIX.md`).

> **How to use this workbook.** This is *your* working document. You will write in it during every segment and lab, and it is designed to stay useful after class: every worksheet doubles as a template you can rerun against your own environment. Where the course uses numbers, they come from the **Acme Retail scenario, which is illustrative** — an invented, customer-neutral scenario, not a real customer and not a sizing guarantee. Every computed number in this workbook is an **estimate to be validated by measurement**, never a binding commitment.
>
> **Recurring scenario (illustrative):** *Acme Retail* — product-discovery + support-search platform: 40 M objects, 768-dim vectors (2 named vectors: `content`, `title`), 1,200 tenants, 85/15 read/write, 450 QPS peak reads, 2 M objects/week ingest, +60 %/yr growth, p95 ≤ 120 ms, recall@10 ≥ 0.97, 99.9 % availability, RPO 1 h / RTO 4 h, SOC 2.

---

## Contents (aligned to the 11 segments)

| Seg | Section | Page anchor |
|---|---|---|
| 1 | Prediction sheet & production framing | §1 |
| 2 | Architecture & responsibility notes | §2 |
| 3 | **Lab 1 — Sizing worksheet** | §3 |
| 4 | Index & quantization decision worksheet | §4 |
| 5 | **Lab 2 — Benchmark record** | §5 |
| 6 | Consistency prediction matrix (6 scenarios) | §6 |
| 7 | **Lab 3 — Failure log** | §7 |
| 8 | Alert-shortlist exercise | §8 |
| 9 | **Lab 4 — Incident record** | §9 |
| 10 | Security & DR self-check checklists | §10 |
| 11 | Capstone planning, readiness gaps, 30/60/90 plan | §11 |

---

## §1 · Segment 1 — Prediction sheet (production framing)

Write **before** the reveal. Wrong predictions marked honestly are worth more than blank boxes — the delta between your prediction and reality is the day's learning signal.

**1.1 First read of the Acme scenario (illustrative).** From your role's perspective, what breaks *first* as Acme grows 60 %/yr?

| My role | Biggest risk (one line) | Confidence (L/M/H) |
|---|---|---|
| | | |

**1.2 Three framing predictions** (commit now, revisit at close):

| # | Question | My prediction (before) | Actual (end of day) |
|---|---|---|---|
| P1 | Roughly how much **memory** does Acme's vector workload need uncompressed? (order of magnitude) | | |
| P2 | With replication factor 3, a write at consistency level **ONE**, and one node down — does the write succeed? | | |
| P3 | Is a Weaviate **backup** the same thing as replication? Why/why not? | | |

**1.3 The operating loop for today:** `decide → measure → defend`. Every lab output must name its decision, its evidence, and its limits.

---

## §2 · Segment 2 — Architecture, capacity & responsibility notes

**2.1 Responsibility matrix** (mark **W** = Weaviate Cloud's job, **Y** = your job, **S** = shared; fill in per deployment model):

| Concern | WCD Shared | WCD Dedicated | BYOC Kubernetes (self-managed) |
|---|---|---|---|
| Server upgrades & patching | | | |
| Backup execution & restore | | | |
| Capacity sizing & scaling decision | | | |
| AuthN/AuthZ configuration (RBAC, keys, OIDC) | | | |
| Network isolation / TLS termination | | | |
| Monitoring stack & alert routing | | | |
| Schema & data model quality | | | |
| Ingestion pipeline correctness (idempotency, DLQ) | | | |

**2.2 Ingestion contract — my notes.** Deterministic IDs (UUIDv5 from a natural key), idempotent writes, per-object error capture, dead-letter queue, backpressure:

```
_________________________________________________________________
_________________________________________________________________
```

**2.3 Schema as an operational decision.** Explicit schema; auto-schema **off** in production; `indexFilterable` / `indexSearchable` / `indexRangeFilters` flags deliberate per property; named vectors and multi-tenancy chosen up front (several choices are effectively immutable — see §6.5):

```
_________________________________________________________________
```

---

## §3 · Segment 3 / Lab 1 — Architecture & sizing worksheet

> Rerun this worksheet with **your own production numbers** after class. All outputs are estimates with uncertainty ranges — validate by measuring a representative slice before committing budget. A spreadsheet version ships in `customer/production-readiness-scorecard.xlsx` (Inputs tab).

### 3.1 The 12 workload inputs

| # | Input | Acme value (illustrative) | **Your environment** |
|---|---|---|---|
| 1 | Objects (current corpus) | 40,000,000 | |
| 2 | Vector dimensions | 768 | |
| 3 | Named vectors per object | 2 (`content`, `title`) | |
| 4 | Tenants | 1,200 | |
| 5 | Read QPS (peak) | 450 | |
| 6 | Ingest rate | 2 M objects/week | |
| 7 | Growth (12 months) | +60 % | |
| 8 | p95 latency target | ≤ 120 ms | |
| 9 | Recall target | recall@10 ≥ 0.97 | |
| 10 | Availability target | 99.9 % | |
| 11 | RPO | 1 h | |
| 12 | RTO | 4 h | |

### 3.2 Memory estimator — walk-through

Weaviate's documented rule of thumb: **memory ≈ 2 × the raw footprint of all vectors held in memory**, plus HNSW graph overhead of **`maxConnections` × 8–10 B per object** (per in-memory vector). Each float32 dimension costs 4 B.

**Step-by-step (fill in the right column with your numbers):**

| Step | Formula | Acme (illustrative) | Yours |
|---|---|---|---|
| A. Vectors in memory | objects × named vectors | 40 M × 2 = **80 M** | |
| B. Bytes per vector | dims × 4 B | 768 × 4 = **3,072 B** | |
| C. Raw vector bytes | A × B | 80 M × 3,072 B ≈ **245.8 GB** | |
| D. Rule-of-thumb ×2 | C × 2 | **491.5 GB** | |
| E. Graph overhead | A × maxConnections × 8–10 B | 80 M × 32 × 8–10 B ≈ **20.5–25.6 GB** | |
| F. Uncompressed estimate | D + E | **≈ 512–517 GB** | |

**Quantized variants** (in-memory vector portion shrinks; originals stay on disk for rescoring; graph overhead does not shrink). Reminder — **nothing quantizes by default** in v1.38: `DEFAULT_QUANTIZATION` defaults to `none`; you must configure it, and once enabled on a collection it cannot be disabled.

| Variant | Vector compression (approx.) | Acme memory (illustrative) | Yours |
|---|---|---|---|
| None (float32) | 1× | ≈ 512–517 GB | |
| **RQ-8** (no training, enable-later OK) | ~4× | (245.8/4)×2 + E ≈ **143–149 GB** | |
| **RQ-1 / BQ** (~1 bit/dim) | ~32× | (245.8/32)×2 + E ≈ **36–41 GB** | |
| PQ (requires training, 10k–100k objects/shard first) | dims/segments-dependent (~24× at 768d/segment defaults) | ≈ 41–46 GB | |
| SQ (requires training) | ~4× | ≈ 143–149 GB | |
| HFresh (disk-based; RQ mandatory, built in) | centroid index in memory only | memory drops to centroid tier; QPS ceiling lower — benchmark it | |

**Headroom.** Set `GOMEMLIMIT` to ~80–90 % of container memory; provision node memory so your estimate fits *under* GOMEMLIMIT with room for compaction, hash trees (async replication: ~2 MB/shard single-tenant, ~16 KB/tenant multi-tenant, per node), and import spikes. Practical planning headroom used in class: **+30 %** on the estimate (illustrative rule, not a guarantee).

### 3.3 Disk estimator

| Step | Formula | Acme (illustrative) | Yours |
|---|---|---|---|
| G. Original vectors on disk | C (always stored, even when quantized) | ≈ 245.8 GB | |
| H. Object + inverted index | objects × avg object payload × LSM factor (~2, illustrative) | 40 M × 2 KB × 2 ≈ 160 GB | |
| I. Working space (compaction, WAL, snapshots) | ~25 % of G+H (illustrative) | ≈ 100 GB | |
| J. Disk estimate per full copy | G + H + I | ≈ **505 GB** | |
| K. × replication factor | J × RF | × 3 ≈ **1.5 TB** cluster-wide | |

SSDs required in practice; avoid NFS.

### 3.4 Uncertainty range & validation plan (mandatory)

| Field | Entry |
|---|---|
| Memory estimate — **low / expected / high** | ______ / ______ / ______ |
| Disk estimate — **low / expected / high** | ______ / ______ / ______ |
| Top 3 assumptions that could break the estimate | 1. ______ 2. ______ 3. ______ |
| Validation plan (what will you measure on a 1–5 % slice, and when) | |

### 3.5 Lab 1 decision record

| Decision | Choice | One-line rationale (trade-off named) |
|---|---|---|
| Deployment model (WCD shared/dedicated vs BYOC K8s) | | |
| Tenancy layout (multi-tenant collection vs collections) | | |
| Shard count (immutable at creation!) & replica factor | | |
| Index family + quantization starting point | | |
| Unknowns to resolve before go-live | | |

---

## §4 · Segment 4 — Index, ingestion & query decision worksheet

**4.1 Index decision tree — my Acme answer and reasoning:**

| Workload card | My pick (HNSW / flat / dynamic / HFresh) | Why |
|---|---|---|
| Card 1 | | |
| Card 2 | | |
| Card 3 | | |

Maturity labels @1.38.3: HNSW/flat **GA**; **HFresh GA in 1.38** (set `searchProbe` explicitly — docs and release notes disagree on the default); dynamic index **Experimental**; async indexing carries **no GA badge** in docs.

**4.2 Quantization ladder notes.** RQ-8 first (no training, ~4×, near-lossless on most datasets); RQ-1/BQ where memory dominates; PQ/SQ where justified (training required). Once set, **cannot be disabled**. `DEFAULT_QUANTIZATION` = `none` by default.

**4.3 Ingestion:** server-side batching (`batch.stream()`, GA server 1.36 / client 4.20) is the course default; always capture `failed_objects` per object; client-side modes (`dynamic`, `fixed_size`, `rate_limit`) for special cases.

**4.4 Benchmark discipline — "spot the broken benchmark" notes:** warm-up, realistic query distribution, recall@k against ground truth, p95/p99 not averages, repeated trials, **one variable at a time**:

```
_________________________________________________________________
```

---

## §5 · Segment 5 / Lab 2 — Benchmark record

One variable at a time. Record **before** and **after**; a change without a baseline is an anecdote.

| Run | Config (exact, incl. index/quantization/ef/filter strategy) | recall@10 | p50 (ms) | p95 (ms) | imports/s | Notes |
|---|---|---|---|---|---|---|
| Baseline | | | | | | |
| Change 1 (what changed: __________) | | | | | | |
| Change 2 (optional) | | | | | | |

**Before/after delta summary:**

| Metric | Before | After | Δ | Acceptable vs target? |
|---|---|---|---|---|
| recall@10 | | | | |
| p95 | | | | |
| imports/s | | | | |

**My recommendation (with limits):**

> We should ________ because ________ (evidence: ________). **Limits:** this was measured on a lab-scale dataset; before production adoption, revalidate at ≥ ____ % of production scale with production query distribution.

---

## §6 · Segment 6 — Consistency prediction matrix

**The rules you're applying** (Weaviate v1.38 facts):

- Consistency levels: **ONE** (1 replica acks/responds), **QUORUM** (`n/2 + 1` replicas), **ALL** (every replica). Write and read levels are tunable per request.
- **Overlap rule:** if `r + w > n` (read level + write level > replication factor), reads see the newest write — strongly consistent. If `r + w ≤ n`, eventual consistency is the best you get.
- **What read consistency reconciles: object versions by ID — NOT the ANN candidate list.** Tunable read consistency does not change which objects a vector query *finds*; it reconciles the retrieved objects' versions across replicas.
- **Async replication is enabled by default for any collection with RF > 1 in v1.38** (cluster-wide scheduler, shared worker pool); it converges replicas in the background via hash-tree comparison. Read repair additionally fixes divergence seen at QUORUM/ALL reads.
- Metadata (schema, tenant states) uses **Raft** and needs a voter quorum — separate from data-plane consistency.
- Delete conflicts are resolved per `deletionStrategy` — default **`TimeBasedResolution`** (also: `NoAutomatedResolution`, `DeleteOnConflict`).

**Commit your prediction BEFORE each reveal.** Score yourself: ✓ right for the right reason / ~ right answer, wrong reason / ✗ wrong.

| # | Scenario | My prediction (succeed/fail + what is returned/stored) | My reasoning (the rule I applied) | Observed / revealed | ✓/~/✗ |
|---|---|---|---|---|---|
| 1 | **RF 3, write @ ONE, then one node lost.** Does the write survive? Is it on all replicas? | | | | |
| 2 | **RF 3, read @ QUORUM where one replica is stale.** What does the client get, and what happens to the stale replica? | | | | |
| 3 | **RF 2, write @ QUORUM, 1 of 2 replicas down.** Does the write succeed? (Careful: quorum of 2 = 2.) | | | | |
| 4 | **Read @ ONE while async replication is still converging** (lag after a burst of ONE-level writes). Can you read stale or missing data? | | | | |
| 5 | **RF 3 across 3 AZs; network partition isolates one AZ (minority side).** What still works from the minority side — reads @ ONE? writes @ QUORUM? schema changes? | | | | |
| 6 | **Object deleted on one replica; a conflicting update lands on another before convergence.** With default `TimeBasedResolution`, what wins? What would `NoAutomatedResolution` do? | | | | |

**6.5 Effectively-immutable choices** (write these down — they cost a rebuild/migration if wrong): shard count (`desiredCount`, fixed at creation), `efConstruction`, `maxConnections`, distance metric, enabled quantization (can't disable), multi-tenancy on/off. Escape hatch: new collection + migration behind a **collection alias**.

**6.6 Topology sketch** — place Acme's shards/replicas across 3 AZs (draw):

```
AZ-a: ____________________  AZ-b: ____________________  AZ-c: ____________________
```

---

## §7 · Segment 7 / Lab 3 — Controlled failure log

Prediction-first: fill the *predict* column for every row **before** the failure is injected. Note: this lab simulates node loss in a shared cluster — it is labeled **simulation, not a real multi-AZ failover test**.

**Failure injected:** ______________________ (e.g., replica pod kill) · **Time:** ______

| Operation | Consistency level | **Predicted** outcome | **Observed** outcome | Match? | Why (mechanism) |
|---|---|---|---|---|---|
| Write | ONE | | | | |
| Write | QUORUM | | | | |
| Write | ALL | | | | |
| Read | ONE | | | | |
| Read | QUORUM | | | | |
| Read | ALL | | | | |

**Recovery & convergence observation** (async replication is default-on for RF > 1 in 1.38):

| Metric (Prometheus) | Value at failure | Value during recovery | Value at convergence | Time to converge |
|---|---|---|---|---|
| `async_replication_objects_diff_total` | | | | |
| `async_replication_propagation_count` | | | | |
| `async_replication_scheduler_queue_depth` | | | | |
| `replication_read_repair_count` | | | | |
| Node status (`GET /v1/nodes`) | | | | |

**Failover vs restore — my one-liner distinction:**

```
_________________________________________________________________
```

---

## §8 · Segment 8 — Alert-shortlist exercise

**Task:** of the 15 candidate alerts presented, pick the **5 that survive** for Acme. Symptom-based first (what the user feels), cause-based only where the cause is unambiguous and actionable.

| # | Alert I keep | Symptom or cause? | Threshold & window | Why it survives (and what I'd do when it fires) |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

**Alerts I explicitly rejected and why (noise, no action, duplicate signal):**

```
_________________________________________________________________
```

**Weaviate signal map — my shortlist of metric families to instrument:** query latency (`queries_durations_ms`), async index queue (`queue_size`, `queue_paused`), tombstones (`vector_index_tombstones`), LSM/compaction (`lsm_bucket_compaction_*`), replication (`async_replication_*`, `replication_read_repair_*`), backup (`backup_*`), readiness (`/v1/.well-known/ready` → 503), runtime config (`weaviate_runtime_config_last_load_success` = 0). Multi-tenant cardinality: set `PROMETHEUS_MONITORING_GROUP=true` at high tenant counts.

**The 8-step evidence-first workflow** (memorize; used in Lab 4): impact → timeline → changes → saturation → layer isolation → hypothesis → safe mitigation → verification.

---

## §9 · Segment 9 / Lab 4 — Incident record

Structure mirrors `operations/incident-template.md` — reuse it verbatim for real incidents at work.

**Incident title:** ______________________ · **Severity:** ____ · **Scribe:** ______

### 9.1 Impact
| Field | Entry |
|---|---|
| What is degraded (user-visible symptom) | |
| Who/what is affected (tenants, endpoints, % of traffic) | |
| SLO(s) breached or at risk | |
| Start time (first evidence, not first alert) | |

### 9.2 Timeline (UTC, evidence-linked)
| Time | Event / evidence (metric, log line, dashboard) |
|---|---|
| | |
| | |
| | |

### 9.3 Changes (what changed before onset?)
| Change | When | Suspect? (Y/N) |
|---|---|---|
| Deploys / config / runtime-overrides hash change | | |
| Data/traffic pattern change | | |
| Infrastructure events (K8s, disk, network) | | |

### 9.4 Hypotheses tested
| # | Hypothesis | Evidence for | Evidence against | Verdict (incl. decoys rejected) |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

### 9.5 Mitigation
| Field | Entry |
|---|---|
| Action taken (safest reversible step first) | |
| Blast radius considered | |
| Rollback plan if mitigation worsens things | |

### 9.6 Verification
| Field | Entry |
|---|---|
| Metric(s) proving recovery | |
| Time recovered | |
| Watch period & regression check | |

### 9.7 Follow-ups
| # | Action | Owner | Due | Evidence of done |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

**Runbook delta:** what did the existing runbook miss? ______________________

---

## §10 · Segment 10 — Security & DR self-check checklists

Check against **your own environment** (or mark N/A for WCD-managed items — but verify who owns each control). These feed §11's readiness gaps.

### 10.1 Security checklist

| ✔ | Control | v1.38 note | Mine? |
|---|---|---|---|
| ☐ | Anonymous access **explicitly disabled** (`AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED=false`) | env-vars table lists default `true` — never rely on the default | |
| ☐ | API-key auth or OIDC enabled; static keys stored as secrets, not in manifests | | |
| ☐ | Dynamic DB users used instead of env-listed users where possible | v1.30+; supports API-driven **key rotation** | |
| ☐ | Key/credential rotation schedule exists and was exercised | | |
| ☐ | RBAC enabled, least-privilege roles (built-ins are only `root`, `viewer`) | GA since 1.29 | |
| ☐ | No workload runs as `root` role | | |
| ☐ | TLS on REST (8080) and gRPC (50051) — terminated at proxy/LB/ingress | in-process TLS not documented; terminate at the proxy | |
| ☐ | Network isolation: cluster not publicly reachable; inter-node ports restricted | | |
| ☐ | RBAC audit logging retained and reviewed (enabled automatically with RBAC) | | |
| ☐ | I can state which controls are mine vs the managed service's | | |

### 10.2 Backup/DR checklist

| ✔ | Control | v1.38 note | Mine? |
|---|---|---|---|
| ☐ | Backups go to a remote backend (S3/GCS/Azure) — filesystem backend is single-node/non-production | | |
| ☐ | Backup schedule satisfies **RPO** (Acme illustrative: 1 h) | incremental backups (v1.37+) help; keep base + chain available | |
| ☐ | **Restore tested** end-to-end within **RTO** — a backup is only proven by a restore | | |
| ☐ | Restore caveats known: fails if collection already exists; RBAC roles/users need `rolesOptions`/`usersOptions: all`; OFFLOADED tenants are never in backups | INACTIVE-tenant inclusion: verify on your version (docs conflict, C-5) | |
| ☐ | "Replication ≠ backup, HA ≠ DR" — I can explain both to an exec | replication won't save you from a bad delete or corruption propagated to all replicas | |
| ☐ | Upgrade doctrine followed: **one minor version at a time, latest patch of each minor, never skip**; backup before each hop | multi-node downgrade floor: 1.27.26 | |
| ☐ | Rolling upgrades: RF ≥ 2, readiness probes, `maxUnavailable: 0`; canary + written rollback criteria | zero-downtime upgrades require replication | |
| ☐ | Collection **aliases** used for zero-downtime schema/vectorizer migrations | watch for dangling aliases after collection deletes | |

**Gaps found (carry into §11.2):**

```
1. _______________________________________________________________
2. _______________________________________________________________
3. _______________________________________________________________
```

---

## §11 · Segment 11 — Capstone, readiness gaps & action plan

### 11.1 Capstone planning page

**Brief:** Acme (illustrative) must upgrade the cluster **and** migrate the `content` vector to HFresh under live load. Produce a decision brief.

| Section | My team's notes |
|---|---|
| Decision (what & when) | |
| Evidence (from Labs 1–4 — cite your own tables) | |
| Upgrade path (one minor at a time: current → target, patch per hop, health gates) | |
| Migration mechanics (new collection + alias swap; dual-write/backfill; verification) | |
| Risk & rollback criteria (what metric, what threshold, who decides) | |
| Security/compliance note (what the change does NOT alter — authN/Z, backup schedule; restore test before the window) | |
| Exec summary (≤ 5 sentences: mitigation, residual risk, follow-ups) | |

### 11.2 Readiness-gap capture

Transfer your biggest gaps from the day (checklists §10, scorecard, lab misses):

| # | Gap | Dimension (scorecard) | Severity (H/M/L) | First step |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |
| 4 | | | | |
| 5 | | | | |

Now score yourself in `course/production-readiness-scorecard.md` (internal quality tool — not a certification).

### 11.3 30/60/90-day action plan

Every row needs an **owner**, a **date**, and **evidence** that will prove it happened. "Improve monitoring" is not an action; "symptom alert on p95 > 120 ms deployed, screenshot in runbook repo" is.

**By day 30 (stabilize & see):**

| Action | Owner | Target date | Evidence of done |
|---|---|---|---|
| | | | |
| | | | |
| | | | |

**By day 60 (harden & rehearse):**

| Action | Owner | Target date | Evidence of done |
|---|---|---|---|
| | | | |
| | | | |

**By day 90 (prove & institutionalize):**

| Action | Owner | Target date | Evidence of done |
|---|---|---|---|
| | | | |

Suggested candidates (adapt, don't copy): 30 — sizing worksheet rerun on production numbers; anonymous access verified off; alert shortlist deployed. 60 — restore test executed & timed vs RTO; upgrade rehearsal on staging (one minor at a time); quantization benchmark on a production slice. 90 — failure-injection game day (repeat Lab 3 on staging); scorecard re-scored, delta reviewed with leadership.

### 11.4 Close-out

| Field | Entry |
|---|---|
| Prediction sheet (§1.2) revisited — biggest surprise of the day | |
| Scorecard total (from scorecard doc) | ______ / 80 |
| Re-score date committed | |

---

*All Acme Retail figures and every worked number in this workbook are **illustrative**. Estimates produced by these worksheets are planning aids, not binding sizing guarantees — validate by measurement. Version-sensitive facts pinned to Weaviate v1.38.3 per `VERSION_MATRIX.md`; re-verify against your running version.*
