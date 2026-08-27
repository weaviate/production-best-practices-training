# OL-3 — Slow Query Investigation (self-paced, ~40 min)

"It's slow" is the vaguest page you will ever get, and there is no instructor here to tell you
what happened — which is the realistic part. In this lab you generate mixed query load on your
own stack, read the latency distribution the way Playbook C says to (percentiles before
averages, evidence before knobs), tune exactly **one** variable, and write the incident-style
summary. Along the way you fix the one thing that cannot be fixed mid-incident: the slow-query
log, which must be enabled *before* you need it.

Scenario: Acme's search users report intermittent slowness. The dashboard mean looks fine — the
mean is lying, as it does. Your job is to work out what moved, why, and what to change — with
evidence, one variable at a time.

## Purpose & objectives

After this lab you can:

1. Read p50 vs p95/p99 from the bench output and Grafana, and classify an incident as tail-only
   or median-shift.
2. Name candidate causes for "tails moved, median didn't" — GC pressure, node contention, `ef`,
   expensive filters — and say what evidence separates them.
3. Enable the slow-query log proactively, and explain why "enable it during the incident" is not
   a plan (restart required).
4. Tune one variable (`ef`), measure the recall/latency trade it buys, and stop there.
5. Write a 5-part incident summary someone else could act on.

## Prerequisites & preflight

- Stack up and seeded (`make up`, `make seed` from `labs/platform/`); harness commands run
  **from the repo's `labs/` directory** with `PYTHONPATH=src`.
- Grafana open at `http://localhost:3000` with the latency panel of the shipped dashboard
  located (read what the panel queries — metric names vary by version).

```bash
cd labs/platform && make verify
PYTHONPATH=src python -m acme.verify
```

**Expected:** `make verify` reports all 7 checks green, and the harness's own verify (run from
`labs/`) passes. If not, `make reset` and re-verify before starting — you cannot investigate
latency on a cluster whose baseline health you cannot prove.

## Timebox (~40 min)

| Minute | Checkpoint |
|---|---|
| 8 | Slow-query log enabled on one node and that node restarted; verify green again |
| 15 | Baseline recorded; `--preset ef-sweep` load run; p50 vs p95/p99 comparison written down |
| 25 | Tail-vs-median analysis done; candidate causes ranked with the evidence for each |
| 33 | One variable (`ef`) tuned and re-measured; trade-off recorded |
| 40 | `make verify` green; incident-style summary written |

## Tasks

1. **Enable the slow-query log — now, before anything is slow.** The teaching point comes
   first because it has a restart in it: the slow-query log cannot be turned on mid-incident,
   so a cluster that reaches an incident without it investigates blind. The exact environment
   key and log format for your version: **check the docs for your version** (look for the
   slow-query log settings — an enable flag and a latency threshold). Then:

   - Add the setting(s) to **one** node's environment in the compose file under
     `labs/platform/` (one node is enough to see the mechanics; production would get all
     three), with the threshold set low enough that demo-scale queries can cross it.
   - Restart that node so the setting takes effect, and confirm health:

   ```bash
   cd labs/platform && docker compose up -d && make verify
   ```

   Compose recreates only the container whose configuration changed. Verify must be back to
   7/7 green before you continue. Write down how long the restart took — in production that is
   the cost of not having done this proactively.

2. **Record the healthy baseline.** From `labs/`:

   ```bash
   PYTHONPATH=src python -m acme.bench --preset baseline
   ```

   Write down p50 / p95 / p99, and note the resting shape of the Grafana latency panel.

3. **Predict, then generate mixed load.** Prediction first: if queries run with *varied* `ef`
   values, which moves more — the median or the tail — and why? Then:

   ```bash
   PYTHONPATH=src python -m acme.bench --preset ef-sweep
   ```

   The sweep runs the query set across a range of `ef` settings — deliberately mixed load, the
   shape a real cluster sees when different clients use different search parameters. (If you
   want more sustained load for the Grafana panel, repeat `--preset baseline` runs
   back-to-back.) While it runs, watch the latency panel.

4. **Investigate: p50 vs p95/p99.** From the sweep output and the Grafana panel, compare
   against task 2's baseline and classify: tail-only, or median shift? Then reason it through
   in writing — **why can tails move when medians don't?** Percentiles are populations, not
   averages: p99 moving alone means a *subset* of queries got slow. Rank the candidate causes
   and note what evidence would implicate each:

   - **GC pressure** — the process pauses everyone occasionally; shows up in memory/heap panels
     (Playbook A) and hits queries at random.
   - **Contention** — one busy or sick node drags every query that touches it; shows up in
     per-node panels and `docker stats`, not in the query text.
   - **`ef`** — high-`ef` queries do more graph work by design; shows up as *specific queries*
     being consistently slower — exactly what your sweep just manufactured.
   - **Filters** — low-selectivity filters combined with vector search; shows up in the
     slow-query log as a pattern in the query shapes (the `filter-strategy` preset explores
     this axis another day).

   Check the slow-query log on the node you enabled it on (`docker compose logs` for that
   node, from `labs/platform/`): do the slow entries correlate with the high-`ef` runs? That
   correlation — which queries, with which parameters — is what you would *not* have had
   without task 1.

5. **Tune ONE variable and re-measure.** The sweep data already shows the `ef` curve; now make
   the change deliberately. Predict first: at the lower `ef` you pick, what happens to p95, and
   what does it cost in recall? Then re-run the bench at that setting (the sweep output shows
   the per-`ef` results; a follow-up `--preset baseline` run gives you the restored-defaults
   comparison). Record latency *and* recall — a latency win that silently spends recall is not
   a win until someone signs off on the recall. One variable, measured, is the whole method;
   resist touching a second knob "while you're in there."

6. **Write the incident-style summary — five parts, one or two sentences each:**

   1. **Evidence:** the numbers — baseline p50/p95/p99 vs. under-load, and what the slow-query
      log showed.
   2. **Hypothesis:** the cause you settled on and the evidence that ranked it above the other
      candidates.
   3. **Fix:** the one variable you changed and its measured effect (latency *and* recall).
   4. **Verification:** how you proved restored state (task 7's checks — the tail recovered,
      verify green).
   5. **Prevention:** the slow-query log is now on *before* the next incident — say why that,
      and p95/p99 alerting, are the takeaways rather than the specific `ef` value.

## Verify your work

```bash
cd labs/platform && make verify
PYTHONPATH=src python -m acme.bench --preset baseline
```

**Expected:** 7/7 green, and the baseline run's p50/p95/p99 back in the neighborhood of task 2
(the presets restore any settings they mutate — this run is your proof of that; if the numbers
still look shifted, something else is loading your machine, or a setting stuck: compare with
`python -m acme.verify`). Your summary has all five parts, each carrying evidence, not vibes.

## Reset & cleanup

Leave the slow-query log **enabled** — that is the production posture this lab exists to teach;
revert the compose edit only if you want the checkout pristine. No other state should need
undoing (the presets restore what they mutate), but if anything looks off:
`make reset && make verify` from `labs/platform/`. Keep your summary — it is the template for
the real one.

Safety boundary: compose stack in `labs/platform/` on your own machine only. Repeated bench
runs are CPU-hungry; if your laptop becomes unusable, stop the runs first. Do not combine this
lab with OL-1's node kill — one fault at a time is the method, in labs as in production.

## If you're stuck

1. **You can't find the slow-query log settings.** Search the official docs for your Weaviate
   version for the slow-query log — do not guess environment keys, and do not copy a blog
   post's keys from a different version. If you truly cannot find it for your version, note
   that as a finding, skip the compose edit, and continue from task 2 — the rest of the lab
   works without it (you'll feel exactly what "investigating blind" means at task 4).
2. **p95/p99 barely move during the sweep.** Laptop-class machines with a small dataset can be
   too fast to show drama. Run 2–3 `--preset baseline` runs concurrently in other terminals to
   add contention, or compare the per-`ef` rows *within* the sweep output — the ef→latency
   relationship is visible there even when the Grafana panel stays calm.
3. **Nothing correlates and you're out of time.** Fall back to Playbook C's order and write the
   summary with what you have: percentile comparison (tail vs. median), one ranked cause list
   with evidence gaps named honestly, and the prevention line (slow-query log now on). An
   incident note that says "cause not confirmed; next evidence needed is X" is a *good* note —
   inventing a cause to close the ticket is the failure mode.
