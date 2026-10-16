# BAP v8.4 — Manuscript Reframing and Novelty Audit

**Status:** Prospective writing/research plan. **Not** a new experimental result, publication acceptance claim, or completed systematic literature review.
**Evidence freeze:** GitHub `abdojat/binary-adaptive-paging`, main at commit `f9019d0e426ef8029902f6029393a64ef64be83a` (2026-10-16). Preserve prior files and CSVs unchanged.

## Decision inherited from v8.3B-2

- v8.2 establishes, under its **software metadata assumptions**, that capped BAP (power-of-two decomposition with cap `K`) refines the fixed grid of `K` pages whose final bucket can be of arbitrary positive length.
- With `S=qK+r`, `0<=r<K`, `M_BAP=q+popcount(r)` and `M_fixed=q+1[r>0]`; thus `M_BAP>=M_fixed`. For maximal PFN-linear, permission-uniform runs **within parents**, the BAP record count and corresponding fixed-width metadata accounting are no lower than fixed-grid's. This is **not** a universal hardware, TLB, update-cost, or arbitrary data-structure theorem.
- v8.1: arithmetic parent choice is faster than binary parent search in both BAP and fixed grids in the tested software lookup cases; BAP-specific superiority was not established.
- v8.3A and v8.3B-0: six-model dynamic translation and incremental-model consistency passed for tested traces (576 matched scenario/model states).
- v8.3B-1: 10 independent benchmark process runs x 288 rows/run. Short single-host C++ pilot with six models; no measured peak dynamic allocation bytes; no kernel/TLB measurements.
- v8.3B-2: for BAP+overlay versus fixed+overlay, lower update mean in **7/16** settings and positive exploratory paired lower CI in **0/16**. Against range+overlay, **11/16** and **3/16**, respectively. No setting has positive exploratory update CI against **both** baselines; no setting satisfies the 10% update / 5% lookup *latency-only* threshold against both. G1/G2/G3 remain unestablished as defined in the protocol.

## Proposed scientific question (reframed)

**Under what explicit representational, alignment, and workload assumptions does binary-decomposed region metadata offer useful trade-offs, and which apparent gains disappear when compared with fixed arithmetic grids and dynamic range baselines?**

This is a *characterization/comparative study*, not an optimization or hardware performance paper. The main value proposition would be **clear bounds + controlled ablations + reproducible counterexamples to overbroad claims**. This is only potentially publishable if related work demonstrates an unsolved evaluation/understanding gap and the breadth/quality of evidence is sufficient.

## Candidate title

**Binary-Decomposed Region Metadata for Address Translation: Formal Bounds, Feasibility Limits, and Controlled Software Comparisons**

## Research questions

- **RQ1 — Structural:** Precisely which partition rules and metadata accounting assumptions imply BAP is a refinement of a fixed grid? Where does this cease to apply?
- **RQ2 — Feasibility:** Which proposed logical chunks are native x86 leaves, and what alignment/physical-contiguity/permissions limits matter? Separate software runs from hugepage claims.
- **RQ3 — Software lookup:** How much of a timing contrast is attributable to parent selection versus partition shape? Report all patterns, non-winning cases, workload sensitivity, and the v8-v8.1 baseline change.
- **RQ4 — Dynamic updates:** With identical overlays and balanced ordered-map implementations, how well does each scheme update and search? Explain why the pilot cannot establish a BAP-specific win and why G2 memory / G3 portability remain unmeasured.

## Provisional contributions — word carefully

1. A mathematically explicit characterization **of this capped BAP construction** relative to a fixed-grid baseline, under stated model assumptions.
2. A transparent evaluation pathway separating (i) logical chunks, (ii) native mapping feasibility, (iii) translation correctness, (iv) structural metadata, (v) software lookup ablations, and (vi) dynamic software updates.
3. An archived empirical comparison exposing benchmark-baseline dependence, workload heterogeneity, and unproven dynamic superiority.

**Do not claim:** general TLB reach improvement; OS integration; hardware x86 translation speedup; metadata savings against an arbitrary-length fixed-grid tail; guaranteed speedup; novel sparse overlays merely by name or concept; publication readiness.

## Prospective manuscript structure

1. **Introduction and motivation:** common implicit assumptions and why controlled alternatives matter; avoid asserting practical speedups.
2. **Background and related work:** segmentation/direct segments, range translations (RMM), TLB coalescing (CoLT), Linux VMA range indexes (Maple Tree), fine-grained Page Overlays. Keep software metadata distinct from hardware translation.
3. **Scope and formal model:** base-page virtual addresses, cap K, partition shapes, physical run records, permissions, allowed fixed-tail flexibility, byte-level correctness; spell out exclusions.
4. **Structural theorems and proof:** size formulas, refinement, record-count and byte-accounting bounds, equality cases, counterexamples or boundary cases.
5. **Evaluation methodology and threats:** exact workload generation, seeds, source commit, baseline implementations, compiler/CPU, randomization/order, per-process replication, exploratory intervals, single-machine limits.
6. **Results:** native-feasibility audit (v5), translation (v6), metadata (v7 and v8.2), lookup ablation (v8-v8.1), dynamic updates (v8.3A–v8.3B-2); negative evidence equally prominent.
7. **Discussion:** when XOR/MSB might still be meaningful, what the model cannot show, and honest implications for system design.
8. **Conclusion:** bounded factual findings and open questions, not an unproven optimization claim.

## Evidence ledger and audit tasks

| Claim/section | Primary repository evidence | Missing work before manuscript submission |
|---|---|---|
| Mathematical partition/refinement under model assumptions | `formal_audit_v82.py`; `results_v82/formal_checks_v82.csv` | Independent human proof audit; articulate all quantifiers and assumptions |
| Native x86 mapping limits | `feasibility_v5.py`; `results_v5/` | Verify exact hardware page profiles against architecture sources; avoid equating software chunks with TLB entries |
| Translation semantics | `translation_v6.py`; `results_v6/` | Ensure chosen semantics align across versions; highlight exclusions |
| Structural metadata | `metadata_lookup_v7.py`; `results_v7/`; v8.2 | Audit accounting assumptions and memory allocator overhead |
| Lookup baseline sensitivity | `lookup_benchmark_v8.cpp`, `lookup_ablation_v81.cpp`, `results_v8/`, `results_v81/` | Reconcile implementations and fixed-bucket run splitting; add interpretation, not cherry-picked numbers |
| Dynamic pilot negative result | `dynamic_benchmark_v83b1.cpp`, `results_v83b1/`, `evaluate_v83b1_gate.py` | Method-order counterbalancing, real allocation bytes, hardware diversity only if a prospective claim demands them |
| Reproducibility | existing run scripts, CSVs and `environment.txt` | Make root README; fix v3 `hash(workload_name)` instability for **future** runs without silently overwriting historical data |

## Prior-work novelty triage (not an exhaustive review)

| Work | Already covers | Implication for BAP | Primary reference |
|---|---|---|---|
| Direct Segments (Basu et al., ISCA 2013) | Direct VA-to-PA translation for a contiguous memory segment with hardware support | Binary chunks are not automatically novel as a way to represent contiguous memory | https://www.csa.iisc.ac.in/~arkapravab/papers/isca13_direct_segment.pdf |
| RMM (Karakostas et al., ISCA 2015) | Arbitrary-length virtually/physically contiguous ranges, range translation framework | A generic range baseline and hardware-feasibility distinction are essential | https://www.microsoft.com/en-us/research/publication/redundant-memory-mappings-for-fast-access-to-large-memories/ |
| CoLT (Pham et al., MICRO 2012) | Coalescing contiguous TLB translations | Do not infer improved TLB reach from software partition count | https://doi.org/10.1109/MICRO.2012.32 |
| Linux Maple Tree | Ordered management and updates of non-overlapping ranges, used for VMAs | A Python list or bare sorted vector is an inadequate high-performance dynamic baseline; `std::map` is fairer but not the same implementation | https://www.kernel.org/doc/html/latest/core-api/maple_tree.html |
| Page Overlays (Seshadri et al., ISCA 2015) | Fine-grained cache-line overlays over a conventional physical page | Different abstraction from this project's sparse *mapping-metadata exception dictionary*; compare mechanisms carefully, and **do not claim overlay concept novelty** | https://www.microsoft.com/en-us/research/publication/page-overlays-an-enhanced-virtual-memory-framework-to-enable-fine-grained-memory-management/ |

## Manuscript go/no-go before drafting a full journal article

- [ ] Independently check all theorem assumptions, equality cases, and relation to established results.
- [ ] Audit at least these five cornerstone works in full text; expand with forward/backward citation search and recent successors.
- [ ] Decide whether the *comparison/characterization* itself has genuine incremental scholarly value beyond existing surveys and conventional benchmarking.
- [ ] Prepare a 1-page **novelty statement** and a 1-page **claims-to-evidence table** for critical review.
- [ ] Recheck the v3 PRNG issue and manuscript text consistency. Treat raw data as immutable; if changed, version results and explain changes.
- [ ] Only then draft a manuscript revision with actual, supported results. If novelty gap is not credible, record the negative result and pivot rather than promising publication.

**Next action in the repository:** commit this document as `docs/v8_4_manuscript_reframing.md`; no new benchmark or rewrite of `Binary Adaptive Paging.docx` / PDF yet.
