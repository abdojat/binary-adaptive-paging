// BAP v8.1 controlled metadata-lookup ablation (not OS/TLB performance).
// Two partition shapes x two parent selectors, with identical record layouts
// and exact identical VA->PFN+permission semantics.
// Copyright (c) 2026 BAP research project; educational experimental code.
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

constexpr uint32_t CAP=512;
constexpr uint64_t PFN_BASE=8192;
constexpr uint64_t REGION_DESC_BYTES=32;
struct Record {uint64_t vpn,pfn;uint32_t len;uint8_t perm;uint8_t pad[3]{};};
struct Slot {uint32_t first,count;};
static_assert(sizeof(Record)==24 && sizeof(Slot)==8);
struct Region {uint64_t start;std::vector<uint64_t> pfn;std::vector<uint8_t> perm;
    uint32_t size()const{return static_cast<uint32_t>(pfn.size());}};
struct Partition {std::vector<Record> records;std::vector<Slot> slots;
    std::vector<uint32_t> relative_starts;};
inline void req(bool b,const char* s){if(!b)throw std::runtime_error(s);}
uint32_t bap_idx(uint32_t size,uint32_t off){
    // Caller validates offset once in the common lookup path.
    const uint32_t full=size/CAP, prefix=full*CAP;
    if(off<prefix)return off/CAP;
    const uint32_t rem=size-prefix;
    const uint32_t xor_value=(off-prefix)^rem;
    // 0 <= off-prefix < rem guarantees xor_value != 0.
    const unsigned k=std::bit_width(xor_value)-1;
    return full+std::popcount(rem>>(k+1));
}
std::vector<uint32_t> bap_sizes(uint32_t size){
    std::vector<uint32_t> v;
    for(int bit=31;bit>=0;--bit)if((size>>bit)&1U){
        uint64_t rem=1ULL<<bit;
        while(rem){uint32_t take=static_cast<uint32_t>(std::min<uint64_t>(CAP,rem));
            v.push_back(take);rem-=take;}
    }
    return v;
}
std::vector<uint32_t> fixed_sizes(uint32_t size){
    std::vector<uint32_t> v;
    for(uint32_t i=0;i<size;){uint32_t take=std::min(CAP,size-i);v.push_back(take);i+=take;}
    return v;
}
Region make_region(uint64_t start,uint32_t size,const std::string& layout){
    Region r{start,{},{}};r.pfn.reserve(size);r.perm.reserve(size);
    for(uint32_t i=0;i<size;++i){
        uint64_t p=PFN_BASE+i; uint8_t a=3;
        if(layout=="contiguous_phase_matched")p+=start%CAP;
        else if(layout=="fragmented_32"||layout=="fragmented_permissions")p+=16ULL*(i/32);
        else req(layout=="contiguous"||layout=="mixed_permissions","unknown layout");
        if(layout=="mixed_permissions"||layout=="fragmented_permissions")
            a=(i<size/3?5:(i<2*size/3?1:3));
        r.pfn.push_back(p);r.perm.push_back(a);
    }
    return r;
}
Partition make_partition(const Region& r,const std::vector<uint32_t>& sizes){
    Partition x;
    uint32_t off=0;
    for(uint32_t len:sizes){
        req(off+len<=r.size() && len>0,"invalid sizes");
        x.relative_starts.push_back(off);
        const uint32_t first=static_cast<uint32_t>(x.records.size()),stop=off+len;
        for(uint32_t i=off;i<stop;){
            uint32_t j=i+1;
            while(j<stop && r.perm[j]==r.perm[i] && r.pfn[j]==r.pfn[j-1]+1)++j;
            x.records.push_back({r.start+i,r.pfn[i],j-i,r.perm[i],{}});i=j;
        }
        x.slots.push_back({first,static_cast<uint32_t>(x.records.size())-first});
        off+=len;
    }
    req(off==r.size(),"incomplete partition");return x;
}
const Record& search_records(const Partition& x,uint32_t parent,uint64_t vpn){
    req(parent<x.slots.size(),"bad parent");
    Slot s=x.slots[parent];uint32_t lo=s.first,hi=s.first+s.count;
    while(lo<hi){uint32_t mid=lo+(hi-lo)/2;if(x.records[mid].vpn<=vpn)lo=mid+1;else hi=mid;}
    req(lo>s.first,"record lookup left-of-range");
    const Record& rec=x.records[lo-1];
    req(vpn>=rec.vpn && vpn<rec.vpn+rec.len,"record lookup gap");return rec;
}
uint32_t binary_parent(const Partition& x,uint32_t off){
    auto it=std::upper_bound(x.relative_starts.begin(),x.relative_starts.end(),off);
    // Partition starts at 0, and off is validated by the common lookup.
    return static_cast<uint32_t>((it-x.relative_starts.begin())-1);
}
// Method identifiers: 0=BAP arithmetic; 1=BAP binary parent;
// 2=fixed512 arithmetic; 3=fixed512 binary parent.
const Record& locate(const Region& r,const Partition& bap,const Partition& grid,
                     uint64_t vpn,int method){
    req(vpn>=r.start && vpn<r.start+r.size(),"outside region");
    uint32_t off=static_cast<uint32_t>(vpn-r.start);
    if(method==0)return search_records(bap,bap_idx(r.size(),off),vpn);
    if(method==1)return search_records(bap,binary_parent(bap,off),vpn);
    if(method==2)return search_records(grid,off/CAP,vpn);
    if(method==3)return search_records(grid,binary_parent(grid,off),vpn);
    throw std::runtime_error("invalid method");
}
void check_region(const Region& r,const Partition& b,const Partition& g){
    req(b.records.size()>=b.slots.size()&&g.records.size()>=g.slots.size(),"bad records");
    for(uint32_t off=0;off<r.size();++off){
        uint64_t vpn=r.start+off;
        req(bap_idx(r.size(),off)==binary_parent(b,off),"BAP parent rank mismatch");
        req(off/CAP==binary_parent(g,off),"fixed parent index mismatch");
        for(int m=0;m<4;++m){const Record& x=locate(r,b,g,vpn,m);
            req(x.pfn+vpn-x.vpn==r.pfn[off],"physical error");
            req(x.perm==r.perm[off],"permission error");
            req((x.perm&(~r.perm[off]))==0,"unexpected privilege");
        }
    }
}
std::vector<uint64_t> trace(const Region& r,const Partition& b,const Partition& g,
                            const std::string& name,uint32_t seed,uint32_t n){
    std::mt19937 rng(seed);std::uniform_int_distribution<uint32_t> uni(0,r.size()-1);
    std::vector<uint64_t> a;a.reserve(n);
    if(name=="boundary_stress"){
        std::vector<uint32_t> points;
        auto add=[&](int64_t i){for(int d=-1;d<=1;++d){auto z=i+d;
            if(z>=0 && z<static_cast<int64_t>(r.size()))points.push_back(static_cast<uint32_t>(z));}};
        for(auto s:b.relative_starts)add(s);
        for(auto s:g.relative_starts)add(s);
        for(auto& x:b.records)add(static_cast<int64_t>(x.vpn-r.start));
        for(auto& x:g.records)add(static_cast<int64_t>(x.vpn-r.start));
        std::sort(points.begin(),points.end());points.erase(std::unique(points.begin(),points.end()),points.end());
        req(!points.empty(),"empty boundary points");
        for(uint32_t i=0;i<n;++i)a.push_back(r.start+points[i%points.size()]);
    }else {
        uint32_t hot_start=r.size()/3;
        uint32_t hot_len=std::max(1U,std::min(r.size()/20,r.size()-hot_start));
        std::uniform_int_distribution<uint32_t> hot(0,hot_len-1);
        std::bernoulli_distribution coin(.9);
        for(uint32_t i=0;i<n;++i){uint32_t off=0;
            if(name=="uniform_random")off=uni(rng);
            else if(name=="sequential")off=i%r.size();
            else if(name=="hot_cold")off=coin(rng)?hot_start+hot(rng):uni(rng);
            else throw std::runtime_error("unknown pattern");
            a.push_back(r.start+off);
        }
    }
    return a;
}
volatile uint64_t global_sink=0;
struct Timings{std::array<double,4> ns;uint64_t checksum;};
Timings benchmark(const Region& r,const Partition& b,const Partition& g,
                  const std::vector<uint64_t>& a,unsigned repeats){
    std::array<std::vector<double>,4> sample;
    uint64_t total=0;
    for(unsigned rep=0;rep<repeats;++rep){
        for(int k=0;k<4;++k){
            int method=(k+rep)%4;
            auto run=[&](){uint64_t check=0;
                for(auto vpn:a){auto& rec=locate(r,b,g,vpn,method);
                    check+=((rec.pfn+vpn-rec.vpn)^rec.perm);}
                return check;};
            uint64_t warm=run();auto t0=std::chrono::steady_clock::now();
            uint64_t chk=run();auto t1=std::chrono::steady_clock::now();
            req(warm==chk,"warmup mismatch");
            sample[method].push_back(std::chrono::duration<double,std::nano>(t1-t0).count()/a.size());
            total^=chk+(static_cast<uint64_t>(rep)<<32)+static_cast<uint64_t>(method);
        }
    }
    global_sink=global_sink^total;
    std::array<double,4> result{};
    for(int method=0;method<4;++method){auto& v=sample[method];std::sort(v.begin(),v.end());result[method]=v[v.size()/2];}
    return {result,total};
}
void self_test(){
    for(uint32_t size=1;size<=1030;++size){
        Region r=make_region(1,size,"fragmented_permissions");
        auto b=make_partition(r,bap_sizes(size)),g=make_partition(r,fixed_sizes(size));
        check_region(r,b,g);
    }
    std::cerr<<"PASS: exhaustive parent selection, translation and permissions (sizes 1..1030)\n";
}
int main(int argc,char**argv){try{
    std::string output="results_v81/ablation_v81.csv";
    uint32_t queries=4096,repeats=5;bool validate=false;
    for(int i=1;i<argc;++i){std::string x=argv[i];
        if(x=="--validate")validate=true;
        else if((x=="--out"||x=="--queries"||x=="--repeats")&&i+1<argc){
            std::string val=argv[++i];if(x=="--out")output=val;
            else if(x=="--queries")queries=static_cast<uint32_t>(std::stoul(val));
            else repeats=static_cast<uint32_t>(std::stoul(val));
        }else throw std::runtime_error("usage: lookup_ablation_v81 [--validate] [--out PATH] [--queries N] [--repeats N]");
    }
    req(queries>0&&repeats>0,"queries and repeats must be positive");
    if(validate)self_test();
    std::ofstream f(output);req(bool(f),"cannot open output; create directory first");
    f<<"start_vpn,region_size_pages,physical_layout,access_pattern,seed,queries,repeats,"
      "bap_parent_count,fixed_parent_count,bap_records,fixed_records,bap_metadata_bytes,"
      "fixed_metadata_bytes,bap_arithmetic_ns,bap_binary_parent_ns,"
      "fixed_arithmetic_ns,fixed_binary_parent_ns,checksum\n";
    f<<std::fixed<<std::setprecision(4);
    std::array<uint32_t,3> sizes{1000,4096,10000},starts{0,1,7};
    std::array<std::string,5> layouts{"contiguous","contiguous_phase_matched","fragmented_32",
                                      "mixed_permissions","fragmented_permissions"};
    std::array<std::string,4> patterns{"uniform_random","sequential","hot_cold","boundary_stress"};
    int count=0;
    for(auto size:sizes)for(auto start:starts)for(const auto& layout:layouts){
        Region r=make_region(start,size,layout);
        Partition b=make_partition(r,bap_sizes(size)),g=make_partition(r,fixed_sizes(size));
        check_region(r,b,g);
        auto bbytes=REGION_DESC_BYTES+24*b.records.size()+8*b.slots.size();
        auto gbytes=REGION_DESC_BYTES+24*g.records.size()+8*g.slots.size();
        for(const auto& pat:patterns)for(uint32_t seed=1;seed<=3;++seed){
            auto a=trace(r,b,g,pat,seed,queries);
            auto v=benchmark(r,b,g,a,repeats);
            f<<start<<','<<size<<','<<layout<<','<<pat<<','<<seed<<','<<queries<<','<<repeats<<','
              <<b.slots.size()<<','<<g.slots.size()<<','<<b.records.size()<<','<<g.records.size()<<','
              <<bbytes<<','<<gbytes<<','<<v.ns[0]<<','<<v.ns[1]<<','<<v.ns[2]<<','<<v.ns[3]
              <<','<<v.checksum<<'\n';++count;
        }
    }
    std::cerr<<"PASS: "<<count<<" ablation rows; four correct variants; checksum="<<global_sink<<"\n";
}catch(const std::exception& e){std::cerr<<"ERROR: "<<e.what()<<'\n';return 1;}}
