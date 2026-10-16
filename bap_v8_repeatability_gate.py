#!/usr/bin/env python3
"""BAP v8 repeatability gate: compare independent benchmark process runs.

Each input must be the full output from lookup_benchmark_v8.cpp, run using the
same binary and configuration. Reported uncertainty is between *process runs*;
seeds and scenarios within one process are not independent replicates.

This is an exploratory CPU microbenchmark analysis, NOT a claim about TLBs,
kernel page walkers, or true page-table speedups.
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

GROUP = ("start_vpn", "region_size_pages", "physical_layout", "access_pattern")
SEED_FIELD = "seed"
REQUIRED = GROUP + (
    SEED_FIELD, "queries", "repeats", "bap_ns_per_lookup",
    "range_indexed_ns_per_lookup", "range_unbounded_ns_per_lookup",
    "range_cap512_ns_per_lookup", "bap_metadata_bytes",
    "range_indexed_metadata_bytes", "checksum"
)
METRICS = (
    "bap_ns_per_lookup", "range_indexed_ns_per_lookup",
    "range_unbounded_ns_per_lookup", "range_cap512_ns_per_lookup"
)
BASES = {
    "indexed": "range_indexed_ns_per_lookup",
    "unbounded": "range_unbounded_ns_per_lookup",
    "cap512": "range_cap512_ns_per_lookup",
}


def read_run(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = [x for x in REQUIRED if x not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing columns: {missing}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path}: no data rows")
    by_case = {}
    for row in rows:
        key = tuple(row[k] for k in GROUP + (SEED_FIELD,))
        if key in by_case:
            raise ValueError(f"{path}: duplicate scenario+seed {key}")
        for field in METRICS:
            if float(row[field]) <= 0:
                raise ValueError(f"{path}: non-positive lookup time in {key}")
        by_case[key] = row
    return by_case


def bootstrap_ci(xs, n_boot=3000, rng=None):
    """Percentile CI for mean *paired difference* across process runs."""
    rng = rng or random.Random(20261016)
    n = len(xs)
    values = []
    for _ in range(n_boot):
        values.append(sum(xs[rng.randrange(n)] for __ in range(n)) / n)
    values.sort()
    return values[int(.025 * n_boot)], values[min(n_boot - 1, int(.975 * n_boot))]


def analyze(paths, output: Path, bootstrap: int):
    if len(paths) < 2:
        raise ValueError("At least 2 separate run CSVs required; 5–10 are preferable")
    runs = [read_run(p) for p in paths]
    keys = set(runs[0]); controls = ("queries", "repeats", "bap_metadata_bytes", "range_indexed_metadata_bytes")
    for idx, run in enumerate(runs):
        if set(run) != keys:
            raise ValueError(f"Run {idx + 1} has different scenarios or seeds")
        for key in keys:
            for field in controls:
                if run[key][field] != runs[0][key][field]:
                    raise ValueError(f"Run {idx+1}: {field} mismatch at {key}")
            # Checksums are deterministic for the same program+trace and flag possible drift.
            if run[key]["checksum"] != runs[0][key]["checksum"]:
                raise ValueError(f"Run {idx+1}: checksum changed at {key}")
    grouped = defaultdict(list)
    for key in keys:
        grouped[key[:4]].append(key)
    lines = []
    for group_key in sorted(grouped):
        group_keys = sorted(grouped[group_key], key=lambda k: int(k[-1]))
        # A replication is one entire process run, averaged over fixed workload seeds.
        per_run = []
        for run in runs:
            seed_averages = {metric: statistics.mean(float(run[key][metric]) for key in group_keys)
                             for metric in METRICS}
            per_run.append(seed_averages)
        bap = [v["bap_ns_per_lookup"] for v in per_run]
        for name, baseline_field in BASES.items():
            baseline = [v[baseline_field] for v in per_run]
            paired_delta = [b - a for a, b in zip(bap, baseline)]
            rng = random.Random(20261016 + sum(ord(c) for c in '|'.join(group_key)) + len(name))
            low, high = bootstrap_ci(paired_delta, bootstrap, rng)
            lines.append({
                "start_vpn": group_key[0], "region_size_pages": group_key[1],
                "physical_layout": group_key[2], "access_pattern": group_key[3],
                "baseline": name, "independent_runs": len(runs), "seeds_per_run": len(group_keys),
                "bap_mean_ns": f"{statistics.mean(bap):.4f}",
                "baseline_mean_ns": f"{statistics.mean(baseline):.4f}",
                "baseline_minus_bap_mean_ns": f"{statistics.mean(paired_delta):.4f}",
                "paired_delta_ci95_low_ns": f"{low:.4f}",
                "paired_delta_ci95_high_ns": f"{high:.4f}",
                "bap_faster_run_fraction": f"{sum(x > 0 for x in paired_delta)/len(paired_delta):.3f}",
                "bap_slower_run_fraction": f"{sum(x < 0 for x in paired_delta)/len(paired_delta):.3f}",
                "interpretation": "BAP faster in all sampled runs" if all(x > 0 for x in paired_delta)
                else "BAP slower in all sampled runs" if all(x < 0 for x in paired_delta)
                else "mixed across runs",
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lines[0])); w.writeheader(); w.writerows(lines)
    print(f"PASS: {len(paths)} independent process runs, {len(keys)} matched scenario-seed rows/run")
    print(f"Wrote {len(lines)} grouped comparisons to {output}")
    focused = [x for x in lines if x["region_size_pages"] == "10000" and x["start_vpn"] == "1"
               and x["access_pattern"] == "uniform_random" and x["baseline"] == "indexed"]
    print("\nUniform random, start=1, size=10000: (+ delta means BAP faster)")
    for x in focused:
        print(f"{x['physical_layout']:<26} BAP {x['bap_mean_ns']:>8} ns vs indexed {x['baseline_mean_ns']:>8} ns; "
              f"paired Δ {x['baseline_minus_bap_mean_ns']:>8} ns; 95% boot CI "
              f"[{x['paired_delta_ci95_low_ns']}, {x['paired_delta_ci95_high_ns']}]")
    print("\nReminder: bootstrap uncertainty is exploratory; isolated environment and independent runs matter.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("runs", nargs="+", type=Path, help="CSV from separate executions of the same binary")
    ap.add_argument("--out", type=Path, default=Path("results_v8/repeatability_summary.csv"))
    ap.add_argument("--bootstrap", type=int, default=3000)
    args = ap.parse_args()
    if args.bootstrap < 200:
        ap.error("--bootstrap must be >= 200")
    try:
        analyze(args.runs, args.out, args.bootstrap)
    except (ValueError, OSError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
