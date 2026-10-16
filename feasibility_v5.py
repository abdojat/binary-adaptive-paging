#!/usr/bin/env python3
"""BAP v5 virtual mapping feasibility audit (stdlib only).

This is a structural feasibility test, NOT a physical-memory allocator, TLB
simulator, hardware implementation, or proof of translation performance.

The original BAP virtual chunks are checked against two explicit profiles:
  ideal_powers_of_two: hypothetical hardware allowing each power of 2 up to cap
  x86_4k_2m: standard x86 leaf page sizes of 4 KiB and 2 MiB only (cap=512)

Comparison paths:
  1) BAP original: region-relative, unconstrained virtual starts.
  2) Split only: preserve original BAP block boundaries; subdivide as needed.
  3) Retile: allow new chunk boundaries and select an aligned dyadic cover.

Physical contiguity, physical alignment, permissions and metadata costs
are NOT evaluated; best-case feasible counts are lower bounds, not measurements.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Block:
    start_page: int
    size_pages: int

    @property
    def end_page(self) -> int:
        return self.start_page + self.size_pages


def _require_power_two(n: int) -> None:
    if n <= 0 or n & (n - 1):
        raise ValueError(f"Expected a positive power of two; got {n}")


def bap_blocks(start_page: int, size_pages: int, cap_pages: int) -> list[Block]:
    """Replica of the BAP limited region-relative decomposition from v3."""
    if start_page < 0 or size_pages <= 0:
        raise ValueError("start_page must be >= 0 and size_pages must be > 0")
    _require_power_two(cap_pages)
    out: list[Block] = []
    cursor = start_page
    for bit in range(size_pages.bit_length() - 1, -1, -1):
        if not (size_pages & (1 << bit)):
            continue
        remaining = 1 << bit
        while remaining:
            chunk = min(cap_pages, remaining)
            out.append(Block(cursor, chunk))
            cursor += chunk
            remaining -= chunk
    verify_cover(out, start_page, size_pages)
    return out


def allowed_sizes(profile: str, cap_pages: int) -> tuple[int, ...]:
    _require_power_two(cap_pages)
    if profile == "ideal_powers_of_two":
        return tuple(1 << k for k in range(cap_pages.bit_length() - 1, -1, -1))
    if profile == "x86_4k_2m":
        if cap_pages != 512:
            raise ValueError("x86_4k_2m profile requires a 512-page cap (2 MiB / 4 KiB)")
        return (512, 1)
    raise ValueError(f"Unknown profile: {profile}")


def virtual_eligible(block: Block, sizes: tuple[int, ...]) -> bool:
    """Necessary *virtual* prerequisites, NOT full hardware support."""
    return block.size_pages in sizes and block.start_page % block.size_pages == 0


def aligned_cover(start_page: int, size_pages: int, sizes: tuple[int, ...]) -> list[Block]:
    """Greedy legal cover on absolute virtual addresses; ideal physical backing."""
    if size_pages <= 0 or not sizes or sizes[-1] != 1:
        raise ValueError("Positive size and allowed base-page size 1 are required")
    end = start_page + size_pages
    cursor = start_page
    blocks: list[Block] = []
    while cursor < end:
        candidate = next((p for p in sizes if p <= end - cursor and cursor % p == 0), None)
        if candidate is None:
            raise AssertionError("No feasible virtual mapping (base-page should always work)")
        blocks.append(Block(cursor, candidate))
        cursor += candidate
    verify_cover(blocks, start_page, size_pages)
    if not all(virtual_eligible(b, sizes) for b in blocks):
        raise AssertionError("Aligned cover produced illegal mapping")
    return blocks


def split_only(blocks: list[Block], sizes: tuple[int, ...]) -> list[Block]:
    """Keep every BAP original block boundary; split within each block only."""
    out: list[Block] = []
    for block in blocks:
        out.extend(aligned_cover(block.start_page, block.size_pages, sizes))
    return out


def verify_cover(blocks: Iterable[Block], start_page: int, size_pages: int) -> None:
    cursor = start_page
    for block in blocks:
        if block.size_pages <= 0 or block.start_page != cursor:
            raise AssertionError(f"Coverage gap/overlap at {cursor}: {block}")
        cursor = block.end_page
    if cursor != start_page + size_pages:
        raise AssertionError(f"Coverage ended at {cursor}, expected {start_page + size_pages}")


def bap_lookup(size_pages: int, offset_pages: int, cap_pages: int) -> Block:
    """Physical-size-capped BAP *virtual* block lookup using XOR/MSB."""
    if size_pages <= 0 or not 0 <= offset_pages < size_pages:
        raise ValueError("Offset must lie inside region")
    _require_power_two(cap_pages)
    k = (offset_pages ^ size_pages).bit_length() - 1
    logical_start = size_pages & ~((1 << (k + 1)) - 1)
    logical_size = 1 << k
    if logical_size <= cap_pages:
        return Block(logical_start, logical_size)
    relative = offset_pages - logical_start
    subindex = relative // cap_pages
    return Block(logical_start + subindex * cap_pages, cap_pages)


def audit(start_page: int, size_pages: int, profile: str, cap_pages: int) -> dict[str, object]:
    sizes = allowed_sizes(profile, cap_pages)
    original = bap_blocks(start_page, size_pages, cap_pages)
    only_split = split_only(original, sizes)
    retiled = aligned_cover(start_page, size_pages, sizes)
    verify_cover(only_split, start_page, size_pages)
    illegal = [b for b in original if not virtual_eligible(b, sizes)]
    return {
        "profile": profile,
        "start_page": start_page,
        "region_size_pages": size_pages,
        "max_chunk_pages": cap_pages,
        "bap_original_chunks": len(original),
        "bap_virtually_eligible_chunks": len(original) - len(illegal),
        "bap_virtually_ineligible_chunks": len(illegal),
        "split_preserve_bap_boundaries_entries": len(only_split),
        "retile_optimal_aligned_entries": len(retiled),
        "physical_contiguity_checked": "NO",
        "tlb_performance_measured": "NO",
    }


def self_test() -> None:
    for region_size in range(1, 257):
        chunks = bap_blocks(0, region_size, 32)
        for offset in range(region_size):
            found = bap_lookup(region_size, offset, 32)
            actual = next(c for c in chunks if c.start_page <= offset < c.end_page)
            if found != actual:
                raise AssertionError(f"BAP lookup mismatch at S={region_size}, a={offset}")
    for region_start in (0, 1, 7, 13, 64, 255):
        for region_size in (13, 1000, 4096, 10000):
            for profile in ("ideal_powers_of_two", "x86_4k_2m"):
                sizes = allowed_sizes(profile, 512)
                b = bap_blocks(region_start, region_size, 512)
                s = split_only(b, sizes)
                r = aligned_cover(region_start, region_size, sizes)
                verify_cover(s, region_start, region_size)
                verify_cover(r, region_start, region_size)
                assert all(virtual_eligible(x, sizes) for x in s + r)
                assert len(s) >= len(r), "Splitting only should not beat retiling"
    aligned = audit(0, 10000, "ideal_powers_of_two", 512)
    assert aligned["bap_original_chunks"] == 21
    assert aligned["retile_optimal_aligned_entries"] == 21
    misaligned = audit(1, 10000, "ideal_powers_of_two", 512)
    assert misaligned["bap_original_chunks"] == 21
    assert misaligned["bap_virtually_ineligible_chunks"] == 21
    assert misaligned["split_preserve_bap_boundaries_entries"] == 204
    assert misaligned["retile_optimal_aligned_entries"] == 30
    conventional = audit(1, 10000, "x86_4k_2m", 512)
    assert conventional["retile_optimal_aligned_entries"] == 802
    print("PASS: XOR/MSB lookup, exact coverage, legal alignment, and reference cases")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("results_v5/feasibility_summary_v5.csv"))
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        self_test()
    cap_pages = 512  # same cap as simulator_v3 and the existing paper
    fieldnames = list(audit(0, 13, "ideal_powers_of_two", cap_pages))
    rows = [
        audit(start, size, profile, cap_pages)
        for profile in ("ideal_powers_of_two", "x86_4k_2m")
        for size in (13, 19, 513, 1000, 4096, 10000)
        for start in (0, 1, 7, 13, 64, 255)
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} audit rows: {args.out}")
    for profile in ("ideal_powers_of_two", "x86_4k_2m"):
        for start in (0, 1, 7, 64):
            d = audit(start, 10000, profile, cap_pages)
            print(f"{profile:21} start={start:3} "
                  f"BAP={d['bap_original_chunks']:3} legal={d['bap_virtually_eligible_chunks']:3} "
                  f"split-only={d['split_preserve_bap_boundaries_entries']:5} "
                  f"retile={d['retile_optimal_aligned_entries']:5}")


if __name__ == "__main__":
    main()
