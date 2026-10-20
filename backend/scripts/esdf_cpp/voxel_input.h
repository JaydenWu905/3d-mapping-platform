#pragma once
// Shared input validation only. This header does not compute an ESDF.
#include <array>
#include <cmath>
#include <cstdint>
#include <istream>
#include <limits>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace distance_input {
#pragma pack(push, 1)
struct Record { float x, y, z, sdf, weight; uint8_t r, g, b, a; };
#pragma pack(pop)
static_assert(sizeof(Record) == 24, "Native MrHash PLY record must be 24 bytes");
using Index = std::array<int, 3>;

inline void positive(double value, const char* name) {
    if (!std::isfinite(value) || value <= 0) throw std::runtime_error(std::string(name) + " must be finite and positive");
}
inline size_t read_header(std::istream& in) {
    uint16_t endian = 1;
    if (*reinterpret_cast<uint8_t*>(&endian) != 1 || !std::numeric_limits<float>::is_iec559)
        throw std::runtime_error("Only little-endian IEEE float32 hosts are supported");
    std::string line;
    if (!std::getline(in, line) || line != "ply") throw std::runtime_error("Not a PLY file");
    if (!std::getline(in, line) || line != "format binary_little_endian 1.0")
        throw std::runtime_error("Expected binary_little_endian PLY");
    const std::vector<std::string> expected = {
        "property float x", "property float y", "property float z", "property float sdf", "property float weight",
        "property uchar red", "property uchar green", "property uchar blue", "property uchar alpha"};
    std::vector<std::string> props;
    size_t count = 0; bool element = false;
    for (int n = 0; n < 100 && std::getline(in, line); ++n) {
        if (line == "end_header") {
            if (!element || count == 0 || props != expected) throw std::runtime_error("Empty or unsupported vertex layout");
            return count;
        }
        if (line.rfind("comment ", 0) == 0 || line.rfind("obj_info ", 0) == 0) continue;
        if (line.rfind("element vertex ", 0) == 0 && !element && props.empty()) {
            std::string value = line.substr(15);
            if (value.empty() || value.find_first_not_of("0123456789") != std::string::npos)
                throw std::runtime_error("Invalid vertex count");
            count = std::stoull(value); element = true;
        } else if (line.rfind("property ", 0) == 0 && element) props.push_back(line);
        else throw std::runtime_error("Unsupported PLY header element");
    }
    throw std::runtime_error("Truncated PLY header");
}
inline bool accepted(const Record& v) {
    if (!std::isfinite(v.x) || !std::isfinite(v.y) || !std::isfinite(v.z) ||
        !std::isfinite(v.sdf) || !std::isfinite(v.weight) || v.weight <= 0)
        throw std::runtime_error("Nonfinite value or nonpositive input weight");
    return v.weight >= 2.0f; // Existing converter threshold; not the MrHash export threshold.
}
inline Index center_index(const Record& v, double h) {
    positive(h, "voxel_size");
    Index result; const double xyz[] = {v.x, v.y, v.z};
    for (int a = 0; a < 3; ++a) {
        double q = xyz[a] / h;
        double i = std::floor(q);
        if (!std::isfinite(q) || i <= std::numeric_limits<int>::min() || i >= std::numeric_limits<int>::max())
            throw std::runtime_error("Coordinate outside target index range");
        if (std::abs(q - (i + 0.5)) > 1e-3)
            throw std::runtime_error("Sample is not a Voxblox center: explicit resampling is required, never add a fixed shift");
        result[a] = static_cast<int>(i);
    }
    return result;
}
class UniqueCenters {
    std::set<Index> seen_;
public:
    Index insert(const Record& value, double h) {
        const auto index = center_index(value, h);
        if (!seen_.insert(index).second)
            throw std::runtime_error("Multiple input samples map to one target voxel; aggregation policy required");
        return index;
    }
};
} // namespace distance_input
