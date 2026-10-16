# Cleanup validation report

Validation date: 2026-10-16. Base revision: `a56b720`. Executed locally under Ubuntu 24.04 / WSL, Python 3.12.3 and GCC 13.3.0. Full command: `python3 scripts/validate_artifact.py --native`. See [execution log](../audit/validation.log).

| Check | Result |
|---|---|
| Frozen-file integrity | PASS: 313 non-packaging files match pre-cleanup SHA-256; moved documents checked at new paths |
| CSV structure and evidence flags | PASS: all 259 archived CSVs nonempty, rectangular, unique headers, finite numeric values, zero reported semantic mismatches, expected oracle/hardware flags |
| Python syntax | PASS: all 16 historical Python entry points and new validator parsed |
| Early simulations | PASS: v0–v2 default exhaustive lookup checks through size 4096, including capped v2; all produced CSV values match archives |
| v3 deterministic lookup | PASS: XOR/MSB checks through size 4096; randomized workloads not rerun |
| Shell syntax | PASS: all four historical drivers with `bash -n` |
| Native compilation | PASS: all three C++ sources, `-O3 -std=c++20 -Wall -Wextra -pedantic`; no compiler diagnostics |
| v5 / v6 / v7 | PASS: built-in validations; 72 / 45 / 540 reproduced rows exactly equal archived parsed CSVs |
| v8.2 structural audit | PASS: 10000 structural sizes and 633 PFN/permission layouts; exact archived CSV equality |
| v8.3A / v8.3B-0 | PASS: 96 scenarios / 576 model rows each; exact archived CSV equality; differential final-state hashes, records, exceptions, compactions and mismatch fields agree |
| Large-region checks | PASS: six rows each for A and B-0; exact archived CSV equality |
| Archived ten-run analyses | PASS: v8 (540 rows/run; 540 summary rows), v8.1 (540; 720), B-1 (288; 192); summaries exactly reproduced as parsed CSV |
| v8.3B-2 decision | PASS: 16-row matrix reproduced; 0/16 both-baseline positive-CI settings and 0/16 joint latency-threshold settings |
| Native self-checks | PASS: v8 full address/permission verification; v8.1 sizes 1–1030; B-1 six-model oracle over four sizes × four layouts |
| Fresh independent native runs | PASS: ten processes for each of three programs, original default configurations; 13680 total rows, all analyzers passed controls/checksums |
| Final integrity | PASS after validation; no archived measurement or manuscript was overwritten |
| Validator failure tests | PASS: three unit tests cover malformed/empty CSVs, duplicate headers, nonfinite values, invalid evidence flags, changed values and line-ending handling |
| Clean-checkout portability | PASS: exported original Git blobs validate (223 LF/CRLF variants); deliberately corrupted scientific CSV rejected by integrity gate |
| Navigation | PASS: local Markdown links resolve; historical inline commands are documented as root-relative |

The 13680 new rows comprise 5400 v8, 5400 v8.1 and 2880 B-1 rows, excluding separate self-check outputs. Temporary native timings differ from archives as expected and were discarded; their log is smoke evidence only. CSV equality uses parsed fields to allow platform line endings; archived preservation separately requires byte-exact SHA-256.

Early checks used the pre-existing virtual environment with Matplotlib 3.11.0. The initial standalone v3 import used system Python and failed because Matplotlib was absent there; it was rerun successfully with `.venv/bin/python`. See [early check log](../audit/early-validation.log) and [successful v3 log](../audit/v3-validation.log). No package installation or historical dependency inference was needed.

No v3/v4 historical randomized workloads were regenerated: the missing Python hash seed prevents a defensible exact-reproduction claim. Figure rendering was not rerun. This validation does not establish general speedup, statistical significance, hardware/TLB performance, formal verification of every possible state, or journal readiness.
