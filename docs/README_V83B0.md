# BAP v8.3B-0 — Incremental Dynamic-Mapping Correctness Gate

**Status:** passing software prototype. This is **not** v8.3B's native timing benchmark and does not prove any improvement over standard memory mapping techniques.

## Why this stage exists

The uploaded v8.3A prototype successfully verified six translation representations, but its update routine validates by materializing the entire region state; eager methods also reconstruct complete metadata. Benchmarking that prototype would primarily benchmark those avoidable actions. v8.3B-0 introduces a local-update algorithm to establish correctness before hardware-level/native-cost comparisons.

## Six implementations

- BAP eager and BAP + exception overlay
- Fixed-grid eager and fixed-grid + exception overlay
- Generic coalesced ranges eager and generic ranges + exception overlay

**Same update semantics and trace** for all six implementations: mapping previously unmapped pages, unmapping mapped pages, changing permissions while retaining PFNs, and one-page COW-like PFN replacement. No shared PFNs, true kernel COW, concurrent updates, real TLB, or OS page-table walker.

**New incremental algorithm:** per-update bounds and alias checks inspect only the affected pages and a per-model PFN-owner index. Eager models patch only intersecting parent record lists. Overlay models only change exceptions and, once a common threshold is reached, merge them into affected parent records; untouched parent metadata is not reconstructed. Each model maintains independent metadata and PFN-owner state. No oracle state is used for its updates.

**Important fairness qualification:** the generic-range implementation uses a Python sorted record list with a whole-range parent. Updating this list is not equivalent to a balanced interval tree and is **not** a realistic optimized dynamic-range performance comparator. The counters `parent_record_scans` etc. are internal diagnostics and must not be described as CPU work, asymptotic optimality, or update latency. Overlay compaction patches exceptions individually rather than batching; this too needs optimization before timing.

## Run from your repository root (Ubuntu/WSL)

Unzip the kit alongside existing `dynamic_correctness_v83a.py`, then run:

```bash
bash run_v83b0.sh
```

The kit's driver creates:

- `results_v83b0/incremental_semantics_v83b0.csv` — 96 scenarios x 6 models = **576 rows**.
- `results_v83b0/large_region_v83b0.csv` — one 10,000-page spot-check x 6 models.

It also compares all 576 scenario/model results with the already committed `results_v83a/dynamic_correctness_v83a.csv` and checks matching end-state SHA256, final base-record count, final overlay exceptions, number of compactions, and zero mismatches. **The matching output is an implementation-consistency check, not independent experimental proof of performance.**

Expected final messages:

```text
PASS: local patch split/merge, overlay exception writes, compaction, PFN index and rejection atomicity
PASS: 96 incremental scenarios; 576 model rows; zero differential semantic mismatches
PASS: 1 incremental scenarios; 6 model rows; zero differential semantic mismatches
CSV CHECK PASS results_v83b0/incremental_semantics_v83b0.csv 576
CSV CHECK PASS results_v83b0/large_region_v83b0.csv 6
PASS: 576 identical scenario/model states; hashes, record counts, exceptions, compactions, mismatches match v8.3A
```

Use Python 3.10+. Only the standard library is needed. All seeds and traces are deterministic. The original `dynamic_correctness_v83a.py` and its committed CSV are dependencies, not replaced or modified.

## Interpretation

G0 (semantics) holds for **the tested abstract states**, including atomic rejection, permissions, byte-address translation, and no physical frame aliases; there is no real OS integration. G1/G2/G3 of the design gate (performance/attribution/practicality/reproducibility) **remain untested**.

The correct next engineering experiment **after** this gate is a native C++ dynamic-update benchmark that isolates genuine incremental update latency, lookup latency and peak metadata allocation, with a balanced dynamic interval-tree baseline plus identical overlays. All methods must use exactly the same operation logs, no oracle checks in the timed loops, and separate verification after updates. A potential update-time advantage must be compared with both fixed-grid+overlay and generic-range+overlay, including compaction and validation costs, before making any BAP-specific claim.

## Files to commit

- `dynamic_incremental_v83b0.py`
- `verify_v83b0_against_v83a.py`
- `run_v83b0.sh`
- `results_v83b0/` with the two CSVs
- this document at `docs/README_V83B0.md`

Keep main Word/PDF report frozen at v8.2; v8.3B-0 is a supplementary correctness artifact.
