# Reproducibility guide

## Evidence identity

Cleanup starts from `a56b720` on the locally available Git history (18 commits). Origin is `https://github.com/abdojat/binary-adaptive-paging.git`. No remote synchronization, push, merge or history rewriting is part of this audit. The [before manifest](../audit/before.sha256.json) hashes the bytes of all 317 tracked working-tree files before edits, including sources, manuscripts, CSVs, figures, environments and binaries. The [after manifest](../audit/after.sha256.json) covers the same files at their final paths. Packaging exceptions are documented in the changelog. Hashes establish byte identity, not scientific validity or provenance of the original measurements.

## Environment

Linux/Ubuntu WSL is the validated path: Python 3.10+ and GCC with C++20, plus Bash. v1–v4 require Matplotlib; other historical Python programs and the new validator are standard-library programs. Install [requirements.txt](../requirements.txt) in a virtual environment for early simulations. It is deliberately not a fabricated historical dependency lock. Record `python3 --version`, `g++ --version`, `python3 -m pip freeze`, `uname -a`, `lscpu`, exact command lines and Git revision for future runs. The archived v8.1/v8.3B-1 environment files report GCC 13.3, Python 3.12.3, i5-12500H and Microsoft hypervisor. These logs do not control host load, power/frequency policy or scheduler effects.

## Safe automated validation

From the root:

```bash
python3 scripts/validate_artifact.py --integrity-only
python3 scripts/validate_artifact.py
python3 scripts/validate_artifact.py --native
```

The first command needs only Python. The others require Bash and g++. They fail on integrity discrepancies, malformed/nonfinite CSV data, failed subprocesses, deterministic CSV differences or inconsistent comparative summaries. They run Python syntax checks, Bash parsing, all three native compilations, v5/v6/v7/v8.2 validations, full v8.3A/B-0 differential scenarios and large-region checks, archived ten-run analyses and the v8.3B-2 decision gate, then native self-checks. `--native` adds ten separate invocations **per binary**, retaining default queries/repeats/updates and all built-in scenario matrices. It does not change source defaults or historical measurements. Temporary outputs are removed on exit; redirect stdout/stderr to a new external log if required. A final integrity check also runs on failure. Do not use `python -O` (historical programs rely on assertions).

For clean-clone portability, integrity accepts an exact SHA-256 match to either the recorded original checkout bytes or original Git-blob bytes, reporting the latter separately. The 223 observed differences were verified to be CRLF/LF only. No generic normalization or tolerance for other changes is applied. Run validator corruption tests with `python3 -m unittest discover -s tests -v`.

Archived native run filenames and consistency checks cannot alone prove historical process independence; that provenance comes from the drivers/environment records. The new native mode actually launches independent subprocesses. Seeds are averaged within process; the analyzers use paired differences between process runs. Their bootstrap intervals are exploratory and not adjusted for multiple comparisons. New timing values are expected to differ; they must not replace the frozen decision or be interpreted as a new speedup finding.

## Manual historical runs without overwriting evidence

Use a disposable copy for commands with hardcoded relative outputs, especially the original shell drivers (they change into their own directory). This example copies only the original source entry points:

```bash
scratch=$(mktemp -d)
cp ./*.py ./*.cpp ./*.sh "$scratch/"
cd "$scratch"
python3 simulator_v0.py --validate
python3 simulator_v1.py --validate --no-plots
python3 simulator_v2.py --validate --no-plots
# v3/v4 are new realizations: see hash limitation below
python3 simulator_v3_workloads.py --validate --no-plots
python3 sensitivity_v4.py
python3 feasibility_v5.py --validate
python3 translation_v6.py --validate
python3 metadata_lookup_v7.py --validate
python3 formal_audit_v82.py
bash run_v83a.sh
bash run_v83b0.sh
bash run_v81.sh
bash run_v83b1.sh
```

These commands can take appreciable time and generate fresh results in the scratch tree. The v8 executable is built with `g++ -O3 -std=c++20 -Wall -Wextra -pedantic lookup_benchmark_v8.cpp -o lookup_benchmark_v8`; create `results_v8/` before running its default command. Use `--out` to redirect native outputs or v5+ Python outputs. Use `--output-dir` for v0–v4. CLI `--help` is available for Python programs; native parsers expose their accepted flags in their source. Keep original seeds, thresholds and scenario settings when comparing versions.

## Known reproducibility gaps

`simulator_v3_workloads.py` seeds the PRNG with `seed + 1000003*size + 9176*start + hash(workload_name)%10000`. Python string hashes are randomized between processes unless `PYTHONHASHSEED` is set before interpreter startup. Thus `--seed` alone does not reproduce v3 workloads. v4 imports and calls that generator, so its seed sweeps inherit the issue. The archive does not record the original hash secret; byte-for-byte reconstruction cannot be promised. Setting a hash seed now creates a documented future realization, not the historical one. No hash function, seed or archived result was changed during cleanup.

v4 `_tmp_runs` contains 200 committed intermediate CSVs and must not be deleted as disposable scratch. Timing checksums are program checksums (not SHA-256); matching them supports trace/result consistency, not cryptographic identity or hardware correctness. Earlier package/environment versions, complete host controls and figure-rendering environments are not locked. Figures and manuscripts are preserved rather than rerendered. Finite differential checks do not prove all possible update sequences; the structural theorem also needs independent human review of its assumptions.
