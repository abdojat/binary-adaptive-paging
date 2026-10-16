#!/usr/bin/env python3
"""BAP v8.3B-0: incremental semantics gate (NO performance claims).

Use the same operation semantics and an independent flat-page oracle from v8.3A.
Unlike v8.3A, updates in these six models never scan/reconstruct the entire
virtual region. Eager models patch only intersecting partition record lists;
overlay models modify only changed-page exceptions and compact by patching
affected parent lists. A generic-range model uses a Python sorted list, NOT
an optimized balanced tree: NO timing or update-complexity comparisons.

The purpose is to validate a candidate incremental architecture before porting
all six models to fair native, allocation-aware benchmarks.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
from bisect import bisect_right
from pathlib import Path
from typing import Optional

from dynamic_correctness_v83a import (
    K, PAGE_SIZE, PERMS, LAYOUTS, SCHEMES, Page, Record, Op, Oracle,
    InvalidUpdate, Snapshot, partitions, bap_parent_idx, make_initial,
    make_op, result, digest_state,
)


def coalesce(rows: list[Record]) -> list[Record]:
    """Merge adjacent physically linear, permission-identical records."""
    merged: list[Record] = []
    for r in sorted(rows, key=lambda x: x.start):
        if r.end <= r.start:
            raise AssertionError("Empty run")
        if merged and merged[-1].end > r.start:
            raise AssertionError("Overlapping records")
        if (merged and merged[-1].end == r.start and merged[-1].perm == r.perm
                and merged[-1].first_pfn + merged[-1].end - merged[-1].start == r.first_pfn):
            p = merged.pop()
            merged.append(Record(p.start, r.end, p.first_pfn, p.perm))
        else:
            merged.append(r)
    return merged


def patch_records(rows: list[Record], lo: int,
                  replacement: tuple[Optional[Page], ...]) -> tuple[list[Record], int]:
    """Replace [lo,hi) without materializing any page outside the update.

    Only the affected PARENT's records are considered. In the generic-range
    model, the parent is the whole range; its Python list update is O(R),
    not a balanced-tree implementation. The scan count is diagnostic only.
    """
    hi = lo + len(replacement)
    kept: list[Record] = []
    for r in rows:
        if r.end <= lo or r.start >= hi:
            kept.append(r)
            continue
        if r.start < lo:
            kept.append(Record(r.start, lo, r.first_pfn, r.perm))
        if r.end > hi:
            kept.append(Record(hi, r.end, r.first_pfn + hi - r.start, r.perm))
    for i, p in enumerate(replacement, lo):
        if p is not None:
            kept.append(Record(i, i + 1, p.pfn, p.perm))
    return coalesce(kept), len(rows)


class IncrementalModel:
    """All six variants have *their own* records, exceptions and PFN index."""
    def __init__(self, initial: tuple[Optional[Page], ...], scheme: str,
                 overlay: bool, threshold_frac: float):
        self.scheme, self.overlay = scheme, overlay
        self.name = f"{scheme}_{'overlay' if overlay else 'eager'}"
        snap = Snapshot(initial, scheme)  # initial construction only
        self.size = len(initial)
        self.bounds = list(snap.bounds)
        self.groups = [list(recs) for recs in snap.groups]
        self.starts = [[r.start for r in group] for group in self.groups]
        self.exc: dict[int, Optional[Page]] = {}
        self.pfn_owner = {p.pfn: i for i, p in enumerate(initial) if p is not None}
        assert len(self.pfn_owner) == sum(p is not None for p in initial)
        self.threshold = max(1, math.ceil(self.size * threshold_frac))
        self.compactions = 0
        self.max_overlay_exceptions = 0
        self.changed_parent_groups = 0
        self.parent_record_scans = 0
        self.pages_validated_for_updates = 0
        self.exceptions_written = 0
        self.compacted_pages = 0
        self.apply_calls = 0

    def parent_index(self, i: int) -> int:
        if self.scheme == "bap":
            return bap_parent_idx(self.size, i)
        if self.scheme == "fixed":
            return i // K
        return 0

    def base_lookup(self, off: int) -> Optional[Page]:
        if not 0 <= off < self.size:
            return None
        index = self.parent_index(off)
        start, end = self.bounds[index]
        if not start <= off < end:
            raise AssertionError("Parent out of range")
        rs = self.groups[index]
        j = bisect_right(self.starts[index], off) - 1
        if j < 0 or off >= rs[j].end:
            return None
        rec = rs[j]
        return Page(rec.first_pfn + (off - rec.start), rec.perm)

    def lookup(self, off: int) -> Optional[Page]:
        if not 0 <= off < self.size:
            return None
        if self.overlay and off in self.exc:
            return self.exc[off]
        return self.base_lookup(off)

    def _validate_locally(self, op: Op) -> tuple[Optional[Page], ...]:
        if not op.replacements or op.offset < 0 or op.offset + op.length > self.size:
            raise InvalidUpdate("Bad offset or length")
        old = tuple(self.lookup(i) for i in range(op.offset, op.offset + op.length))
        new = op.replacements
        if op.kind == "map":
            if any(x is not None for x in old) or any(x is None for x in new):
                raise InvalidUpdate("map requires unmapped destinations")
        elif op.kind in ("unmap", "protect", "cow_remap"):
            if any(x is None for x in old):
                raise InvalidUpdate("requires mapped pages")
            if op.kind == "unmap" and any(x is not None for x in new):
                raise InvalidUpdate("unmap must clear pages")
            if op.kind == "protect" and any(a.pfn != b.pfn for a, b in zip(old, new)):
                raise InvalidUpdate("protect must preserve frames")
            if op.kind == "cow_remap" and (op.length != 1 or new[0] is None
                                            or new[0].pfn == old[0].pfn):
                raise InvalidUpdate("cow_remap must change one PFN")
        else:
            raise InvalidUpdate("unknown operation")
        # Atomic alias check: remove the old owners conceptually, then check
        # candidate new owners. Only the changed pages are inspected.
        offsets = set(range(op.offset, op.offset + op.length))
        seen_new: set[int] = set()
        for p in new:
            if p is None:
                continue
            if p.pfn in seen_new:
                raise InvalidUpdate("duplicate PFN in replacement")
            seen_new.add(p.pfn)
            incumbent = self.pfn_owner.get(p.pfn)
            if incumbent is not None and incumbent not in offsets:
                raise InvalidUpdate("physical alias forbidden")
        return old

    def _write_base(self, offset: int,
                    replacement: tuple[Optional[Page], ...]) -> None:
        """Patch only intersecting parent metadata, never full-region pages."""
        end = offset + len(replacement)
        cur = offset
        while cur < end:
            index = self.parent_index(cur)
            _, parent_end = self.bounds[index]
            stop = min(end, parent_end)
            local_new = replacement[cur - offset:stop - offset]
            modified, scanned = patch_records(self.groups[index], cur, local_new)
            self.groups[index] = modified
            self.starts[index] = [r.start for r in modified]
            self.parent_record_scans += scanned
            self.changed_parent_groups += 1
            cur = stop

    def apply(self, op: Op) -> None:
        old = self._validate_locally(op)  # reject atomically before any mutation
        self.pages_validated_for_updates += op.length
        # Maintain a private reverse PFN lookup in O(update length).
        for p in old:
            if p is not None:
                del self.pfn_owner[p.pfn]
        for i, p in enumerate(op.replacements, op.offset):
            if p is not None:
                self.pfn_owner[p.pfn] = i
        if self.overlay:
            for i, val in enumerate(op.replacements, op.offset):
                if val == self.base_lookup(i):
                    self.exc.pop(i, None)
                else:
                    self.exc[i] = val
                self.exceptions_written += 1
            self.max_overlay_exceptions = max(self.max_overlay_exceptions, len(self.exc))
            if len(self.exc) >= self.threshold:
                # Commit exceptions into exactly their affected metadata ranges.
                # A future native implementation should batch adjacent keys.
                for i, val in sorted(self.exc.items()):
                    self._write_base(i, (val,))
                    self.compacted_pages += 1
                self.exc.clear()
                self.compactions += 1
        else:
            self._write_base(op.offset, op.replacements)
        self.apply_calls += 1

    def validate_canonical(self) -> None:
        for (lo, hi), rs, starts in zip(self.bounds, self.groups, self.starts):
            if starts != [r.start for r in rs]:
                raise AssertionError("stale starts")
            previous = None
            for r in rs:
                if not (lo <= r.start < r.end <= hi):
                    raise AssertionError("bad record bounds")
                if previous is not None:
                    if previous.end > r.start:
                        raise AssertionError("record overlap")
                    if (previous.end == r.start and previous.perm == r.perm
                        and previous.first_pfn + previous.end - previous.start == r.first_pfn):
                        raise AssertionError("uncoalesced adjacent records")
                previous = r

    @property
    def base_record_count(self) -> int:
        return sum(len(x) for x in self.groups)


def check(oracle: Oracle, models: list[IncrementalModel],
          changed: range, rng: random.Random, exhaustive_limit: int) -> int:
    n = len(oracle.pages)
    if n <= exhaustive_limit:
        pts = list(range(n))
    else:
        choices = {0, n - 1, n // 2}
        for i in changed:
            choices.update(j for j in (i-1, i, i+1) if 0 <= j < n)
        for k in (32, K):
            for i in range(0, n + 1, k):
                choices.update(j for j in (i-1, i) if 0 <= j < n)
        for model in models:
            for p, q in model.bounds:
                choices.update(j for j in (p-1, p, q-1, q) if 0 <= j < n)
        # Match v8.3A's PRNG draw count so deterministic update logs stay
        # bit-for-bit comparable with the previously published v8.3A CSV.
        choices.update(rng.randrange(n) for _ in range(min(96, n)))
        pts = sorted(choices)
    checks = 0
    for i in pts:
        expected = oracle.lookup(i)
        for m in models:
            actual = m.lookup(i)
            if actual != expected:
                raise AssertionError(f"Model {m.name}: page {i}: {actual} vs {expected}")
            for access in ("r", "w", "x"):
                for byte in (0, 17, PAGE_SIZE - 1):
                    if result(actual, access, byte) != result(expected, access, byte):
                        raise AssertionError(f"Translation mismatch: {m.name}: {i} {access} {byte}")
                    checks += 1
    for m in models:
        for off in (-1, n):
            if m.lookup(off) is not None:
                raise AssertionError("Out-of-bounds lookup accepted")
        m.validate_canonical()
    return checks


def scenario(size: int, start: int, layout: str, threshold: float,
             seed: int, nupdates: int, exhaustive: int) -> list[dict[str, object]]:
    initial = make_initial(size, layout)
    oracle = Oracle(initial)
    models = [IncrementalModel(initial, s, o, threshold)
              for s in SCHEMES for o in (False, True)]
    rng = random.Random(seed*1000003+size*997+start*53+sum(ord(x) for x in layout))
    checks = check(oracle, models, range(0), rng, exhaustive)
    invalids = 0
    operations = {x: 0 for x in ("map", "unmap", "protect", "cow_remap")}
    for seq in range(nupdates):
        kind = ("map", "unmap", "protect", "cow_remap", "protect", "cow_remap", "unmap", "map")[seq%8]
        op = make_op(oracle, kind, rng, seq, size)
        for model in models:
            model.apply(op)
        oracle.apply(op)
        operations[kind] += 1
        checks += check(oracle, models, range(op.offset, op.offset + op.length), rng, exhaustive)
        if seq % 11 == 0:
            i = next(i for i, p in enumerate(oracle.pages) if p is not None)
            bad = Op("map", i, (Page(9_000_000+seq, "rw"),))
            before = digest_state(oracle)
            for model in models:
                state_before = (model.base_record_count, len(model.exc),
                                dict(model.pfn_owner), model.compactions)
                try:
                    model.apply(bad)
                except InvalidUpdate:
                    pass
                else:
                    raise AssertionError(f"Invalid map accepted by {model.name}")
                if state_before != (model.base_record_count, len(model.exc),
                                    model.pfn_owner, model.compactions):
                    raise AssertionError("Rejected update was not atomic")
            try:
                oracle.apply(bad)
            except InvalidUpdate:
                pass
            else:
                raise AssertionError("Oracle accepted invalid map")
            assert digest_state(oracle) == before
            invalids += 1
            checks += check(oracle, models, range(i, i+1), rng, exhaustive)
    final_hash = digest_state(oracle)
    output = []
    for m in models:
        output.append({
            "region_size_pages":size,"start_vpn":start,"physical_layout":layout,
            "threshold_fraction":threshold,"seed":seed,"updates":nupdates,
            "model":m.name,"oracle_comparisons":checks//len(models),
            "map_ops":operations["map"],"unmap_ops":operations["unmap"],
            "protect_ops":operations["protect"],"cow_remap_ops":operations["cow_remap"],
            "invalid_updates_rejected":invalids,"final_state_sha256":final_hash,
            "parent_groups":len(m.groups),"base_records":m.base_record_count,
            "pending_exceptions":len(m.exc),"peak_exception_count":m.max_overlay_exceptions,
            "compactions":m.compactions,"compacted_pages":m.compacted_pages,
            "changed_parent_groups":m.changed_parent_groups,
            "parent_record_scans":m.parent_record_scans,
            "locally_validated_pages":m.pages_validated_for_updates,
            "semantic_mismatches":0,"update_latency_measured":"NO",
            "native_memory_bytes_measured":"NO","tlb_measured":"NO",
        })
    return output


def self_test() -> None:
    for s in range(1, 1041):
        for scheme in SCHEMES:
            p = partitions(s, scheme)
            assert p[0][0] == 0 and p[-1][1] == s
            for off in (0, s//2, s-1):
                idx = bap_parent_idx(s,off) if scheme=="bap" else off//K if scheme=="fixed" else 0
                assert p[idx][0] <= off < p[idx][1]
    # Test split/merge, exceptions, compaction, physical aliases and rejection.
    for layout in LAYOUTS:
        for scheme in SCHEMES:
            for overlay in (False, True):
                init=make_initial(64,layout)
                m=IncrementalModel(init,scheme,overlay,.01)
                o=Oracle(init)
                samples = [
                    Op("map",0,(Page(1000000,"rw"),)),
                    Op("protect",1,(Page(init[1].pfn,"r"),)),
                    Op("cow_remap",2,(Page(1000001,"rw"),)),
                    Op("unmap",3,(None,)),
                    Op("map",3,(Page(1000002,"rx"),)),
                ]
                for op in samples:
                    m.apply(op);o.apply(op)
                    for i in range(64):
                        assert m.lookup(i)==o.lookup(i)
                    m.validate_canonical()
                bad=Op("map",3,(Page(1000003,"rw"),))
                try:m.apply(bad)
                except InvalidUpdate:pass
                else:raise AssertionError("invalid update accepted")
                alias=Op("cow_remap",2,(Page(init[1].pfn,"rw"),))
                try:m.apply(alias)
                except InvalidUpdate:pass
                else:raise AssertionError("physical alias accepted")
    print("PASS: local patch split/merge, overlay exception writes, compaction, PFN index and rejection atomicity")


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--validate",action="store_true")
    ap.add_argument("--sizes",default="13,513,1000")
    ap.add_argument("--starts",default="0,1")
    ap.add_argument("--layouts",default=",".join(LAYOUTS))
    ap.add_argument("--thresholds",default="0.01,0.10")
    ap.add_argument("--seeds",default="1,2")
    ap.add_argument("--updates",type=int,default=32)
    ap.add_argument("--exhaustive-limit",type=int,default=64)
    ap.add_argument("--out",type=Path,default=Path("results_v83b0/incremental_semantics_v83b0.csv"))
    args=ap.parse_args()
    sizes=[int(x) for x in args.sizes.split(",")]
    starts=[int(x) for x in args.starts.split(",")]
    layouts=args.layouts.split(",")
    thresholds=[float(x) for x in args.thresholds.split(",")]
    seeds=[int(x) for x in args.seeds.split(",")]
    if not sizes or min(sizes)<3 or max(sizes)>200000 or not starts or min(starts)<0:
        ap.error("invalid size/start")
    if not layouts or any(x not in LAYOUTS for x in layouts):
        ap.error("invalid layouts")
    if not thresholds or any(x<=0 or x>1 for x in thresholds):
        ap.error("invalid thresholds")
    if not seeds or args.updates<4 or args.exhaustive_limit<1:
        ap.error("invalid seeds/updates/limit")
    if args.validate:
        self_test()
    rows=[]
    for s in sizes:
        for start in starts:
            for layout in layouts:
                for threshold in thresholds:
                    for seed in seeds:
                        rows.extend(scenario(s,start,layout,threshold,seed,args.updates,args.exhaustive_limit))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f"PASS: {len(rows)//6} incremental scenarios; {len(rows)} model rows; zero differential semantic mismatches")
    print("OUTPUT:",args.out)
    print("NOTE: parent_record_scans is a logical diagnostic, NOT native incremental latency or fair dynamic-range-tree cost")


if __name__=="__main__":
    main()
