#!/usr/bin/env python3
"""BAP v8.3A: differential semantic correctness of six dynamic-mapping models.

Standard library only, deterministic scenarios. This is NOT a timing benchmark,
operating-system paging implementation, TLB model, or BAP speedup demonstration.

Eager models: BAP, fixed K-page grid, generic globally coalesced ranges.
Overlay models: immutable base snapshot plus common exception dictionary, same
compaction rule for all three representations.

All eagerly maintained metadata is rebuilt from its own per-page state on an
update; operation counts/latency therefore MUST NOT be interpreted as incremental
update costs. All physical page IDs unique in active mappings (no aliasing).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import random
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

K = 512
PAGE_SIZE = 4096
PERMS = ("r", "rw", "rx", "rwx")
LAYOUTS = ("contiguous", "fragmented_32", "mixed_permissions", "fragmented_permissions")
SCHEMES = ("bap", "fixed", "ranges")


@dataclass(frozen=True)
class Page:
    pfn: int
    perm: str

    def __post_init__(self) -> None:
        if self.pfn < 0 or not self.perm or any(c not in "rwx" for c in self.perm):
            raise ValueError("Bad PFN or permission")


@dataclass(frozen=True)
class Record:
    start: int  # relative VPN
    end: int  # exclusive
    first_pfn: int
    perm: str


@dataclass(frozen=True)
class Op:
    kind: str
    offset: int
    replacements: tuple[Optional[Page], ...]

    @property
    def length(self) -> int:
        return len(self.replacements)


class InvalidUpdate(ValueError):
    pass


def validate_update(pages: list[Optional[Page]], op: Op) -> None:
    if not op.replacements or op.offset < 0 or op.offset + op.length > len(pages):
        raise InvalidUpdate("Invalid update bounds")
    current = pages[op.offset:op.offset + op.length]
    if op.kind == "map":
        if any(x is not None for x in current) or any(x is None for x in op.replacements):
            raise InvalidUpdate("map requires entirely unmapped destination")
    elif op.kind in {"unmap", "protect", "cow_remap"}:
        if any(x is None for x in current):
            raise InvalidUpdate("operation requires mapped pages")
        if op.kind == "unmap" and any(x is not None for x in op.replacements):
            raise InvalidUpdate("unmap must remove mapping")
        if op.kind == "protect" and any(a.pfn != b.pfn for a,b in zip(current,op.replacements)):
            raise InvalidUpdate("protect must retain physical frames")
        if op.kind == "cow_remap" and (op.length != 1 or op.replacements[0] is None
                                          or op.replacements[0].pfn == current[0].pfn):
            raise InvalidUpdate("cow_remap must replace one frame")
    else:
        raise InvalidUpdate("unknown operation")
    # No active PFN aliases. Compute replacement state first for atomic validation.
    candidate = list(pages)
    candidate[op.offset:op.offset + op.length] = op.replacements
    active = [p.pfn for p in candidate if p is not None]
    if len(active) != len(set(active)):
        raise InvalidUpdate("physical aliases excluded")


class Oracle:
    def __init__(self, pages: tuple[Optional[Page], ...]):
        self.pages = list(pages)

    def apply(self, op: Op) -> None:
        validate_update(self.pages, op)
        self.pages[op.offset:op.offset + op.length] = op.replacements

    def lookup(self, off: int) -> Optional[Page]:
        return self.pages[off] if 0 <= off < len(self.pages) else None


def partitions(size: int, scheme: str) -> list[tuple[int,int]]:
    if scheme == "ranges":
        return [(0,size)]
    out = []
    at = 0
    for _ in range(size // K):
        out.append((at,at+K))
        at += K
    tail = size-at
    if tail:
        if scheme == "fixed":
            out.append((at,size))
        else:
            for bit in reversed(range(tail.bit_length())):
                if tail & (1<<bit):
                    length=1<<bit
                    out.append((at,at+length))
                    at += length
    assert out[0][0] == 0 and out[-1][1] == size
    return out


def bap_parent_idx(size: int, off: int) -> int:
    full = size // K
    prefix = full*K
    if off < prefix:
        return off//K
    tail = size-prefix
    x = (off-prefix)^tail
    k = x.bit_length()-1
    return full + (tail>>(k+1)).bit_count()


class Snapshot:
    """Representation from its own pages; no oracle dependency."""
    def __init__(self, pages: tuple[Optional[Page], ...], scheme: str):
        self.pages=pages
        self.scheme=scheme
        self.bounds=partitions(len(pages),scheme)
        self.groups: list[tuple[Record,...]]=[]
        self.starts: list[tuple[int,...]]=[]
        n=0
        for lo,hi in self.bounds:
            records=[]
            i=lo
            while i<hi:
                p=pages[i]
                if p is None:
                    i+=1
                    continue
                j=i+1
                while j<hi:
                    q=pages[j]
                    if q is None or q.perm!=p.perm or q.pfn != pages[j-1].pfn + 1:
                        break
                    j+=1
                records.append(Record(i,j,p.pfn,p.perm))
                i=j
            recs=tuple(records)
            self.groups.append(recs)
            self.starts.append(tuple(r.start for r in recs))
            n+=len(recs)
        self.record_count=n

    @property
    def parent_count(self) -> int:
        return len(self.bounds)

    def lookup(self, off: int) -> Optional[Page]:
        if off < 0 or off >= len(self.pages):
            return None
        if self.scheme=="bap":
            ix=bap_parent_idx(len(self.pages),off)
        elif self.scheme=="fixed":
            ix=off//K
        else:
            ix=0
        lo,hi=self.bounds[ix]
        if not lo<=off<hi:
            raise AssertionError("parent arithmetic index incorrect")
        start_index=bisect_right(self.starts[ix],off)-1
        if start_index<0:
            return None
        rec=self.groups[ix][start_index]
        if off>=rec.end:
            return None
        return Page(rec.first_pfn+(off-rec.start),rec.perm)


class Model:
    def __init__(self, initial: tuple[Optional[Page], ...], scheme: str,
                 overlay: bool, threshold: float):
        self.scheme=scheme
        self.overlay=overlay
        self.name=scheme+("_overlay" if overlay else "_eager")
        self.snap=Snapshot(initial,scheme)
        self.eager_pages=list(initial) if not overlay else None
        self.exceptions: dict[int, Optional[Page]]={}
        self.compactions=0
        self.max_overlay=0
        self.threshold=max(1,math.ceil(len(initial)*threshold))

    def lookup(self, off: int) -> Optional[Page]:
        if off<0 or off>=len(self.snap.pages):
            return None
        if self.overlay and off in self.exceptions:
            return self.exceptions[off]
        return self.snap.lookup(off)

    def apply(self, op: Op) -> None:
        # Derive own preupdate state. No access to oracle's storage.
        pages=[self.lookup(i) for i in range(len(self.snap.pages))] if self.overlay else list(self.eager_pages)
        validate_update(pages,op)
        if self.overlay:
            for i,v in enumerate(op.replacements,op.offset):
                if v==self.snap.pages[i]:
                    self.exceptions.pop(i,None)
                else:
                    self.exceptions[i]=v
            self.max_overlay=max(self.max_overlay,len(self.exceptions))
            if len(self.exceptions)>=self.threshold:
                base=list(self.snap.pages)
                for i,p in self.exceptions.items():
                    base[i]=p
                self.snap=Snapshot(tuple(base),self.scheme)
                self.exceptions.clear()
                self.compactions+=1
        else:
            self.eager_pages[op.offset:op.offset+op.length]=op.replacements
            self.snap=Snapshot(tuple(self.eager_pages),self.scheme)


def make_initial(size: int, layout: str) -> tuple[Optional[Page], ...]:
    out=[]
    for i in range(size):
        if i % 17 == 0:  # deliberately unmapped holes
            out.append(None)
            continue
        pfn=8192+i+(16*(i//32) if layout in {"fragmented_32","fragmented_permissions"} else 0)
        perm=("rx" if i<size//3 else "r" if i<2*size//3 else "rw") if layout in {
            "mixed_permissions","fragmented_permissions"} else "rw"
        out.append(Page(pfn,perm))
    return tuple(out)


def make_op(oracle: Oracle, kind: str, rng: random.Random, seq: int, size: int) -> Op:
    width=1 if kind=="cow_remap" else rng.choice((1,1,2,3))
    valid=[i for i in range(size-width+1) if all(
        (p is None if kind=="map" else p is not None)
        for p in oracle.pages[i:i+width])]
    if not valid:
        width=1
        valid=[i for i,p in enumerate(oracle.pages) if (p is None if kind=="map" else p is not None)]
    if not valid:
        raise AssertionError("No possible valid update; check operation schedule")
    start=rng.choice(valid)
    if kind=="map":
        replacements=tuple(Page(2_000_000+seq*128+d,"rw") for d in range(width))
    elif kind=="unmap":
        replacements=(None,)*width
    elif kind=="protect":
        replacements=tuple(Page(p.pfn,"r" if p.perm!="r" else "rw")
                           for p in oracle.pages[start:start+width])
    elif kind=="cow_remap":
        replacements=(Page(1_000_000+seq*128,"rw"),)
    else:
        raise AssertionError(kind)
    return Op(kind,start,replacements)


def result(p: Optional[Page],access: str,byte: int) -> tuple[str,Optional[int]]:
    if p is None:
        return ("unmapped",None)
    if access not in p.perm:
        return ("protection",None)
    return ("ok",p.pfn*PAGE_SIZE+byte)


def oracle_translate(oracle: Oracle, start_vpn: int, virtual_address: int,
                     access: str) -> tuple[str, Optional[int]]:
    if virtual_address < 0:
        return ("unmapped", None)
    vpn, byte = divmod(virtual_address, PAGE_SIZE)
    return result(oracle.lookup(vpn-start_vpn), access, byte)


def model_translate(model: Model, start_vpn: int, virtual_address: int,
                    access: str) -> tuple[str, Optional[int]]:
    if virtual_address < 0:
        return ("unmapped", None)
    vpn, byte = divmod(virtual_address, PAGE_SIZE)
    return result(model.lookup(vpn-start_vpn), access, byte)


def verify(oracle: Oracle, models: list[Model], size: int, start: int,
           changed: range, rng: random.Random, exhaustive: int) -> int:
    if size<=exhaustive:
        samples=list(range(size))
    else:
        sample={0,size-1,size//2}
        for v in changed:
            sample.update(x for x in (v-1,v,v+1) if 0<=x<size)
        for boundary in range(0,size+1,32):
            sample.update(x for x in (boundary-1,boundary) if 0<=x<size)
        for boundary in range(0,size+1,K):
            sample.update(x for x in (boundary-1,boundary) if 0<=x<size)
        for model in models:
            for p,q in model.snap.bounds:
                sample.update(x for x in (p-1,p,q-1,q) if 0<=x<size)
        sample.update(rng.randrange(size) for _ in range(min(96,size)))
        samples=sorted(sample)
    comparisons=0
    test_accesses=(("r",0),("r",17),("r",PAGE_SIZE-1),("w",17),("x",17))
    for off in samples:
        expected=oracle.lookup(off)
        targets=[((start+off)*PAGE_SIZE+byte,access,
                  oracle_translate(oracle,start,(start+off)*PAGE_SIZE+byte,access))
                 for access,byte in test_accesses]
        for m in models:
            actual=m.lookup(off)
            if actual!=expected:
                raise AssertionError(f"{m.name} incorrect page start={start}, size={size}, VPN={start+off}: {actual} != {expected}")
            for va,access,want in targets:
                if model_translate(m,start,va,access)!=want:
                    raise AssertionError(f"{m.name} VA->PA/permission mismatch at {va} {access}")
                comparisons+=1
    for m in models:
        for invalid_va in ((start-1)*PAGE_SIZE,(start+size)*PAGE_SIZE):
            if model_translate(m,start,invalid_va,"r") != ("unmapped",None):
                raise AssertionError("out-of-region mapping accepted")
    return comparisons


def digest_state(oracle: Oracle) -> str:
    s=";".join("-" if p is None else f"{p.pfn}:{p.perm}" for p in oracle.pages)
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def scenario(size: int,start: int,layout: str,threshold: float,seed: int,
             nupdates: int,exhaustive: int) -> list[dict[str,object]]:
    initial=make_initial(size,layout)
    oracle=Oracle(initial)
    models=[Model(initial,scheme,overlay,threshold) for scheme in SCHEMES for overlay in (False,True)]
    rng=random.Random(seed*1000003+size*997+start*53+sum(ord(x) for x in layout))
    checks=verify(oracle,models,size,start,range(size) if size<=exhaustive else range(0),rng,exhaustive)
    ops={k:0 for k in ("map","unmap","protect","cow_remap")}
    rejected=0
    for index in range(nupdates):
        kind=("map","unmap","protect","cow_remap","protect","cow_remap","unmap","map")[index%8]
        op=make_op(oracle,kind,rng,index,size)
        for m in models:
            m.apply(op)
        oracle.apply(op)
        ops[kind]+=1
        checks+=verify(oracle,models,size,start,range(op.offset,op.offset+op.length),rng,exhaustive)
        # Atomic rejection: mapping an already mapped page must not alter ANY model.
        if index%11==0:
            mapped=next(i for i,p in enumerate(oracle.pages) if p is not None)
            invalid=Op("map",mapped,(Page(9_000_000+index,"rw"),))
            before=digest_state(oracle)
            for m in models:
                try: m.apply(invalid)
                except InvalidUpdate: pass
                else: raise AssertionError("Invalid map wrongly accepted by "+m.name)
            try: oracle.apply(invalid)
            except InvalidUpdate: pass
            else: raise AssertionError("Invalid map accepted by oracle")
            if digest_state(oracle)!=before:
                raise AssertionError("Invalid operation mutated oracle")
            rejected+=1
            checks+=verify(oracle,models,size,start,range(mapped,mapped+1),rng,exhaustive)
    state_hash=digest_state(oracle)
    rows=[]
    for m in models:
        rows.append({
            "size_pages":size,"start_vpn":start,"layout":layout,"threshold_fraction":threshold,
            "seed":seed,"updates":nupdates,"model":m.name,"oracle_checks":checks//len(models),
            "map_ops":ops["map"],"unmap_ops":ops["unmap"],"protect_ops":ops["protect"],
            "cow_remap_ops":ops["cow_remap"],"invalid_updates_rejected":rejected,
            "final_parent_count":m.snap.parent_count,"final_base_records":m.snap.record_count,
            "final_overlay_exceptions":len(m.exceptions),"max_overlay_exceptions":m.max_overlay,
            "compactions":m.compactions,"final_oracle_sha256":state_hash,
            "semantic_mismatches":0,"incremental_update_cost_measured":"NO",
            "lookup_latency_measured":"NO","tlb_measured":"NO",
        })
    return rows


def parse_ints(v: str)->list[int]:
    return [int(x.strip()) for x in v.split(",")]


def parse_floats(v: str)->list[float]:
    return [float(x.strip()) for x in v.split(",")]


def self_test()->None:
    for size in range(1,1041):
        for scheme in SCHEMES:
            parts=partitions(size,scheme)
            assert sum(b-a for a,b in parts)==size
            if scheme=="bap":
                for off in range(size):
                    ix=bap_parent_idx(size,off)
                    assert parts[ix][0]<=off<parts[ix][1]
    for size in (13,64,513):
        for layout in LAYOUTS:
            rows=scenario(size,1,layout,.05,12,12,64)
            assert len(rows)==6 and all(x["semantic_mismatches"]==0 for x in rows)
    # Targeted fault, compaction and atomicity tests, including partially invalid ranges.
    init=(Page(100,"rw"),None,Page(200,"rx"))
    for scheme in SCHEMES:
        for overlay in (False,True):
            m=Model(init,scheme,overlay,.99)
            invalid_ops=(
                Op("map",0,(Page(301,"rw"),)),                  # mapped target
                Op("unmap",0,(None,None)),                       # mixed mapped/hole
                Op("protect",1,(Page(101,"r"),)),                # hole
                Op("cow_remap",1,(Page(201,"rw"),)),            # hole
                Op("protect",0,(Page(999,"r"),)),               # illegal PFN change
                Op("map",2,(Page(301,"rw"),Page(302,"rw"))),     # outside region
            )
            for bad in invalid_ops:
                prior=[m.lookup(i) for i in range(len(init))]
                try: m.apply(bad)
                except InvalidUpdate: pass
                else: raise AssertionError(f"{m.name} accepted invalid {bad.kind}")
                assert [m.lookup(i) for i in range(len(init))]==prior, "Rejected operation was not atomic"
            m.apply(Op("unmap",0,(None,)))
            assert m.lookup(0) is None
            m.apply(Op("map",1,(Page(101,"r"),)))
            assert m.lookup(1)==Page(101,"r")
            m.apply(Op("protect",2,(Page(200,"r"),)))
            assert m.lookup(2)==Page(200,"r")
            m.apply(Op("cow_remap",2,(Page(201,"rw"),)))
            assert m.lookup(2)==Page(201,"rw")
            if overlay:
                assert m.compactions>=1
    print("PASS: BAP/fixed/range parent indexes, six-model differential semantics, byte addresses, overlay compaction, invalid-update atomicity")


def main()->None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--validate",action="store_true")
    p.add_argument("--sizes",default="13,513,1000")
    p.add_argument("--starts",default="0,1")
    p.add_argument("--layouts",default=",".join(LAYOUTS))
    p.add_argument("--thresholds",default="0.01,0.10")
    p.add_argument("--seeds",default="1,2")
    p.add_argument("--updates",type=int,default=32)
    p.add_argument("--exhaustive-limit",type=int,default=64)
    p.add_argument("--out",type=Path,default=Path("results_v83a/dynamic_correctness_v83a.csv"))
    args=p.parse_args()
    sizes=parse_ints(args.sizes);starts=parse_ints(args.starts)
    thresholds=parse_floats(args.thresholds);seeds=parse_ints(args.seeds)
    layouts=args.layouts.split(",")
    if not sizes or min(sizes)<3 or max(sizes)>200000 or not starts or min(starts)<0:
        p.error("sizes must be 3..200000 and starts nonnegative")
    if any(x not in LAYOUTS for x in layouts) or not thresholds or any(x<=0 or x>1 for x in thresholds):
        p.error("bad layouts or thresholds")
    if not seeds or args.updates<4 or args.exhaustive_limit<1:
        p.error("invalid seeds/updates/exhaustive-limit")
    if args.validate:self_test()
    rows=[]
    for size in sizes:
        for start in starts:
            for layout in layouts:
                for th in thresholds:
                    for seed in seeds:
                        rows.extend(scenario(size,start,layout,th,seed,args.updates,args.exhaustive_limit))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f"PASS: {len(rows)//6} differential scenarios, {len(rows)} model rows, zero semantic mismatches")
    print("OUTPUT:",args.out)
    print("All six models: exact PFNs, read/write/execute permissions, unmapped faults, bounds, invalid-operation atomicity")
    print("NOTE: No latency / incremental update cost / TLB measurements have been performed.")


if __name__=="__main__":main()
