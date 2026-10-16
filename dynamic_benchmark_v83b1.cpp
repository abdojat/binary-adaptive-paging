// BAP v8.3B-1: native C++20 DYNAMIC UPDATE pilot (software only).
// Six methods; identical update logs, flat oracle, balanced ordered range maps.
// Experimental timing ONLY, not kernel/TLB measurements or a speedup claim.
#include <algorithm>
#include <array>
#include <bit>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <numeric>
#include <optional>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
using u32=uint32_t; using u64=uint64_t;
constexpr u32 K=512;
[[noreturn]] void fail(const std::string &s){throw std::runtime_error(s);}
void require(bool b,const std::string& s){if(!b)fail(s);}
struct Page{u64 pfn;u32 perm;bool operator==(const Page&)const=default;};
using Opt=std::optional<Page>;
struct Run{u32 end;u64 pfn;u32 perm;}; // map key is start
using Tree=std::map<u32,Run>; // balanced red-black tree, NOT a global vector scan
bool adjacent(u32 first,const Run& a,u32 second,const Run& b){
 return a.end==second&&a.perm==b.perm&&a.pfn+(a.end-first)==b.pfn;
}
void put_merge(Tree &t,u32 start,const Run& r){
 auto [it,good]=t.emplace(start,r);
 require(good,"duplicate run start");
 while(it!=t.begin()){
   auto prev=std::prev(it);
   if(!adjacent(prev->first,prev->second,it->first,it->second))break;
   prev->second.end=it->second.end;
   it=t.erase(it);it=prev;
 }
 while(true){auto next=std::next(it);if(next==t.end()||!adjacent(it->first,it->second,next->first,next->second))break;
   it->second.end=next->second.end;t.erase(next);
 }
}
void patch_tree(Tree &t,u32 lo,const std::vector<Opt>& repl){
 const u32 hi=lo+static_cast<u32>(repl.size());
 auto it=t.upper_bound(lo);if(it!=t.begin())--it;
 std::vector<std::pair<u32,Run>> add;
 while(it!=t.end()&&it->first<hi){
   u32 first=it->first;Run r=it->second;
   if(r.end<=lo){++it;continue;}
   if(first<lo)add.emplace_back(first,Run{lo,r.pfn,r.perm});
   if(r.end>hi)add.emplace_back(hi,Run{r.end,r.pfn+(hi-first),r.perm});
   it=t.erase(it);
 }
 for(u32 j=0;j<repl.size();){
   if(!repl[j]){++j;continue;}
   u32 stop=j+1;
   while(stop<repl.size()&&repl[stop]&&repl[stop]->perm==repl[j]->perm &&
         repl[stop]->pfn==repl[stop-1]->pfn+1)++stop;
   add.emplace_back(lo+j,Run{lo+stop,repl[j]->pfn,repl[j]->perm});j=stop;
 }
 std::sort(add.begin(),add.end(),[](auto&a,auto&b){return a.first<b.first;});
 for(const auto& [first,r]:add)put_merge(t,first,r);
}
Opt find_in(const Tree&t,u32 off){
 auto it=t.upper_bound(off);if(it==t.begin())return std::nullopt;
 --it;if(off>=it->second.end)return std::nullopt;
 return Page{it->second.pfn+(off-it->first),it->second.perm};
}
std::vector<u32> parent_sizes(u32 size,int kind){
 std::vector<u32> a;u32 full=size/K;
 for(u32 i=0;i<full;++i)a.push_back(K);
 u32 rem=size-full*K;
 if(rem){if(kind==0){for(int bit=31;bit>=0;--bit)if(rem&(1U<<bit))a.push_back(1U<<bit);}
 else a.push_back(rem);}
 if(kind==2)a={size};
 return a;
}
u32 bap_idx(u32 size,u32 off){
 u32 full=size/K,prefix=full*K;if(off<prefix)return off/K;
 u32 rem=size-prefix,x=(off-prefix)^rem;
 require(x!=0,"bad bap index");unsigned k=std::bit_width(x)-1;
 return full+std::popcount(rem>>(k+1));
}
struct Model{
 u32 n;int kind;bool overlay;u32 threshold;std::vector<u32> boundary;std::vector<Tree> parents;
 std::map<u32,Opt> changes;std::unordered_map<u64,u32> owner;
 u32 compact_count=0,peak_overlay=0;u64 record_scans=0;
 Model(const std::vector<Opt>& v,int kind_,bool overlay_,double thresh):n(v.size()),kind(kind_),overlay(overlay_),threshold(std::max<u32>(1,std::ceil(n*thresh))){
   boundary.push_back(0);for(u32 s:parent_sizes(n,kind))boundary.push_back(boundary.back()+s);
   require(boundary.back()==n,"invalid partition");parents.resize(boundary.size()-1);
   for(u32 i=0;i<n;++i){if(v[i])owner.emplace(v[i]->pfn,i);}
   require(owner.size()==static_cast<size_t>(std::count_if(v.begin(),v.end(),[](const Opt&x){return bool(x);})),"initial PFN alias");
   for(u32 i=0;i<n;){u32 parent=index(i),end=boundary[parent+1],j=i+1;
     if(!v[i]){++i;continue;}
     while(j<end&&v[j]&&v[j]->perm==v[i]->perm&&v[j]->pfn==v[j-1]->pfn+1)++j;
     parents[parent].emplace(i,Run{j,v[i]->pfn,v[i]->perm});i=j;
   }
 }
 u32 index(u32 off)const{
   if(kind==1)return off/K;
   if(kind==2)return 0;
   return bap_idx(n,off);
 }
 Opt base(u32 off)const{return find_in(parents[index(off)],off);}
 Opt lookup(u32 off)const{if(off>=n)return std::nullopt;
   if(overlay){auto it=changes.find(off);if(it!=changes.end())return it->second;}
   return base(off);
 }
 void base_patch(u32 lo,const std::vector<Opt>& r){
   u32 hi=lo+static_cast<u32>(r.size()),cur=lo;
   while(cur<hi){u32 idx=index(cur),stop=std::min(hi,boundary[idx+1]);
     std::vector<Opt> sub(r.begin()+(cur-lo),r.begin()+(stop-lo));
     patch_tree(parents[idx],cur,sub);cur=stop;
   }
 }
 void apply(u32 lo,const std::vector<Opt>& r,int op){
   u32 len=static_cast<u32>(r.size());require(len>0&&lo<=n&&len<=n-lo,"update bounds");
   std::vector<Opt> old;old.reserve(len);
   std::unordered_set<u64> new_pfns;
   for(u32 i=0;i<len;++i){auto prev=lookup(lo+i);old.push_back(prev);
     if(op==0)require(!prev&&r[i],"map onto mapped");
     if(op==1)require(prev&&!r[i],"unmap absent");
     if(op==2)require(prev&&r[i]&&prev->pfn==r[i]->pfn,"protect invalid");
     if(op==3)require(len==1&&prev&&r[i]&&prev->pfn!=r[i]->pfn,"cow invalid");
     if(r[i]){require(new_pfns.insert(r[i]->pfn).second,"duplicate PFN in replacement");
       auto it=owner.find(r[i]->pfn);require(it==owner.end()||(it->second>=lo&&it->second<lo+len),"PFN alias");
     }
   }
   for(const auto&p:old)if(p)owner.erase(p->pfn);
   for(u32 i=0;i<len;++i)if(r[i])owner[r[i]->pfn]=lo+i;
   if(!overlay)base_patch(lo,r);
   else{
     for(u32 i=0;i<len;++i){u32 at=lo+i;if(r[i]==base(at))changes.erase(at);else changes[at]=r[i];}
     peak_overlay=std::max<u32>(peak_overlay,changes.size());
     if(changes.size()>=threshold){
       // Same adjacent exception batching and compaction for all three schemes.
       auto it=changes.begin();while(it!=changes.end()){
         u32 begin=it->first;std::vector<Opt> batch{it->second};++it;
         while(it!=changes.end()&&it->first==begin+batch.size()){batch.push_back(it->second);++it;}
         base_patch(begin,batch);
       }
       changes.clear();++compact_count;
     }
   }
 }
 u64 records()const{u64 s=0;for(const auto& p:parents)s+=p.size();return s;}
 void invariant()const{
  for(u32 i=0;i<parents.size();++i){u32 prev=boundary[i];bool has=false;u32 prev_start=0;Run prev_record{};
    for(const auto&[start,r]:parents[i]){
       require(start>=boundary[i]&&r.end<=boundary[i+1]&&start<r.end,"record out-of-parent");
       require(start>=prev,"overlap");
       if(has)require(!adjacent(prev_start,prev_record,start,r),"unmerged neighbors");
       prev=r.end;has=true;prev_start=start;prev_record=r;
    }
  }
 }
};
struct Op{int type;u32 start;std::vector<Opt> replacement;std::vector<u32> queries;};
struct Scenario{std::vector<Opt> initial;std::vector<Op> operations;};
struct Oracle{std::vector<Opt> p;
 explicit Oracle(const std::vector<Opt>&v):p(v){}
 void apply(const Op&op){std::copy(op.replacement.begin(),op.replacement.end(),p.begin()+op.start);}
};
std::vector<Opt> initial(u32 n,int layout){
 std::vector<Opt> v(n);
 for(u32 i=0;i<n;++i){if(i%17==0)continue;
  u64 p=8192+i+((layout==1||layout==3)?16ULL*(i/32):0ULL);
  u32 perm=(layout==2||layout==3)?(i<n/3?5:i<2*n/3?1:3):3;
  v[i]=Page{p,perm};
 }return v;
}
int choose_type(const std::string& mix,u32 seq){
 if(mix=="mixed"){const int v[]={0,1,2,3,2,3,1,0};return v[seq%8];}
 if(mix=="protect_heavy"){const int v[]={2,2,2,2,0,1,2,3};return v[seq%8];}
 if(mix=="cow_heavy"){const int v[]={3,3,3,3,0,1,2,3};return v[seq%8];}
 fail("unknown mix");
}
Scenario make_scenario(u32 n,u32 start,int layout,const std::string&mix,u32 seed,u32 nops,u32 queries_per_op){
 std::mt19937 rng(seed*1000003u+n*997u+start*53u+layout*17u);
 Scenario sc;sc.initial=initial(n,layout);Oracle oracle(sc.initial);
 std::uniform_int_distribution<u32> any(0,n-1);
 for(u32 seq=0;seq<nops;++seq){
   int type=choose_type(mix,seq);u32 len=type==3?1:1+(rng()%3);
   std::vector<u32> valid;
   for(u32 i=0;i+len<=n;++i){
     bool good=true;
     for(u32 j=0;j<len;++j){
       if(bool(oracle.p[i+j])!=(type!=0)){good=false;break;}
     }
     if(good)valid.push_back(i);
   }
   if(valid.empty()&&len>1){len=1;for(u32 i=0;i<n;++i)
     if(bool(oracle.p[i])==(type!=0))valid.push_back(i);
   }
   require(!valid.empty(),"no valid operation");
   u32 at=valid[rng()%valid.size()];Op op{type,at,{}, {}};
   for(u32 j=0;j<len;++j){
     if(type==1){op.replacement.emplace_back();continue;}
     if(type==0||type==3)op.replacement.emplace_back(Page{10000000ULL+seq*128ULL+j,3});
     else {auto p=*oracle.p[at+j];p.perm=(p.perm==1?3:1);op.replacement.emplace_back(p);}
   }
   oracle.apply(op);
   for(u32 q=0;q<queries_per_op;++q){
     u32 v=(q<queries_per_op/2)?any(rng):std::min<u32>(n-1,n/3+static_cast<u32>(rng()%std::max<u32>(1,n/20)));
     op.queries.push_back(v);
   }
   sc.operations.push_back(std::move(op));
 }
 return sc;
}
u64 checksum(const Opt &p,u32 off){return p?((p->pfn+off)*1315423911ULL ^ p->perm):0x9e3779b97f4a7c15ULL;}
volatile u64 sink=0;
struct Row{double update_ns,lookup_ns,mixed_ns;u64 records,parents,exceptions,peak,compactions,check;};
void oracle_gate(const Scenario&sc,int kind,bool overlay,double threshold){
 Oracle oracle(sc.initial);Model model(sc.initial,kind,overlay,threshold);
 auto compare_all=[&](){
   model.invariant();
   for(u32 i=0;i<oracle.p.size();++i){
      require(model.lookup(i)==oracle.p[i],"oracle mismatch at page "+std::to_string(i));
   }
   require(model.lookup(oracle.p.size())==std::nullopt,"out-of-region mapping");
 };
 compare_all();
 for(const auto&op:sc.operations){model.apply(op.start,op.replacement,op.type);oracle.apply(op);compare_all();}
}
Row measure(const Scenario&sc,int kind,bool overlay,double threshold){
 Model model(sc.initial,kind,overlay,threshold);u64 update_total=0,lookup_total=0,ck=0;
 using Clock=std::chrono::steady_clock;
 for(const auto& op:sc.operations){
   auto a=Clock::now();model.apply(op.start,op.replacement,op.type);auto b=Clock::now();
   update_total+=std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count();
   auto c=Clock::now();for(auto off:op.queries)ck+=checksum(model.lookup(off),off);
   auto d=Clock::now();lookup_total+=std::chrono::duration_cast<std::chrono::nanoseconds>(d-c).count();
 }
 model.invariant();sink=sink ^ ck;
 double n=sc.operations.size(),q=sc.operations[0].queries.size();
 return {update_total/n,lookup_total/(n*q),(update_total+lookup_total)/(n*q),
 model.records(),model.parents.size(),model.changes.size(),model.peak_overlay,model.compact_count,ck};
}
void self_test(){
 // Atomic rejection tests: already mapped destination and active-PFN alias.
 for(int kind=0;kind<3;++kind)for(int ov=0;ov<2;++ov){
   auto init=initial(13,0); Model m(init,kind,ov,.05);
   std::vector<Opt> before;
   for(u32 i=0;i<13;++i)before.push_back(m.lookup(i));
   for(int which=0;which<2;++which){
     bool rejected=false;
     try{
       if(which==0)m.apply(1,{Page{999999,3}},0); // already mapped
       else m.apply(0,{Page{init[1]->pfn,3}},0); // alias with mapped page 1
     }catch(const std::runtime_error&){rejected=true;}
     require(rejected,"invalid update wrongly accepted");
     for(u32 i=0;i<13;++i)require(m.lookup(i)==before[i],"rejected update was not atomic");
   }
 }
 for(u32 size:{13U,19U,513U,1000U})for(int layout=0;layout<4;++layout){
  Scenario sc=make_scenario(size,1,layout,"mixed",3,32,8);
  for(int kind=0;kind<3;++kind)for(int ov=0;ov<2;++ov)oracle_gate(sc,kind,ov,.05);
 }
 std::cerr<<"PASS: six-model dynamic lookup/update semantic oracle on 4 sizes x 4 layouts\n";
}
int main(int argc,char**argv){try{
 std::string out="results_v83b1/native_update_pilot.csv";int updates=128,queries=16;bool validate=false;
 for(int i=1;i<argc;++i){std::string arg=argv[i];if(arg=="--validate")validate=true;
 else if((arg=="--out"||arg=="--updates"||arg=="--queries")&&i+1<argc){std::string v=argv[++i];
   if(arg=="--out")out=v;else if(arg=="--updates")updates=std::stoi(v);else queries=std::stoi(v);
 }else fail("usage: dynamic_benchmark_v83b1 [--validate] [--out path] [--updates N] [--queries N]");}
 require(updates>=8&&queries>=2,"updates>=8 queries>=2 required");
 if(validate)self_test();
 std::ofstream f(out);require(bool(f),"cannot open CSV; create directory first");
 f<<"region_pages,start_vpn,layout,mix,seed,method,updates,queries_per_update,update_ns_per_op,lookup_ns_per_query,mixed_ns_per_query,base_records,parent_count,pending_exceptions,peak_exceptions,compactions,checksum,oracle_verified,native_memory_bytes_measured,tlb_measured\n";
 f<<std::fixed<<std::setprecision(4);
 int count=0;
 const std::array<std::string,2> mixes{"mixed","protect_heavy"};
 for(u32 size:{1000U,4096U})for(u32 start:{0U,1U})for(int layout:{0,3})for(const auto&mix:mixes)for(u32 seed:{1U,2U,3U}){
   auto sc=make_scenario(size,start,layout,mix,seed,updates,queries);
   int shift=seed%6;
   for(int m=0;m<6;++m){int method=(m+shift)%6,kind=method/2;bool overlay=method%2;
     oracle_gate(sc,kind,overlay,.05); // entirely outside timed pass
     auto row=measure(sc,kind,overlay,.05);
     f<<size<<','<<start<<','<<(layout==0?"contiguous":"fragmented_permissions")<<','<<mix<<','<<seed<<','
      <<(kind==0?"bap":kind==1?"fixed":"ranges")<<(overlay?"_overlay":"_eager")<<','<<updates<<','<<queries<<','
      <<row.update_ns<<','<<row.lookup_ns<<','<<row.mixed_ns<<','<<row.records<<','<<row.parents<<','
      <<row.exceptions<<','<<row.peak<<','<<row.compactions<<','<<row.check<<",YES,NO,NO\n";
     ++count;
   }
 }
 std::cerr<<"PASS: "<<count<<" verified pilot rows; per-case checksums saved. Timings are exploratory only.\n";
}catch(const std::exception&e){std::cerr<<"ERROR: "<<e.what()<<'\n';return 1;}}
