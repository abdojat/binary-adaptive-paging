#!/usr/bin/env python3
"""BAP v7: explicit metadata-budget and instrumented search-work gate.

Uses the *software models* from translation_v6.py (and feasibility_v5.py).
Every representation receives identical VA->PFN and permission semantics.
This is NOT a TLB or page-walker benchmark, a measured CPU latency experiment,
or a verified in-memory footprint of a kernel implementation.

Assumed compact hypothetical layout, with 8-byte-aligned logical records:
  common region descriptor: 32 bytes/model/region (VPN base, length, root, flags)
  BAP parent-directory slot: 8 bytes/parent (child start index + child count)
  contiguous/permissible run record: 24 bytes for ALL models
      (absolute start VPN uint64, length uint32, start PFN uint64, flags uint8,
       reserved bytes for alignment). Supports page runs up to 2**32-1 pages.
No Python object overhead, memory allocator overhead, page-table-tree bytes,
TLB tags, caches, region-discovery index, or dynamic update costs are counted.

A BAP parent is located by region-relative bit arithmetic and indexed directly
into an array, assuming a BAP-specific arithmetic index and directory layout.
Search cost is counted as key comparisons (not cycles). BAP must ALSO pay for
bit arithmetic and a parent-directory access. Generic range uses one global
binary search; the BAP model uses one binary search *within* a parent.
"""
from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Sequence

from feasibility_v5 import bap_blocks, bap_lookup
from translation_v6 import (BASE_PAGE_BYTES, HUGE_PAGE_PAGES, Record, Region,
                            TranslationModel, build_bap, build_range,
                            sample_region)

REGION_DESCRIPTOR_BYTES = 32
RANGE_RECORD_BYTES = 24
BAP_PARENT_SLOT_BYTES = 8
WORKLOADS = ("uniform_random", "sequential", "hot_cold", "boundary_stress")
PHYSICAL_LAYOUTS = ("contiguous", "contiguous_phase_matched", "fragmented_32",
                    "mixed_permissions", "fragmented_permissions")


def bap_parent_index(size_pages: int, offset: int, cap_pages: int = HUGE_PAGE_PAGES) -> int:
    """Arithmetic rank in capped descending-binary BAP parent array.

    The full-sized chunks are a prefix of floor(S/cap) cap-sized parents.
    The remainder is decomposed by its set bits in descending order.
    """
    if cap_pages <= 0 or cap_pages & (cap_pages-1):
        raise ValueError("cap must be a power of two")
    if not 0 <= offset < size_pages:
        raise ValueError("offset outside region")
    full = size_pages // cap_pages
    prefix = full * cap_pages
    if offset < prefix:
        return offset // cap_pages
    rem = size_pages - prefix
    k = ((offset - prefix) ^ rem).bit_length() - 1
    return full + (rem >> (k+1)).bit_count()


def search_counted(records: Sequence[Record], vpn: int) -> tuple[Record, int]:
    """Rightmost record start <= VPN; return comparisons made against keys."""
    lo, hi, compares = 0, len(records), 0
    while lo < hi:
        mid = (lo + hi) // 2
        compares += 1
        if records[mid].start_vpn <= vpn:
            lo = mid + 1
        else:
            hi = mid
    i = lo - 1
    if i < 0 or vpn >= records[i].end_vpn:
        raise AssertionError("Missing record")
    return records[i], compares


def metadata_budget(model: TranslationModel) -> int:
    if model.parent_children is None:
        return REGION_DESCRIPTOR_BYTES + RANGE_RECORD_BYTES*len(model.records)
    return (REGION_DESCRIPTOR_BYTES + RANGE_RECORD_BYTES*len(model.records)
            + BAP_PARENT_SLOT_BYTES*len(model.parent_children))


def _check_result(record: Record, region: Region, vpn: int) -> None:
    i = vpn - region.start_vpn
    if record.start_pfn + vpn - record.start_vpn != region.physical_frames[i]:
        raise AssertionError("Physical translation mismatch")
    if record.permissions != region.permissions[i]:
        raise AssertionError("Permission mismatch")
    # Byte-address semantics sampled at an interior offset, too.
    byte_offset = 17
    actual = (record.start_pfn + vpn - record.start_vpn)*BASE_PAGE_BYTES + byte_offset
    expected = region.physical_frames[i]*BASE_PAGE_BYTES + byte_offset
    if actual != expected:
        raise AssertionError("Byte-level translation mismatch")


def bap_search(model: TranslationModel, vpn: int, starts: list[int]) -> int:
    if model.parent_children is None:
        raise ValueError("Not BAP")
    a = vpn - model.region.start_vpn
    part = bap_lookup(model.region.size_pages, a, HUGE_PAGE_PAGES)
    index = bap_parent_index(model.region.size_pages, a, HUGE_PAGE_PAGES)
    if starts[index] != model.region.start_vpn + part.start_page:
        raise AssertionError("BAP arithmetic-index mismatch")
    rec, ncomp = search_counted(model.parent_children[starts[index]], vpn)
    _check_result(rec, model.region, vpn)
    return ncomp


def generate_trace(size: int, pattern: str, seed: int, n: int,
                   boundaries: Sequence[int]) -> list[int]:
    rng = random.Random(seed)
    if pattern == "uniform_random":
        return [rng.randrange(size) for _ in range(n)]
    if pattern == "sequential":
        return [i % size for i in range(n)]
    if pattern == "hot_cold":
        hot_start = size // 3
        hot_size = max(1, size // 20)
        return [(hot_start + rng.randrange(min(hot_size, size-hot_start)))
                if rng.random() < .9 else rng.randrange(size) for _ in range(n)]
    if pattern == "boundary_stress":
        coords = set()
        for b in boundaries:
            for delta in (-1, 0, 1):
                if 0 <= b + delta < size:
                    coords.add(b + delta)
        samples = sorted(coords) or [0]
        return [samples[i % len(samples)] for i in range(n)]
    raise ValueError(pattern)


def _metric_distribution(xs: list[int]) -> tuple[str, int, int]:
    vals = sorted(xs)
    p95 = vals[(95*len(vals) - 1)//100]
    return f"{mean(xs):.4f}", p95, max(xs)


def measure_case(start: int, size: int, layout: str, pattern: str,
                 seed: int, num_accesses: int) -> dict[str, object]:
    region = sample_region(start, size, layout)
    bap = build_bap(region)
    cap = build_range(region, HUGE_PAGE_PAGES)
    unlimited = build_range(region, None)
    starts = [b.start_page for b in bap_blocks(start, size, HUGE_PAGE_PAGES)]
    if starts != sorted(bap.parent_children or {}):
        raise AssertionError("Unstable BAP parent order")
    boundaries = [b-start for b in starts]
    boundaries.extend(r.start_vpn-start for r in cap.records)
    offsets = generate_trace(size, pattern, seed, num_accesses, boundaries)
    bap_cmp, cap_cmp, unlimited_cmp = [], [], []
    for offset in offsets:
        vpn = start + offset
        bap_cmp.append(bap_search(bap, vpn, starts))
        for model, counts in ((cap, cap_cmp), (unlimited, unlimited_cmp)):
            rec, c = search_counted(model.records, vpn)
            _check_result(rec, region, vpn)
            counts.append(c)
    bavg, bp95, bmax = _metric_distribution(bap_cmp)
    cavg, cp95, cmax = _metric_distribution(cap_cmp)
    uavg, up95, umax = _metric_distribution(unlimited_cmp)
    # Each model gets exactly one common region descriptor and the same run-record layout.
    bbytes, cbytes, ubytes = (metadata_budget(m) for m in (bap, cap, unlimited))
    return {
        "start_vpn": start, "region_size_pages": size, "physical_layout": layout,
        "pattern": pattern, "seed": seed, "n_accesses": num_accesses,
        "bap_parent_count": len(starts), "bap_run_records": len(bap.records),
        "range_cap512_records": len(cap.records),
        "range_unbounded_records": len(unlimited.records),
        "bap_metadata_bytes": bbytes, "range_cap512_metadata_bytes": cbytes,
        "range_unbounded_metadata_bytes": ubytes,
        "bap_minus_range_cap512_bytes": bbytes - cbytes,
        "bap_minus_range_unbounded_bytes": bbytes - ubytes,
        "bap_avg_child_key_comparisons": bavg,
        "range_cap512_avg_key_comparisons": cavg,
        "range_unbounded_avg_key_comparisons": uavg,
        "bap_p95_child_key_comparisons": bp95,
        "range_cap512_p95_key_comparisons": cp95,
        "range_unbounded_p95_key_comparisons": up95,
        "bap_max_child_key_comparisons": bmax,
        "range_cap512_max_key_comparisons": cmax,
        "range_unbounded_max_key_comparisons": umax,
        "bap_extra_lookup_stage": "XOR/MSB+rank+parent-directory-read",
        "region_discovery_modeled": "NO", "memory_bytes_measured": "NO",
        "translation_latency_measured": "NO", "tlb_misses_measured": "NO",
    }


def self_test() -> None:
    for size in range(1, 1100):
        for start in (0, 1, 7):
            bs = bap_blocks(start, size, HUGE_PAGE_PAGES)
            for offset in range(size):
                idx = bap_parent_index(size, offset)
                if idx < 0 or idx >= len(bs):
                    raise AssertionError("Bad BAP index")
                found = bap_lookup(size, offset, HUGE_PAGE_PAGES)
                if bs[idx].start_page != start+found.start_page or bs[idx].size_pages != found.size_pages:
                    raise AssertionError(f"BAP index wrong S={size} a={offset}")
    for layout in PHYSICAL_LAYOUTS:
        for start in (0, 1, 7):
            row = measure_case(start, 513, layout, "boundary_stress", 17, 100)
            assert row["bap_metadata_bytes"] >= REGION_DESCRIPTOR_BYTES
            assert row["bap_avg_child_key_comparisons"]
    assert measure_case(1, 10000, "contiguous", "uniform_random", 1, 100)["bap_metadata_bytes"] == 704
    assert measure_case(1, 10000, "contiguous", "uniform_random", 1, 100)["range_cap512_metadata_bytes"] == 512
    assert measure_case(1, 10000, "contiguous", "uniform_random", 1, 100)["range_unbounded_metadata_bytes"] == 56
    print("PASS: BAP direct arithmetic index, reference translation, metadata budgets and lookup traces")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--accesses", type=int, default=1024)
    ap.add_argument("--seeds", type=str, default="1,2,3")
    ap.add_argument("--out", type=Path, default=Path("results_v7/metadata_lookup_v7.csv"))
    args = ap.parse_args()
    if args.accesses <= 0:
        ap.error("--accesses must be positive")
    seeds = [int(x.strip()) for x in args.seeds.split(",")]
    if not seeds:
        ap.error("at least one seed required")
    if args.validate:
        self_test()
    rows = [measure_case(start,size,layout,pattern,seed,args.accesses)
            for size in (1000,4096,10000)
            for start in (0,1,7)
            for layout in PHYSICAL_LAYOUTS
            for pattern in WORKLOADS
            for seed in seeds]
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Generated {len(rows)} scenario/trace results at {args.out}")
    for layout in PHYSICAL_LAYOUTS:
        row=next(r for r in rows if r["start_vpn"]==1 and r["region_size_pages"]==10000
                 and r["physical_layout"]==layout and r["pattern"]=="uniform_random" and r["seed"]==seeds[0])
        print(f"{layout:25} BAP={row['bap_metadata_bytes']:6} B  cap={row['range_cap512_metadata_bytes']:6} B  unbounded={row['range_unbounded_metadata_bytes']:6} B"
              f"   child_cmp={row['bap_avg_child_key_comparisons']} global_cap_cmp={row['range_cap512_avg_key_comparisons']}")

if __name__ == "__main__":
    main()
