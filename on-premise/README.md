# On-Premise Weaviate: Operations & Troubleshooting

A self-study module for platform and SRE teams running **self-hosted Weaviate** — docker-compose or
Kubernetes/Helm — as opposed to Weaviate Cloud. If someone else runs your cluster for you, most of
this module is not your problem. If *you* run it, all of it is.

## Who this is for

- Platform engineers and SREs who own a Weaviate deployment end to end: capacity, upgrades,
  backups, on-call.
- Developers who deploy self-hosted Weaviate and get paged when it misbehaves.
- Anyone rehearsing for the day a node goes down at 03:00.

## How this relates to the instructor-led course

The instructor-led production-best-practices course covers schema design, querying, batching, and
client-side discipline. This module is the **operations deep-dive** that the course points at but
does not walk through live: deployment topology, upgrade ladders, backup/restore drills, and
symptom-driven incident playbooks. Use it two ways:

1. **Self-study deep-dive** after the course — work through OPS-GUIDE.md top to bottom, doing the
   checkpoints against your own cluster.
2. **Reference under pressure** — TROUBLESHOOTING-PLAYBOOKS.md is written to be opened mid-incident
   and followed step by step.

The same ground rules apply as in the course: evidence before conclusions, no hand-waving, and
**verify on your version** — behavior described here was verified against Weaviate 1.37–1.39, and
anything version-dependent says so explicitly. When in doubt, the release notes and official docs
for *your exact version* win over this document.

## File map

| File | What it is |
|---|---|
| `README.md` | This file — orientation and scope. |
| `OPS-GUIDE.md` | The operations guide: topology, versions & upgrades, security hardening, resources, backup/restore, observability, routine ops calendar. |
| `TROUBLESHOOTING-PLAYBOOKS.md` | Eight symptom-driven playbooks: memory pressure, node down / quorum loss, slow queries, import failures, disk pressure, backup/restore failures, gRPC connectivity, after-upgrade regressions. |
| `labs/` | Three self-paced ops labs (below) — the playbooks, rehearsed on your own stack. |

## Hands-on labs

Reading a playbook is not the same as having run it. The `labs/` directory holds three self-paced
labs (**~2 hours total**) that run against the 3-node docker-compose stack in the repo's
`labs/platform/` — your own machine, your own faults, no instructor required. Do them in order;
each assumes a healthy cluster (`make up`, `make seed`, `make verify` all green) to start.

| Lab | Time | What you rehearse |
|---|---|---|
| `OL-1-node-failure-drill.md` | ~45 min | Kill one node of your own cluster; predict, then prove, what ONE/QUORUM/ALL each survive; watch async replication converge on evidence, not hope. |
| `OL-2-memory-and-compression.md` | ~40 min | Baseline memory evidence, then measure what RQ-8 quantization actually trades — vector memory vs recall vs latency — and write the recommendation with a rollback path. Mechanics demo, not capacity numbers. |
| `OL-3-slow-query-investigation.md` | ~40 min | Generate mixed load, read p50 vs p95/p99 playbook-style, enable the slow-query log *before* the incident, tune one variable, write the incident summary. |

Every fault in these labs is one you inflict yourself with standard docker commands, so you always
know the ground truth — and the same rule applies as everywhere else here: verify on your version.

All examples use a fictional company, **Acme**. Adapt names, sizes, and schedules to your reality —
but do not skip the drills.
