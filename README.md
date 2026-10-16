# Binary Adaptive Paging research artifact

This repository records an exploratory operating-systems research study from v0 through v8.4A: binary decomposition of region mappings, alignment and physical-layout constraints, software translation metadata, lookup ablations, and dynamic-update correctness and timing. It contains Python models, C++20 microbenchmarks, archived CSVs and figures, and frozen Word/PDF manuscripts. It is not a kernel paging implementation.

**Current conclusion:** BAP-specific general speedup is not demonstrated. The v8.2 structural result favors a fair fixed-grid baseline under the stated metadata model; the v8.3B-2 decision is negative for the proposed dynamic speedup. v8.4/v8.4A are interpretation and preliminary novelty audits, not additional experiments or publication-readiness endorsements.

## Start here

- [Experiment index](EXPERIMENT_INDEX.md): sources, inputs, outputs and verification for every stage.
- [Reproducibility guide](docs/REPRODUCIBILITY.md): installation, safe commands, seed and environment limitations.
- [Documentation map and historical instructions](docs/README.md).
- [Scientific scope and documentation audit](docs/SCIENTIFIC_SCOPE.md).
- [Cleanup changelog](docs/CLEANUP_CHANGELOG.md) and [validation report](docs/VALIDATION_REPORT.md).
- [v8.3B-2 research decision](docs/v8_3b2_research_decision.md) and [v8.4A novelty audit](docs/v8_4a_novelty_audit.md).

## Research progression and supported claims

v0–v2 examine logical mapping counts, relative-origin XOR/MSB selection, alignment and capped versus unbounded chunks. Their “estimated TLB reach” is a simplified modeled quantity. v3 adds sparse/dense workloads and splitting; v4 sweeps chunk caps, density thresholds and seeds. v5 checks virtual page-size/alignment feasibility. v6 checks physical translation and permissions. v7 models metadata storage and comparison counts. v8 measures native software lookup; v8.1 adds controlled arithmetic-versus-binary parent-selection ablations. v8.2 audits structural dominance. v8.3A and v8.3B-0 check six dynamic models; v8.3B-1 measures a native pilot; v8.3B-2 evaluates its falsification gate. v8.4 and v8.4A document reframing and novelty concerns.

For cap `K=2^k` and size `S=qK+r`, `0 <= r < K`, capped BAP has `q+popcount(r)` parents. Fixed Grid with an arbitrary-length final software bucket has `q+1[r>0]`. BAP refines that fixed partition. If records are maximal PFN-consecutive, permission-uniform runs within each parent, BAP cannot have fewer records. With identical accounting (`32 + 24*records + 8*parents` bytes), its metadata is no smaller. This is a scoped software representation result, not a hardware or dynamic-latency theorem. The executable audit checks finite cases; it is not a proof-assistant development.

In the archived dynamic pilot (ten process runs), BAP+overlay has a lower update mean in 7/16 settings against Fixed Grid+overlay and 11/16 against Generic Range+overlay. Exploratory paired lower confidence bounds are positive in 0/16 and 3/16 respectively. No setting meets the two-baseline positive-CI criterion or the joint 10% update / 5% lookup latency-only threshold. Peak live allocation bytes and cross-host reproducibility remain unassessed. The original negative decision is preserved.

## Fair comparisons and limitations

Fixed Grid and Generic Range must receive the same translation semantics, traces, overlay policy and compaction rules as BAP. v8's indexed range baseline and v8.1's fixed arithmetic grid are different constructions; their measurements cannot be pooled as interchangeable baselines. v8.3B-0's Python sorted list is a correctness comparator, not an optimized dynamic range index. v8.3B-1 uses balanced `std::map` records for all three partition families, with eager and overlay variants; it does not implement Linux Maple Tree.

| Quantity | Meaning | Does not establish |
|---|---|---|
| Simulated mapping count | Logical chunks under each model's rules | Legal hardware leaves or TLB misses |
| Modeled metadata bytes | Explicit record/directory accounting | Allocator overhead or peak resident memory |
| Software lookup ns/query | Native user-space metadata lookup | Hardware page-walk latency |
| Dynamic update ns/op | Native pilot operations including compaction | Kernel update/shootdown or full COW cost |
| Hardware/TLB performance | Not measured | Any TLB or whole-system speedup |

Single-host short timings, uncorrected multiple comparisons, limited layouts and operation distributions restrict inference. Seeds within a process are not independent replications. No concurrency, real faults, shared-frame aliases, full fork/COW lifecycle or OS integration is established. Novelty remains unsettled.

## Install and validate

Use Linux or Ubuntu/WSL, Python 3.10+ (tested here with 3.12.3), Bash and a C++20 compiler (tested with GCC 13.3). Python v5 onward and the artifact validator use only the standard library. v1–v4 import Matplotlib even when plotting is disabled; its historical version was not recorded.

```bash
# Ubuntu/WSL; install missing prerequisites in your own environment
sudo apt-get install python3 python3-venv g++ bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt

# From the repository root; no archived outputs are overwritten
python scripts/validate_artifact.py --integrity-only
python scripts/validate_artifact.py
# Also execute ten independent processes for each native benchmark
python scripts/validate_artifact.py --native
```

The validator compiles into temporary storage, checks archived CSVs, replays deterministic correctness gates, reproduces comparative summaries from archived runs, and verifies SHA-256 preservation before and after. Fresh timing results are validation evidence only. Original `run_*.sh` entry points remain runnable but write into historical result paths: use them only in a disposable copy. See the guide for safe historical reruns.

## Repository layout

```text
README.md, EXPERIMENT_INDEX.md    current navigation and evidence map
*.py, *.cpp, run_*.sh            original experimental entry points
results/, results_v*/           frozen results, figures, environments, repetitions
docs/                           versioned research notes and current guides
scripts/                        non-destructive artifact validator
audit/                          before/after SHA-256 manifests and inventory
*.docx, *.pdf                    frozen manuscripts/design protocol
```

Original result paths are retained, including v4 `_tmp_runs` evidence. Compiled binaries are no longer tracked; build from the retained C++ sources. No history has been rewritten. No license was present at the audited revision; redistribution terms need author clarification before an external artifact release.
