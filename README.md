# Production Best Practices with Weaviate - Training

Materials for the instructor-led course **Advanced: Production Best Practices with Weaviate** (2 days x 4 hours or one full day), plus a self-study operations module for on-premise deployments. Customer-agnostic: the running example throughout is **Acme**, a fictional company.

## What's here

| Path | Contents |
|---|---|
| `deck/` | Course slide deck (71 slides, no speaker notes): architecture & sizing, ingestion, indexing & compression, querying, replication & failure, observability, security/RBAC, multi-tenancy, backup & upgrade |
| `course/` | Participant workbook (Lab 1 sizing worksheet and course reference sheets) |
| `labs/` | Four hands-on labs + capstone: sizing (paper), benchmark & tune (`acme` harness), failure & recovery, observability & incident |
| `on-premise/` | Self-study module for self-hosted Weaviate: ops guide + symptom-driven troubleshooting playbooks |
| `VERSION_MATRIX.md` | The exact versions this course is pinned to and why |

## Version baseline

Weaviate **1.39.x** / Python client **4.23.x** / Helm chart 17.8.x with `image.tag` override (no 1.39 chart at time of writing). Where behavior differs across versions the materials say so; the course rule is *verify on your version*.

## How the labs run

Lab 1 and the capstone are deliberate paper labs. Labs 2-4 run against a Weaviate cluster provided by your instructor (Weaviate Cloud or the 3-node compose stack in `labs/platform/`). **No credentials exist anywhere in this repository**; endpoints and API keys are distributed separately by the instructor, per pair.

## For self-study

Start with `deck/` for theory, then `on-premise/OPS-GUIDE.md` if you operate Weaviate yourself; keep `on-premise/TROUBLESHOOTING-PLAYBOOKS.md` within arm's reach for incidents. The labs are runnable self-paced against your own cluster via `labs/platform/` (docker compose).

(c) Weaviate - training material. Estimates in these materials are labeled estimates and are not sizing guarantees.
