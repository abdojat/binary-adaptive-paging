#!/usr/bin/env python3
"""Verify incremental v8.3B-0 output matches frozen v8.3A cases exactly.

Checks the scenario key and four independently generated observable metrics.
Does not claim equal latency, structural complexity, or storage footprint.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path


def read(path: Path, renamed: bool) -> dict[tuple[str, ...], dict[str,str]]:
    with path.open(newline="",encoding="utf-8-sig") as f:
        rows=list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"Empty file: {path}")
    out={}
    for r in rows:
        key=(r["region_size_pages"] if renamed else r["size_pages"],r["start_vpn"],
             r["physical_layout"] if renamed else r["layout"],r["threshold_fraction"],
             r["seed"],r["updates"],r["model"])
        if key in out:
            raise ValueError(f"Duplicate case in {path}: {key}")
        out[key]=r
    return out


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--old",type=Path,default=Path("results_v83a/dynamic_correctness_v83a.csv"))
    p.add_argument("--new",type=Path,default=Path("results_v83b0/incremental_semantics_v83b0.csv"))
    args=p.parse_args()
    before=read(args.old,False);after=read(args.new,True)
    if set(before)!=set(after):
        raise AssertionError(f"Changed scenario keys: missing {len(set(before)-set(after))}, new {len(set(after)-set(before))}")
    pairs=[("final_oracle_sha256","final_state_sha256"),
           ("final_base_records","base_records"),
           ("final_overlay_exceptions","pending_exceptions"),
           ("compactions","compactions"),
           ("semantic_mismatches","semantic_mismatches")]
    for k,b in before.items():
        n=after[k]
        for c_old,c_new in pairs:
            if b[c_old]!=n[c_new]:
                raise AssertionError(f"Mismatch {k}: {c_old}={b[c_old]} vs {c_new}={n[c_new]}")
    print(f"PASS: {len(before)} identical scenario/model states; hashes, record counts, exceptions, compactions, mismatches match v8.3A")


if __name__=="__main__":
    main()
