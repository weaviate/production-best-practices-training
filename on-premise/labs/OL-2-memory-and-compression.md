# OL-2 — Memory & Compression Operations (self-paced, ~40 min)

Memory is the resource that kills self-hosted Weaviate clusters — OPS-GUIDE section 4 and
Playbook A both end up here. This lab makes the biggest structural mitigation, **RQ-8
quantization**, concrete: you capture baseline memory evidence, benchmark the uncompressed
collection, build an RQ-8 compressed variant of the same data, and then make the call the way an
SRE has to — in writing, with numbers, and with a rollback path.

**Every number in this lab is a mechanics demo, not a capacity claim.** The seeded dataset
(50k objects × 256 dims) is deliberately small; the *mechanisms* — ≈4× less vector memory,
rescoring from disk, a measurable recall/latency trade — are what transfer to production scale.
The absolute numbers do not.

Scenario: Acme's on-prem cluster grows 15% month over month. The memory trend line says you have
a quarter, maybe two, before the OOM killer introduces itself. Procurement for more RAM takes
eight weeks. Before that meeting, you want first-hand evidence of what RQ-8 costs and saves.

## Purpose & objectives

After this lab you can:

1. Capture per-node memory evidence from two independent sources (Grafana memory panels and
   `docker stats`) and explain why you want both.
2. Run the `baseline` and `rq8` bench presets and build a before/after table: memory footprint,
   recall, p50/p95 latency.
3. Explain why quantization settings on an existing collection are treated as immutable in
   practice — and therefore why the preset builds a **separate collection**.
4. Write a 5-sentence compression recommendation with a rollback path, honestly caveated.

## Prerequisites & preflight

- Stack up and seeded (`make up`, `make seed` from `labs/platform/`); harness commands run
  **from the repo's `labs/` directory** with `PYTHONPATH=src`.
- Grafana open in a browser at `http://localhost:3000`; find the memory panels on the shipped
  dashboard (read what the panels query rather than memorizing metric names — they vary by
  version).

```bash
cd labs/platform && make verify
docker stats --no-stream
```

**Expected:** all 7 verify checks green; `docker stats` lists the three Weaviate containers
(weaviate-1/2/3) each holding a steady, boring amount of memory — tens to a few hundred MB on
the seeded demo data (machine-dependent; verify on yours). If verify is red, `make reset` first.

## Timebox (~40 min)

| Minute | Checkpoint |
|---|---|
| 8 | Preflight green; baseline memory evidence recorded (Grafana panel + `docker stats`) |
| 16 | `--preset baseline` run; recall and p50/p95 recorded; prediction for RQ-8 written down |
| 26 | `--preset rq8` complete (includes its ~1–2 min re-seed); second memory reading taken |
| 33 | Before/after table complete, every row caveated |
| 40 | 5-sentence recommendation with rollback path written; cleanup done |

## Tasks

1. **Capture baseline memory evidence — two sources.** In Grafana, screenshot or note the
   per-node memory panels at idle. In a terminal:

   ```bash
   docker stats --no-stream
   ```

   Record per-container memory. Two sources because they can disagree: the dashboard shows the
   process's view over time (trend — the thing that predicts OOM), `docker stats` shows the
   container's view right now. This is memory reading 1 of 3.

2. **Run the uncompressed baseline.** From `labs/`:

   ```bash
   PYTHONPATH=src python -m acme.bench --preset baseline
   ```

   Record from the printed summary: recall, p50/p95 latency, throughput. Take memory reading 2
   (`docker stats --no-stream` plus the Grafana panel) after the run.

3. **Predict before compressing.** Write down: after building the RQ-8 variant, (a) roughly how
   much less vector memory should the compressed collection need, (b) will recall crater, hold,
   or something in between — and *why* (hint: what does rescoring read, and from where)?

4. **Build and benchmark the RQ-8 variant.** From `labs/`:

   ```bash
   PYTHONPATH=src python -m acme.bench --preset rq8
   ```

   This preset creates a **separate collection** with RQ-8 enabled, re-seeds the same data into
   it (expect ~1–2 minutes for the re-seed — an estimate; verify on your machine), and runs the
   same benchmark. It uses a separate collection **deliberately**: quantization settings on an
   existing collection are not something you toggle in place — treat them as immutable once the
   collection holds data, and treat "compress an existing collection" as a migration
   (new collection, re-import, cut over), exactly as the preset models. Verify what your version
   allows before assuming otherwise — check the docs for your version.

   Two mechanisms to watch for in the results:

   - **Vector memory drops ≈4×** for the compressed collection (8-bit codes instead of
     float32). On this demo dataset the absolute saving is small; at production scale the same
     ratio is the difference between fitting in the fleet and not.
   - **Rescoring reads original vectors from disk** to repair result quality: expect recall
     close to baseline at some latency cost, often visible in the tail — how much depends on
     your disk (verify on your run).

   Take memory reading 3 when it finishes, and score your task-3 predictions.

5. **Build the before/after table.** Columns: metric, baseline, rq8, delta. Rows: memory (your
   three readings — note that both collections now coexist, so *total* process memory rose; the
   comparison that matters is per-collection vector memory, ≈4× apart), recall, p50, p95. Label
   every row **"mechanics demo — 50k × 256, not capacity evidence."**

6. **The decision exercise — exactly 5 sentences.** For a hypothetical Acme collection 100×
   this size and still growing, write the recommendation you would put in front of the team:

   1. The recommendation itself (RQ-8, more RAM, or both — and in what order).
   2. The expected gain, stated with the RQ-8 ≈4× vector-memory reduction claim *as a claim to
      be validated on staging data*, not a promise.
   3. The cost: rescoring reads original vectors from disk, so disk latency now sits in the
      query path — name what you would measure before and after.
   4. The rollback path: because compression is a new collection plus a cut-over, rollback is
      "point clients back at the uncompressed collection" — say what you keep running, and for
      how long, to make that real.
   5. The mandatory caveat: today's numbers are from 50k × 256 vectors — a mechanics demo — and
      the production decision needs the same measurement re-run at representative scale.

## Verify your work

```bash
cd labs/platform && make verify
```

**Expected:** all 7 checks green. Your table has every row filled from *your* runs, not this
document's prose, and your recommendation has all five sentences including the rollback path and
the scale caveat. Sanity check: rq8 recall should be in the same neighborhood as baseline — if
it cratered, do not force the expected story; note it honestly and check the run output
(evidence before conclusions).

## Reset & cleanup

The rq8 preset leaves its extra collection behind, which would skew any later memory
observations (including OL-3's baselines). Return to the seeded baseline:

```bash
cd labs/platform && make reset && make verify
```

Keep your table and recommendation. Safety boundary: never enable or disable quantization on a
shared or production collection as part of a lab — in production, RQ-8 is evaluated on a staging
copy with your own recall/latency check before rollout, and this lab is the rehearsal of that
method, not a substitute for it. Do not quote this lab's absolute numbers in a capacity plan;
for planning, use the memory model in OPS-GUIDE section 4.

## If you're stuck

1. **The rq8 run seems hung.** It re-seeds ~50k objects into a new collection first — that is
   the ~1–2 minute pause before any benchmark output. Watch `docker stats` (CPU active on the
   Weaviate containers) or the harness's progress output before concluding it is stuck.
2. **Memory readings look identical before and after rq8.** On a dataset this small, the
   per-container delta can drown in noise — that is itself a finding worth writing down. The
   comparison the lab wants is the *per-collection vector memory* difference, which the bench
   output reports; the container totals are context, not the verdict.
3. **Recall or latency numbers make no sense (recall near zero, latencies wildly unstable).**
   Something else is loading your machine, or the stack is degraded. Close the noise, run
   `make verify`, and if it is not 7/7 green, `make reset` and redo tasks 2 and 4 back-to-back —
   the two runs must be compared under the same conditions or the comparison is worthless.
