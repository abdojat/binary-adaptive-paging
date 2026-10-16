# BAP v8.3B-2 — Scientific Go/No-Go Gate

This is a **reanalysis of existing v8.3B-1 measurements**, **not** a new benchmark, optimization, or proof of BAP superiority. Its purpose is to freeze a defensible decision before investing in native allocation profiling or kernel-level work.

## Inputs and command

Place `evaluate_v83b1_gate.py` at the repository root. The existing files under `results_v83b1/` must remain unchanged.

```bash
python3 evaluate_v83b1_gate.py \
  --summary results_v83b1/paired_pilot_summary.csv \
  --runs results_v83b1/repetitions/run_*.csv \
  --out results_v83b1/decision_matrix_v83b2.csv \
  --report docs/v8_3b2_research_decision.md
```

Requires Python 3.10+ standard library only; **does not rerun any C++ models**.

The script validates all ten runs, complete six-model scenarios, checksum and mapping-structure stability, source evidence flags, the 192 preexisting exploratory comparisons, and the decision matrix. Never use a locally changed result file without separately identifying the revision. Avoid editing the threshold criteria after seeing outcomes.

## Reading the result

- **G0:** semantic/oracle agreement on the executed traces. Does not imply production OS correctness.
- **G1:** candidate BAP+overlay must beat **both** fixed-grid+overlay and generic-range+overlay; in this conservative screening report a positive exploratory lower CI is required for both. Since these are **uncorrected exploratory CIs**, this is a screening decision, **not** a corrected statistical significance test.
- **G2:** prospectively chosen update improvement ≥10%, lookup slowdown ≤5%, and peak metadata increase ≤10%. The current pilot has **no measured peak bytes**, so the full gate cannot be assessed.
- **G3:** one WSL/Intel system is not cross-hardware reproducibility.

**If the pilot cannot establish G1, do not spend on a full v8.3B-2 performance campaign.** Instead document the negative pilot, retain the data, and pursue a revised novel mechanism or a comparative paper with sharply delimited claims. Not demonstrating the advantage on the tested workloads is not a theorem that no such workload exists.

## Files for GitHub

- `evaluate_v83b1_gate.py`
- `docs/README_V83B2.md`
- generated `docs/v8_3b2_research_decision.md`
- generated `results_v83b1/decision_matrix_v83b2.csv`

Keep `Binary Adaptive Paging.docx` and `.pdf` on v8.2 until the research framing is revised deliberately. Do not commit compiled binaries or overwrite earlier CSVs.
