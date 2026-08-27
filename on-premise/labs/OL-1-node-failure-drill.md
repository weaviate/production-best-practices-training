# OL-1 — Node Failure & Recovery Drill (self-paced, ~45 min)

You will kill one node of your own 3-node cluster, watch exactly what breaks and what does not,
and bring it back. The point is not the outage — it is the **evidence**: what replication factor
buys you, what each consistency level trades away, and what "the node is back" actually looks
like versus "the data has converged." No instructor injects the fault: you do, on the compose
stack in `labs/platform/`, where the blast radius is one laptop. The same rule applies as
everywhere in this module: **verify on your version** — exact status strings and timings below
were observed on the pinned stack (Weaviate 1.39.x) and may differ on yours.

Scenario: Acme runs a 3-node self-hosted cluster, RF=3 on the seeded collection. At 03:00 the VM
under one node reboots. You are on call. Today you rehearse it at a civilized hour.

## Purpose & objectives

After this lab you can:

1. Read `/v1/nodes?output=verbose` on a healthy and a degraded cluster and state, from evidence,
   which node is down and what that means for shards.
2. Predict — and then demonstrate with `python -m acme.chaos write-drill` — which of consistency
   levels ONE / QUORUM / ALL keep working with 1 of 3 nodes down, and why.
3. Distinguish "node restarted" from "async replication converged," and name the evidence that
   separates the two.
4. Say what, in production, would have paged you at each stage of this drill.

## Prerequisites & preflight

- The 3-node stack from `labs/platform/` is up and seeded: `make up`, then `make seed`.
- Harness commands run **from the repo's `labs/` directory** with `PYTHONPATH=src`.
- Grafana open in a browser at `http://localhost:3000` (the stack's dashboard).

Run the preflight (from `labs/platform/`):

```bash
make verify
curl -s "http://localhost:8080/v1/nodes?output=verbose" | jq '.nodes[] | {name, status}'
```

**Expected:** `make verify` reports **all 7 checks green**, and the nodes output lists **three**
nodes (weaviate-1/2/3), all with a healthy status (exact status strings vary by version — verify
on yours). If either disagrees, fix that first (`make reset`, then re-run `make verify`). Do not
start this lab on a cluster you cannot prove is healthy — you will not be able to tell your
fault from a pre-existing one.

## Timebox (~45 min)

| Minute | Checkpoint |
|---|---|
| 10 | Preflight green; healthy `/v1/nodes?output=verbose` baseline saved; predictions written down |
| 20 | Node killed; degraded evidence captured; `write-drill` run and outcomes explained vs. predictions |
| 35 | Node restored; async replication convergence observed (ALL succeeds again) |
| 40 | `make verify` green; final drill shows ONE/QUORUM/ALL all succeeding |
| 45 | Post-drill write-up done |

If you blow a checkpoint by more than ~5 minutes, skip ahead rather than perfecting the current
step — the write-drill (task 4) and the convergence watch (task 6) are the parts that must not
be cut.

## Tasks

1. **Capture the healthy baseline.** Save it — you will diff against it later:

   ```bash
   curl -s "http://localhost:8080/v1/nodes?output=verbose" | jq . > /tmp/ol1-nodes-healthy.json
   jq '.nodes[] | {name, status}' /tmp/ol1-nodes-healthy.json
   ```

   Skim the verbose output: note shard information per node and that all three nodes are
   healthy. In Grafana, find the panels showing per-node health/activity and note their resting
   shape.

2. **Predict before you touch anything.** Write down (really — the course rule is evidence
   before conclusions, and a prediction made *after* seeing the result is not a prediction):

   - With 1 of 3 nodes down and RF=3, which write consistency levels succeed: ONE? QUORUM? ALL?
   - Will ordinary queries at the default consistency keep working?
   - What will `/v1/nodes` show for the dead node?

3. **Kill one node.** From `labs/platform/`:

   ```bash
   make lab3-kill
   ```

   (If your checkout lacks that target, the equivalent is `docker compose stop weaviate-1` from
   the same directory — check the Makefile to see which node the helper stops.) Note the
   wall-clock time.

4. **Observe the degraded cluster — three lenses.** Give it ~30 seconds, then:

   ```bash
   curl -s "http://localhost:8080/v1/nodes?output=verbose" | jq '.nodes[] | {name, status}'
   ```

   - **API:** the stopped node shows as unhealthy/unavailable or drops from the list
     (representation varies by version and timing — verify on yours). Diff against your saved
     baseline.
   - **Grafana:** watch the dashboard react — which panels notice, and how quickly? In
     production this lag is your alerting grace period.
   - **Query behavior:** run a query against `http://localhost:8080` (any port whose node is
     still up). It should still succeed. Write down *why*.

   Now run the write drill (from the `labs/` directory):

   ```bash
   PYTHONPATH=src python -m acme.chaos write-drill
   ```

   The drill attempts writes at consistency ONE, QUORUM, and ALL and reports each outcome.
   **Expected with 1 of 3 down and RF=3:** ONE succeeds, QUORUM succeeds (2 of 3 replicas can
   acknowledge), **ALL fails** (it demands the replica on the dead node). Compare against your
   task-2 predictions and explain any miss. This is the lab's core lesson: a client that
   hard-codes ALL experiences an outage right now, even though the cluster is healthy-degraded.
   RF=3 bought you the ONE and QUORUM rows; the consistency level is what *spends* that
   redundancy — or refuses to.

5. **Restore the node.** From `labs/platform/`:

   ```bash
   make lab3-verify
   ```

   This restarts the stopped node and re-checks the cluster (equivalent by hand:
   `docker compose start weaviate-1`, then re-check `/v1/nodes`). Note the wall-clock time.

6. **Watch async replication converge.** The node reporting healthy is not the finish line:
   replicas that missed writes during the outage catch up **asynchronously**. Re-run the write
   drill every minute or so:

   ```bash
   PYTHONPATH=src python -m acme.chaos write-drill
   ```

   **Expected:** ALL flips back to succeeding once the returned node has caught up — on this
   small dataset typically within a couple of minutes (an estimate; verify on your run). The
   moment ALL succeeds again is your *evidence* of convergence; the gap between task 5's
   timestamp and that moment is what convergence cost today. Record both.

7. **Post-drill write-up.** Answer in writing, a few sentences each:

   - **What would have paged you in production**, and when? (Node-down alert at task 3? Only the
     failed-ALL writes at task 4? Nothing until a user complained?) If the honest answer is
     "nothing," that is the finding.
   - **Your node-down runbook**, first draft: the first three commands you run, the decision
     point (1-of-3 down vs. 2-of-3 down — see Playbook B for why those are different incidents),
     and what evidence lets you declare recovery *complete* rather than merely started.

## Verify your work

```bash
cd labs/platform && make verify
curl -s "http://localhost:8080/v1/nodes?output=verbose" | jq '.nodes[] | {name, status}'
```

**Expected:** all 7 verify checks green; three healthy nodes; and your final `write-drill` shows
ONE, QUORUM, and ALL all succeeding. If ALL still fails after several minutes, do not assume
"just slow" — check the restarted node's logs (`docker compose logs weaviate-1` from
`labs/platform/`) before moving on.

## Reset & cleanup

If verify is green there is nothing to undo — the node rejoined with its data volume intact, so
this is the cluster you started with. If anything is wedged: `make reset` from `labs/platform/`
re-baselines the stack. Delete `/tmp/ol1-nodes-healthy.json` if you care. Keep your write-up.

Safety boundary: this drill is for the `labs/platform/` compose stack on your own machine only —
never against a shared or production cluster without an agreed game day. Stop exactly **one**
node (two of three loses RAFT quorum — a different and worse incident, discussed in Playbook B,
not rehearsed here), and never delete containers or volumes: the recovery lesson depends on the
node rejoining with its data intact.

## If you're stuck

1. **`write-drill` errors on all levels, even ONE.** You are probably pointing at the dead
   node's port, or the stack was not healthy at preflight. Confirm which node `make lab3-kill`
   stopped (`docker compose ps` from `labs/platform/`) and that ports 8080–8082 map to
   weaviate-1/2/3; the harness must reach a *surviving* node.
2. **ALL never recovers in task 6.** Check the restarted node actually came back:
   `docker compose ps` should show it up, and `/v1/nodes?output=verbose` should list three
   healthy nodes again. If the container is up but the node stays unhealthy, read its logs — a
   node that crash-loops on start is a different problem than slow convergence.
3. **Everything is wedged and you can't tell what state you're in.** Stop debugging the drill:
   `make reset` from `labs/platform/`, wait for `make verify` to go green, and restart the lab
   from task 1. A clean known-good baseline beats twenty minutes of archaeology — that is also
   the production lesson.
