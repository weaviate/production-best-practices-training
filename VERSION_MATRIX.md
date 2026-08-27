# VERSION_MATRIX — pinned technical baseline

Checked **2026-07-13** against primary sources only (see `SOURCES.md`; per-claim evidence in `research/claim-ledger.csv`).
Authority order used: current official docs/release notes/source → behavior reproduced against the pinned environment → existing course repo → curriculum/marketing material.

## Version contract

| Component | Pin | Source of truth | Notes |
|---|---|---|---|
| Weaviate Database | **v1.38.3** | github.com/weaviate/weaviate `releases/latest` (2026-07-10) | Latest stable. Support window = 1.36.x/1.37.x/1.38.x. v1.38.4 does not exist (404). |
| Server Docker image | `cr.weaviate.io/semitechnologies/weaviate:1.38.3` | Official Docker install docs | Digest to be recorded at first pull in the lab environment (registry unreachable from build sandbox at pin time — see BUILDINFO.md). |
| Python client | **weaviate-client == 4.22.0** | GitHub releases/latest + docs changelog (2026-06-18) | Docs client page displays stale 4.21.3 — flagged. Compat matrix pairs 1.38.x ↔ 4.22.x. |
| TypeScript client | 3.13.1 (reference only) | GitHub releases | Docs compat matrix has blank TS cells for 1.38.x — flagged; not the canonical lab language. |
| Helm chart | **weaviate-helm 17.8.3** | github.com/weaviate/weaviate-helm releases (2026-07-01) | Chart pins app **v1.38.2** — labs MUST override `image.tag=1.38.3` to match the server pin. |
| Kubernetes (labs) | 1.31.x (kind node image pinned in labs/platform/) | kind release matrix | No supported-K8s statement in weaviate-helm release notes — flagged; chosen as current widely-supported minor. |
| Python (labs) | 3.12.x | PROJECT_CONFIG + client support | Managed via `uv`; lockfile committed. |
| Tooling | uv (lock), ruff, mypy, pytest | course engineering contract | Exact versions in `labs/pyproject.toml` + lockfile. |
| Prometheus / Grafana (labs) | pinned in `labs/platform/` compose/manifests | official images | Versions recorded at environment build. |

## Feature maturity map (v1.38.3) — teaching labels

Full detail + verbatim sources: `research/feature-maturity-matrix.md`.

| Feature | Maturity @1.38.3 | Course stance |
|---|---|---|
| HNSW, flat index | GA | Core |
| HFresh index | **GA in 1.38** (preview in 1.36) | Core, with explicit `searchProbe` (see contradictions) |
| Dynamic index | **Experimental** ("use with caution", v1.25+) | Taught as exists-but-not-default; not in core labs |
| Async vector indexing | No maturity badge in docs | Taught with "no GA badge" label; required by dynamic index & AutoPQ |
| RQ-8 / RQ-1 | Documented without preview label (v1.32/v1.33; flat since 1.35) | Core quantization ladder. **Nothing quantizes by default**: `DEFAULT_QUANTIZATION` defaults to `none` |
| PQ / BQ / SQ | GA | Taught where justified |
| ACORN filter strategy | Default since v1.34 | Core |
| Server-side batching (`batch.stream()` / `data.ingest`) | GA server 1.36 / python client 4.20 | Core default ingestion path |
| Async replication | GA since 1.29; **default-on for RF>1 in 1.38**; cluster-wide scheduler | Core |
| Replica movement | **Production-ready in 1.38**, still gated by `REPLICA_MOVEMENT_ENABLED=true` | Core |
| Collection aliases | GA | Core (zero-downtime migration) |
| RBAC | GA since 1.29 (built-ins: `root`, `viewer` only) | Core |
| Dynamic DB users | v1.30+ | Core |
| MCP Server | **CONFLICT: GitHub v1.38.0 notes say "Preview"; weaviate.io 1.38 blog says "generally available"** | Appendix only; discrepancy shown verbatim, unresolved |
| Boost API, nested-object filtering, namespaces, alter-schema-reindex | Preview in 1.38 | Appendix only, labeled Preview |
| HNSW snapshots | Default-on since 1.36 | Mentioned in ops content |

## Known contradictions & stale docs (tracked; do not paper over)

| # | Contradiction | Handling |
|---|---|---|
| C-1 | HFresh `searchProbe` default: docs say 64; v1.38.3 release notes say raised to 256 (#11955) | Labs set `searchProbe` explicitly; slide shows "configure explicitly". To be resolved by live check against pinned server when environment is available. |
| C-2 | MCP Server GA (blog) vs Preview (GitHub release) | Preserved verbatim in appendix A6. |
| C-3 | Docs python-client page shows 4.21.3; latest is 4.22.0 | Pin from GitHub releases; noted. |
| C-4 | Slow-query-log settings: runtime-config page says runtime-mutable; env-vars page says restart-required | Teach as "verify on your version"; live check planned. |
| C-5 | Backups & INACTIVE tenants: concepts page vs 1.37 blog disagree | Teach v1.37+ behavior (INACTIVE included, OFFLOADED always skipped) with caveat + restore-test discipline; live check planned. |
| C-6 | Helm chart app version (1.38.2) ≠ latest server (1.38.3) | Explicit `image.tag` override in all lab manifests. |
| C-7 | Anonymous access default: env-vars table says `true`; auth page silent | Security module teaches explicit disable regardless. |
| C-8 | Replication `deletionStrategy` default: source-course audit found wording conflicting with r3 research (NoAutomatedResolution vs newer default) | Teach "verify on your version"; live check planned; see audit/existing-course-audit.md. |

## Upgrade doctrine (verified)

One minor version at a time; never skip; use the latest patch of each minor at every hop (docs.weaviate.io/deploy/migration). Multi-node RAFT downgrade floor: v1.27.26. Pre-1.30 collections: BlockMax WAND 3-stage migration applies. No documented breaking changes 1.36→1.38.
