# BYOC reference: Weaviate on Kubernetes (kind)

**Read this first: kind is a *learning fallback*, not the course delivery
path, and it does NOT reproduce multi-AZ behavior.**

## Where this fits

| Path | What it is | When to use |
|---|---|---|
| **Canonical (live delivery)** | The docker-compose 3-node cluster in `labs/platform/docker-compose.yaml`, running on pre-provisioned sandboxes | All in-class labs (2, 3, 4, capstone demo) |
| **This directory (kind)** | The same topology expressed as Kubernetes: kind cluster (3 workers, `kindest/node:v1.31.9`) + weaviate-helm **17.8.3** with `image.tag=1.38.3` | Self-study of the BYOC/Helm mechanics after class; laptop experimentation |
| **Real multi-AZ** | Cloud Kubernetes (EKS/GKE/AKS) with nodes in ≥3 availability zones | Actual production HA - cannot be simulated locally |

## What kind teaches vs what it lies about

Teaches (faithfully): Helm values shape, chart-pin vs image-pin (the chart
pins app **1.38.2**; we override `image.tag=1.38.3` to match the course
version contract — contradiction C-6 in `VERSION_MATRIX.md`), StatefulSet
rollout with `maxUnavailable: 0`, PodDisruptionBudgets, readiness gates,
topologySpreadConstraints *syntax*.

Lies about (unavoidably): the three "zones" (`sim-az-a/b/c`) are labels on
**one physical machine sharing one kernel, one disk, and one power cord**.
Scheduling spreads pods "across zones", but zone failure isolation is zero.
Any conclusion about AZ resilience drawn from kind is invalid. Real multi-AZ
requires cloud Kubernetes with actual zonal node groups.

## Usage (requires network egress)

```bash
export WEAVIATE_API_KEY_ROOT=<rotated-key>
export WEAVIATE_API_KEY_READONLY=<rotated-key>
./install.sh
```

The script is strict-mode bash, checks prerequisites (`kind`, `kubectl`,
`helm`), refuses placeholder keys, pins chart `17.8.3` + image `1.38.3`,
applies timeouts on every step, and ends with a 3/3-ready health wait loop.

Prerequisite versions: kind ≥ 0.23, helm ≥ 3.14, kubectl matching 1.31.x.

## Notes / pending validation

* `values-weaviate.yaml` key names follow the weaviate-helm 17.8.3 schema;
  `helm template` validation needs the chart pulled and is tracked in
  `labs/PENDING_VALIDATION.md`.
* API keys go into a Kubernetes Secret created by the script - never into
  values files or this repo.
* Backups on the BYOC path should use `backup-s3`/`backup-gcs`/`backup-azure`;
  `backup-filesystem` is single-node-only per the docs.
