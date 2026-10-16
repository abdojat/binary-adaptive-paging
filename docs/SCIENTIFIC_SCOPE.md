# Scientific scope and documentation audit

This is a repository evidence audit, not a new literature review or a manuscript revision. Existing citations and novelty judgments are preserved; their external full texts were not re-audited during cleanup.

| Historical statement or potential ambiguity | Current reading / evidence |
|---|---|
| v0–v4 `estimated_tlb_reach_pages`, reduction figures | Modeled logical mappings only. No TLB experiment. Alignment, contiguity and permissions limit hardware interpretations. |
| “Fixed” across versions | Early fixed base-page mapping differs from the arbitrary-tail fixed software grid in v8.1/v8.2. Do not equate those baselines or extrapolate early percentage reductions. |
| v5 legal/eligible chunks | Virtual alignment/page-profile audit; physical contiguity and actual hardware performance are not checked here. |
| v7/v8 metadata bytes | Explicit representation accounting, not measured peak allocation or resident memory. |
| v8 indexed ranges vs v8.1 Fixed Grid | Baseline implementation changes; v8.1 isolates parent selector and partition effects. Arithmetic selection helps both families and is not itself BAP superiority. |
| v8.2 “formal” result | Explicit refinement/record-count theorem with executable finite audit, not machine-checked proof in a proof assistant. No universal latency theorem. |
| v8.3 protocol says “proposed,” “NOW,” and “next” | Frozen protocol predates completed A/B-0/B-1/B-2 artifacts. Its larger proposed matrix is not the smaller pilot's executed matrix. |
| v8.3A/B-0 counts and correctness | G0 evidence for checked abstract traces. Eager snapshot rebuilding and Python lists are not native performance evidence. |
| v8.3B-1 says do not declare G1/G2 yet | Later B-2 locks a negative speedup decision; full G2 cannot be assessed without allocation bytes, G3 lacks hardware/compiler diversity. |
| Handoff files ask to copy/upload/commit/push | Completed historical instructions; current navigation is docs/README.md. No automatic publication is required. |
| v8.4/v8.4A novelty triage | Prospective characterization and preliminary prior-art assessment. Does not establish novelty or journal readiness. |
| Main manuscript physical prerequisites “remain open” in the logical-algorithm discussion | Later v6 sections explicitly model physical backing/permissions. Read this as unresolved native hardware realization, not absence of the v6 software model; author clarification would improve consistency. |
| Main manuscript pilot-host versus local-host descriptions | Earlier v8 pilot describes Xeon/KVM/GCC 14.2; later local archives report i5/WSL/GCC 13.3. Preserve dataset identities instead of attributing all files to one machine. |

The v8.3B-2 negative finding remains: neither a BAP-specific dynamic improvement against both fair overlay baselines nor practical joint latency thresholds is established. Generic overlay gains must not be attributed solely to BAP. Software `std::map` results do not represent Maple Tree, a hardware range TLB, or kernel page-table walkers. No measured peak dynamic memory, concurrency, physical aliases, shootdowns or full copy-on-write lifecycle is supplied.

The Word/PDF manuscripts remain frozen, as requested. Later caveats are exposed here rather than silently rewriting their scientific claims. An author-led manuscript consistency review and independent full-text novelty review remain necessary before submission. Absence of a license and incomplete original environment provenance are artifact-release concerns.
