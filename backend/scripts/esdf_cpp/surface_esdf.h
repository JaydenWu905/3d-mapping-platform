#pragma once
// Signed Euclidean distance to the piecewise-linear native TSDF zero surface.
// Native integer samples retain world coordinates. Target centers require all
// eight cell corners (weight >= 2). No inferred/free-space allocation.
#include "voxel_input.h"
#include "live_progress.h"
#include <Eigen/Geometry>
#include <algorithm>
#include <numeric>
#include <unordered_map>
#include <voxblox/io/layer_io.h>
namespace surface_esdf {
using Vec = Eigen::Vector3d;
using Id = distance_input::Index;
struct Hash { size_t operator()(const Id& i) const {size_t h=0; for(int x:i) h^=std::hash<int>()(x)+0x9e3779b9+(h<<6)+(h>>2); return h;} };
struct Sample {float sdf,weight;};
using Samples=std::unordered_map<Id,Sample,Hash>;
struct Triangle {Vec a,b,c;};
inline double triangle_distance2(const Vec& p,const Triangle& t) {
    // Closest point on triangle, Ericson region tests, with segment fallback.
    Vec ab=t.b-t.a, ac=t.c-t.a, ap=p-t.a;
    double d1=ab.dot(ap),d2=ac.dot(ap);
    if(d1<=0 && d2<=0)return ap.squaredNorm();
    Vec bp=p-t.b; double d3=ab.dot(bp),d4=ac.dot(bp);
    if(d3>=0 && d4<=d3)return bp.squaredNorm();
    double vc=d1*d4-d3*d2;
    if(vc<=0 && d1>=0 && d3<=0)return (p-(t.a+(d1/(d1-d3))*ab)).squaredNorm();
    Vec cp=p-t.c; double d5=ab.dot(cp),d6=ac.dot(cp);
    if(d6>=0 && d5<=d6)return cp.squaredNorm();
    double vb=d5*d2-d1*d6;
    if(vb<=0 && d2>=0 && d6<=0)return (p-(t.a+(d2/(d2-d6))*ac)).squaredNorm();
    double va=d3*d6-d5*d4;
    if(va<=0 && d4-d3>=0 && d5-d6>=0)return (p-(t.b+((d4-d3)/((d4-d3)+(d5-d6)))*(t.c-t.b))).squaredNorm();
    double inv=1/(va+vb+vc);
    return (p-(t.a+ab*(vb*inv)+ac*(vc*inv))).squaredNorm();
}
struct Node {Vec lo,hi;size_t begin,end;int left=-1,right=-1;};
class Bvh {
    std::vector<Triangle>& tris; std::vector<Node> nodes;
    LiveProgress* progress_; size_t indexed_=0;
    int build(size_t b,size_t e) {
        Node n; n.lo=Vec::Constant(INFINITY); n.hi=Vec::Constant(-INFINITY); n.begin=b;n.end=e;
        Vec clo=n.lo,chi=n.hi;
        for(size_t j=b;j<e;++j){const auto& t=tris[j];n.lo=n.lo.cwiseMin(t.a).cwiseMin(t.b).cwiseMin(t.c);n.hi=n.hi.cwiseMax(t.a).cwiseMax(t.b).cwiseMax(t.c);Vec c=(t.a+t.b+t.c)/3;clo=clo.cwiseMin(c);chi=chi.cwiseMax(c);}
        int k=nodes.size();nodes.push_back(n);
        if(e-b>8){Eigen::Index axis; (chi-clo).maxCoeff(&axis);size_t m=(b+e)/2;
            std::nth_element(tris.begin()+b,tris.begin()+m,tris.begin()+e,[axis](const Triangle& x,const Triangle& y){return x.a[axis]+x.b[axis]+x.c[axis]<y.a[axis]+y.b[axis]+y.c[axis];});
            int l=build(b,m),r=build(m,e);nodes[k].left=l;nodes[k].right=r;}
        else if(progress_){indexed_+=e-b;if(indexed_%4096<8 || indexed_==tris.size())progress_->emit("building_index",indexed_,tris.size(),"三角形");}
        return k;
    }
    double box(const Vec& p,int k) const {const auto& n=nodes[k];return (n.lo-p).cwiseMax(Vec::Zero()).squaredNorm()+(p-n.hi).cwiseMax(Vec::Zero()).squaredNorm();}
    void query(const Vec& p,int k,double& best) const {
        if(box(p,k)>best)return;const auto& n=nodes[k];
        if(n.left<0){for(size_t j=n.begin;j<n.end;++j)best=std::min(best,triangle_distance2(p,tris[j]));return;}
        int a=n.left,b=n.right;if(box(p,a)>box(p,b))std::swap(a,b);query(p,a,best);query(p,b,best);
    }
public:
    explicit Bvh(std::vector<Triangle>& t,LiveProgress* progress=nullptr):tris(t),progress_(progress){if(t.empty())throw std::runtime_error("No TSDF zero-crossing surface");nodes.reserve(t.size()/2+1);build(0,t.size());}
    double distance(const Vec& p,double max) const {double best=max*max;query(p,0,best);return std::sqrt(best);}
};
inline Id native_index(const distance_input::Record& v,double h) {
    Id i; double xyz[]={v.x,v.y,v.z};for(int a=0;a<3;++a){double q=xyz[a]/h,r=std::round(q);
        if(r<=std::numeric_limits<int>::min()+2.0 || r>=std::numeric_limits<int>::max()-2.0 || std::abs(q-r)>1e-3)throw std::runtime_error("Expected uniform native integer-center samples");i[a]=static_cast<int>(r);}
    return i;
}
// Six tetrahedra around the same cube diagonal: adjacent cells share face diagonals.
constexpr int offsets[8][3]={{0,0,0},{1,0,0},{0,1,0},{1,1,0},{0,0,1},{1,0,1},{0,1,1},{1,1,1}};
constexpr int tetra[6][4]={{0,1,3,7},{0,3,2,7},{0,2,6,7},{0,6,4,7},{0,4,5,7},{0,5,1,7}};
inline bool corners(const Samples& s,const Id& i,double d[8]) {
    for(int c=0;c<8;++c){Id j={i[0]+offsets[c][0],i[1]+offsets[c][1],i[2]+offsets[c][2]};auto it=s.find(j);if(it==s.end()||it->second.weight<2)return false;d[c]=it->second.sdf;}return true;
}
inline void mesh_cell(const Id& i,const double d[8],double h,std::vector<Triangle>& out) {
    Vec p[8];for(int c=0;c<8;++c)p[c]=Vec(i[0]+offsets[c][0],i[1]+offsets[c][1],i[2]+offsets[c][2])*h;
    auto add=[&](Vec a,Vec b,Vec c){if((b-a).cross(c-a).squaredNorm()>h*h*h*h*1e-20)out.push_back({a,b,c});};
    auto edge=[&](int a,int b)->Vec {return p[a]+(d[a]/(d[a]-d[b]))*(p[b]-p[a]);};
    for(const auto& t:tetra){int pos[4],neg[4],np=0,nn=0;for(int c:t){if(d[c]>=0)pos[np++]=c;else neg[nn++]=c;}
        if(np==0||nn==0)continue;
        if(np==1){add(edge(pos[0],neg[0]),edge(pos[0],neg[1]),edge(pos[0],neg[2]));}
        else if(nn==1){add(edge(neg[0],pos[0]),edge(neg[0],pos[1]),edge(neg[0],pos[2]));}
        else{Vec a=edge(pos[0],neg[0]),b=edge(pos[0],neg[1]),c=edge(pos[1],neg[0]),e=edge(pos[1],neg[1]);add(a,b,c);add(b,e,c);}
    }
}
inline int run(const std::string& input,const std::string& output,double h,double max) {
    std::ifstream in(input,std::ios::binary);if(!in)throw std::runtime_error("Cannot open PLY");size_t count=distance_input::read_header(in);
    LiveProgress progress; progress.emit("reading_input",0,count,"体素记录",true);
    Samples samples;samples.reserve(count);size_t filtered=0;
    for(size_t k=0;k<count;++k){distance_input::Record v;if(!in.read(reinterpret_cast<char*>(&v),sizeof(v)))throw std::runtime_error("Truncated PLY payload");bool accepted=distance_input::accepted(v);Id i=native_index(v,h);if(!samples.emplace(i,Sample{v.sdf,v.weight}).second)throw std::runtime_error("Duplicate native voxel");filtered+=!accepted;if((k+1)%4096==0 || k+1==count)progress.emit("reading_input",k+1,count,"体素记录",k+1==count);}
    if(in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("Trailing PLY payload");
    std::vector<Triangle> tris;size_t support=0;double d[8];
    size_t scanned=0;progress.emit("surface_extraction",0,samples.size(),"候选体素",true);
    for(const auto& item:samples){++scanned;if(scanned%4096==0 || scanned==samples.size())progress.emit("surface_extraction",scanned,samples.size(),"候选体素",scanned==samples.size());if(!corners(samples,item.first,d))continue;++support;mesh_cell(item.first,d,h,tris);}
    std::cout<<"SURFACE_ESDF source="<<count<<" low_weight="<<filtered<<" supported_centers="<<support<<" triangles="<<tris.size()<<std::endl;
    progress.emit("building_index",0,tris.size(),"三角形",true);
    Bvh bvh(tris,&progress);progress.emit("building_index",tris.size(),tris.size(),"三角形",true);
    voxblox::Layer<voxblox::EsdfVoxel> layer(h,16);
    std::filesystem::create_directories(output+"/preview");
    std::ofstream ply(output+"/preview/esdf_vis.ply");
    // Count preview first while querying once; temporary stream keeps memory bounded.
    std::string tmp=output+"/preview/centers.tmp";std::ofstream rows(tmp);rows<<std::setprecision(9);size_t visible=0,observed=0,outside=0;
    size_t queried=0;progress.emit("distance_computation",0,support,"支撑中心",true);
    for(const auto& item:samples){const auto& i=item.first;if(!corners(samples,i,d))continue;
        Vec p=(Vec(i[0],i[1],i[2])+Vec::Constant(.5))*h;
        double dist=bvh.distance(p,max);++queried;if(queried%1024==0 || queried==support)progress.emit("distance_computation",queried,support,"支撑中心",queried==support);if(dist>=max){++outside;continue;} // No claim outside calculated radius.
        double sdf=(d[0]+d[7])/2;if(sdf<0)dist=-dist;
        voxblox::Point pf=p.cast<voxblox::FloatingPoint>();auto block=layer.allocateBlockPtrByCoordinates(pf);auto& v=block->getVoxelByCoordinates(pf);v.distance=dist;v.observed=true;++observed;
        if(std::abs(dist)<=1.5){int r=dist<0?255:30,b=dist<0?30:255;rows<<p.x()<<' '<<p.y()<<' '<<p.z()<<' '<<dist<<' '<<r<<" 100 "<<b<<'\n';++visible;}
    }
    rows.close();if(!rows)throw std::runtime_error("Preview rows write failed");
    if(!observed)throw std::runtime_error("No valid ESDF samples");
    progress.emit("writing_outputs",0,0,"",true);
    if(!voxblox::io::SaveLayer(layer,output+"/map.esdf",true))throw std::runtime_error("ESDF save failed");
    ply<<"ply\nformat ascii 1.0\ncomment observed support only; unallocated/unobserved is unknown\nelement vertex "<<visible<<"\nproperty float x\nproperty float y\nproperty float z\nproperty float distance\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n";
    std::ifstream rr(tmp);size_t bytes=std::filesystem::file_size(tmp),copied=0;progress.emit("writing_preview",0,bytes,"字节",true);
    char buffer[1048576];while(rr){rr.read(buffer,sizeof(buffer));auto n=rr.gcount();if(n>0){ply.write(buffer,n);copied+=n;progress.emit("writing_preview",copied,bytes,"字节",copied==bytes);}}if(rr.bad())throw std::runtime_error("Preview rows read failed");ply.close();if(!ply)throw std::runtime_error("Preview save failed");std::filesystem::remove(tmp);
    std::ofstream metadata(output+"/conversion.json");metadata<<"{\"algorithm\":\"native_tsdf_zero_surface_tetra_bvh_v1\",\"resolution_m\":"<<h<<",\"source_count\":"<<count<<",\"low_weight\":"<<filtered<<",\"supported_centers\":"<<support<<",\"triangles\":"<<tris.size()<<",\"observed\":"<<observed<<",\"outside_distance_radius\":"<<outside<<",\"preview_count\":"<<visible<<",\"unknown_policy\":\"eight observed weight>=2 corners required; no extrapolation\"}\n";metadata.close();if(!metadata)throw std::runtime_error("Metadata save failed");
    std::cout<<"SURFACE_ESDF observed="<<observed<<" outside_radius="<<outside<<std::endl;return 0;
}
}
