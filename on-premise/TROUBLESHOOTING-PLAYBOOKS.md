# Weaviate On-Premise Troubleshooting Playbooks

Symptom-driven playbooks for the Acme platform team. Written to be opened mid-incident.

Every playbook follows the same shape:

**Symptom → First 5 minutes (evidence) → Likely causes, ranked → Fix per cause → Verify
recovered → Prevent recurrence.**

Ground rules, same as the course:

- **Evidence before action.** The first five minutes of every playbook is collection, not fixing.
  Save what you collect — you will want it for the postmortem.
- **Verify on your version.** Version-dependent behavior below is stated against 1.37–1.39.
- Exact metric names and less-common config keys vary by version: read them off your own
  `/metrics` endpoint and the docs for your version rather than trusting memory (yours or ours).

Endpoints used throughout (adjust host/port/auth to your environment):

```bash
BASE=http://localhost:8080
curl -s $BASE/v1/meta | jq .version          # what am I running?
curl -s $BASE/v1/.well-known/ready           # is this node serving?
curl -s $BASE/v1/nodes | jq .                # cluster + shard view
curl -s $BASE/v1/cluster/statistics | jq .   # RAFT view
```

---

## Playbook A — Memory pressure / OOM kills

### Symptom

Pods/containers restarting with OOMKilled; kernel logs show oom-killer; or no kills yet but memory
climbs steadily, GC burns CPU, and latency degrades ("GC thrash").

### First 5 minutes — collect

```bash
# Kubernetes: confirm it was actually an OOM kill, and on which node(s)
kubectl get pods -o wide
kubectl describe pod <pod> | grep -A5 "Last State"    # look for OOMKilled

# docker-compose
docker inspect <container> --format '{{.State.OOMKilled}}'
dmesg | grep -i oom

# Memory trend, not just current value: pull the last 24h of per-node memory and
# Go heap metrics from Prometheus. Heap sawtooth with rising floor = growth;
# flat-top near the limit with heavy GC = thrash.

# Rough live check
kubectl top pods    # or: docker stats --no-stream
```

Also record: object counts and dimensions per collection (to recompute the memory model from
OPS-GUIDE section 4), recent changes (imports? new collection? upgrade?), and whether
`GOMEMLIMIT` is set.

### Likely causes, ranked

1. **The cluster has outgrown its memory** — data grew; HNSW vector memory now exceeds what the
   ~2× raw-vector-bytes estimate says fits. Most common by far.
2. **No / wrong `GOMEMLIMIT`** — Go runtime doesn't know the budget, so the kernel finds out first.
3. **A burst consumer** — very large batch imports, huge `limit` queries, or aggregations spiking
   allocations above steady state.
4. **Undersized after a topology change** — RF increased, node removed, or shards rebalanced onto
   fewer nodes.

### Fix per cause

**Cause 1 — outgrown memory.** Short term: add memory (vertical) if you can. Structural fix:
**quantization**. RQ-8 gives approximately a **4× reduction in vector memory**, with rescoring
reading original vectors from disk to preserve result quality — for most workloads this is the
single biggest lever you have. Test recall and latency on a staging copy of your data before and
after; enable it per collection per the docs for your version. Note: **RQ4 appears in the 1.39
release notes but is release-notes-only at this point — treat it cautiously and do not build a
capacity plan on it.** Alternatives/complements: reduce dimensions at the embedding-model level,
or shard/scale out.

**Cause 2 — GOMEMLIMIT.** Set it to roughly 80–90% of the container limit (estimate; tune). This
converts hard kills into GC pressure you can see on a dashboard. It does not create memory — if
cause 1 is also true, fix that too.

**Cause 3 — burst consumer.** Find the client (request logs, timing correlation), then bound it:
smaller batches, paginate instead of huge limits, schedule imports off-peak. Backpressure belongs
in the client — see Playbook D.

**Cause 4 — topology.** Recompute the per-node memory model with the *current* shard placement
(`/v1/nodes` shows shard counts per node) and resize accordingly.

### Verify recovered

- No OOM kills for a full daily traffic cycle.
- Memory usage flat or sawtoothing with a stable floor, comfortably under the limit.
- p95/p99 back to baseline (GC thrash shows up in tails first).
- If you enabled RQ-8: canary queries return expected results; recall spot-check passed.

### Prevent recurrence

- Alert on memory *trend* (sustained growth, projected time-to-limit), not only on threshold.
- Re-run the OPS-GUIDE section 4 capacity checkpoint monthly.
- Load-test imports at realistic burst sizes in staging.

---

## Playbook B — Node down / RAFT quorum loss (3-node cluster)

### Symptom

Alerts: node not ready, or node count dropped. Possibly schema/tenant operations failing while
some queries still work.

### First 5 minutes — collect

```bash
# From EACH surviving node (per-node view matters — they can disagree):
curl -s $BASE/v1/nodes | jq .                 # who is present, shard status
curl -s $BASE/v1/cluster/statistics | jq .    # RAFT state: leader, peers
curl -s $BASE/v1/.well-known/ready

# Why is the node down?
kubectl get pods -o wide; kubectl describe pod <down-pod>; kubectl logs <down-pod> --previous
```

Record: how many nodes are down (1 of 3, or 2 of 3 — completely different incidents), whether
RAFT reports a leader, and the RF of your important collections.

### What still works — know this before you "fix" anything

With **1 of 3 nodes down** (quorum intact, RF=3 assumed; verify against your RF):

- RAFT still has 2-of-3 majority: schema and tenant operations continue.
- Reads/writes at consistency **ONE**: work.
- Reads/writes at **QUORUM**: work — 2 of 3 replicas can still answer.
- Reads/writes at **ALL**: **fail** for shards with a replica on the dead node. If clients
  hard-code ALL, they experience this as an outage even though the cluster is healthy-degraded.

With **2 of 3 nodes down**: RAFT quorum is lost — metadata operations (schema changes, tenant
ops) fail cluster-wide. Data reads at ONE may still be served from the surviving node's replicas.
This is a real outage; focus entirely on getting a second node back.

With **RF=1**: any node down means its shards are simply unavailable at every consistency level.
There is no replica to fail over to. (This is why OPS-GUIDE section 1 says RF=1 is not HA.)

### Likely causes, ranked

1. OOM kill / crash loop on the node (see Playbook A — check `--previous` logs first).
2. Infrastructure: node/VM died, volume detached, network partition.
3. Disk full on that node (see Playbook E).
4. Operator action: eviction, drain, botched rolling update.

### Fix per cause

In all cases the shape is the same: **fix the underlying cause, bring the node back with its data
volume intact, and let it rejoin.** Do not delete the node's data volume as a "clean start" unless
you have explicitly decided to rebuild it from replicas and you know your RF supports that.

- Crash loop → Playbook A / logs; fix the crash cause first or it will just die again.
- Infra → restore the volume attachment / replace the VM; on Kubernetes let the StatefulSet
  reschedule with the same PVC.
- Disk → Playbook E on that node.

### Verify recovered

```bash
curl -s $BASE/v1/nodes | jq .                 # all 3 present, shards healthy
curl -s $BASE/v1/cluster/statistics | jq .    # stable leader, 3 peers
```

- **Async replication convergence:** after the node returns, replicas that missed writes catch up
  asynchronously. Do not declare recovery the moment the node is `ready` — give convergence time,
  then verify: reads at ALL succeed again, and spot-check recent writes (written during the
  outage) are readable *from the returned node*.
- Canary queries pass; consistency-ALL clients recovered.

### Prevent recurrence

- Quarterly failure drill (OPS-GUIDE section 7): kill a staging node under load on purpose.
- Audit client consistency levels: ALL should be a deliberate choice, not a default.
- Alert on node-not-ready with a short grace period, and separately on RAFT leaderlessness.

---

## Playbook C — Slow queries

### Symptom

Latency SLO breach — usually p95/p99 first. Users say "it's slow"; the mean says everything is
fine. The mean is lying.

### First 5 minutes — collect

- **Percentiles, not averages.** Pull p50 / p95 / p99 for the affected window and a baseline
  window. Decide which incident you have:
  - **Tail-only** (p50 flat, p99 up): a subset of queries is slow — usually specific filters,
    huge limits, cold shards, or one sick node.
  - **Median shift** (p50 up too): everything is slower — resource pressure, upgrade regression,
    data growth crossing a threshold.
- **Slow-query log.** This is your best evidence — but note: **enabling the slow-query log
  requires a restart**, so it must be enabled proactively in production, *before* the incident.
  If Acme's clusters don't have it on yet, that is a today-priority change (config keys in the
  docs for your version). If it is on: read it. It tells you *which* queries, with what filters,
  are slow — replacing an hour of guessing.
- Correlate with node health: `/v1/nodes`, per-node memory/CPU (a single struggling node drags
  the tail for every query that touches it — cross-check Playbooks A and E).
- What changed? Deploy, upgrade, import, new query pattern, data growth.

### Likely causes, ranked

1. **Resource pressure** (memory/GC or disk) masquerading as a query problem — rule out via
   Playbooks A/E before touching query parameters.
2. **Expensive filters** — low-selectivity or unindexed-property filters combined with vector
   search.
3. **Vector search parameters** — `ef` (HNSW) or, for RQ-compressed collections, the rescoring
   `searchProbe`. Note: **`searchProbe` defaults to 256 since v1.38.2** — if you upgraded through
   1.38.2, your effective defaults may have changed under you; check what your queries actually
   run with.
4. **Query shape** — very large `limit`, heavy aggregations, huge cross-reference expansions.
5. **Data growth** crossed a threshold (index no longer fits the page cache, etc.).

### Fix per cause

**Cause 1.** Fix the resource problem; re-measure; only then tune queries.

**Cause 2 — filters.** From the slow-query log, identify the offending filters. Ensure filtered
properties are indexed appropriately; check the filter-strategy options available on your version
(the docs describe how filtered vector search is executed and what knobs exist — verify the exact
names for your version). Consider restructuring: pre-filter by tenant/collection design instead of
low-selectivity where-clauses over everything.

**Cause 3 — search parameters.** Tune deliberately, one knob at a time, measuring recall *and*
latency on a fixed query set: higher `ef` / `searchProbe` = better recall, more latency; lower =
the reverse. Record the values you settle on and why.

**Cause 4.** Fix the client: paginate, cap limits, move aggregations off the hot path.

**Cause 5.** Back to capacity planning (OPS-GUIDE section 4) — this one is not a tuning problem.

### Verify recovered

- p95/p99 back under SLO for a full traffic cycle — verify the *tail*, since that is what broke.
- Slow-query log volume back to baseline.
- If you changed `ef`/`searchProbe`: recall spot-check on the fixed query set passed.

### Prevent recurrence

- Slow-query log enabled everywhere, always (it needs a restart — never enable it reactively).
- Latency SLOs and alerts defined on p95/p99.
- A fixed benchmark query set run before/after every upgrade and every tuning change.

---

## Playbook D — Import / ingestion failures

### Symptom

Batch imports erroring, throughput collapsing, or — worst — imports "succeeding" while object
counts don't add up.

### First 5 minutes — collect

- **Client-side error output.** With server-side batching, individual objects can fail while the
  batch call as a whole "works" — the failures are reported per object. Get the actual failed
  objects and their error messages from the client's error/failed-object results. If the import
  code doesn't capture these, that is the first bug, independent of today's incident.
- Server logs from the import window on all nodes.
- Cluster health: `/v1/nodes` (a down node fails writes at some consistency levels — Playbook B),
  memory (Playbook A), disk (Playbook E).
- Count check: expected objects vs. actual (aggregate count per collection).

### Likely causes, ranked

1. **Resource pressure on the server** — imports are the heaviest thing most clusters do; memory
   or disk pressure shows up here first.
2. **Data problems** — schema mismatches, invalid vectors (wrong dimensions), malformed
   properties: per-object failures with clear messages, if anyone reads them.
3. **Client overrunning the server** — no backpressure: firing batches as fast as possible until
   timeouts and errors cascade.
4. **Cluster degraded** — node down + write consistency requirements (Playbook B).

### Fix per cause

**Cause 1.** Playbooks A/E. Then resume at reduced rate.

**Cause 2.** Fix the data or the schema; the per-object errors tell you which. Then re-import
*only the failed objects* — which is where ID discipline pays off (below).

**Cause 3 — backpressure.** Use the client's batching machinery (modern clients manage batch
sizing/concurrency and surface errors) rather than hand-rolled parallel fire-and-forget. Reduce
concurrency and batch size until errors stop, then step up while watching server metrics.

**Cause 4.** Playbook B first; imports resume after.

**The failed-object discipline (applies to every cause):** every import run must (1) capture every
failed object with its error, (2) persist that list somewhere durable, (3) retry failed objects
after fixing the cause, (4) reconcile final counts against the source of truth. An import pipeline
without these four steps loses data silently.

**Deterministic IDs make retries safe.** Generate object IDs deterministically from your source
data (e.g. UUIDv5 from the source primary key) instead of letting IDs be random. Then re-importing
an object is an idempotent upsert, not a duplicate — so the recovery procedure for *any* import
failure becomes "re-run the batch", with no dedup pass. If Acme's pipeline uses random IDs today,
fix that before the next large import.

### Verify recovered

- Failed-object list drained: all retried, zero remaining errors.
- Counts reconcile with the source system exactly.
- Canary query returns newly imported data.

### Prevent recurrence

- Failed-object capture + deterministic IDs as pipeline code-review requirements.
- Alert on import error rate and on indexing backlog growth (read the queue/backlog metrics your
  version exposes off your own `/metrics` endpoint).
- Rehearse large imports in staging at production rates.

---

## Playbook E — Disk pressure

### Symptom

Disk-usage alert on the data volume; or write errors / crash with a full `PERSISTENCE_DATA_PATH`.

### First 5 minutes — collect

```bash
df -h <data-volume-mountpoint>
du -sh <PERSISTENCE_DATA_PATH>/*        # what is actually big?
# Growth rate from your disk-usage dashboard: full in days, or hours?
```

Record which node(s), what's largest, and the growth slope. A slow climb and a sudden spike are
different incidents (spike → recent import? backup staged locally? log explosion?).

### What grows on a Weaviate data volume

- **Object storage (LSM-based):** updates and deletes write new versions; old versions and deleted
  data occupy space until compaction reclaims them. Heavy update/delete churn = disk usage well
  above "live data" size.
- **Inverted indexes** for filterable/searchable properties — grow with data and with how many
  properties you index.
- **Vector index data.**
- **Tombstones:** deletions (including tenant/object cleanup) leave tombstones that occupy space
  until cleanup/compaction processes them. Delete-heavy workloads can see disk usage *rise* after
  mass deletions before it falls.
- Non-Weaviate guests: local backup staging, logs, cores.

### Likely causes, ranked

1. Organic data growth crossing capacity — most common and most benign.
2. Update/delete churn outrunning compaction and tombstone cleanup.
3. A one-off: local backup copies, log files, someone's scratch data on the wrong volume.
4. Undersized volume from day one.

### Fix per cause — safe vs. unsafe

**Safe:**

- **Grow the volume** (Kubernetes: expand the PVC if the storage class allows; compose: grow the
  underlying disk/filesystem). This is the fix for causes 1 and 4, and buys time for 2.
- Remove non-Weaviate files you can positively identify (old local backup staging, rotated logs).
- Delete data *through Weaviate* (objects, tenants, collections you truly don't need) — but note
  tombstones mean space returns after cleanup, not instantly. Do not delete-through-the-API as an
  emergency space fix on a nearly full disk.
- For churn-heavy workloads: review tombstone-cleanup-related settings for your version (check
  the exact keys in the docs) so cleanup keeps pace.

**Unsafe — do not do these:**

- **Never hand-delete files inside `PERSISTENCE_DATA_PATH`** — segment files, WALs, index files:
  all of it is live state. Deleting "old-looking" files corrupts the store.
- Never `truncate` files Weaviate has open.
- Don't disable compaction/cleanup to "reduce I/O" during pressure — it is the mechanism that
  reclaims your space.

If the disk is 100% full and the node is down: grow the volume first (or move a positively
identified non-Weaviate file off), then start Weaviate and let it recover.

### Verify recovered

- Headroom restored below the warn threshold and the growth slope explainable.
- Node ready, shards healthy in `/v1/nodes`, canary queries pass.
- No write errors in logs post-recovery.

### Prevent recurrence

- Alert early on both usage level and growth rate (OPS-GUIDE section 4).
- Keep backups off the data volume.
- Include disk-per-object in the monthly capacity review; delete-heavy workloads get their
  tombstone behavior reviewed explicitly.

---

## Playbook F — Backup or restore fails

### Symptom

Backup reports failure or hangs; restore fails; or restore "succeeds" but data is missing.

### First 5 minutes — collect

```bash
# Status of the operation (backend = e.g. s3/gcs/azure/filesystem; check your config)
curl -s $BASE/v1/backups/<backend>/<backup-id> | jq .          # backup status
# restore status endpoint: see the docs for your version for the exact path

curl -s $BASE/v1/meta | jq .version    # on BOTH the source of the backup and the restore target
```

- Server logs around the operation, all nodes — backups are cluster-wide, and one node's failure
  fails the job.
- Backend evidence: does the backup exist in the bucket? Credentials valid? Bucket reachable from
  *all* nodes?
- **Which server version wrote this backup?** (This is why OPS-GUIDE section 5 says version-tag
  every backup.)

### Likely causes, ranked

1. **Version/format incompatibility** — headline rule, verified: **backups taken in pre-1.39
   formats are not restorable on a 1.39 server.** More generally, restoring across versions is
   the first thing to rule out: the safe assumption is same-version restore unless the docs for
   your versions explicitly bless the pair.
2. **Backend/infrastructure** — expired credentials, permissions, network to object storage from
   some nodes, bucket lifecycle rules that quietly deleted old backups.
3. **Partial failure** — one node erred mid-job; the operation fails or completes partially.
4. **Restore-target conflicts** — restoring into a cluster where the collection already exists,
   or topology differences between source and target.
5. **Multi-tenant expectations** — "missing" data that was never in the backup: **FROZEN tenants
   are skipped** (HOT and COLD are included since 1.37). If frozen tenants exist, their data is in
   the offload storage, not the backup.

### Fix per cause

**Cause 1.** No workaround exists on the restore side. Restore onto a server matching the backup's
version, then (if needed) walk that restored cluster up the upgrade ladder one minor at a time,
taking fresh backups per hop. And per OPS-GUIDE section 2: after any upgrade to 1.39, take a fresh
backup immediately — otherwise you hold only backups your current server cannot restore.

**Cause 2.** Fix credentials/network/permissions; confirm from *every* node (a backup can fail
because one node of three can't reach the bucket). Review bucket lifecycle rules against your
retention policy.

**Cause 3.** Read the per-node error in status output and logs; fix that node's issue; re-run the
backup. Treat any partially failed backup as no backup.

**Cause 4.** Restore into a clean target, or use the restore options your version provides for
naming/selecting collections (check the docs). Don't improvise merges during an incident.

**Cause 5.** Not a bug — an architecture fact. Recover frozen-tenant data via the offload
storage's own durability story. If that story doesn't exist, escalate: it's a data-durability gap,
not a restore failure.

### Verify recovered

Backup: status `SUCCESS`; artifact present in the backend; and — for anything important — restore
tested into scratch. Restore: object counts per collection match expectation; canary queries pass;
tenant list (and tenant states) match what should exist.

### Prevent recurrence

- Monthly restore drill (OPS-GUIDE section 5) — nearly every cause above is caught by a drill
  before it matters.
- Version-tag backups; alert on backup-job failure the day it happens.
- Document the frozen-tenant boundary in the backup runbook so nobody rediscovers it mid-restore.

---

## Playbook G — gRPC connectivity issues

### Symptom

Clients failing to connect or timing out on data operations (modern clients use gRPC for
queries/batching), while REST endpoints — health checks, `/v1/meta` — look fine. "The health check
passes but the app is down."

### First 5 minutes — collect

```bash
# Is the gRPC port reachable from where the CLIENT runs? Default: 50051.
nc -zv <weaviate-host> 50051

# Compare paths: REST OK + gRPC dead = network/LB/config issue on the gRPC path specifically
curl -s http://<weaviate-host>:8080/v1/meta | jq .version
```

- Exact client library and version, exact server version.
- Full client error text (gRPC status codes — UNAVAILABLE, DEADLINE_EXCEEDED, UNIMPLEMENTED —
  point at different layers).
- What sits between client and server: Service/Ingress/LB/proxy/service mesh? gRPC (HTTP/2) has
  different requirements from plain HTTP, and many LB/ingress setups need explicit configuration
  to carry it.

### Likely causes, ranked

1. **gRPC port not exposed end-to-end** — 50051 missing from the Service/LB/firewall while 8080
   is open. Most common on first deployment.
2. **LB/proxy not handling gRPC** — ingress not configured for HTTP/2-gRPC pass-through, or
   **idle/response timeouts killing long-lived gRPC streams** mid-batch (imports die after a
   suspiciously round number of seconds).
3. **Client/server version mismatch** — verified pairing: **Python client 4.23.x pairs with
   server 1.39.x.** A client much newer than the server (or the reverse) can fail on gRPC
   features one side lacks; check the client-release-to-server-version compatibility table for
   your client language.
4. **TLS mismatch** — one side expecting TLS on the gRPC channel, the other not, or certs valid
   for the REST hostname but not the gRPC one.
5. **Client misconfiguration** — wrong gRPC host/port in the connection settings (clients
   configure REST and gRPC endpoints separately; the REST one being right proves nothing about
   the gRPC one).

### Fix per cause

1. Expose 50051 the whole way: container port → Service → LB/firewall. Verify with `nc`/`grpcurl`
   from the client's network, not from the Weaviate host.
2. Configure the ingress/LB for gRPC per its documentation; raise idle/stream timeouts above your
   longest realistic batch/query duration.
3. Align versions per the compatibility table — and fold client upgrades into the server upgrade
   ladder (OPS-GUIDE section 2) so they move together deliberately.
4. Make TLS symmetric and certs valid for the names actually dialed.
5. Fix the client's gRPC host/port settings.

### Verify recovered

- A real data operation (query and a small batch insert) succeeds from the affected client
  environment — not just a port check.
- A batch import running longer than the previous timeout completes.
- No elevated gRPC error rate over the next traffic cycle.

### Prevent recurrence

- Synthetic check that exercises the gRPC path (a tiny real query), not only REST health.
- Client version pinned and recorded in the same upgrade runbook as the server version.
- LB/ingress gRPC settings documented next to the deployment manifests.

---

## Playbook H — After-upgrade regressions

### Symptom

Something is worse after an upgrade: latency up, errors up, a feature behaving differently, a
crash loop.

### First 5 minutes — collect

- Pin the timeline: exactly what was upgraded (server minor? patch? chart? client?), when, and
  when the symptom started. "After" must be established, not assumed.
- `curl -s $BASE/v1/meta | jq .version` on **every node** — a half-rolled upgrade (nodes on mixed
  versions) is itself a leading cause.
- Compare your benchmark/canary query results against the pre-upgrade run (you ran one — OPS-GUIDE
  section 2).
- Read the release notes for the version you landed on, looking for changed defaults. Concrete
  example of the class: `searchProbe` defaulting to 256 since v1.38.2 — a behavior change you get
  by upgrading, not by touching config.
- Classify: crash/unavailability (act now) vs. degradation (measure first) vs. behavior change
  (maybe working as newly intended).

### First, understand your rollback limits

- **You generally cannot restore a newer-format backup onto an older server** — so "restore
  yesterday's post-upgrade backup onto the old version" is not a path. Specifically (verified):
  pre-1.39-format backups don't restore on 1.39; the reverse direction is not a supported escape
  hatch either.
- Downgrading a server binary over data files a newer version has already migrated is not a
  supported operation. Assume you cannot do it safely unless the release notes for your exact
  versions say otherwise.
- Your only true rollback asset is the **pre-upgrade backup + the old binary** — and it is a
  restore to a point in time: **every write since the upgrade is lost** if you use it.

This is why the default posture is: **roll forward with fixes.**

### Likely causes, ranked

1. **Changed defaults/behavior in the new version** — intended changes interacting with your
   workload (the `searchProbe` class of issue).
2. **Incomplete rollout** — mixed-version nodes, old chart with new image or vice versa, a config
   key renamed/removed between versions that is now silently ignored.
3. **Client/server mismatch** — server upgraded, clients not (or not to a paired release — see
   Playbook G, e.g. client 4.23.x ↔ server 1.39.x).
4. **A genuine regression in the release.**

### Fix per cause

1. Read the release notes/docs for the changed default; explicitly set the value your workload
   needs; benchmark to confirm (Playbook C method: one knob at a time).
2. Complete the rollout: all nodes to the same target version; validate every config key you set
   still exists under that version (check the docs — don't assume warnings will tell you).
3. Upgrade clients to the paired release.
4. Roll forward: check whether a newer patch in the same minor fixes it (weekly release-note scan,
   OPS-GUIDE section 7); search/file an upstream issue with your evidence; mitigate meanwhile
   (config, client-side workarounds). Reserve the pre-upgrade-backup restore for the case where
   the cluster is truly unusable *and* losing post-upgrade writes is acceptable — and say that
   trade-off out loud before executing it.

### Verify recovered

- Benchmark/canary results back to (or better than) the pre-upgrade baseline.
- All nodes on one version; `/v1/nodes` healthy; error rates at baseline over a full traffic
  cycle.
- A fresh backup taken and verified **on the new version** (mandatory after landing on 1.39 —
  see OPS-GUIDE section 2).

### Prevent recurrence

- **One minor at a time, always** — small hops make regressions attributable and keep every
  migration step tested (OPS-GUIDE section 2).
- Pre-upgrade backup per hop, retained until the hop has soaked.
- Quarterly upgrade rehearsal in staging with the benchmark query set, so changed defaults are
  discovered on Acme's staging cluster instead of by Acme's users.
- Release notes read *before* the upgrade, with a written list of changed defaults to re-test.

---

*Verified against Weaviate 1.37–1.39. Re-verify version-dependent statements on your version
before acting on them.*
