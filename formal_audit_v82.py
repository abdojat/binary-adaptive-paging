#!/usr/bin/env python3
"""BAP v8.2 structural dominance audit (Python standard library only).

Hypotheses: software region metadata; max chunk K a power of two;
fixed-grid permits a last block of arbitrary positive size <K;
records store maximal PFN-consecutive, permission-equal runs WITHIN parents.
No x86/native-page feasibility, TLB, runtime, dynamic updates, or novelty claims.
"""
from __future__ import annotations
import argparse
import csv
import random
from pathlib import Path


def check_cap(cap):
    if cap < 1 or cap & (cap-1):
        raise ValueError('cap must be positive power of two')


def bap_parts(size, cap):
    if size < 1: raise ValueError('size')
    check_cap(cap)
    q, r = divmod(size, cap)
    sizes = [cap]*q + [1<<k for k in range(r.bit_length()-1, -1, -1) if r & (1<<k)]
    out=[]; at=0
    for s in sizes:
        out.append((at,s)); at+=s
    assert at==size
    return out


def fixed_parts(size, cap):
    if size < 1: raise ValueError('size')
    check_cap(cap)
    q, r = divmod(size, cap)
    out=[(i*cap,cap) for i in range(q)]
    if r: out.append((q*cap,r))
    return out


def record_count(parts, pfns, perms):
    # A maximal contiguous physical and permission-uniform run per parent.
    count=0
    for start,length in parts:
        count+=1
        for i in range(start+1,start+length):
            if pfns[i]!=pfns[i-1]+1 or perms[i]!=perms[i-1]:
                count+=1
    return count


def check_exact(size,cap, layout, rng):
    bap,fixed=bap_parts(size,cap),fixed_parts(size,cap)
    q,r=divmod(size,cap)
    assert len(bap)==q+r.bit_count()
    assert len(fixed)==q+(r!=0)
    fixed_cuts={st+length for st,length in fixed}
    bap_cuts={st+length for st,length in bap}
    assert fixed_cuts<=bap_cuts
    assert len(bap)-len(fixed)==r.bit_count()-int(r>0)

    if layout=='contiguous':
        pfns=list(range(10240, 10240+size));perms=['rw']*size
    elif layout=='fragmented':
        pfns=[10240+i+16*(i//32) for i in range(size)];perms=['rw']*size
    elif layout=='mixed_permissions':
        pfns=list(range(10240, 10240+size));perms=['rx' if i<size//3 else 'r' if i<(2*size)//3 else 'rw' for i in range(size)]
    elif layout=='random':
        pfns=[];p=10240;perms=[]
        for i in range(size):
            if rng.random()<.12:p+=rng.randrange(2,8)
            else:p+=1
            pfns.append(p)
            perms.append(['rw','r','rx'][rng.randrange(3)] if rng.random()<.07 else (perms[-1] if perms else 'rw'))
    else: raise ValueError('unknown layout')
    rb=record_count(bap,pfns,perms)
    rf=record_count(fixed,pfns,perms)
    extra_boundary_count=len(bap)-len(fixed)
    assert 0<=rb-rf<=extra_boundary_count, (size,layout,rb,rf)
    B=32+24*rb+8*len(bap)
    F=32+24*rf+8*len(fixed)
    assert B>=F
    assert B-F==24*(rb-rf)+8*extra_boundary_count
    return {'size':size,'cap':cap,'layout':layout,'remainder':r,
            'bap_parents':len(bap),'fixed_parents':len(fixed),
            'bap_records':rb,'fixed_records':rf,
            'bap_metadata_bytes':B,'fixed_metadata_bytes':F,
            'delta_metadata_bytes':B-F}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cap',type=int,default=512)
    ap.add_argument('--sizes-exhaustive',type=int,default=10000)
    ap.add_argument('--random-cases',type=int,default=600)
    ap.add_argument('--out',type=Path,default=Path('results_v82/formal_checks_v82.csv'))
    args=ap.parse_args()
    check_cap(args.cap)
    if args.sizes_exhaustive<1 or args.random_cases<0: ap.error('bad bounds')
    rng=random.Random(20261016)
    # Exhaustive *structural* theorem check without generating PFN arrays.
    for s in range(1,args.sizes_exhaustive+1):
        b,f=bap_parts(s,args.cap),fixed_parts(s,args.cap)
        q,r=divmod(s,args.cap)
        assert len(b)==q+r.bit_count()
        assert len(f)==q+int(r>0)
        assert {st+n for st,n in f} <= {st+n for st,n in b}
    rows=[]
    # Reproducible deterministic representative cases including paper S=10000.
    for size in (13,19,255,256,257,511,512,513,1000,4096,10000):
        for layout in ('contiguous','fragmented','mixed_permissions'):
            rows.append(check_exact(size,args.cap,layout,rng))
    for _ in range(args.random_cases):
        size=rng.randint(1,2048)
        rows.append(check_exact(size,args.cap,'random',rng))
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('w',newline='',encoding='utf-8') as file:
        w=csv.DictWriter(file,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f'PASS: {args.sizes_exhaustive} exhaustive structural sizes, {len(rows)} PFN/permission layouts')
    print(f'OUTPUT: {args.out}')
    for x in rows:
        if x['size']==10000:
            print('S=10000',x['layout'],'parents',x['bap_parents'],x['fixed_parents'],'records',x['bap_records'],x['fixed_records'],'metadata',x['bap_metadata_bytes'],x['fixed_metadata_bytes'])

if __name__=='__main__':main()
