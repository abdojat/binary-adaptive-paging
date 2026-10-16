# BAP v8.4A — Preliminary Novelty and Claims Audit

**Date:** 2026-10-16  
**Repository evidence freeze:** `abdojat/binary-adaptive-paging`, `main` at commit `d8caeb6a94a90374f4357a72ff3edf48cdebd7ff`.  
**Status:** Evidence-grounded *preliminary prior-art triage*, **not** an exhaustive/systematic literature review, a peer-review verdict, or a new experiment. Prior-art characterization below is based on the authoritative abstracts and project documentation identified in the references; not every full article was audited page by page.

## Executive verdict

**Current claim of a new, broadly superior binary-paging translation mechanism: NO-GO.** Existing work already studies range-based translation, coalescing, arbitrary-length segments, and range indexing. The project's own v8.1 and v8.3B-2 controls do not show general superiority over a simpler fixed arithmetic grid. The bounded refinement theorem is mathematically valid *within its defined software metadata model* but is a simple consequence of the partition rule; its value as a publishable contribution remains unproven.

**Conditional alternative:** a characterization / controlled-negative-results article might be viable **only** if a fuller novelty review establishes a real missing question in the literature, the comparisons are strengthened to a defensible publication standard, and all claims are strictly scoped. No journal acceptance or quartile is guaranteed.

## 1. Strongest presently defensible formal fact

Let `K=2^k` be the maximum parent length in base pages, and `S=qK+r`, `0 <= r < K`.

- Fixed arithmetic grid: `q` whole `K`-page parents and one arbitrary-length remainder parent if `r>0`, giving `P_fixed=q+1[r>0]`.
- This capped BAP construction: `q` whole `K`-page parents followed by the descending-bit decomposition of `r`, giving `P_BAP=q+popcount(r)`.
- Therefore `P_BAP-P_fixed=popcount(r)-1[r>0] >= 0`, with equality if the remainder has at most one set bit.
- Every fixed-parent boundary is also a BAP-parent boundary. Thus the BAP partition *refines* this fixed partition.
- When records are maximal permission-uniform, physically consecutive runs **restricted to each parent**, splitting a fixed parent cannot reduce the number of records; BAP's record count is no lower. With the *same* 24-byte record and 8-byte parent-entry accounting, BAP metadata bytes are no lower in this model.

**Scope warning:** the fixed grid here permits an arbitrary-sized final software parent. This is NOT an x86 page-size-legal hardware leaf representation; it says nothing general about page-table entries, page-walk time, TLB reach, allocator bytes, or update cost.

## 2. Prior-art overlap and genuinely missing comparisons

| Work | What the authoritative source establishes | Relationship to BAP | Novelty risk |
|---|---|---|---|
| **Direct Segments**, Basu et al., ISCA 2013 | Contiguous virtual-to-physical translation through base/limit/offset hardware alongside ordinary paging | Direct region-to-physical mapping is not a BAP invention; BAP does **not** reproduce their measured hardware path | High for claims about direct/range translation |
| **CoLT**, Pham et al., MICRO 2012 | Coalesced TLB entries exploit intermediate physical contiguity | Software chunk counts alone cannot establish TLB-reach gains | High for TLB claims |
| **RMM**, Karakostas et al., ISCA 2015 | Ranges of contiguous virtual and physical pages; software range table and proposed hardware range TLB | Arbitrary-range translation is an essential baseline. Fixed-length power-of-two chunks can add representation overhead | High for range-based novelty |
| **Maple Tree**, Linux documentation | Cache-aware B-tree for nonoverlapping ranges with range-update APIs, used for Linux VMAs | Dynamic range management and splitting/updates already have mature implementations. `std::map` is *not* identical to Maple Tree | High for generic dynamic-update novelty |
| **Page Overlays**, Seshadri et al., ISCA 2015 | Overlay of cache-line subsets over a physical page for fine-grained memory operations | Distinct from the project's sparse **mapping-metadata** exception overlay; name resemblance is not equivalence, nor evidence our overlay is new | Moderate; distinguish levels carefully |
| **FlexPointer**, Chen et al., ACM TACO 2023 | Tagged pointers/range IDs address indexing of variable-bound ranges in a range TLB | Overlaps the **problem formulation** of rapid range selection, though its mechanism differs substantially from XOR/MSB relative parent selection | **High-priority full-text audit** |
| **Dyadic decomposition**, standard mathematical technique | Intervals can be broken into power-of-two dyadic pieces in many settings | Descending-bit decomposition by itself cannot responsibly be claimed as new. Alignment/relative-origin choices in BAP differ from some canonical dyadic interval settings | High for decomposition-as-invention claims |

### Verified references

1. Basu et al., *Efficient Virtual Memory for Big Memory Servers*, ISCA 2013, DOI: https://doi.org/10.1145/2485922.2485943 ; university author copy: https://research.cs.wisc.edu/multifacet/papers/isca13_direct_segment.pdf
2. Pham et al., *CoLT: Coalesced Large-Reach TLBs*, MICRO 2012, DOI: https://doi.org/10.1109/MICRO.2012.32 ; institutional abstract: https://www.researchwithrutgers.org/en/publications/colt-coalesced-large-reach-tlbs/
3. Karakostas et al., *Redundant Memory Mappings for Fast Access to Large Memories*, ISCA 2015, https://www.microsoft.com/en-us/research/publication/redundant-memory-mappings-for-fast-access-to-large-memories/
4. Linux, *Maple Tree*, https://www.kernel.org/doc/html/latest/core-api/maple_tree.html
5. Seshadri et al., *Page Overlays*, ISCA 2015, https://www.microsoft.com/en-us/research/publication/page-overlays-an-enhanced-virtual-memory-framework-to-enable-fine-grained-memory-management/
6. Chen et al., *FlexPointer: Fast Address Translation Based on Range TLB and Tagged Pointers*, ACM TACO 2023, DOI https://doi.org/10.1145/3579854 ; university abstract https://ir.pku.edu.cn/handle/20.500.11897/678249
7. Mathematical background, *Dyadic decomposition*, https://www.tricki.org/article/Dyadic_decomposition

## 3. Claims-to-evidence ledger

| Candidate manuscript claim | Current evidence | Decision |
|---|---|---|
| XOR/MSB maps relative offsets to the prescribed BAP parent | Algorithms and correctness checks v6/v8.1 | **KEEP**, as construction-specific property |
| BAP parents refine the fixed arbitrary-tail grid; cannot use fewer software run records under stated rules | Formal v8.2 model, audit code, independent math | **KEEP**, with assumptions and equality case; originality unsettled |
| BAP reduces metadata more than fair fixed-grid baseline | v8.2 contradicts, under measured structural model | **REJECT** |
| BAP's parent selection is faster than binary parent search | v8.1 confirms but fixed grid shows same selector advantage | **KEEP WITH CONTROLS**, not BAP novelty |
| BAP is faster than fixed arithmetic lookup on average | v8.1 does not establish it | **REJECT** |
| BAP improves x86 TLB reach/OS paging | No hardware translation or TLB experiment | **REJECT** |
| BAP's dynamic overlay has a special update advantage | v8.3B-2: no prespecified setting meets the two-baseline timing criteria; allocation bytes absent | **REJECT CURRENT SPEEDUP CLAIM** |
| All six dynamic software representations agree on tested translation semantics | v8.3A/B-0 and C++ pilot oracle with stated exclusions | **KEEP, LIMITED TO TESTED TRACES** |
| A negative/comparative paper is definitely novel or journal-ready | Not established by preliminary literature review or short single-host experiments | **NOT YET SUPPORTED** |

## 4. Practical next decision

1. **Do not** edit/rewrite the main v8.2 Word/PDF into a speedup paper; preserve raw CSVs and code.
2. **Read the complete FlexPointer and RMM papers** (not just their abstracts), and their citing works, emphasizing *range indexing*, *alignment*, *metadata storage*, and *update semantics*. Check whether BAP's remaining proposed questions are already answered.
3. Obtain independent technical review of the elementary refinement/record theorem and its assumptions; verify how the result relates to established dyadic decomposition/buddy allocation and variable-length range indexing.
4. **Author one defensible novelty statement** that describes an actual *new finding* beyond the theorem restatement and elementary benchmark controls. If no nontrivial gap emerges, choose a new algorithm/research question or archive BAP as a well-documented negative study rather than manufacturing journal claims.
5. Only if that review finds a credible publication gap, plan an improved *prospective* evaluation and a new draft. Fix the v3 unstable `hash(workload_name)` generation **for future versioned runs**, never silently rewrite historical data.

**Recommendation:** Current positioning should be 'exploratory comparative characterization' rather than 'novel OS paging acceleration'. Go/no-go for an actual journal submission is **DEFER / NOT READY**, not a proof of impossibility.
