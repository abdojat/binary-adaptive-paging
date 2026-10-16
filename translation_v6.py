#!/usr/bin/env python3
"""BAP v6: end-to-end *software-model* translation correctness gate.

Imports the existing feasibility_v5.py from this repository.
This is not an x86 BAP implementation, a TLB, or a performance benchmark.

Three competing representations for identical VA -> PFN and access semantics:
  (1) BAP: XOR/MSB chooses logical region-relative parent; extra metadata
      segments within parents account for non-contiguous physical pages and
      protection changes. This assumes a proposed region-aware translation
      mechanism, NOT supported as large pages by stock x86.
  (2) Generic contiguous runs: arbitrary virtual starts, linearly contiguous
      physical frames, and permission-uniform ranges (capped or unbounded).
      This is also a *representation model*, NOT stock x86 leaf hardware.
  (3) x86-like 4 KiB / 2 MiB page leaves: 2 MiB virtual AND physical
      alignment, full 512-frame contiguity, uniform permissions.

All mapping counts are structural. Counts across representations are NOT
interchangeable with TLB entry counts, latency or memory-overhead bytes.
"""
from __future__ import annotations

import argparse
import csv
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from feasibility_v5 import bap_blocks, bap_lookup

BASE_PAGE_BYTES = 4096
HUGE_PAGE_PAGES = 512


class UnmappedAddress(ValueError):
    pass


class ProtectionFault(PermissionError):
    pass


@dataclass(frozen=True)
class Region:
    start_vpn: int
    physical_frames: tuple[int, ...]
    permissions: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.start_vpn < 0 or not self.physical_frames:
            raise ValueError("Region start must be nonnegative and region nonempty")
        if len(self.physical_frames) != len(self.permissions):
            raise ValueError("Every virtual page needs a frame and permission")
        if len(set(self.physical_frames)) != len(self.physical_frames):
            raise ValueError("This experiment assumes no overlapping physical frames")
        if any(p < 0 for p in self.physical_frames):
            raise ValueError("Negative physical frame")
        if any(not x or any(c not in "rwx" for c in x) for x in self.permissions):
            raise ValueError("Only combinations of r/w/x permissions accepted")

    @property
    def size_pages(self) -> int:
        return len(self.physical_frames)

    @property
    def end_vpn(self) -> int:
        return self.start_vpn + self.size_pages


@dataclass(frozen=True)
class Record:
    start_vpn: int
    size_pages: int
    start_pfn: int
    permissions: str

    @property
    def end_vpn(self) -> int:
        return self.start_vpn + self.size_pages


@dataclass
class TranslationModel:
    name: str
    region: Region
    records: list[Record]
    parent_children: dict[int, list[Record]] | None = None
    huge_pages: int = 0

    def translate(self, virtual_address_bytes: int, access: str) -> int:
        if access not in {"r", "w", "x"}:
            raise ValueError("Access is r, w or x")
        vpn, byte_offset = divmod(virtual_address_bytes, BASE_PAGE_BYTES)
        if not self.region.start_vpn <= vpn < self.region.end_vpn:
            raise UnmappedAddress(f"VPN {vpn} outside region")

        if self.parent_children is not None:
            # XOR/MSB identifies the original BAP parent, not its physical frame.
            relative_block = bap_lookup(self.region.size_pages, vpn - self.region.start_vpn,
                                        HUGE_PAGE_PAGES)
            parent_start = self.region.start_vpn + relative_block.start_page
            children = self.parent_children[parent_start]
            record = search_record(children, vpn)
        else:
            record = search_record(self.records, vpn)
        if access not in record.permissions:
            raise ProtectionFault(f"Permission denied: access={access}, VPN={vpn}")
        pfn = record.start_pfn + vpn - record.start_vpn
        return pfn * BASE_PAGE_BYTES + byte_offset


def search_record(records: Sequence[Record], vpn: int) -> Record:
    i = bisect_right(records, vpn, key=lambda r: r.start_vpn) - 1
    if i < 0 or vpn >= records[i].end_vpn:
        raise AssertionError(f"Metadata does not cover VPN {vpn}")
    return records[i]


def split_into_linear_runs(region: Region, offset: int, length: int,
                           cap_pages: int | None = None) -> list[Record]:
    """Cut by physical discontinuity, permission changes and optional cap."""
    if cap_pages is not None and cap_pages < 1:
        raise ValueError("cap must be >= 1")
    out: list[Record] = []
    cursor = offset
    stop = offset + length
    while cursor < stop:
        end = cursor + 1
        while end < stop and (cap_pages is None or end - cursor < cap_pages):
            if region.permissions[end] != region.permissions[cursor]:
                break
            if region.physical_frames[end] != region.physical_frames[end - 1] + 1:
                break
            end += 1
        out.append(Record(region.start_vpn + cursor, end - cursor,
                          region.physical_frames[cursor], region.permissions[cursor]))
        cursor = end
    return out


def build_bap(region: Region) -> TranslationModel:
    parents = bap_blocks(region.start_vpn, region.size_pages, HUGE_PAGE_PAGES)
    children: dict[int, list[Record]] = {}
    records: list[Record] = []
    for block in parents:
        within = split_into_linear_runs(region, block.start_page - region.start_vpn,
                                        block.size_pages)
        children[block.start_page] = within
        records.extend(within)
    check_cover(region, records)
    return TranslationModel("bap_region_relative", region, records, children)


def build_range(region: Region, cap_pages: int | None) -> TranslationModel:
    rows = split_into_linear_runs(region, 0, region.size_pages, cap_pages)
    check_cover(region, rows)
    name = "generic_range_unbounded" if cap_pages is None else "generic_range_cap512"
    return TranslationModel(name, region, rows)


def build_x86(region: Region) -> TranslationModel:
    rows: list[Record] = []
    i = 0
    huge = 0
    while i < region.size_pages:
        v = region.start_vpn + i
        p = region.physical_frames[i]
        good = (v % HUGE_PAGE_PAGES == 0 and p % HUGE_PAGE_PAGES == 0
                and region.size_pages - i >= HUGE_PAGE_PAGES)
        if good:
            perm = region.permissions[i]
            for d in range(1, HUGE_PAGE_PAGES):
                if (region.physical_frames[i+d] != p + d or
                        region.permissions[i+d] != perm):
                    good = False
                    break
        size = HUGE_PAGE_PAGES if good else 1
        rows.append(Record(v, size, p, region.permissions[i]))
        if good:
            huge += 1
        i += size
    check_cover(region, rows)
    return TranslationModel("x86_4k_2m_leaves", region, rows, huge_pages=huge)


def check_cover(region: Region, records: Sequence[Record]) -> None:
    cursor = region.start_vpn
    for record in records:
        if record.start_vpn != cursor or record.size_pages < 1:
            raise AssertionError("Gap, overlap or empty metadata record")
        idx = record.start_vpn - region.start_vpn
        for d in range(record.size_pages):
            if (region.physical_frames[idx+d] != record.start_pfn + d or
                    region.permissions[idx+d] != record.permissions):
                raise AssertionError("Record violates physical contiguity/permissions")
        cursor = record.end_vpn
    if cursor != region.end_vpn:
        raise AssertionError("Incomplete mapping cover")


def sample_region(start: int, size: int, workload: str) -> Region:
    # Example PFNs are exact data, not a claim about real allocator behavior.
    first = 8192  # 2 MiB aligned
    if workload == "contiguous":
        frames = tuple(first + i for i in range(size))
        perms = ("rw",) * size
    elif workload == "contiguous_phase_matched":
        # Matching (VA mod 512) and (PA mod 512) makes huge-page alignment possible.
        frames = tuple(first + start % HUGE_PAGE_PAGES + i for i in range(size))
        perms = ("rw",) * size
    elif workload == "fragmented_32":
        # Deterministic discontiguity at every 32-page boundary.
        frames = tuple(first + i + 16 * (i // 32) for i in range(size))
        perms = ("rw",) * size
    elif workload == "mixed_permissions":
        frames = tuple(first + i for i in range(size))
        perms = tuple("rx" if i < size // 3 else "r" if i < 2 * size // 3 else "rw"
                      for i in range(size))
    elif workload == "fragmented_permissions":
        frames = tuple(first + i + 16 * (i // 32) for i in range(size))
        perms = tuple("rx" if i < size // 3 else "r" if i < 2 * size // 3 else "rw"
                      for i in range(size))
    else:
        raise ValueError(workload)
    return Region(start, frames, perms)


def verify_models(region: Region, models: Sequence[TranslationModel]) -> int:
    checks = 0
    for i, pfn in enumerate(region.physical_frames):
        for byte_off in (0, 17, 4095):
            va = (region.start_vpn + i) * BASE_PAGE_BYTES + byte_off
            for model in models:
                for mode in "rwx":
                    if mode not in region.permissions[i]:
                        try:
                            model.translate(va, mode)
                        except ProtectionFault:
                            pass
                        else:
                            raise AssertionError(f"Protection error: {model.name} @ {i}")
                    else:
                        actual = model.translate(va, mode)
                        if actual != pfn * BASE_PAGE_BYTES + byte_off:
                            raise AssertionError(f"Translation error: {model.name} @ {i}")
                    checks += 1
    for model in models:
        for vp in (region.start_vpn-1, region.end_vpn):
            try:
                model.translate(vp * BASE_PAGE_BYTES, "r")
            except UnmappedAddress:
                pass
            else:
                raise AssertionError(f"Unmapped access accepted by {model.name}")
    return checks


def trial(start: int, size: int, workload: str) -> dict[str, object]:
    region = sample_region(start, size, workload)
    bap = build_bap(region)
    generic_capped = build_range(region, HUGE_PAGE_PAGES)
    generic_unbounded = build_range(region, None)
    x86 = build_x86(region)
    checks = verify_models(region, (bap, generic_capped, generic_unbounded, x86))
    parents = bap_blocks(start, size, HUGE_PAGE_PAGES)
    return {
        "start_vpn": start,
        "region_size_pages": size,
        "physical_layout": workload,
        "bap_logical_parent_chunks": len(parents),
        "bap_physical_permission_subrecords": len(bap.records),
        "bap_extra_subrecords_over_parents": len(bap.records) - len(parents),
        "generic_range_cap512_records": len(generic_capped.records),
        "generic_range_unbounded_records": len(generic_unbounded.records),
        "x86_4k_2m_leaf_entries": len(x86.records),
        "x86_2m_leaves": x86.huge_pages,
        "access_checks_passed": checks,
        "tlb_performance_measured": "NO",
        "hypothetical_range_hardware_measured": "NO",
    }


def self_test() -> None:
    # Exhaustively test all region pages, all r/w/x outcomes and byte offsets.
    for size in (1, 13, 19, 512, 513, 1000):
        for start in (0, 1, 7):
            for layout in ("contiguous", "fragmented_32", "mixed_permissions"):
                trial(start, size, layout)
    case = trial(1, 10000, "contiguous")
    assert case["bap_logical_parent_chunks"] == 21
    assert case["bap_physical_permission_subrecords"] == 21
    assert case["generic_range_cap512_records"] == 20
    assert case["generic_range_unbounded_records"] == 1
    assert case["x86_4k_2m_leaf_entries"] == 10000
    assert case["x86_2m_leaves"] == 0
    matched = trial(1, 10000, "contiguous_phase_matched")
    assert matched["x86_4k_2m_leaf_entries"] == 802
    assert matched["x86_2m_leaves"] == 18
    print("PASS: complete VA->PA byte translation, permissions, unmapped regions, physical runs")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("results_v6/translation_semantics_v6.csv"))
    args = parser.parse_args()
    if args.validate:
        self_test()
    scenarios = (
        (start, size, layout)
        for size in (1000, 4096, 10000)
        for start in (0, 1, 7)
        for layout in ("contiguous", "contiguous_phase_matched", "fragmented_32", "mixed_permissions", "fragmented_permissions")
    )
    rows = [trial(*s) for s in scenarios]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Created {len(rows)} simulation rows at {args.out}")
    for row in rows:
        if row["start_vpn"] == 1 and row["region_size_pages"] == 10000:
            print(row["physical_layout"], "BAP",row["bap_physical_permission_subrecords"],
                  "ranges(cap512)", row["generic_range_cap512_records"],
                  "ranges(unbounded)", row["generic_range_unbounded_records"],
                  "x86 leaves",row["x86_4k_2m_leaf_entries"])


if __name__ == "__main__":
    main()
