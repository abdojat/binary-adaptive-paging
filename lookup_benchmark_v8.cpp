// BAP v8: native C++ microbenchmark of *software metadata* translation lookup.
// Reproducible sample workloads; not a TLB, page walker, kernel, or hardware test.
// Compile: g++ -O3 -std=c++20 -Wall -Wextra -pedantic lookup_benchmark_v8.cpp -o lookup_benchmark_v8
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

constexpr uint32_t CAP = 512;
constexpr uint64_t PFN_BASE = 8192;
constexpr uint64_t REGION_DESCRIPTOR_BYTES = 32; // hypothetical, same assumption as v7
struct Record {
    uint64_t vpn;
    uint64_t pfn;
    uint32_t len;
    uint8_t perm;
    uint8_t padding[3]{};
};
struct DirectorySlot {uint32_t first, count;};
static_assert(sizeof(Record) == 24);
static_assert(sizeof(DirectorySlot) == 8);

struct Region {
    uint64_t start;
    std::vector<uint64_t> frames;
    std::vector<uint8_t> perms;
    uint32_t size() const {return static_cast<uint32_t>(frames.size());}
};
struct BAP {
    std::vector<Record> records;
    std::vector<DirectorySlot> directory;
};
struct IndexedRange {
    std::vector<Record> records;
    std::vector<DirectorySlot> bucket_directory;
};
[[noreturn]] void fail(const std::string& s) {throw std::runtime_error(s);}
void ensure(bool b, const std::string& s) { if (!b) fail(s); }

std::vector<uint32_t> bap_sizes(uint32_t size) {
    std::vector<uint32_t> sizes;
    for (int bit = 31; bit >= 0; --bit) {
        if ((size >> bit) & 1U) {
            uint64_t rest = 1ULL << bit;
            while (rest != 0) {
                uint32_t take = static_cast<uint32_t>(std::min<uint64_t>(CAP, rest));
                sizes.push_back(take); rest -= take;
            }
        }
    }
    return sizes;
}
uint32_t parent_index(uint32_t size, uint32_t off) {
    if (off >= size) fail("bad offset");
    uint32_t full = size / CAP;
    uint32_t prefix = full * CAP;
    if (off < prefix) return off / CAP;
    uint32_t rem = size - prefix;
    uint32_t x = (off-prefix) ^ rem;
    if (!x) fail("unexpected zero XOR");
    unsigned k = std::bit_width(x) - 1U;
    return full + std::popcount(rem >> (k+1));
}
Region make_region(uint64_t start, uint32_t size, const std::string& layout) {
    Region r{start, {}, {}};
    r.frames.reserve(size);r.perms.reserve(size);
    for (uint32_t i=0;i<size;++i) {
        uint64_t pfn = PFN_BASE + i;
        uint8_t perm=3; // r|w
        if (layout == "contiguous_phase_matched") pfn += start % CAP;
        else if (layout == "fragmented_32" || layout == "fragmented_permissions") pfn += 16ULL*(i/32);
        else if (layout != "contiguous" && layout != "mixed_permissions") fail("unknown layout");
        if (layout == "mixed_permissions" || layout == "fragmented_permissions") {
            perm = i < size/3 ? 5 : i < 2*size/3 ? 1 : 3; // rx, r, rw
        }
        r.frames.push_back(pfn);r.perms.push_back(perm);
    }
    return r;
}
std::vector<Record> runs(const Region& r, uint32_t lo, uint32_t limit, uint32_t cap=0) {
    std::vector<Record> out;
    uint32_t end=lo+limit;
    for (uint32_t i=lo;i<end;) {
        uint32_t j=i+1;
        while (j<end && (!cap || j-i<cap) && r.perms[j]==r.perms[i] && r.frames[j]==r.frames[j-1]+1) ++j;
        out.push_back({r.start+i,r.frames[i],j-i,r.perms[i],{}});
        i=j;
    }
    return out;
}
BAP make_bap(const Region& r) {
    BAP m;
    uint32_t cursor=0;
    for (uint32_t len : bap_sizes(r.size())) {
        auto group=runs(r,cursor,len);
        m.directory.push_back({static_cast<uint32_t>(m.records.size()),static_cast<uint32_t>(group.size())});
        m.records.insert(m.records.end(),group.begin(),group.end());
        cursor+=len;
    }
    ensure(cursor==r.size(), "BAP incomplete");
    return m;
}
const Record& search(const std::vector<Record>& v, uint32_t first, uint32_t count, uint64_t vpn) {
    uint32_t lo=first,hi=first+count;
    while (lo<hi) {uint32_t mid=lo+(hi-lo)/2; if(v[mid].vpn<=vpn) lo=mid+1; else hi=mid;}
    if (lo==first || vpn >= v[lo-1].vpn + v[lo-1].len) fail("record search gap");
    return v[lo-1];
}
IndexedRange make_indexed(const Region& r, const std::vector<Record>& recs) {
    IndexedRange m{recs,{}};
    uint32_t n=(r.size()+CAP-1)/CAP;
    m.bucket_directory.reserve(n);
    for (uint32_t b=0;b<n;++b) {
        uint64_t first_vpn=r.start+uint64_t(b)*CAP;
        uint64_t last_vpn=std::min(r.start+r.size()-1,first_vpn+CAP-1);
        auto it_first=std::upper_bound(recs.begin(),recs.end(),first_vpn,[](uint64_t v,const Record& x){return v<x.vpn;});
        auto it_last=std::upper_bound(recs.begin(),recs.end(),last_vpn,[](uint64_t v,const Record& x){return v<x.vpn;});
        ensure(it_first!=recs.begin() && it_last!=recs.begin(),"bad index");
        uint32_t first=static_cast<uint32_t>(it_first-recs.begin()-1);
        uint32_t last=static_cast<uint32_t>(it_last-recs.begin()-1);
        m.bucket_directory.push_back({first,last-first+1});
    }
    return m;
}

const Record& locate_bap(const Region& r, const BAP& b, uint64_t vpn) {
    uint32_t off=static_cast<uint32_t>(vpn-r.start);
    auto dir=b.directory[parent_index(r.size(),off)];
    return search(b.records,dir.first,dir.count,vpn);
}
const Record& locate_global(const std::vector<Record>& recs,uint64_t vpn) {
    return search(recs,0,static_cast<uint32_t>(recs.size()),vpn);
}
const Record& locate_indexed(const Region& r,const IndexedRange& m,uint64_t vpn) {
    uint32_t off=static_cast<uint32_t>(vpn-r.start);
    auto d=m.bucket_directory[off/CAP];
    return search(m.records,d.first,d.count,vpn);
}
uint64_t translate(const Record& rec,uint64_t vpn) {return rec.pfn+vpn-rec.vpn;}
void verify_one(const Region& r,const Record& rec,uint32_t off) {
    ensure(rec.vpn<=r.start+off && r.start+off<rec.vpn+rec.len,"bad record coverage");
    ensure(translate(rec,r.start+off)==r.frames[off],"bad physical mapping");
    ensure(rec.perm==r.perms[off],"bad permissions");
}
void verify_all(const Region& r,const BAP& bap,const std::vector<Record>& cap,
                const std::vector<Record>& unlimited,const IndexedRange& indexed) {
    for(uint32_t off=0;off<r.size();++off){
        uint64_t vpn=r.start+off;
        verify_one(r,locate_bap(r,bap,vpn),off);
        verify_one(r,locate_global(cap,vpn),off);
        verify_one(r,locate_global(unlimited,vpn),off);
        verify_one(r,locate_indexed(r,indexed,vpn),off);
    }
}
std::vector<uint64_t> make_trace(const Region& r,const BAP& b,const std::vector<Record>& cap,
                                 const std::string& pattern,uint32_t seed,uint32_t n){
    std::mt19937 rng(seed);
    std::uniform_int_distribution<uint32_t> uniform(0,r.size()-1);
    std::vector<uint64_t> trace;trace.reserve(n);
    if(pattern=="boundary_stress"){
        std::vector<uint32_t> points;
        auto add=[&](int64_t at){for(int d=-1;d<=1;++d){int64_t p=at+d;if(p>=0 && p<r.size())points.push_back(static_cast<uint32_t>(p));}};
        uint32_t cursor=0;
        for (auto slot : b.directory){add(cursor); uint32_t total=0;for(uint32_t j=slot.first;j<slot.first+slot.count;++j)total+=b.records[j].len;cursor+=total;}
        for(auto rec:cap)add(static_cast<int64_t>(rec.vpn-r.start));
        std::sort(points.begin(),points.end());points.erase(std::unique(points.begin(),points.end()),points.end());
        if(points.empty())points.push_back(0);
        for(uint32_t i=0;i<n;++i)trace.push_back(r.start+points[i%points.size()]);
    }else{
        uint32_t hot_start=r.size()/3;
        uint32_t hot_len=std::max(1U,std::min(r.size()/20,r.size()-hot_start));
        std::uniform_int_distribution<uint32_t> hot(0,hot_len-1);
        std::bernoulli_distribution hot_coin(.9);
        for(uint32_t i=0;i<n;++i){
            uint32_t off=0;
            if(pattern=="uniform_random")off=uniform(rng);
            else if(pattern=="sequential")off=i%r.size();
            else if(pattern=="hot_cold")off=hot_coin(rng)?hot_start+hot(rng):uniform(rng);
            else fail("unknown access pattern");
            trace.push_back(r.start+off);
        }
    }
    return trace;
}
volatile uint64_t g_checksum=0;
using Clock=std::chrono::steady_clock;
struct Results {std::array<double,4> median_ns; uint64_t checksum;};
Results benchmark(const Region& r,const BAP& bap,const std::vector<Record>& cap,
                  const std::vector<Record>& unlimited,const IndexedRange& idx,
                  const std::vector<uint64_t>& trace,uint32_t repeats){
    std::array<std::vector<double>,4> samples;
    uint64_t total_checksum=0;
    for(uint32_t round=0;round<repeats;++round){
        // Rotate measured lookup order to reduce systematic first/last bias.
        for(uint32_t x=0;x<4;++x){
            uint32_t method=(x+round)%4;
            auto run=[&](){
                uint64_t checksum=0;
                for(auto vpn:trace){
                    const Record* rec=nullptr;
                    switch(method){
                        case 0:rec=&locate_bap(r,bap,vpn);break;
                        case 1:rec=&locate_global(cap,vpn);break;
                        case 2:rec=&locate_global(unlimited,vpn);break;
                        case 3:rec=&locate_indexed(r,idx,vpn);break;
                    }
                    checksum += translate(*rec,vpn) ^ rec->perm;
                }
                return checksum;
            };
            uint64_t warm=run();
            auto begin=Clock::now();uint64_t sum=run();auto end=Clock::now();
            ensure(warm==sum,"warmup and timed checksums differ");
            total_checksum^=sum+(static_cast<uint64_t>(round)<<32)+method;
            samples[method].push_back(std::chrono::duration<double,std::nano>(end-begin).count()/trace.size());
        }
    }
    g_checksum = g_checksum ^ total_checksum;
    std::array<double,4> med{};
    for(uint32_t i=0;i<4;++i){auto& v=samples[i];std::sort(v.begin(),v.end());med[i]=v[v.size()/2];}
    return {med,total_checksum};
}
int main(int argc,char**argv){
    try{
        std::string out="results_v8/lookup_latency_v8.csv";
        uint32_t queries=4096,repeats=5;
        for(int i=1;i<argc;++i){
            std::string arg=argv[i];
            if((arg=="--out"||arg=="--queries"||arg=="--repeats") && i+1<argc){
                std::string value=argv[++i];
                if(arg=="--out")out=value;
                else if(arg=="--queries")queries=static_cast<uint32_t>(std::stoul(value));
                else repeats=static_cast<uint32_t>(std::stoul(value));
            }else fail("usage: lookup_benchmark_v8 [--out FILE] [--queries N] [--repeats N]");
        }
        ensure(queries>0 && repeats>0,"queries/repeats must be > 0");
        std::ofstream file(out);ensure(bool(file),"output directory missing or path unwritable");
        file<<"start_vpn,region_size_pages,physical_layout,access_pattern,seed,queries,repeats,"
              "bap_records,range_cap512_records,range_unbounded_records,bap_directory_slots,range_bucket_slots,"
              "bap_metadata_bytes,range_cap512_metadata_bytes,range_unbounded_metadata_bytes,range_indexed_metadata_bytes,"
              "bap_ns_per_lookup,range_cap512_ns_per_lookup,range_unbounded_ns_per_lookup,range_indexed_ns_per_lookup,checksum\n";
        file<<std::fixed<<std::setprecision(4);
        std::array<uint32_t,3> sizes{1000,4096,10000};
        std::array<uint32_t,3> starts{0,1,7};
        std::array<std::string,5> layouts{"contiguous","contiguous_phase_matched","fragmented_32","mixed_permissions","fragmented_permissions"};
        std::array<std::string,4> patterns{"uniform_random","sequential","hot_cold","boundary_stress"};
        uint32_t ncases=0;
        for(uint32_t size:sizes)for(uint32_t start:starts)for(const auto& layout:layouts){
            Region r=make_region(start,size,layout);
            BAP bap=make_bap(r);
            auto cap=runs(r,0,size,CAP),unlimited=runs(r,0,size);
            auto indexed=make_indexed(r,cap);
            verify_all(r,bap,cap,unlimited,indexed);
            uint64_t bbytes=REGION_DESCRIPTOR_BYTES+sizeof(Record)*bap.records.size()+sizeof(DirectorySlot)*bap.directory.size();
            uint64_t cbytes=REGION_DESCRIPTOR_BYTES+sizeof(Record)*cap.size();
            uint64_t ubytes=REGION_DESCRIPTOR_BYTES+sizeof(Record)*unlimited.size();
            uint64_t ibytes=cbytes+sizeof(DirectorySlot)*indexed.bucket_directory.size();
            for(const auto& pattern:patterns)for(uint32_t seed=1;seed<=3;++seed){
                auto trace=make_trace(r,bap,cap,pattern,seed,queries);
                auto z=benchmark(r,bap,cap,unlimited,indexed,trace,repeats);
                file<<start<<','<<size<<','<<layout<<','<<pattern<<','<<seed<<','<<queries<<','<<repeats<<','
                    <<bap.records.size()<<','<<cap.size()<<','<<unlimited.size()<<','
                    <<bap.directory.size()<<','<<indexed.bucket_directory.size()<<','
                    <<bbytes<<','<<cbytes<<','<<ubytes<<','<<ibytes<<','
                    <<z.median_ns[0]<<','<<z.median_ns[1]<<','<<z.median_ns[2]<<','<<z.median_ns[3]<<','<<z.checksum<<'\n';
                ++ncases;
            }
        }
        std::cerr<<"PASS: validated every address and permission for all layouts. "
                 <<ncases<<" timing rows; checksum="<<g_checksum<<"\n";
    }catch(const std::exception& e){std::cerr<<"ERROR: "<<e.what()<<'\n';return 1;}
}
