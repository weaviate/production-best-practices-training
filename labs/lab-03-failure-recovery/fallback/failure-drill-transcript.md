# FALLBACK — Lab 3 failure-drill transcript (SIMULATED)

> **SIMULATION NOTICE:** every output below is instructor-authored to match
> the expected behavior of the pinned stack (Weaviate 1.38.3, RF=3, 3 nodes,
> one node stopped). It was NOT captured from a live cluster. Use it only
> for the 5-minute recovery path; treat values as illustrative.

## 1. Killing weaviate-1

```text
$ python -m acme.chaos kill weaviate-1
SIMULATION: single-host compose node stop ≈ node failure. It is NOT an AZ outage or a network partition.
Stopping weaviate-1…
weaviate-1 is down. Restore with: python -m acme.chaos restore weaviate-1
```

`make verify` immediately after (expected failures only):

| check | result | detail |
|---|---|---|
| server version | PASS | got 1.38.3, expected 1.38.3 |
| readiness (all nodes) | **FAIL** | :8080: 200; :8081: ConnectError; :8082: 200 |
| node count / health | **FAIL** | 3 nodes (2 HEALTHY), expected 3 |
| vector index queue drained | PASS | total queued vectors: 0 |
| collection counts | PASS | (served by surviving replicas) |
| sample query | PASS | near_vector returned 10/10 |
| prometheus | **FAIL** | 2/3 weaviate targets up |

## 2. Consistency drill with 1 of 3 replicas down (RF=3)

```text
$ python -m acme.chaos write-drill
```

| level | writes ok | writes failed | reads ok | reads failed | first error |
|---|---|---|---|---|---|
| ONE | 20 | 0 | 20 | 0 | - |
| QUORUM | 20 | 0 | 20 | 0 | - |
| ALL | 0 | 20 | 20* | 0 | UnexpectedStatusCodeError: write at ALL requires 3/3 replica acks; 1 replica unavailable |

\* reads in the ALL row were issued against objects written at lower levels
during the drill; a read AT level ALL would also fail while a replica is
down (needs responses from all replicas).

Interpretation (overlap rule, n=3): ONE (w=1) and QUORUM (w=2) are
satisfiable with 2 live replicas; ALL (w=3) is not. `QUORUM/QUORUM` keeps
`r + w = 4 > 3` — strong consistency preserved through the failure.

## 3. Restore + convergence

```text
$ python -m acme.chaos restore weaviate-1
Starting weaviate-1…
weaviate-1 is READY. Now watch convergence: python -m acme.chaos convergence

$ python -m acme.chaos convergence
Watching async replication (Ctrl-C to stop)…
  queue_depth=14 active_workers=6 objects_propagated_delta=0
  queue_depth=9  active_workers=8 objects_propagated_delta=3260
  queue_depth=4  active_workers=5 objects_propagated_delta=2481
  queue_depth=1  active_workers=2 objects_propagated_delta=612
  queue_depth=0  active_workers=0 objects_propagated_delta=40
  queue_depth=0  active_workers=0 objects_propagated_delta=0
  queue_depth=0  active_workers=0 objects_propagated_delta=0
  queue_depth=0  active_workers=0 objects_propagated_delta=0
Converged: no pending async-replication work for 3 consecutive polls.
```

Prometheus instant values during recovery (text stand-in for the Grafana
"Async replication" panel):

| metric | t+0s | t+30s | t+90s | t+180s |
|---|---:|---:|---:|---:|
| `async_replication_scheduler_queue_depth` (sum) | 14 | 9 | 1 | 0 |
| `async_replication_scheduler_workers_active` (sum) | 6 | 8 | 2 | 0 |
| `async_replication_propagation_count` (rate/s) | 0.4 | 2.1 | 0.3 | 0 |
| `replication_read_repair_count` (rate/s) | 0.2 | 0.1 | 0 | 0 |

How to tell the repair mechanisms apart: read-repair counters only move when
QUORUM/ALL *reads* hit stale replicas; async-replication counters move on
their own schedule (default comparison every 30s, accelerating to 3s while
differences exist) regardless of read traffic.

## 4. What this proves / does not prove

Proves: leaderless data plane keeps serving through a single node loss;
ONE/QUORUM writes survive; ALL trades availability for consistency; the
returned replica is repaired automatically (hash-tree diff → propagation).
Does NOT prove: AZ-loss tolerance (single host!), partition behavior,
disaster recovery. Replication ≠ backup: a bad delete replicates perfectly.
