#!/usr/bin/env python3
"""BAP v8.1 paired process-run ablation analysis (stdlib only).

Positive paired delta = first method in contrast is faster than comparator.
Uncertainty: exploratory percentile bootstrap over separate benchmark processes.
NOT a claim about TLBs, OS performance, or independent seeds/scenarios.
"""
import argparse
import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

GROUP = ("start_vpn", "region_size_pages", "physical_layout", "access_pattern")
CONTROLS = ("queries", "repeats", "bap_parent_count", "fixed_parent_count",
            "bap_records", "fixed_records", "bap_metadata_bytes", "fixed_metadata_bytes", "checksum")
METRICS = ("bap_arithmetic_ns", "bap_binary_parent_ns",
           "fixed_arithmetic_ns", "fixed_binary_parent_ns")
CONTRASTS = {
    "bap_selector_arithmetic_vs_binary": ("bap_arithmetic_ns", "bap_binary_parent_ns"),
    "fixed_selector_arithmetic_vs_binary": ("fixed_arithmetic_ns", "fixed_binary_parent_ns"),
    "partition_bap_vs_fixed_binary": ("bap_binary_parent_ns", "fixed_binary_parent_ns"),
    "partition_bap_vs_fixed_arithmetic": ("bap_arithmetic_ns", "fixed_arithmetic_ns"),
}

def read_file(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        expected = set(GROUP + ("seed",) + CONTROLS + METRICS)
        missing = expected - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path}: missing columns {sorted(missing)}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"{path}: empty")
    ix = {}
    for row in rows:
        k = tuple(row[z] for z in GROUP + ("seed",))
        if k in ix:
            raise ValueError(f"{path}: duplicate scenario/seed {k}")
        if any(float(row[m]) <= 0 for m in METRICS):
            raise ValueError(f"{path}: nonpositive timings at {k}")
        ix[k] = row
    return ix

def ci(xs, nboot, seed):
    rng = random.Random(seed)
    sims = sorted(sum(xs[rng.randrange(len(xs))] for _ in xs) / len(xs)
                  for _ in range(nboot))
    return sims[int(.025*nboot)], sims[min(nboot-1, int(.975*nboot))]

def analyze(paths, output, bootstrap):
    if len(paths) < 3:
        raise ValueError("At least three separate process runs are required; ten are recommended")
    runs = [read_file(p) for p in paths]
    reference = runs[0]
    for num, run in enumerate(runs[1:], 2):
        if set(run) != set(reference):
            raise ValueError(f"Run {num}: changed scenario/seed keys")
        for key, base in reference.items():
            other = run[key]
            for k in CONTROLS:
                if other[k] != base[k]:
                    raise ValueError(f"Run {num}: changed {k} for {key}")
    groups = defaultdict(list)
    for key in reference:
        groups[key[:4]].append(key)
    out = []
    for key, seed_keys in sorted(groups.items()):
        sk = sorted(seed_keys, key=lambda k: int(k[-1]))
        per_run = []
        for run in runs:
            per_run.append({m:statistics.mean(float(run[s][m]) for s in sk) for m in METRICS})
        baseline = reference[sk[0]]
        for name, (test, comparison) in CONTRASTS.items():
            a = [row[test] for row in per_run]
            b = [row[comparison] for row in per_run]
            delta = [y-x for x,y in zip(a,b)]
            seed=20261016+sum(ord(c) for c in name + '|'.join(key))
            low,high=ci(delta,bootstrap,seed)
            out.append(dict(zip(GROUP,key)) | {
                "contrast":name,
                "independent_process_runs":len(runs),
                "seeds_per_run":len(sk),
                "method_A":test,
                "method_B":comparison,
                "A_mean_ns":f"{statistics.mean(a):.4f}",
                "B_mean_ns":f"{statistics.mean(b):.4f}",
                "B_minus_A_mean_ns":f"{statistics.mean(delta):.4f}",
                "delta_bootstrap95_low_ns":f"{low:.4f}",
                "delta_bootstrap95_high_ns":f"{high:.4f}",
                "A_faster_run_fraction":f"{sum(x>0 for x in delta)/len(delta):.3f}",
                "bap_metadata_bytes":baseline["bap_metadata_bytes"],
                "fixed_metadata_bytes":baseline["fixed_metadata_bytes"],
            })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('w', newline='', encoding='utf-8') as f:
        writer=csv.DictWriter(f, fieldnames=list(out[0]));writer.writeheader();writer.writerows(out)
    print(f"PASS: {len(runs)} matching process runs, {len(reference)} scenario-seed rows/run, {len(out)} contrasts")
    print(f"Wrote {output}")
    target = [x for x in out if x['start_vpn']=='1' and x['region_size_pages']=='10000'
              and x['physical_layout']=='mixed_permissions' and x['access_pattern']=='uniform_random']
    print("\nPredeclared focus: S=10000, start=1, mixed_permissions, uniform_random")
    for x in target:
        print(f"{x['contrast']:37s} A={x['A_mean_ns']} B={x['B_mean_ns']} delta={x['B_minus_A_mean_ns']} "
              f"CI=[{x['delta_bootstrap95_low_ns']}, {x['delta_bootstrap95_high_ns']}] A-wins={x['A_faster_run_fraction']}")
    print("Note: CIs exploratory; several contrasts/scenarios are examined; no multiple-testing correction.")

if __name__ == '__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('runs',nargs='+',type=Path)
    ap.add_argument('--out',type=Path,default=Path('results_v81/ablation_summary_v81.csv'))
    ap.add_argument('--bootstrap',type=int,default=2000)
    ar=ap.parse_args()
    if ar.bootstrap<200:ap.error('bootstrap must be >=200')
    try:analyze(ar.runs,ar.out,ar.bootstrap)
    except (ValueError,OSError) as e:ap.error(str(e))
