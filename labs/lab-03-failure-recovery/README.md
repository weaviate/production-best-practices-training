# Lab 3 — Controlled Failure & Recovery (predict first)

## Purpose & objectives

Predict, then observe, cluster behavior under node loss at ONE/QUORUM/ALL,
and watch async replication converge on recovery.

| Objective | Coverage |
|---|---|
| **TO-3** HA, consistency & scaling (Analyze/Evaluate) | Primary |
| EO-3.1 | Overlap rule predictions at ONE/QUORUM/ALL with RF=3; what read consistency does and does NOT reconcile |
| EO-3.2 | Async-replication convergence metrics interpreted |
| EO-3.3 | Failover vs restore/DR distinction; immutable topology choices |

## Scenario

Acme's change board asks: "what actually happens when we lose a node
during business hours?" You will kill one of three replicas, run writes and
reads at each consistency level, bring the node back, and watch the
anti-entropy machinery repair it — with your predictions on paper *before*
each step. **Grading favors correct reasoning over lucky guessing.**

## Prerequisites & preflight

```bash
make verify && PYTHONPATH=src python -m acme.chaos status
```
Expected: `All 7 checks passed.` and a table showing all three nodes
`running`.

## Timebox — 35 minutes

| Checkpoint | At minute |
|---|---|
| T1 prediction matrix committed (6 cells, in ink) | 6 |
| T2 node killed, drill run, observations recorded | 16 |
| T3 node restored, convergence observed | 24 |
| T4 failover-vs-DR paragraph + prediction scoring | 30 |
| Debrief | 30–35 |

## Participant tasks

1. **Predict (before touching anything).** RF=3, one node down. For each of
   ONE / QUORUM / ALL, predict: do writes succeed? do reads succeed? Fill
   the 6-cell matrix in the workbook with a one-line justification each
   (the overlap rule: `r + w > n` ⇒ strong consistency). *Prompt: quorum of
   3 is 2 — which levels can tolerate exactly one dead replica?*
2. **Kill a node.**
   ```bash
   PYTHONPATH=src python -m acme.chaos kill weaviate-1
   ```
   Note the simulation banner. Check `make verify` — which checks fail now,
   and is that what you expected? (readiness FAIL for one node, prometheus
   target down — the cluster still serves.)
3. **Run the consistency drill.**
   ```bash
   PYTHONPATH=src python -m acme.chaos write-drill
   ```
   Record the per-level success/failure table next to your predictions.
   *Prompt: the RAFT metadata plane still has quorum (2/3) — what would
   ALSO break if a second node died? (Do NOT try it — quorum-loss is an
   instructor-led demo; the tool refuses without an explicit flag.)*
4. **Restore & watch convergence.**
   ```bash
   PYTHONPATH=src python -m acme.chaos restore weaviate-1
   PYTHONPATH=src python -m acme.chaos convergence
   ```
   Watch `queue_depth` / `objects_propagated_delta` fall to zero (async
   replication is default-on for RF>1 since 1.38, cluster-wide scheduler).
   Also open Grafana → async replication panels. *Prompt: which mechanism
   repaired the returned node — read repair or async replication — and how
   would you tell from the metrics alone?*
5. **Write the boundary paragraph.** 4–6 sentences: what this drill proved
   (failover within a cluster), what it cannot prove (AZ loss, DR), and why
   "replication is my backup" is wrong for Acme's RPO of 1h.
6. **Score your predictions.** Mark each of the 6 cells right/wrong with the
   corrected reasoning where wrong.

## Hints (progressive)

<details><summary>Hint 1</summary>
n=3 replicas, one down ⇒ 2 reachable. ONE needs 1 ack, QUORUM needs 2,
ALL needs 3. Count.
</details>

<details><summary>Hint 2</summary>
Read consistency reconciles OBJECT VERSIONS by ID across replicas — it does
not merge ANN candidate lists. If your justification says "merges search
results", rewrite it (that's the KC-3 distractor).
</details>

<details><summary>Hint 3</summary>
During convergence, `async_replication_scheduler_queue_depth` spikes after
the node returns, propagation counters climb, then both flatten. If the
convergence watcher times out, check that prometheus still lists all three
targets (`up{job="weaviate"}`).
</details>

## Verify your work

```bash
PYTHONPATH=src python -m acme.chaos status   # all three running
make verify                                       # 7/7 PASS again
```
Expected: everything green — the cluster ends the lab exactly as it began.
Done means: filled prediction matrix (scored), drill output table, one
convergence observation (metric name + what it did), boundary paragraph.

## Reset & cleanup

```bash
PYTHONPATH=src python -m acme.chaos restore weaviate-1   # if still down
make reset                                                   # removes drill objects
```
Both idempotent. The write-drill cleans up after itself when all nodes are
back; `make reset` catches anything left.

## Recovery path if environment fails (5-minute fallback)

`fallback/failure-drill-transcript.md` contains a full, **clearly labeled
simulated** transcript: kill output, per-level drill table, convergence
watcher output, and prometheus metric tables as text. Do tasks 1, 5, 6
against it — prediction and interpretation are the assessed skills, and
they need no live cluster.

## Safety boundary

* SIMULATION: a compose `stop` on one host approximates node failure — not
  AZ loss, not a partition. Conclusions about AZ resilience do not transfer.
* Never kill a second node: RAFT quorum loss freezes the metadata plane
  (instructor demo only; the tool requires `--allow-quorum-loss`).
* Shared-cluster etiquette: one team drives the drill at a time; benchmark
  numbers taken during someone's drill are garbage.
