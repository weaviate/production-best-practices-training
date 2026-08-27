# Lab 4 — Incident Investigation (evidence first)

## Purpose & objectives

Run the 8-step evidence-first workflow on a live degraded cluster, find the
mechanism, mitigate safely, verify, and write the incident record.

| Objective | Coverage |
|---|---|
| **TO-4** Observability & troubleshooting (Analyze/Create) | Primary |
| **TO-7** (partial) Incident communication | Incident record + runbook delta |
| EO-4.1 | Weaviate signal map: queue depth, batch metrics, request rates, saturation |
| EO-4.2 | DB-time vs external-time separation; slow-query evidence |

## Scenario

It's 14:07 at Acme. Support reports sluggish search for several B2B
storefronts. The on-call dashboard shows elevated p95 and a climbing
indexing backlog. Something changed in the last half hour — **and at least
one thing that changed is innocent.** Your team owns the investigation.

(The degradation is injected by the instructor. Participants: do not read
`labs/instructor/` — the point is finding it from evidence.)

## Prerequisites & preflight

```bash
make verify
```
Expected **before injection**: `All 7 checks passed.` During the incident,
verify itself becomes a diagnostic: note WHICH checks degrade.

Dashboards: Grafana `http://localhost:3000` (admin / acme-lab),
Prometheus `http://localhost:9090`.

## Timebox — 40 minutes

| Checkpoint | At minute |
|---|---|
| T1 impact statement + timeline started | 6 |
| T2 change list (incl. the innocent one) drafted | 14 |
| T3 hypothesis named with supporting signals | 22 |
| T4 mitigation applied + verified | 30 |
| T5 incident record + runbook delta done | 35 |
| Debrief | 35–40 |

## Participant tasks — follow the workflow IN ORDER

1. **Impact.** Quantify before explaining: which operations are slow
   (queries? writes? both?), which collections/tenants, how bad (p95 vs
   baseline from your Lab 2 JSON). Sources: Grafana, `queries_durations_ms`,
   `batch_durations_ms`, slow-query log (`docker compose --env-file .env -f
   platform/docker-compose.yaml logs weaviate-0 | grep -i slow`).
2. **Timeline.** When did it start? Prometheus range queries beat vibes:
   `rate(requests_total[1m])`, `queue_size`, `batch_size_objects`.
3. **What changed?** List EVERY change signal you can find: schema version
   / config hash (`weaviate_runtime_config_hash`, schema endpoints, alias
   list), deploys, load pattern shifts. *Prompt: write down at least two
   candidate changes before proceeding.*
4. **Saturation.** CPU/mem per container (`docker stats`), goroutines,
   `concurrent_queries_count`, vector-index queue depth per shard
   (`/v1/nodes?output=verbose` → `vectorQueueLength`). Which resource is
   actually scarce?
5. **Layer isolation.** Is DB time or something upstream to blame? Compare
   direct near_vector latency (your Lab 2 harness, 1 trial) against the
   reported symptom. Which tenant's shard is hot?
6. **Hypothesis.** One sentence naming the MECHANISM (not "it's slow"):
   what workload/change is producing which signal. Name the decoy and why
   you reject it. *Prompt: does your hypothesis explain BOTH the latency
   regression and the queue growth?*
7. **Safe mitigation.** Choose the least-privilege action that stops the
   bleeding (hint: the harmful thing is a *workload*, and the instructor
   plays the "workload owner" — asking them to stop it / rate-limit it IS a
   valid production mitigation; so is deactivating the abused tenant after
   stating the blast radius). Apply, then re-measure the impact metric.
8. **Verify & record.** `make verify` back to 7/7; complete the incident
   record (impact, timeline, root cause, decoy rejected, mitigation,
   verification, follow-ups) + one runbook delta (what check would have
   found this in 5 minutes?).

## Hints (progressive)

<details><summary>Hint 1</summary>
Segment the impact: is EVERY collection slow, or mostly one tenant of
`AcmeProductMT`? `PROMETHEUS_MONITORING_GROUP=true` groups per-class
metrics — the nodes API (`?output=verbose`) still shows per-shard queue
lengths.
</details>

<details><summary>Hint 2</summary>
Look at batch shape, not just batch volume: `batch_size_objects` histogram
falling toward 1 while `requests_total` climbs means someone is importing
with pathologically small batches. Who ingests into one tenant only?
</details>

<details><summary>Hint 3</summary>
The schema-version/alias change you found is real but harmless: a
vectorCache limit tweak + a new alias touch NO query path. If your root
cause is "a config change", check whether its mechanism could possibly
produce an indexing backlog. It can't. Follow the write path.
</details>

## Verify your work

```bash
make verify
```
Expected after mitigation + instructor `restore`: **7/7 PASS**, and your
impact metric (p95 / queue depth) back to baseline — cite the number in the
key-findings checklist (root cause, decoy explicitly rejected, safe
mitigation, verification evidence).

## Reset & cleanup

Instructor: `PYTHONPATH=src python3 instructor/incident_injector.py restore`.
Participants: `make reset` if collection state looks off. Both idempotent.

## Recovery path if environment fails (5-minute fallback)

`fallback/incident-evidence-pack.md` — a **clearly labeled simulated**
evidence bundle: alert screenshot stand-ins (text tables), prometheus metric
tables, slow-query log excerpts, `/v1/nodes` output, and the alias/schema
change trail. Run tasks 1–3, 6, and 8 against the pack. The workflow is the
deliverable, not the clicking.

## Safety boundary

* Mitigate with the LEAST destructive action first; never delete
  collections or restart nodes as step one. State blast radius before any
  state-changing action.
* `labs/instructor/` is off-limits to participants (no hidden state in the
  participant path: everything you need is observable from the cluster).
* This is a shared cluster: coordinate before cluster-wide mitigations.
