# BAP v8.3 — Dynamic Mapping Design & Falsification Gate

**Status:** Proposed protocol only; not a completed experiment or proven optimization.  
**Date:** 2026-10-16  
**Scope:** Software translation metadata, not kernel paging, TLB miss rates, or hardware latency.

## Decision inherited from v8.2

In the evaluated model, capped BAP partitions are refinements of a fixed grid of `K` pages with an arbitrary-length final bucket. If each parent stores maximal physically contiguous, permission-uniform run records, then BAP's parent and record counts cannot be lower than this fixed grid's counts. v8.1 found no general software-lookup win over arithmetic fixed-grid indexing. We cannot claim a generic speed, metadata, or TLB advantage.

## Research question and falsifiable hypothesis

Can a **BAP-specific** indexing/update mechanism reduce incremental `map`, `unmap`, `protect`, and one-page COW-like remap costs **after** equally optimized fixed-grid and dynamic-range comparators are given the same indexing, lazy overlay, and compaction strategy?

- **H0:** No incremental update/lookup advantage remains with equal semantics and comparable optimizations.
- **H1 (unproven):** A precisely specified BAP-specific choice delivers lower incremental update latency in a prespecified localized-update workload **without** unacceptable lookup or memory overhead.

## Candidate to screen: immutable snapshot + sparse exception overlay

1. Base snapshot records define the initial page-to-physical-frame map and permissions.
2. Update operations write sparse exceptions (present/absent, PFN, permissions), rather than eagerly rebuild every affected large range.
3. Lookup first checks the overlay, then the base representation.
4. At a **fixed predeclared threshold**, compaction incorporates exceptions into a fresh base snapshot.
5. **The identical overlay and compaction policy is supplied to all baseline methods.** If overlaying itself produces the advantage, it is not a BAP-specific novelty.

This is a *candidate design*, not a new algorithm whose superiority has been established. The first gate may reject it.

## Required comparison models

| ID | Model | Essential control |
|---|---|---|
| A | Eager capped BAP | BAP parent partitions, per-parent run records |
| B | Eager fixed grid | Arithmetic `off // K`, final bucket may be shorter |
| C | Dynamic generic ranges | Maximal PFN-consecutive, permission-uniform mapped runs with ordered range index |
| D | BAP + sparse overlay | Same overlay and compaction as E and F |
| E | Fixed-grid + sparse overlay | Same overlay and compaction as D and F |
| F | Generic range + sparse overlay | Same overlay and compaction as D and E |

The generic-range index should be realistically updateable (e.g., balanced range tree). No naive global scan as the only comparator.

## State and operation semantics

Use a **flat per-base-page oracle** `vpn -> unmapped | (pfn, permissions)` as ground truth. Every implementation processes the **same deterministic update log and query sequence**.

- `map(start, length, physical_layout, permissions)`: fill unmapped pages only.
- `unmap(start, length)`: mark mapped pages unmapped; accesses afterward must fault.
- `protect(start, length, permissions)`: change r/w/x bits of existing mappings.
- `cow_remap(vpn, new_pfn, permissions)`: model a private one-page PFN change and optional permission change. This is **not** a modeled `fork()`, data copy, or reference count.
- `lookup(vpn, access)`: exact physical byte address, protection fault, or unmapped fault.

Exclude physical-frame aliases, shared mappings, real kernel faults, concurrency, and filesystem/device semantics from the first gate. Verify every address on small regions and boundary/random samples after *every* update on large ones. Document exclusions.

## Prespecified experimental matrix

- Regions: `1000`, `4096`, `10000` base pages; starts `0`, `1`, `7`; `K=512` initially.
- Layouts: contiguous; fragmented every 32 pages; mixed permissions; both combined.
- Update mixes: localized `protect` toggles; random single-page COW-like remaps; contiguous unmap/remap; clustered mixed events.
- Update density per epoch: `0.1%`, `1%`, `10%`; overlay compaction thresholds `1%`, `5%`, `10%`.
- Lookup patterns: uniform random, sequential, hot/cold, boundary stress.
- Deterministic numeric seeds; identical logs for each method. Report all outcomes rather than only positive workloads.

## Required outcome measures

- **Correctness:** exact byte translation and r/w/x/unmapped outcomes after each operation.
- **Update costs:** actual measured native update latency (ns/op), actual insert/erase/modify operations, bytes copied, and compaction count.
- **Lookup costs:** measured lookup ns/op and complete mixed lookup+update workload time.
- **Storage:** actual metadata bytes and peak live bytes in addition to abstract structural record counts.
- **Statistical controls:** independent process runs, paired workload traces, checksums, environment record, uncertainty and multiple-comparison caveats.

Metadata record-count deltas computed by rebuilding a canonical representation **are not measured incremental update cost**. Do not label them as such.

## Precommitted go/no-go gates

1. **G0 Correctness:** zero discrepancies against the flat oracle.
2. **G1 Attribution:** improvement against BOTH the fixed-grid+same-overlay and generic-range+same-overlay designs, on a workload declared in advance. Improvement against an eager/unindexed baseline only is **not** sufficient.
3. **G2 Practicality (proposed thresholds):** at least **10%** lower update latency, with no more than **5%** lookup latency regression and **10%** peak metadata increase, including compaction. These are *proposed design thresholds*, not observed findings or publication standards.
4. **G3 Reproducibility:** preserve sign and practically relevant magnitude across independent runs and hardware/compiler sensitivity checks.

If the candidate fails G1/G2, **stop** the BAP-specific dynamic speedup claim. Pivot to a fair comparative study with negative findings, or propose a *different* mechanism with an identifiable advantage before running more benchmarks.

## Immediate next action

**NOW:** Commit this protocol to the repository as `docs/v8_3_design_gate.md`. No new timing runs and no paper edits yet. The next engineering implementation, after the specification is fixed, is a differential-correctness model that exercises the five operations above with deterministic traces. A later, separate C++ implementation is required for **real** update and lookup cost measurements.

## Prior work and constraints

1. Linux Kernel Documentation, *Maple Tree*: https://www.kernel.org/doc/html/latest/core-api/maple_tree.html — nonoverlapping range index with update APIs.
2. Karakostas et al., *Redundant Memory Mappings for Fast Access to Large Memories*, ISCA 2015: https://www.microsoft.com/en-us/research/publication/redundant-memory-mappings-for-fast-access-to-large-memories/ — range translation with proposed hardware range TLB and software range tables.
3. Linux Kernel Documentation, *Transparent Hugepage Support*: https://www.kernel.org/doc/html/latest/admin-guide/mm/transhuge.html — large-page mapping split/demotion; not interchangeable with metadata-only updates.

**Research integrity note:** The cited prior work motivates baselines and limitations; it does not establish the proposed overlay as novel or effective.
