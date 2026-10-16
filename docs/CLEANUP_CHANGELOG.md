# Cleanup changelog — 2026-10-16

Base revision: `a56b720`; all 18 locally available commits inspected for artifact progression. No commits, pushes, merges, fetches or history rewriting were performed during cleanup.

## Changes

1. Added a root research README, complete v0–v8.4A experiment index, reproducibility guide, scientific-scope/stale-statement audit, documentation map and validation report.
2. Moved `README_START_HERE.md`, `README_START_V84.md`, `START_HERE.md`, `README_V83A.md` and `v8_4a_novelty_audit.md` into `docs/`, preserving exact contents. New navigation links resolve to their new locations. Inline historical paths and commands remain explicitly repository-root-relative; old handoffs are clearly marked historical.
3. Removed three build products from the Git index using `git rm --cached`: `lookup_benchmark_v8`, `lookup_ablation_v81`, `dynamic_benchmark_v83b1`. Local copies and all C++ sources remain. No historical Git objects were removed.
4. Updated `.gitignore` for named binaries, object/executable/debug files, build output and validation scratch. Removed the broad `*.log` rule so research logs are not silently hidden. Did not ignore or remove v4 `_tmp_runs`.
5. Added `scripts/validate_artifact.py` for frozen-file SHA-256, syntax/build/CSV checks, deterministic correctness replay, archived comparative summary verification and optional ten-process native repetitions. All generated outputs use temporary storage. Added corruption-rejection tests under `tests/`.
6. Added a minimal Matplotlib dependency declaration with an explicit historical-version caveat; no claimed historical lockfile, algorithm edits, new seed policy or new experiment defaults.
7. Recorded before/after checksums and a full original-artifact inventory under `audit/`, plus the validation execution log.

## Preservation accounting

The baseline has 317 tracked files: 259 CSVs (including 200 v4 intermediates), 15 PNGs, 16 Python sources, four shell scripts, three C++ sources, three binaries, 11 Markdown documents, two environment logs, two DOCX documents, one PDF and `.gitignore`. All 313 non-packaging files retain their original SHA-256, with five paths remapped into `docs/`. The three local binary files also retain their hashes but are intentionally untracked; `.gitignore` is the only original file edited in place. The main Word/PDF manuscripts and the design-gate Word file are unchanged.

Two untracked user files appeared after the initial inspection: `BAP_Complete_Final_Technical_Report_v0_to_v8_4A.docx` and `RESEARCH_STATUS_V84A.md`. They were not edited, moved, staged or included in the historical evidence baseline.

## Scientific boundaries

The v8.2 model-specific dominance result and the v8.3B-2 negative decision are unchanged. No benchmark optimization, threshold/seed adjustment, result substitution or figure/manuscript regeneration was performed. Temporary deterministic reproductions verify archived values; temporary native runs exercise correctness and analysis, not new research claims. Full-text novelty review, peak allocation measurement, controlled multi-host timings and an author-led manuscript review remain outside this cleanup.
