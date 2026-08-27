# FALLBACK — Lab 4 incident evidence pack (SIMULATED)

> **SIMULATION NOTICE:** instructor-authored evidence matching the injected
> scenario's expected signals on the pinned stack (1.38.3). NOT captured
> live. Metric "screenshots" are rendered as text tables. Use only for the
> 5-minute recovery path.

Incident declared 14:07. Baseline p95 (from Lab 2 baseline JSON): 18.7 ms.

## A. Alert feed (Grafana-style, text stand-in)

| time | alert | state |
|---|---|---|
| 13:41 | (none firing) | OK |
| 13:52 | QueryP95High — `AcmeProductMT` p95 > 3x baseline for 5m | FIRING |
| 13:55 | VectorIndexQueueGrowing — `queue_size` slope > 0 for 10m | FIRING |
| 14:02 | RequestRateAnomaly — `requests_total` 6x weekly norm | FIRING |

## B. Prometheus tables (instant vectors, 15s scrape)

`queries_durations_ms` p95 (ms), grouped per class:

| class | 13:30 | 13:50 | 14:10 |
|---|---:|---:|---:|
| AcmeProduct | 18 | 22 | 27 |
| AcmeProductMT | 19 | 74 | 112 |
| AcmeProductHFresh | 24 | 26 | 29 |

`rate(requests_total[1m])` per node (req/s):

| node | 13:30 | 13:50 | 14:10 |
|---|---:|---:|---:|
| weaviate-0 | 41 | 214 | 259 |
| weaviate-1 | 39 | 208 | 244 |
| weaviate-2 | 43 | 219 | 251 |

`batch_size_objects` (avg objects per batch request): 13:30 → **214**;
13:50 → **1.4**; 14:10 → **1.2**.  `batch_durations_ms` p95: 9 → 41 → 63.

## C. Nodes API (`GET /v1/nodes?output=verbose`, 14:10, trimmed)

```json
{ "nodes": [ { "name": "weaviate-0", "status": "HEALTHY",
  "shards": [
    {"class": "AcmeProductMT", "name": "tenant-007", "objectCount": 141388, "vectorQueueLength": 83112},
    {"class": "AcmeProductMT", "name": "tenant-012", "objectCount": 498,    "vectorQueueLength": 0},
    {"class": "AcmeProduct",   "name": "9Zk3aLpQ2RfX", "objectCount": 16714, "vectorQueueLength": 0}
  ]}]}
```
(One tenant shard holds ALL the backlog; every other shard is drained.)

## D. Slow-query log excerpt (LOG_FORMAT=json, threshold 500ms)

```json
{"level":"warning","msg":"slow query detected","class":"AcmeProductMT","tenant":"tenant-007","took_ms":812,"query_type":"near_vector","time":"14:04:11Z"}
{"level":"warning","msg":"slow query detected","class":"AcmeProductMT","tenant":"tenant-007","took_ms":1033,"query_type":"near_vector","time":"14:06:47Z"}
```

## E. Change trail (the part that needs judgment)

1. 13:44 log: `"msg":"schema version incremented","action":"update_class","class":"AcmeProduct"` —
   diff shows `vectorCacheMaxObjects: 1e12 → 9e11`.
2. 13:44 alias list now contains `AcmeCatalogV2 → AcmeProduct` (new).
3. 13:47 onward: sustained stream of 1-object batch inserts into
   `AcmeProductMT` / `tenant-007` from an internal "nightly sync"
   service account (product_ids `INC-*`), during business hours.
4. `weaviate_runtime_config_last_load_success` = 1 throughout (no runtime
   config errors).

## F. What a complete answer contains (self-check, don't read early)

Root cause: misbehaving ingest job hammering ONE tenant with batch_size=1
client-side batches → request-rate saturation + vector-index queue backlog
on tenant-007's shard → MT latency regression. Decoy: the 13:44 cache-limit
tweak + alias creation are visible changes with no mechanism linking them to
queue growth (and non-MT classes barely degraded). Mitigation: stop/rate-
limit the sync job (or deactivate tenant-007 with stated blast radius);
verify p95 and `vectorQueueLength` return to baseline; follow-ups: batch
shape alert (`batch_size_objects` < 10 while `requests_total` high),
server-side batching mandate for integrators, per-tenant ingest quotas.
