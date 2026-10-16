# What to do next — BAP v8.3

1. Read `BAP_v83_Dynamic_Mapping_Design_Gate.docx` (English, 4 pages).
2. Add `v8_3_design_gate.md` to the existing GitHub repository under `docs/v8_3_design_gate.md`.
3. Do **not** alter the main Word/PDF paper or rerun v8.1/v8.2 benchmarks at this stage.
4. After the design gate is fixed, the following implementation stage is a small deterministic correctness model for map, unmap, mprotect-style permission changes and one-page COW-like remaps with identical baseline semantics.
5. Compare BAP against fixed-grid and generic dynamic ranges; include the same lazy-overlay optimization in each baseline.

The protocol makes no claim that the candidate will outperform existing mapping methods.
