# BAP v8.3B-1: Native Dynamic Update Pilot

**Scope:** This is an experimental C++20 software-metadata benchmark, **not** a Linux kernel implementation, x86 TLB benchmark, measured physical-memory footprint, or proof that BAP outperforms alternatives.

## Why this is the next step

Version v8.3B-0 passed the 576-state differential-correctness gate against v8.3A, but Python's generic-range record container used a list and its diagnostic scan counts cannot support performance claims. The new native pilot runs the **same balanced `std::map` record data structure for all three partition schemes** (BAP parent partitions, fixed 512-page grid, globally coalesced ranges), each both eager and with the *same* sparse exception overlay and compaction threshold. Lookup and updates have identical page/PFN/permission semantics. Per-model PFN ownership uses `std::unordered_map` in all six versions.

## Model, operations, and verification

- Two region lengths (1,000 and 4,096 pages), virtual starts 0 and 1, two layouts (contiguous and fragmented+permissions), two prespecified update mixes (`mixed`, `protect_heavy`), three deterministic seeds.
- Four operations: map into holes, unmap, protect while keeping PFN, and one-page COW-like PFN replacement. No aliasing, concurrency, actual COW copying, kernel page table, or TLB.
- Six methods: `bap_eager`, `bap_overlay`, `fixed_eager`, `fixed_overlay`, `ranges_eager`, `ranges_overlay`.
- A **separate, untimed oracle pass checks every mapped/unmapped page and exact PFN+permission after every update** for each scenario and method. The measured pass replays the same update and lookup trace, and time excludes oracle checking.
- Batched adjacent exception compaction is implemented identically for all overlay versions; compaction time **is included** in update timing. Region discovery is excluded identically for all.
- `std::map` is an ordered balanced tree; it is *not* equivalent to Linux Maple Tree or RMM. Compiler and allocator effects remain. Fixed parent indexing remains simple arithmetic and BAP uses XOR/MSB for the tail.

## Run from the repository root in Ubuntu/WSL

Unzip these files into your existing repository, preserving `results_v83b1/`.

```bash
RUNS=10 UPDATES=128 QUERIES=16 bash run_v83b1.sh
```

Each execution yields 288 rows (48 seed-scenarios x six methods). Ten separate invocations yield 2,880 timing rows. The analyzer checks all per-scenario checksums and structural-state controls, averages each group of three seeds *within* a process run, and generates descriptive paired process-run means and exploratory bootstrap confidence intervals.

**A negative difference (`baseline - BAP`) means BAP was slower; a positive difference means BAP was faster.** Count *independent process runs*, not seeds, as replications. Treat all metrics as a **pilot**, not publication-quality estimates: multiple contrasts were compared, the timings use short workloads, host load is not controlled, allocation instrumentation is absent, and only two sizes/layouts are included.

## Files to commit

- `dynamic_benchmark_v83b1.cpp`
- `run_v83b1.sh`
- `analyze_v83b1.py`
- `docs/README_V83B1.md`
- `results_v83b1/environment.txt`, `results_v83b1/selfcheck.csv`, `results_v83b1/repetitions/*.csv`, `results_v83b1/paired_pilot_summary.csv`

Do **not** commit compiled executables. Update `.gitignore` accordingly. Preserve the main Word/PDF paper as v8.2; v8.3B-1 is a separate pilot artifact.

## Decision after this pilot

Do not declare G1/G2 pass yet. Review whether BAP+overlay is consistently competitive with **both** fixed+overlay and ranges+overlay in the prespecified update-heavy scenarios, and whether it worsens lookup cost. For a stronger test, instrument complete peak live allocation bytes, add more sizes/layouts and longer mixed traces, isolate CPU frequency/scheduling, replicate on independent hardware, and study how much of the outcome is due to grouping rather than BAP-specific arithmetic. A purely generic overlay benefit is not BAP novelty.
