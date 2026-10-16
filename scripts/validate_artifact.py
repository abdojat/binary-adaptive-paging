#!/usr/bin/env python3
"""Read-only archive validation; all experimental output goes to a temporary tree.

Run without -O: historical programs use assertions for scientific checks.
--native executes ten independent processes for EACH of the three benchmarks,
using their original defaults. New timings never replace historical evidence.
"""
import argparse
import ast
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MOVED = ('README_START_HERE.md', 'README_START_V84.md', 'START_HERE.md',
         'README_V83A.md', 'v8_4a_novelty_audit.md')
BINARIES = ('lookup_benchmark_v8', 'lookup_ablation_v81', 'dynamic_benchmark_v83b1')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integrity():
    baseline = json.loads((ROOT / 'audit/before.sha256.json').read_text())
    git_blobs = json.loads((ROOT / 'audit/git-blobs.sha256.json').read_text())
    count = 0
    checkout_variants = 0
    for name, expected in baseline.items():
        if name == '.gitignore' or name in BINARIES:
            continue  # explicitly documented packaging changes
        path = ROOT / ('docs/' + name if name in MOVED else name)
        require(path.is_file(), f'Missing frozen file: {name}')
        actual = digest(path)
        require(actual in (expected, git_blobs[name]), f'Changed frozen file: {name}')
        checkout_variants += actual != expected
        count += 1
    print(f'PASS: {count} frozen files match pre-cleanup SHA-256 '
          f'({checkout_variants} match original Git-blob bytes instead of local checkout bytes)', flush=True)
    return baseline


def rows(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), f'Bad header: {path}')
        data = list(reader)
    require(data, f'Empty CSV: {path}')
    for row in data:
        require(None not in row and all(v is not None and v != '' for v in row.values()), f'Ragged/empty row: {path}')
        for key, value in row.items():
            try:
                number = float(value)
            except ValueError:
                continue
            require(math.isfinite(number), f'Nonfinite value: {path} {key}')
        if 'semantic_mismatches' in row:
            require(row['semantic_mismatches'] == '0', f'Semantic mismatch: {path}')
        if 'oracle_verified' in row:
            require(row['oracle_verified'] == 'YES', f'Oracle failure: {path}')
        for key in ('tlb_measured', 'tlb_performance_measured', 'native_memory_bytes_measured'):
            if key in row:
                require(row[key] == 'NO', f'Unexpected measurement claim: {path} {key}')
    return data


def same_csv(a, b):
    require(rows(a) == rows(b), f'CSV differs: {a} vs {b}')


def run(args, cwd, env):
    print('+ ' + ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, env=env, check=True)


def validate(work, native):
    env = os.environ.copy()
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['MPLBACKEND'] = 'Agg'
    env.pop('PYTHONOPTIMIZE', None)
    py = sys.executable
    baseline = integrity()
    paths = [ROOT / p for p in baseline if p.endswith('.csv')]
    for p in paths:
        rows(p)
    print(f'PASS: {len(paths)} archived CSVs structurally valid and finite', flush=True)
    for p in list(ROOT.glob('*.py')) + list((ROOT / 'scripts').glob('*.py')):
        ast.parse(p.read_text(encoding='utf-8-sig'), filename=str(p))
    print('PASS: Python syntax', flush=True)
    for p in ROOT.glob('*.sh'):
        run(['bash', '-n', p], work, env)
    # Copy only historical source into the scratch tree, preserving relative imports.
    for pattern in ('*.py', '*.cpp'):
        for p in ROOT.glob(pattern):
            shutil.copy2(p, work / p.name)
    for source in BINARIES:
        run(['g++', '-O3', '-std=c++20', '-Wall', '-Wextra', '-pedantic',
             work / (source + '.cpp'), '-o', work / source], work, env)
    for source, archive in (
        ('feasibility_v5.py', 'results_v5/feasibility_summary_v5.csv'),
        ('translation_v6.py', 'results_v6/translation_semantics_v6.csv'),
        ('metadata_lookup_v7.py', 'results_v7/metadata_lookup_v7.csv'),
        ('formal_audit_v82.py', 'results_v82/formal_checks_v82.csv'),
        ('dynamic_correctness_v83a.py', 'results_v83a/dynamic_correctness_v83a.csv'),
        ('dynamic_incremental_v83b0.py', 'results_v83b0/incremental_semantics_v83b0.csv')):
        out = work / Path(archive).name
        command = [py, source, '--out', out]
        if source != 'formal_audit_v82.py':
            command.append('--validate')
        run(command, work, env)
        same_csv(out, ROOT / archive)
    run([py, 'verify_v83b0_against_v83a.py', '--old', work / 'dynamic_correctness_v83a.csv',
         '--new', work / 'incremental_semantics_v83b0.csv'], work, env)
    for source, archive in (
        ('dynamic_correctness_v83a.py', 'results_v83a/large_region_spotcheck.csv'),
        ('dynamic_incremental_v83b0.py', 'results_v83b0/large_region_v83b0.csv')):
        out = work / Path(archive).name
        run([py, source, '--sizes', '10000', '--starts', '1', '--layouts', 'fragmented_permissions',
             '--thresholds', '0.05', '--seeds', '1', '--updates', '12', '--out', out], work, env)
        same_csv(out, ROOT / archive)
    for version, analyzer, summary, expected in (
        ('v8', 'bap_v8_repeatability_gate.py', 'repeatability_summary.csv', 540),
        ('v81', 'analyze_v81.py', 'ablation_summary_v81.csv', 540),
        ('v83b1', 'analyze_v83b1.py', 'paired_pilot_summary.csv', 288)):
        archive = ROOT / ('results_' + version)
        inputs = sorted((archive / 'repetitions').glob('run_*.csv'))
        require({p.name for p in inputs} == {f'run_{i}.csv' for i in range(1, 11)}, 'Expected ten archived runs')
        require(all(len(rows(p)) == expected for p in inputs), 'Wrong archived run row count')
        output = work / summary
        run([py, analyzer, *inputs, '--out', output], work, env)
        same_csv(output, archive / summary)
    run([py, 'evaluate_v83b1_gate.py', '--summary', work / 'paired_pilot_summary.csv',
         '--runs', *sorted((ROOT / 'results_v83b1/repetitions').glob('run_*.csv')),
         '--out', work / 'decision.csv', '--report', work / 'decision.md'], work, env)
    same_csv(work / 'decision.csv', ROOT / 'results_v83b1/decision_matrix_v83b2.csv')
    # Native self-checks run even without the optional full ten-process exercise.
    run([work / 'lookup_benchmark_v8', '--out', work / 'v8_selfcheck.csv'], work, env)
    run([work / 'lookup_ablation_v81', '--validate', '--out', work / 'v81_selfcheck.csv'], work, env)
    run([work / 'dynamic_benchmark_v83b1', '--validate', '--out', work / 'dynamic_selfcheck.csv'], work, env)
    if native:
        for binary, analyzer, count in zip(BINARIES,
                ('bap_v8_repeatability_gate.py', 'analyze_v81.py', 'analyze_v83b1.py'), (540, 540, 288)):
            output_dir = work / (binary + '_runs')
            output_dir.mkdir()
            inputs = []
            for i in range(1, 11):
                out = output_dir / f'run_{i}.csv'
                run([work / binary, '--out', out], work, env)
                require(len(rows(out)) == count, f'Wrong native row count: {out}')
                inputs.append(out)
            run([py, analyzer, *inputs, '--out', output_dir / 'summary.csv'], work, env)
    integrity()
    print('PASS: artifact validation complete; new timings are smoke evidence only', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--integrity-only', action='store_true')
    args = parser.parse_args()
    require(not sys.flags.optimize, 'Do not use python -O')
    if args.integrity_only:
        integrity()
        return
    with tempfile.TemporaryDirectory(prefix='bap-validation-') as directory:
        try:
            validate(Path(directory), args.native)
        finally:
            integrity()


if __name__ == '__main__':
    main()
