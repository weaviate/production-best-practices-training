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

All examples use a fictional company, **Acme**. Adapt names, sizes, and schedules to your reality —
but do not skip the drills.
