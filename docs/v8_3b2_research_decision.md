# v8.3B-2 — Dynamic Pilot Research Decision

**Evidence:** GitHub `results_v83b1/` generated from v8.3B-1, archived pilot; not kernel/TLB benchmarks.
**Audit:** 10 separately recorded runs; 288 scenario-model rows per run; 16 scenario groups; 192 contrasts.

## Result matrix (BAP + overlay)

| Metric | Faster than Fixed overlay | Faster than Ranges overlay | Positive exploratory 95% CI vs Fixed | Positive exploratory 95% CI vs Ranges |
|---|---:|---:|---:|---:|
| `update_ns_per_op` | 7/16 | 11/16 | 0/16 | 3/16 |
| `lookup_ns_per_query` | 2/16 | 12/16 | 0/16 | 4/16 |
| `mixed_ns_per_query` | 6/16 | 13/16 | 0/16 | 4/16 |

Settings with positive exploratory update CI against **both** overlays: **0/16**.
Settings meeting both predeclared update ≥10% and lookup slowdown ≤5% latency criteria: **0/16** (not a full G2 assessment).

## Decision

- **G0 correctness:** PASS for the tested software-mapping traces; all methods reported oracle verification and matching checksums. No actual OS paging guarantee.
- **G1 BAP-specific attribution:** **NOT DEMONSTRATED** by this pilot. No tested setting had a positive exploratory update-delta CI against both optimized overlay comparators.
- **G2 practicality:** **NOT DEMONSTRATED / PARTLY UNASSESSABLE.** Peak allocated bytes were not measured; no result can satisfy the full prescribed threshold assessment.
- **G3 reproducibility:** repeatable on one WSL/Intel host, but multi-machine/compiler sensitivity is **UNTESTED**.
- **Research go/no-go:** STOP the present BAP-specific dynamic-speedup claim. Preserve code/data as a negative/comparative result. Only resume optimization work after a new, clearly distinguishable BAP-specific mechanism and a new prospective hypothesis are defined.

## Scientific limits

- Per-process runs, not seeds/queries, are the statistical replication unit. Bootstrap CIs are exploratory and uncorrected for multiplicity; CI overlap/positivity is a conservative screening heuristic, not a formal adjusted hypothesis test.
- Only two sizes, two layouts, and short traces were tested; observed failure is not a mathematical proof that no workload can benefit.
- `std::map` is not a kernel Maple Tree. Allocator, cache, compiler and short-operation timing overhead can confound tiny differences.
- The benchmark fixes a method order for each seed across processes. Larger prospective studies should counterbalance method order and use longer measurement windows.
- Previous formal dominance (v8.2) concerns **structural metadata** under precise assumptions; it does not prove comparative update-latency dominance.

## Recommended next research action

Create a **comparative/negative-results manuscript plan** with a validated related-work novelty matrix, a precise statement of theoretical assumptions, and a transparent analysis of the v8.1/v8.3B-1 null results. Do not revise the current v8.2 paper into a speedup claim, perform hardware implementation, or spend on expensive repeated benchmarks at this stage.

## Reproduction

```bash
python3 evaluate_v83b1_gate.py --summary results_v83b1/paired_pilot_summary.csv --runs results_v83b1/repetitions/run_*.csv --out results_v83b1/decision_matrix_v83b2.csv --report docs/v8_3b2_research_decision.md
```
