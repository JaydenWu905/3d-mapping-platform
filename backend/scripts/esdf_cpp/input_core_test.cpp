// Tests only the production input header; does not link Voxblox or compute ESDF.
#include "voxel_input.h"
#include <iostream>
#include <sstream>
#include <set>
#include <functional>
#include <stdexcept>
using namespace distance_input;
void require(bool value) { if (!value) throw std::runtime_error("test assertion"); }
void rejects(const std::function<void()>& f) {
    bool failed=false; try { f(); } catch (const std::exception&) { failed=true; }
    require(failed);
}
int main() {
    const std::string header = "ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
        "property float x\nproperty float y\nproperty float z\nproperty float sdf\nproperty float weight\n"
        "property uchar red\nproperty uchar green\nproperty uchar blue\nproperty uchar alpha\nend_header\n";
    std::istringstream valid(header); require(read_header(valid)==1);
    for (auto input : {std::string("ply\n"), std::string("ply\nformat ascii 1.0\n")})
        rejects([&]{std::istringstream f(input); read_header(f);});
    Record v{.025f,.025f,-.025f,.2f,2,255,0,0,0};
    require(accepted(v)); require(center_index(v,.05)==Index{0,0,-1});
    // Signed projected TSDF remains signed; it is not converted to Euclidean distance.
    v.sdf=-.2f; require(accepted(v)); require(v.sdf<0);
    v.weight=1; require(!accepted(v));
    v.weight=0; rejects([&]{accepted(v);});
    v.weight=-1; rejects([&]{accepted(v);});
    v.weight=std::numeric_limits<float>::infinity(); rejects([&]{accepted(v);});
    v.weight=2; v.sdf=std::numeric_limits<float>::quiet_NaN(); rejects([&]{accepted(v);});
    v.sdf=.2f; v.x=0; rejects([&]{center_index(v,.05);}); // Native MrHash integer sample cannot be shifted.
    v.x=.025f; UniqueCenters seen;require(seen.insert(v,.05)==Index{0,0,-1});
    rejects([&]{seen.insert(v,.05);}); // Executes the same duplicate guard as the production driver.
    rejects([&]{positive(0,"h");}); rejects([&]{positive(-1,"h");});
    std::string empty=header; empty.replace(empty.find("vertex 1"),8,"vertex 0");
    rejects([&]{std::istringstream f(empty);read_header(f);});
    std::cout << "CPP_INPUT_CORE_ONLY PASS: no Voxblox, no ESDF algorithm or map serialization tested\n";
}
