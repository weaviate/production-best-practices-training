# On-Premise Weaviate Operations Guide

Audience: the Acme platform team running self-hosted Weaviate (docker-compose or Kubernetes/Helm).
Everything here follows the course discipline: **evidence first, then action; verify on your
version; practice the scary operations before you need them.**

Version scope: written and verified against Weaviate **1.37–1.39**. Version-dependent statements
say so explicitly. For anything else — exact config keys, metric names, chart values — treat the
official docs for your exact version as the source of truth.

---

## 1. Deployment topologies

### Single node

One Weaviate process, one data volume. Fine for development, demos, and small internal tools where
downtime is acceptable.

What a single node **cannot** give you, no matter how big the machine:

- No high availability. Node down = cluster down.
- No replication. Disk loss = data loss since your last backup.
- Restarts (upgrades, OOM kills, host maintenance) are user-visible outages.

If any of those are unacceptable, you need a cluster.

### 3-node RAFT cluster

Since Weaviate moved cluster metadata to RAFT consensus, the practical minimum for HA is **three
nodes**: RAFT needs a majority (quorum) to accept metadata changes, and with three nodes you can
lose one and keep a 2-of-3 majority. Two nodes is worse than it sounds — losing either one loses
quorum, so you have paid for redundancy without getting availability.

**RAFT quorum protects metadata operations (schema changes, tenant operations). It does not, by
itself, replicate your data.** That is the replication factor's job.

### Replication factor: why HA needs RF > 1

Replication factor (RF) is set per collection. With RF=1, each shard lives on exactly one node —
so even in a 3-node cluster, losing a node makes that node's shards unavailable. **A 3-node
cluster with RF=1 is not HA. It is three single points of failure that share a schema.**

For HA at Acme scale:

- RF=3 on a 3-node cluster: every shard on every node; any single node can fail with no data
  unavailability. Costs 3× the storage and memory for vectors.
- RF=2 is a middle ground but interacts awkwardly with quorum-based consistency on reads/writes;
  think it through per collection before choosing it.

Choose RF at collection creation time and treat changing it as a planned migration, not a knob —
verify on your version what changing RF on an existing collection actually does before relying
on it.

**Checkpoint.** Run this against your cluster and confirm you see the node count and shard
distribution you think you have:

```bash
curl -s http://localhost:8080/v1/nodes | jq .
```

If what you believe about your topology and what `/v1/nodes` says disagree, stop and reconcile
that before doing anything else in this guide.

---

## 2. Version & upgrade management

### Supported window

Treat **1.37–1.39** as the supported window this material is verified against. Running older than
that means you are outside both this guide and, in practice, most upstream attention. Know your
version cold:

```bash
curl -s http://localhost:8080/v1/meta | jq .version
```

### The upgrade ladder: one minor at a time

Upgrade **one minor version per hop** (1.37 → 1.38 → 1.39), with health verification between hops.
Skipping minors means skipping the migration steps each minor performs on startup, and puts you in
a state nobody has tested.

Per hop:

1. Take a backup and **verify it completed successfully** (poll the backup status endpoint until
   it reports success — a started backup is not a finished backup).
2. Upgrade to the next minor only.
3. Verify health before declaring the hop done:
   - `/v1/.well-known/ready` returns 200 on every node.
   - `/v1/nodes` shows all nodes healthy and shard counts as expected.
   - `/v1/meta` reports the version you think you deployed.
   - A known query returns known results (keep a "canary query" with an expected answer).
4. Soak — let it run under real traffic for a period you have agreed in advance (hours to a day,
   not minutes) before the next hop.

### Helm caveat (verified at time of writing)

Helm chart **17.8.x does not yet ship a 1.39 chart default** — to run 1.39 you override the image
tag to a 1.39.x image:

```yaml
# values override — chart 17.8.x
image:
  tag: "1.39.x"   # pin the exact patch you tested, not a floating tag
```

Check the chart repository before every upgrade: this caveat is dated the moment a newer chart
lands.

### CRITICAL: 1.39 backup format rule

**Backups taken in pre-1.39 formats are not restorable on a 1.39 server.** Two operational
consequences, both non-negotiable:

1. **Immediately after upgrading to 1.39, take a fresh backup.** Until you do, your only backups
   are ones a 1.39 server cannot restore — meaning that for that window you have an upgraded
   cluster and no usable backup for it.
2. Your rollback story changes: see the after-upgrade-regressions playbook. In general you cannot
   restore newer-format backups onto older servers either, so the pre-upgrade backup + the old
   binary is your rollback path, and it goes stale the moment new writes land on 1.39.

### Checkpoint

Write down, right now: current version, target version, the ladder of hops between them, and where
the pre-upgrade backup for each hop will live. If you cannot fill in that table, you are not ready
to upgrade.

---

## 3. Security hardening

### The default is anonymous access — fix that first

Open-source Weaviate ships with **anonymous access allowed by default**. That is convenient for a
laptop and indefensible in production. The first production act on any Acme cluster is:

```yaml
# environment
AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "false"
```

Then enable authentication (API keys and/or OIDC) and authorization (RBAC) — the exact set of
config keys for API-key users and RBAC roles varies by version, so **check the exact keys for your
version in the docs** rather than copying a blog post. The order matters: turning off anonymous
access without configuring auth locks everyone out, so stage both together and test with a
non-admin key.

Minimum bar for a production cluster:

- Anonymous access disabled.
- Auth enabled; at least two identities: an admin key (break-glass, rarely used) and per-service
  keys with the narrowest RBAC roles your version supports.
- Read-only roles for dashboards and humans-poking-around.

### API keys never live in values files

A Helm values file goes into Git; Git history is forever. API keys and OIDC secrets go into
**Kubernetes Secrets created out-of-band** (sealed-secrets, external-secrets, SOPS, or a manual
`kubectl create secret` from a vault-sourced value), and the values file references the Secret by
name only. Check the chart documentation for the exact values keys that reference an existing
Secret on your chart version.

Same principle for docker-compose: keys come from an env file that is excluded from version
control, or from your secrets manager — never inline in the committed compose file.

### Network posture

- Do not expose 8080 (HTTP) or 50051 (gRPC) to networks that do not need them. Cluster-internal
  ports (gossip, RAFT) should be reachable only between Weaviate nodes.
- TLS: terminate at an ingress/LB you control, or configure it end-to-end if your threat model
  requires it. gRPC through an LB has its own failure modes — see the gRPC playbook.

**Checkpoint.** From a network location that should *not* have access, run
`curl -s http://<host>:8080/v1/meta`. If you get a version string back with no credentials, your
hardening is not done.

---

## 4. Resource management

### Memory: the rule of thumb

The dominant memory consumer is the HNSW vector index, which lives in memory. Rule of thumb
(**an estimate for planning, not a guarantee — measure your own cluster**):

> RAM needed for vectors ≈ **2 × raw vector bytes**, where raw vector bytes =
> objects × dimensions × 4 bytes (float32). The ~2× covers the HNSW graph structure and
> operational overhead on top of the vectors themselves.

Worked example (estimate): 10M objects × 1536 dims × 4 B ≈ 61 GB raw → plan on the order of
**~120 GB** of vector memory per copy, multiplied by your replication factor across the cluster.
On top of that, leave room for the OS page cache — Weaviate's on-disk structures benefit heavily
from it.

Quantization (e.g. RQ-8, ≈4× vector-memory reduction) changes this arithmetic dramatically — see
the memory-pressure playbook.

### GOMEMLIMIT

Weaviate is a Go process; set `GOMEMLIMIT` so the Go runtime knows its budget and starts GC'ing
harder before the kernel OOM-kills the process. Common practice is to set it to roughly 80–90% of
the container memory limit (estimate — tune for your workload):

```yaml
# environment
GOMEMLIMIT: "100GiB"   # below the container limit, e.g. limit 120Gi
```

An OOM kill is a crash with recovery cost; GC pressure is degradation with a metrics trail. You
want the second failure mode, not the first.

### What happens under memory pressure

In order of increasing badness:

1. GC runs more often and burns CPU; p95/p99 latency climbs.
2. Allocations start failing or stalling; imports slow down or error.
3. The kernel OOM-kills the process; the node restarts, replays/recovers, and (with RF=1) its
   shards are unavailable the whole time. Repeat OOM kills can become a crash loop.

The observability section tells you how to see stage 1 before you meet stage 3.

### Disk headroom

Keep real headroom on the `PERSISTENCE_DATA_PATH` volume — compactions, backups staged locally,
and tombstone-heavy periods all need scratch space. As a planning estimate, alert well before the
volume is full (e.g. warn at 70–75%, act at 85%) and treat a full data volume as an outage in
progress, not a warning. See the disk-pressure playbook for what actually grows and what is safe
to remove (short version: almost nothing, by hand).

**Checkpoint.** For your largest collection, compute the raw-vector-bytes estimate above and
compare with the live memory usage of the process. If the model and reality disagree by more than
~2×, find out why before trusting any capacity plan built on the model.

---

## 5. Backup & restore operations

### Backups

Configure a backup backend (filesystem for single-node testing; S3-compatible/GCS/Azure object
storage for anything real — module names and config keys are in the docs for your version).
Backups are triggered per-request via the backup API and cover the collections you specify.

Non-negotiables:

- **Verify completion.** Trigger, then poll status until `SUCCESS`. A cron job that fires the
  request and exits is not a backup system; it is a hope system.
- **Version-tag your backups.** Name or label every backup with the exact server version that
  produced it. The restore-compatibility rules (notably the 1.39 format rule in section 2) make
  "which version wrote this?" the first question of every restore.
- **Pre-upgrade backups are mandatory** — one per hop of the upgrade ladder.

### Multi-tenant nuance (verified for 1.37+)

Since **1.37**, backups include **HOT and COLD tenants**. **FROZEN tenants are skipped** —
frozen tenant data lives in offloaded storage, and the backup does not capture it. If Acme uses
tenant offloading, your backup story is therefore *two* stories: the Weaviate backup (hot/cold)
plus the durability and recovery story of the offload storage itself. Document both.

**Restore-test regardless.** Whatever mix of tenant states you run, the only proof that your
backup covers what you think it covers is a restore into a scratch environment followed by
counting and querying what came back.

### Restore drills: a practiced skill, not a checkbox

The schedule that has worked for teams like Acme's:

- **Backups:** daily automated, plus on-demand before every upgrade hop and schema migration.
- **Restore drill: monthly.** Restore the latest production backup into a scratch cluster running
  the same server version. Verify object counts per collection, run the canary queries, check
  tenant lists for multi-tenant collections. Time the drill — the duration is your real RTO input.
- Keep a written runbook of the drill and update it every time reality diverges from it.

The first time you run a restore must not be during an incident. Teams that skip drills discover
mid-outage that the backup bucket credentials expired four months ago.

---

## 6. Observability setup

### Metrics enablement

```yaml
# environment
PROMETHEUS_MONITORING_ENABLED: "true"
```

This exposes a Prometheus metrics endpoint (on a dedicated metrics port — check the port and any
related keys for your version in the docs). Scrape every node individually; per-node visibility is
the whole point in a cluster.

On Kubernetes, the Helm chart has values for enabling monitoring and (depending on your stack)
ServiceMonitor-style scrape configs — check your chart version's values reference.

### Dashboards

Weaviate publishes Grafana dashboards; start from those rather than building from scratch, then
add Acme-specific panels (canary query latency, import throughput). Wire dashboards to the same
per-node scrape so a sick node stands out instead of averaging away.

### What to alert on

Alert on symptoms first, causes second:

| Signal | Why | Suggested posture |
|---|---|---|
| Memory usage per node vs. limit (and Go heap trend) | The path to OOM is visible for hours before the kill | Warn at sustained high usage; page on rapid growth |
| Query latency percentiles — p50, p95, **p99** | Tail latency degrades first; averages lie | Alert on p95/p99 against your SLO, not on the mean |
| Import/queue failure signals (batch errors, indexing queue backlog growth) | Silent import failure is data loss discovered weeks later | Any sustained non-zero failure rate warrants a look |
| Node availability (`/v1/.well-known/ready` per node, node count in `/v1/nodes`) | A quietly missing node turns the next failure into an outage | Page on any node not ready beyond a short grace period |
| Disk usage on the data volume | Full disk is an outage in progress | Warn early (see section 4) |

Exact metric names vary by version — build alerts from the metric list your actual endpoint
exposes (`curl` it and read), not from a blog post.

### 1.39 note: debug endpoints

As of **1.39**, pprof/debug endpoints require explicit enablement:

```yaml
# environment
DEBUG_ENDPOINTS_ENABLED: "true"
```

Decide your posture in advance: enabled always (behind network controls) so profiling data is
available during an incident, or disabled with a documented, rehearsed procedure for turning it on
(which implies a restart). Discovering mid-incident that you cannot profile is the worst version.

**Checkpoint.** Kill a non-production node on purpose. Did an alert fire within your grace period?
If not, your node-availability alerting is decorative.

---

## 7. Routine ops calendar

Boring on purpose. The calendar exists so that the skills you need during incidents are warm.

### Weekly

- Review dashboards for trend, not just state: memory growth per node, p95/p99 drift, disk growth
  rate, import error counts.
- Verify last night's backup reports `SUCCESS` (automated check with an alert on failure — the
  weekly task is confirming the automation itself is alive).
- Scan Weaviate release notes for new patch releases in your minor and for security advisories.
- Check certificate and credential expiry horizons (backup bucket creds included).

### Monthly

- **Restore drill** (section 5): latest production backup → scratch cluster → verify counts,
  canary queries, tenant lists. Record the duration.
- Patch-version upgrade if a relevant patch exists (after reading its release notes).
- Review capacity model vs. reality: re-run the section 4 checkpoint numbers.
- Review RBAC: keys and roles that exist vs. keys and roles that should exist.

### Quarterly

- **Upgrade rehearsal**: run the full one-minor upgrade ladder (backup → upgrade → verify → soak)
  in a staging cluster that mirrors production topology — even if you do not plan to upgrade
  production this quarter. The rehearsal keeps the runbook honest.
- Failure drill: take down one node of the staging cluster under load; confirm behavior matches
  the node-down playbook and that alerts, dashboards, and the on-call runbook all told the truth.
- Review this guide and the playbooks against the current docs for your version, and update
  anything that has drifted.

---

*Everything above was written against Weaviate 1.37–1.39. If you are reading this far from that
window, re-verify before acting.*
