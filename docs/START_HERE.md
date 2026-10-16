# Next action after v8.3B-1

The ten-run native pilot was reviewed. BAP+overlay did not establish a consistent advantage against both fixed-grid+overlay and generic-range+overlay. Do **not** run a larger native timing benchmark yet. Instead, **lock the decision using existing CSVs**.

1. Place `evaluate_v83b1_gate.py` in your repository root.
2. Place `docs/README_V83B2.md` in `docs/` and optionally keep the provided `docs/v8_3b2_research_decision.md` as an initial review record.
3. In Ubuntu/WSL (from your repo root), run:

```bash
python3 evaluate_v83b1_gate.py \
  --summary results_v83b1/paired_pilot_summary.csv \
  --runs results_v83b1/repetitions/run_*.csv \
  --out results_v83b1/decision_matrix_v83b2.csv \
  --report docs/v8_3b2_research_decision.md
```

Expected essentials for the **uploaded ten-run dataset**:

```text
PASS: 10 matching process runs, 288 rows/run, 16 settings, 192 contrasts
BAP overlay vs fixed overlay: update wins 7/16; positive exploratory CI 0/16
BAP overlay vs ranges overlay: update wins 11/16; positive exploratory CI 3/16
G1 both-baseline CI-positive settings: 0/16; latency-only 10%/5% settings: 0/16
DECISION: current BAP-specific dynamic speedup NOT DEMONSTRATED. Memory/G3 unassessed.
```

4. Review output, then commit:

```bash
git add evaluate_v83b1_gate.py docs/README_V83B2.md \
  docs/v8_3b2_research_decision.md results_v83b1/decision_matrix_v83b2.csv
git commit -m "Record v8.3B-1 falsification gate and research decision"
git push
```

Keep main Word/PDF at v8.2 while deciding on a stronger comparative manuscript, not a generic BAP performance claim. No new CPU-intensive experiments are needed for this gate.
