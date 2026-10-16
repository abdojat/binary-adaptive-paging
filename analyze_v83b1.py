#!/usr/bin/env python3
"""Exploratory paired run analysis for six-model native dynamic-update pilot.

Unit of replication: complete independent benchmark process run, averaged over
three deterministic workload seeds. Does not correct for multiple comparisons.
A positive paired delta (baseline - BAP) means BAP has lower time.
"""
import argparse
import csv
import random
import statistics
from collections import defaultdict
from pathlib import Path

CASE = ('region_pages', 'start_vpn', 'layout', 'mix', 'seed')
GROUP = CASE[:-1]
METHODS = ('bap_eager', 'bap_overlay', 'fixed_eager', 'fixed_overlay',
           'ranges_eager', 'ranges_overlay')
METRICS = ('update_ns_per_op', 'lookup_ns_per_query', 'mixed_ns_per_query')
COMPARE = (('bap_overlay','fixed_overlay'),('bap_overlay','ranges_overlay'),
           ('bap_eager','fixed_eager'),('bap_eager','ranges_eager'))


def load(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f'Empty file: {path}')
    keyed = defaultdict(dict)
    for x in rows:
        k = tuple(x[z] for z in CASE)
        m = x['method']
        if m in keyed[k]:
            raise ValueError(f'Duplicate model: {path} {k} {m}')
        if x['oracle_verified'] != 'YES' or x['native_memory_bytes_measured'] != 'NO':
            raise ValueError(f'Unexpected correctness/memory claim in {path}: {k} {m}')
        for metric in METRICS:
            if float(x[metric]) <= 0:
                raise ValueError(f'Bad time: {path} {k} {m}')
        keyed[k][m] = x
    for k, ms in keyed.items():
        if set(ms) != set(METHODS):
            raise ValueError(f'Incomplete case {path}: {k}')
        if len({x['checksum'] for x in ms.values()}) != 1:
            raise ValueError(f'Checksum disagreement {path}: {k}')
        if len({(x['updates'], x['queries_per_update']) for x in ms.values()}) != 1:
            raise ValueError(f'Workload control mismatch {path}: {k}')
    return keyed


def bootstrap(xs, rng, n=2000):
    values = sorted(sum(rng.choice(xs) for _ in xs)/len(xs) for __ in range(n))
    return values[int(.025*n)], values[min(n-1,int(.975*n))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('runs', type=Path, nargs='+')
    ap.add_argument('--out', type=Path, default=Path('results_v83b1/paired_pilot_summary.csv'))
    args = ap.parse_args()
    if len(args.runs) < 3:
        ap.error('At least three independent process runs required')
    runs = [load(p) for p in args.runs]
    keyset = set(runs[0])
    if any(set(run) != keyset for run in runs[1:]):
        ap.error('Runs do not contain identical scenario/seed keys')
    for key in keyset:
        for run in runs[1:]:
            for m in METHODS:
                for field in ('checksum', 'updates', 'queries_per_update', 'base_records',
                              'parent_count', 'pending_exceptions', 'peak_exceptions', 'compactions'):
                    if runs[0][key][m][field] != run[key][m][field]:
                        ap.error(f'Run state changed: {key} {m} {field}')
    groups = defaultdict(list)
    for key in keyset:
        groups[key[:-1]].append(key)
    output = []
    for group, keys in sorted(groups.items()):
        keys.sort(key=lambda x:int(x[-1]))
        for a,b in COMPARE:
            for metric in METRICS:
                A,B = [],[]
                for run in runs:
                    A.append(statistics.mean(float(run[k][a][metric]) for k in keys))
                    B.append(statistics.mean(float(run[k][b][metric]) for k in keys))
                diffs = [y-x for x,y in zip(A,B)]
                rng = random.Random(20261016+sum(ord(x) for x in '|'.join(group)+(a+b+metric)))
                low,high=bootstrap(diffs,rng)
                output.append(dict(zip(GROUP,group)) | {
                    'candidate': a, 'baseline': b,'metric':metric,
                    'independent_runs':len(runs),'seeds_per_run':len(keys),
                    'candidate_mean_ns':f'{statistics.mean(A):.4f}',
                    'baseline_mean_ns':f'{statistics.mean(B):.4f}',
                    'baseline_minus_candidate_mean_ns':f'{statistics.mean(diffs):.4f}',
                    'exploratory_ci95_low_ns':f'{low:.4f}',
                    'exploratory_ci95_high_ns':f'{high:.4f}',
                    'candidate_faster_run_fraction':f'{sum(z>0 for z in diffs)/len(diffs):.3f}',
                })
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f, fieldnames=list(output[0]))
        writer.writeheader();writer.writerows(output)
    print(f'PASS: {len(runs)} independent runs, {len(keyset)} matched seed-scenarios/run, '
          f'{len(output)} paired comparisons. Wrote {args.out}')
    print('CAUTION: exploratory timings only; dynamic allocation peak bytes NOT measured; '
          'multiple comparisons uncorrected; no kernel/TLB claims.')


if __name__=='__main__':
    main()
