#!/usr/bin/env python3
"""BAP v8.3B-2: frozen negative-result and reproducibility decision gate.

Reads already-collected v8.3B-1 runs and their paired exploratory summary.
Does not rerun models, measure memory or establish statistical significance.
Python 3.10+ standard library only.
"""
import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

METHODS = ('bap_eager','bap_overlay','fixed_eager','fixed_overlay','ranges_eager','ranges_overlay')
METRICS = ('update_ns_per_op','lookup_ns_per_query','mixed_ns_per_query')
PAIRS = (('bap_overlay','fixed_overlay'),('bap_overlay','ranges_overlay'),
         ('bap_eager','fixed_eager'),('bap_eager','ranges_eager'))
CASE = ('region_pages','start_vpn','layout','mix','seed')
GROUP = CASE[:-1]


def rows(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        rd = csv.DictReader(f)
        out = list(rd)
    if not out:
        raise ValueError('empty CSV '+str(path))
    return out


def run_checks(paths, min_runs=10):
    if len(paths) < min_runs:
        raise ValueError(f'need {min_runs} independent process run files; got {len(paths)}')
    ref = None
    checks = {}
    raw_runs = []
    for path in paths:
        ls = rows(path)
        keyset = set()
        keyed_rows = {}
        grouped = defaultdict(list)
        for r in ls:
            if r['method'] not in METHODS:
                raise ValueError(f'unknown method in {path}: {r["method"]}')
            key = tuple(r[k] for k in CASE) + (r['method'],)
            if key in keyset: raise ValueError(f'duplicate {key} in {path}')
            keyset.add(key)
            keyed_rows[key]=r
            grouped[tuple(r[k] for k in CASE)].append(r)
            if r['oracle_verified']!='YES' or r['native_memory_bytes_measured']!='NO' or r['tlb_measured']!='NO':
                raise ValueError(f'unexpected evidence flags in {path}: {key}')
            if any(float(r[k])<=0 or not math.isfinite(float(r[k])) for k in METRICS):
                raise ValueError(f'invalid time in {path}: {key}')
            const_key = tuple(r[k] for k in CASE)+(r['method'],)
            controls=tuple(r[k] for k in ('updates','queries_per_update','base_records','parent_count',
                                         'pending_exceptions','peak_exceptions','compactions','checksum'))
            if ref is not None and checks[const_key]!=controls:
                raise ValueError(f'structural state or checksum changed: {path} {const_key}')
            if ref is None: checks[const_key] = controls
        for k, records in grouped.items():
            if len(records)!=6 or set(r['method'] for r in records)!=set(METHODS):
                raise ValueError(f'incomplete six-model case: {path} {k}')
            if len({r['checksum'] for r in records})!=1:
                raise ValueError(f'checksum disagrees among models: {path} {k}')
            if len({(r['updates'],r['queries_per_update']) for r in records})!=1:
                raise ValueError(f'workload parameters differ: {path} {k}')
        if ref is not None and keyset!=ref:
            raise ValueError(f'scenario/model keys changed in {path}')
        if ref is None: ref=keyset
        raw_runs.append(keyed_rows)
    return len(ref),len(paths),raw_runs


def summary_checks(summary, n_runs, raw_runs):
    data={}
    for r in rows(summary):
        key=tuple(r[x] for x in GROUP)+(r['candidate'],r['baseline'],r['metric'])
        if key in data: raise ValueError('duplicate summary comparison '+str(key))
        if (r['candidate'],r['baseline']) not in PAIRS or r['metric'] not in METRICS:
            raise ValueError('unknown summary comparison '+str(key))
        if int(r['independent_runs'])!=n_runs or int(r['seeds_per_run'])!=3:
            raise ValueError('run/seed count disagrees with expected experiment '+str(key))
        # Cross-check the published summary against all raw-run timing values.
        means_A=[];means_B=[];paired=[]
        for run in raw_runs:
            vals_A=[];vals_B=[]
            for seed in ('1','2','3'):
                root=tuple(r[x] for x in GROUP)+(seed,)
                if root+(r['candidate'],) not in run or root+(r['baseline'],) not in run:
                    raise ValueError('missing expected seed 1/2/3 in a raw run: '+str(key))
                vals_A.append(float(run[root+(r['candidate'],)][r['metric']]))
                vals_B.append(float(run[root+(r['baseline'],)][r['metric']]))
            a,b=statistics.mean(vals_A),statistics.mean(vals_B)
            means_A.append(a);means_B.append(b);paired.append(b-a)
        observed_A=statistics.mean(means_A)
        observed_B=statistics.mean(means_B)
        observed_delta=statistics.mean(paired)
        raw_fraction=sum(x>0 for x in paired)/len(paired)
        fields=(('candidate_mean_ns',observed_A),('baseline_mean_ns',observed_B),
                ('baseline_minus_candidate_mean_ns',observed_delta),
                ('candidate_faster_run_fraction',raw_fraction))
        for field,expected in fields:
            # Summary files store 4 decimals for times and 3 for fractions.
            tolerance=0.00011 if field!='candidate_faster_run_fraction' else 0.00051
            if abs(float(r[field])-expected)>tolerance:
                raise ValueError(f'stale or incorrect summary: {key} {field}: '
                                 f'summary {r[field]} vs raw {expected:.6f}')
        data[key]=r
    groups={key[:4] for key in data}
    if len(data)!=len(groups)*len(PAIRS)*len(METRICS):
        raise ValueError('summary is missing a contrast or has unexpected entries')
    if len(groups)!=16 or len(data)!=192:
        raise ValueError(f'expected 16 distinct settings x 12 contrasts = 192; got {len(groups)} / {len(data)}')
    return data,groups


def floatval(r,field):return float(r[field])


def evaluate(data,groups):
    matrix=[]
    for g in sorted(groups):
        d=dict(zip(GROUP,g))
        comparisons={}
        for baseline in ('fixed_overlay','ranges_overlay'):
            update=data[g+('bap_overlay',baseline,'update_ns_per_op')]
            lookup=data[g+('bap_overlay',baseline,'lookup_ns_per_query')]
            mix=data[g+('bap_overlay',baseline,'mixed_ns_per_query')]
            gain=100.0 * (floatval(update,'baseline_mean_ns')-floatval(update,'candidate_mean_ns'))/floatval(update,'baseline_mean_ns')
            lookup_slowdown=100.0 * (floatval(lookup,'candidate_mean_ns')-floatval(lookup,'baseline_mean_ns'))/floatval(lookup,'baseline_mean_ns')
            comparisons[baseline]={'gain':gain,'lookup_slowdown':lookup_slowdown,
                'ci_low':floatval(update,'exploratory_ci95_low_ns'),
                'ci_high':floatval(update,'exploratory_ci95_high_ns'),
                'mixed_gain':100.0*(floatval(mix,'baseline_mean_ns')-floatval(mix,'candidate_mean_ns'))/floatval(mix,'baseline_mean_ns')}
            d.update({f'{baseline}_update_gain_pct':round(gain,4),
                      f'{baseline}_lookup_slowdown_pct':round(lookup_slowdown,4),
                      f'{baseline}_update_ci_low_ns':round(comparisons[baseline]['ci_low'],4),
                      f'{baseline}_update_ci_high_ns':round(comparisons[baseline]['ci_high'],4),
                      f'{baseline}_mixed_gain_pct':round(comparisons[baseline]['mixed_gain'],4)})
        # G1: both comparator paired exploratory CI lower bounds positive.
        attribution = all(comparisons[b]['ci_low']>0 for b in comparisons)
        # G2 latency-only component: ≥10% update improvement and ≤5% lookup slowdown against both.
        practical_latency=all(comparisons[b]['gain']>=10 and comparisons[b]['lookup_slowdown']<=5 for b in comparisons)
        d['both_baselines_exploratory_ci_positive']='YES' if attribution else 'NO'
        d['both_baselines_latency_threshold_met']='YES' if practical_latency else 'NO'
        d['full_G2_verdict']='UNASSESSABLE_NO_PEAK_LIVE_ALLOCATED_BYTES'
        d['G3_verdict']='UNASSESSABLE_SINGLE_HOST'
        matrix.append(d)
    return matrix


def write_csv(path,items):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(items[0]));w.writeheader();w.writerows(items)


def write_report(path, n_runs, n_cases, matrix, summary):
    data,_=summary
    pair_counts={}
    for metric in METRICS:
        for b in ('fixed_overlay','ranges_overlay'):
            r=[v for k,v in data.items() if k[4:]==('bap_overlay',b,metric)]
            pair_counts[(metric,b)]=(sum(floatval(v,'baseline_minus_candidate_mean_ns')>0 for v in r),
                                     sum(floatval(v,'exploratory_ci95_low_ns')>0 for v in r),
                                     sum(floatval(v,'exploratory_ci95_high_ns')<0 for v in r))
    both=sum(x['both_baselines_exploratory_ci_positive']=='YES' for x in matrix)
    threshold=sum(x['both_baselines_latency_threshold_met']=='YES' for x in matrix)
    out=["# v8.3B-2 — Dynamic Pilot Research Decision", "",
         "**Evidence:** GitHub `results_v83b1/` generated from v8.3B-1, archived pilot; not kernel/TLB benchmarks.",
         f"**Audit:** {n_runs} separately recorded runs; {n_cases} scenario-model rows per run; 16 scenario groups; 192 contrasts.", "",
         "## Result matrix (BAP + overlay)", "",
         "| Metric | Faster than Fixed overlay | Faster than Ranges overlay | Positive exploratory 95% CI vs Fixed | Positive exploratory 95% CI vs Ranges |",
         "|---|---:|---:|---:|---:|"]
    for m in METRICS:
        f=pair_counts[(m,'fixed_overlay')];r=pair_counts[(m,'ranges_overlay')]
        out.append(f"| `{m}` | {f[0]}/16 | {r[0]}/16 | {f[1]}/16 | {r[1]}/16 |")
    out += ["",f"Settings with positive exploratory update CI against **both** overlays: **{both}/16**.",
            f"Settings meeting both predeclared update ≥10% and lookup slowdown ≤5% latency criteria: **{threshold}/16** (not a full G2 assessment).", "",
            "## Decision", "",
            "- **G0 correctness:** PASS for the tested software-mapping traces; all methods reported oracle verification and matching checksums. No actual OS paging guarantee.",
            "- **G1 BAP-specific attribution:** **NOT DEMONSTRATED** by this pilot. No tested setting had a positive exploratory update-delta CI against both optimized overlay comparators.",
            "- **G2 practicality:** **NOT DEMONSTRATED / PARTLY UNASSESSABLE.** Peak allocated bytes were not measured; no result can satisfy the full prescribed threshold assessment.",
            "- **G3 reproducibility:** repeatable on one WSL/Intel host, but multi-machine/compiler sensitivity is **UNTESTED**.",
            "- **Research go/no-go:** STOP the present BAP-specific dynamic-speedup claim. Preserve code/data as a negative/comparative result. Only resume optimization work after a new, clearly distinguishable BAP-specific mechanism and a new prospective hypothesis are defined.","",
            "## Scientific limits", "",
            "- Per-process runs, not seeds/queries, are the statistical replication unit. Bootstrap CIs are exploratory and uncorrected for multiplicity; CI overlap/positivity is a conservative screening heuristic, not a formal adjusted hypothesis test.",
            "- Only two sizes, two layouts, and short traces were tested; observed failure is not a mathematical proof that no workload can benefit.",
            "- `std::map` is not a kernel Maple Tree. Allocator, cache, compiler and short-operation timing overhead can confound tiny differences.",
            "- The benchmark fixes a method order for each seed across processes. Larger prospective studies should counterbalance method order and use longer measurement windows.",
            "- Previous formal dominance (v8.2) concerns **structural metadata** under precise assumptions; it does not prove comparative update-latency dominance.", "",
            "## Recommended next research action", "",
            "Create a **comparative/negative-results manuscript plan** with a validated related-work novelty matrix, a precise statement of theoretical assumptions, and a transparent analysis of the v8.1/v8.3B-1 null results. Do not revise the current v8.2 paper into a speedup claim, perform hardware implementation, or spend on expensive repeated benchmarks at this stage.", "",
            "## Reproduction", "",
            "```bash", "python3 evaluate_v83b1_gate.py --summary results_v83b1/paired_pilot_summary.csv --runs results_v83b1/repetitions/run_*.csv --out results_v83b1/decision_matrix_v83b2.csv --report docs/v8_3b2_research_decision.md", "```", ""]
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text('\n'.join(out),encoding='utf-8')
    return pair_counts,both,threshold


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--summary',type=Path,default=Path('results_v83b1/paired_pilot_summary.csv'))
    ap.add_argument('--runs',nargs='+',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=Path('results_v83b1/decision_matrix_v83b2.csv'))
    ap.add_argument('--report',type=Path,default=Path('docs/v8_3b2_research_decision.md'))
    ap.add_argument('--min-runs',type=int,default=10,help='minimum run files; default research gate requires 10')
    args=ap.parse_args()
    cases,nruns,raw_runs=run_checks(args.runs,args.min_runs)
    data,groups=summary_checks(args.summary,nruns,raw_runs)
    matrix=evaluate(data,groups)
    write_csv(args.out,matrix)
    stats,both,threshold=write_report(args.report,nruns,cases,matrix,(data,groups))
    print(f'PASS: {nruns} matching process runs, {cases} rows/run, {len(groups)} settings, 192 contrasts')
    print(f'BAP overlay vs fixed overlay: update wins {stats[("update_ns_per_op","fixed_overlay")][0]}/16; positive exploratory CI {stats[("update_ns_per_op","fixed_overlay")][1]}/16')
    print(f'BAP overlay vs ranges overlay: update wins {stats[("update_ns_per_op","ranges_overlay")][0]}/16; positive exploratory CI {stats[("update_ns_per_op","ranges_overlay")][1]}/16')
    print(f'G1 both-baseline CI-positive settings: {both}/16; latency-only 10%/5% settings: {threshold}/16')
    print('DECISION: current BAP-specific dynamic speedup NOT DEMONSTRATED. Memory/G3 unassessed.')
    print(f'WROTE: {args.out} and {args.report}')

if __name__=='__main__':main()
