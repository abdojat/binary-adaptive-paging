# BAP — End-of-phase Research Status (v0–v8.4A)

**Evidence freeze:** 2026-10-16, `abdojat/binary-adaptive-paging` main `a56b7205f444922528f2e624cf0aa8f9977c3fcc`. This is a research synopsis, not a journal acceptance claim.

## Verifiable findings

- **Logical translation:** region-relative XOR/MSB parent indexing identifies the intended capped power-of-two parent. Page-to-PFN and permission semantics were tested in software, not in an x86 page walker.
- **Formal representation:** for `S=qK+r`, `0<=r<K`, capped BAP has `q+popcount(r)` parents while a flexible-tail fixed software grid has `q+1[r>0]`. BAP refines the fixed-grid partition and cannot reduce parent-limited maximal contiguous, permission-constant record counts under the shared representation model. This theorem is not a statement about TLBs or native hardware legality.
- **Native lookup:** v8.1's four-way partition/selector ablation does not establish general BAP superiority over fixed arithmetic parent indexing. Some individual workload results favor BAP, but strong controls often do not.
- **Dynamic correctness:** v8.3A and v8.3B-0 archive 576 six-model comparison rows each; both report zero semantic mismatches and match on final state, record counts, overlays and compactions.
- **Dynamic native pilot:** v8.3B-1 archives 10 independent process runs x 288 rows = 2,880 user-space measurements. BAP+overlay has lower mean update latency than fixed+overlay in 7/16 settings and than ranges+overlay in 11/16; in zero settings does the exploratory positive update-time interval survive both alternatives, and zero satisfy the prespecified 10% update improvement and 5% lookup-regression constraints against both. Peak allocator memory bytes and cross-hardware replication are missing.
- **Prior art:** Direct Segments, RMM, CoLT, FlexPointer, the Linux Maple Tree, Page Overlays (distinct mechanism), and standard dyadic decomposition constrain broad novelty claims. The preliminary review does not itself prove novelty or publication readiness.

## Final scientific position

The dataset supports a **bounded comparative characterization and negative/heterogeneous software results**. It does **not** currently justify claims of an original general paging accelerator, improved TLB reach, superior OS throughput or robust BAP-specific dynamic speedup. G0 passed on tested traces; G1 not demonstrated, full G2 unassessable for allocation and failed for the tested latency component, G3 untested across independent hosts.

## Safe next actions using existing work

1. Freeze raw result bytes, create an experiment index and smoke tests, consolidate root README, remove tracked compiled binaries without changing Git history, fix links/paths, and document the historical v3 Python `hash(workload_name)` seed risk without overwriting results.
2. Have an independent reviewer audit the proof, reference contracts and equality cases; reconcile stale manuscript claims; turn results into a transparent comparative research report.
3. Only after a concrete gap is identified, extend the **existing** C++ benchmark with allocator high-water measurement, counterbalanced method order, longer traces / one larger region, and a second host. A pilot rerun should not be used to cherry-pick positive effects.

See `BAP_Complete_Final_Technical_Report_v0_to_v8_4A.docx` for the full integrated report and `CODEX_REPOSITORY_CLEANUP_PROMPT.md` for a safe execution brief. These are pre-cleanup snapshots; after file relocation, update only paths/provenance references unless new source evidence requires content changes.
