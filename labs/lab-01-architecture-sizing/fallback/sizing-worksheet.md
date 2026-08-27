# Fallback: standalone sizing worksheet + worked example

Use this if the participant workbook is unavailable. Content mirrors the
workbook estimator sheet.

## 12-input workload profile (fill one column per card)

| # | Input | Value | given/derived/assumed | Uncertainty |
|---|---|---|---|---|
| 1 | Object count | | | |
| 2 | Vector dims x named vectors | | | |
| 3 | Avg payload size | | | |
| 4 | Tenants (count, activity mix) | | | |
| 5 | Peak read QPS (+ query shape) | | | |
| 6 | Ingest rate (steady + burst) | | | |
| 7 | Growth (12–18 mo) | | | |
| 8 | Latency SLO (p95/p99) | | | |
| 9 | Recall target @k | | | |
| 10 | Availability SLO | | | |
| 11 | RPO / RTO | | | |
| 12 | Compliance & budget constraints | | | |

## Estimator formulas (course rules of thumb — ranges, not guarantees)

```
raw_vector_bytes  = objects x dims x 4
memory_estimate   ≈ 2 x raw_vector_bytes                  (docs rule of thumb)
graph_overhead    ≈ objects x maxConnections x 10 B       (per layer, dominant layer 0)
with RQ-8         ≈ memory_estimate / 4  (+ originals on disk for rescoring)
disk_estimate     ≈ 2–3 x (payload_bytes + raw_vector_bytes)   + backups
GOMEMLIMIT        ≈ 80–90% of container/VM memory
```

## Worked example — Card D "Docent" (practice card, not assessed)

10M objects, 384-dim, 1 KB payload, single tenant, 200 QPS, p95 ≤ 120 ms,
recall ≥ 0.97, 99.9%, RPO 24h/RTO 8h, modest budget.

```
raw vectors  = 10,000,000 x 384 x 4 B        = 15.36 GB
memory (x2)  = ~31 GB          LOW 26 / EXPECTED 31 / HIGH 40 GB
graph        = 10M x 32 x 10 B = 3.2 GB      (inside the x2 headroom)
with RQ-8    = vectors resident ~3.9 GB -> total ~12–16 GB expected
disk         = 2.5 x (10 GB payload + 15.4 GB vectors) ≈ 64 GB + backups
topology     = 3 nodes, RF 3, 3 shards, HNSW + RQ-8
             -> per node with RF3: EVERY node holds a full copy (~16 GB) —
                replication multiplies memory, sharding divides it.
validation   = import 1M-object sample; measure recall@10 + p95 with the
               Lab 2 harness; verify RQ-8 recall delta < 1 pt before scaling.
```

Key trap the example demonstrates: with RF = node count, sharding does NOT
reduce per-node memory — every node stores every shard replica. To shrink
per-node footprint you need nodes > RF.
