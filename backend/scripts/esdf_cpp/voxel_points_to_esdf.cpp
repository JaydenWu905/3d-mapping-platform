#include <fstream>
#include <iostream>
#include <string>
#include <queue>
#include <unordered_set>
#include <unordered_map>
#include <iomanip>
#include <filesystem>
#include "voxel_input.h"
#include <cmath>
#include <functional>
#include <cstdlib>
#include <sys/stat.h>
#include <sys/types.h>

#include <voxblox/core/esdf_map.h>
#include <voxblox/integrator/esdf_integrator.h>

#include "surface_esdf.h"

// 自定义哈希函数：用于 std::unordered_set<voxblox::GlobalIndex>
struct GlobalIndexHash {
    std::size_t operator()(const voxblox::GlobalIndex& idx) const {
        std::size_t h = 0;
        h ^= std::hash<int>()(idx.x()) + 0x9e3779b9 + (h << 6) + (h >> 2);
        h ^= std::hash<int>()(idx.y()) + 0x9e3779b9 + (h << 6) + (h >> 2);
        h ^= std::hash<int>()(idx.z()) + 0x9e3779b9 + (h << 6) + (h >> 2);
        return h;
    }
};

struct QueueNode {
    double distance;
    voxblox::GlobalIndex index;
    bool operator>(const QueueNode& other) const {
        return distance > other.distance;
    }
};

// 递归创建目录（mkdir -p 的 C++ 实现）
static bool ensure_directory(const std::string& path) {
    std::filesystem::create_directories(path);
    return std::filesystem::is_directory(path);
}

int run(int argc, char* argv[]) {
    // ================= 命令行参数解析 =================
    std::string input_file;
    std::string output_dir;
    double voxel_size = 0.1;
    double source_voxel_size = 0;
    bool validate_only = false, legacy_diagnostic = false, surface_mode = false;
    std::string input_grid;
    int input_resolution = 0;
    double max_esdf_distance = 2.5;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if (arg == "--surface-esdf") { surface_mode = true; }
        else if (arg == "--validate-only") { validate_only = true; }
        else if (arg == "--legacy-diagnostic") { legacy_diagnostic = true; }
        else if (arg == "--input-grid" && i + 1 < argc) { input_grid = argv[++i]; }
        else if (arg == "--source-voxel-size" && i + 1 < argc) { source_voxel_size = std::stod(argv[++i]); }
        else if (arg == "--input-resolution" && i + 1 < argc) { input_resolution = std::stoi(argv[++i]); }
        else if (arg == "--input" && i + 1 < argc) {
            input_file = argv[++i];
        }
        else if (arg == "--output_dir" && i + 1 < argc) {
            output_dir = argv[++i];
        }
        else if (arg == "--voxel_size" && i + 1 < argc) {
            voxel_size = std::stod(argv[++i]);
        }
        else if (arg == "--max_esdf_distance" && i + 1 < argc) {
            max_esdf_distance = std::stod(argv[++i]);
        } else { throw std::runtime_error("Unknown or incomplete argument: " + arg); }
    }
    distance_input::positive(voxel_size, "voxel_size");
    distance_input::positive(max_esdf_distance, "max_esdf_distance");
    distance_input::positive(source_voxel_size, "source_voxel_size");
    if (surface_mode) {
        if (validate_only || legacy_diagnostic || input_grid != "mrhash_integer_centers" || input_resolution != 0 ||
            std::abs(source_voxel_size-voxel_size)>voxel_size*1e-6 || input_file.empty() || output_dir.empty())
            throw std::runtime_error("surface-esdf requires explicit uniform same-resolution native input and output");
        return surface_esdf::run(input_file,output_dir,voxel_size,max_esdf_distance);
    }
    if (input_grid != "voxblox_centers" || input_resolution != 0 ||
        std::abs(source_voxel_size - voxel_size) > voxel_size * 1e-6)
        throw std::runtime_error("Only explicitly uniform, same-resolution Voxblox-center input is supported; native/mixed MrHash requires a resampling policy");
    if (validate_only == legacy_diagnostic)
        throw std::runtime_error("Production ESDF disabled: select --validate-only or --legacy-diagnostic; TSDF-to-ESDF and unknown-space policy remain unresolved");

    if (input_file.empty() || (!validate_only && output_dir.empty())) {
        std::cerr << "Usage: " << argv[0]
            << " --input <voxel_points.ply> --output_dir <output_dir>"
            << " [--voxel_size 0.1] [--max_esdf_distance 2.5]" << std::endl;
        return -1;
    }

    std::string output_esdf = output_dir + "/diagnostic-unaccepted.esdf";
    std::string output_ply = output_dir + "/preview/diagnostic-unaccepted.ply";

    if (!validate_only && !ensure_directory(output_dir + "/preview")) throw std::runtime_error("Cannot create output directory");

    std::cout << "[INFO] Input PLY: " << input_file << std::endl;
    if (!validate_only) {
        std::cout << "[INFO] Unaccepted diagnostic layer: " << output_esdf << std::endl;
        std::cout << "[INFO] Diagnostic PLY: " << output_ply << std::endl;
    }
    std::cout << "[INFO] Voxel size: " << voxel_size
        << ", Max ESDF distance: " << max_esdf_distance << std::endl;
    // =====================================================

    std::cout << "[INFO] Initializing ESDF map, voxel size: " << voxel_size << std::endl;
    voxblox::EsdfMap::Config esdf_map_config;
    esdf_map_config.esdf_voxel_size = voxel_size;
    esdf_map_config.esdf_voxels_per_side = 16;
    voxblox::EsdfMap esdf_map(esdf_map_config);

    std::cout << "[INFO] Reading binary point cloud file: " << input_file << std::endl;
    std::ifstream infile(input_file, std::ios::binary);
    if (!infile.is_open()) {
        std::cerr << "[ERROR] Failed to open input file!" << std::endl;
        return -1;
    }

    const size_t declared_count = distance_input::read_header(infile);
    distance_input::Record vd;
    distance_input::UniqueCenters input_indices;
    size_t count = 0;
    size_t filtered = 0;

    std::cout << "[INFO] Start traversing point cloud and filling ESDF map..." << std::endl;
    for (size_t record = 0; record < declared_count; ++record) {
        if (!infile.read(reinterpret_cast<char*>(&vd), sizeof(vd))) throw std::runtime_error("Truncated PLY payload");
        if (!distance_input::accepted(vd)) {
            filtered++;
            continue;
        }

        input_indices.insert(vd, voxel_size);
        ++count;
        if (validate_only) continue;
        voxblox::Point position(vd.x, vd.y, vd.z);
        voxblox::Block<voxblox::EsdfVoxel>::Ptr block =
            esdf_map.getEsdfLayerPtr()->allocateBlockPtrByCoordinates(position);

        if (block != nullptr) {
            voxblox::EsdfVoxel& voxel = block->getVoxelByCoordinates(position);
            voxel.distance = vd.sdf;
            voxel.observed = true;
        }

        if (count % 5000000 == 0) {
            std::cout << "[INFO] Processed " << (count / 1000000) << " million points..." << std::endl;
        }
    }
    if (infile.peek() != std::char_traits<char>::eof()) throw std::runtime_error("Trailing PLY payload");
    if (!count) throw std::runtime_error("No samples survive weight >= 2");
    infile.close();
    if (validate_only) {
        std::cout << "INPUT_VALIDATION_ONLY accepted=" << count << " filtered=" << filtered
                  << "; no ESDF computed or saved" << std::endl;
        return 0;
    }
    std::cerr << "UNACCEPTED LEGACY DIAGNOSTIC: projected TSDF seeds and positive expansion into unknown are not a validated signed Euclidean field" << std::endl;
    std::cout << "[INFO] Reading complete. Total points processed: " << count
        << ", filtered low-weight points: " << filtered << std::endl;

    // ================= 波前传播（全局 ESDF 扩展） =================
    std::cout << "[INFO] Starting Wavefront Propagation (Dijkstra) up to "
        << max_esdf_distance << " m..." << std::endl;

    std::priority_queue<QueueNode, std::vector<QueueNode>, std::greater<QueueNode>> pq;
    std::unordered_set<voxblox::GlobalIndex, GlobalIndexHash> processed, seeds;
    std::unordered_map<voxblox::GlobalIndex, double, GlobalIndexHash> best;

    voxblox::BlockIndexList seed_block_list;
    esdf_map.getEsdfLayer().getAllAllocatedBlocks(&seed_block_list);

    size_t seed_count = 0;
    for (const auto& block_idx : seed_block_list) {
        const voxblox::Block<voxblox::EsdfVoxel>& block = esdf_map.getEsdfLayer().getBlockByIndex(block_idx);
        for (size_t i = 0; i < block.num_voxels(); ++i) {
            const voxblox::EsdfVoxel& voxel = block.getVoxelByLinearIndex(i);
            if (voxel.observed) {
                voxblox::VoxelIndex local_idx = block.computeVoxelIndexFromLinearIndex(i);
                voxblox::GlobalIndex global_idx = voxblox::getGlobalVoxelIndexFromBlockAndVoxelIndex(
                    block_idx, local_idx, block.voxels_per_side());

                double abs_dist = std::abs(voxel.distance);
                pq.push({ abs_dist, global_idx });
                seeds.insert(global_idx);
                best[global_idx] = abs_dist;
                seed_count++;
            }
        }
    }
    std::cout << "[INFO] Seeds loaded: " << seed_count << ". Starting propagation..." << std::endl;

    size_t propagated_count = 0;
    size_t neighbor_checks = 0;

    while (!pq.empty()) {
        QueueNode current = pq.top();
        pq.pop();

        if (current.distance > max_esdf_distance || processed.count(current.index) ||
            current.distance > best.at(current.index)) continue;
        processed.insert(current.index);

        for (int dx = -1; dx <= 1; ++dx) {
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dz = -1; dz <= 1; ++dz) {
                    if (dx == 0 && dy == 0 && dz == 0) continue;

                    voxblox::GlobalIndex neighbor_idx(
                        current.index.x() + dx,
                        current.index.y() + dy,
                        current.index.z() + dz);

                    if (processed.count(neighbor_idx) || seeds.count(neighbor_idx)) continue;

                    double step_dist = std::sqrt(static_cast<double>(dx * dx + dy * dy + dz * dz)) * voxel_size;
                    double new_dist = current.distance + step_dist;

                    if (new_dist > max_esdf_distance) continue;
                    auto previous = best.find(neighbor_idx);
                    if (previous != best.end() && new_dist >= previous->second) continue;
                    best[neighbor_idx] = new_dist;

                    voxblox::Point neighbor_pos = voxblox::getCenterPointFromGridIndex(neighbor_idx, voxel_size);
                    voxblox::Block<voxblox::EsdfVoxel>::Ptr block =
                        esdf_map.getEsdfLayerPtr()->allocateBlockPtrByCoordinates(neighbor_pos);

                    if (block != nullptr) {
                        voxblox::EsdfVoxel& voxel = block->getVoxelByCoordinates(neighbor_pos);
                        if (!voxel.observed) ++propagated_count;
                        voxel.distance = new_dist;
                        voxel.observed = true; // Legacy diagnostic policy, NOT production unknown handling.
                    }
                    pq.push({ new_dist, neighbor_idx });
                    neighbor_checks++;

                    if (neighbor_checks % 1000000 == 0) {
                        std::cout << "[INFO] Propagated " << (neighbor_checks / 1000000)
                            << " million neighbor checks, " << propagated_count
                            << " new voxels..." << std::endl;
                    }
                }
            }
        }
    }

    std::cout << "[INFO] Wavefront Propagation complete. New voxels extended: "
        << propagated_count << std::endl;

    // ================= 保存 ESDF 文件 =================
    std::cout << "[INFO] Saving ESDF file to: " << output_esdf << std::endl;
    if (!esdf_map.getEsdfLayer().saveToFile(output_esdf, true))
        throw std::runtime_error("Failed to save diagnostic ESDF layer");
    std::cout << "[INFO] ESDF saved successfully!" << std::endl;

    // ================= 动态计算并验证梯度信息 =================
    std::cout << "[INFO] Verifying gradient calculation for sample voxels..." << std::endl;
    size_t num_blocks = esdf_map.getEsdfLayer().getNumberOfAllocatedBlocks();
    if (num_blocks > 0) {
        voxblox::BlockIndexList block_list;
        esdf_map.getEsdfLayer().getAllAllocatedBlocks(&block_list);

        int printed_count = 0;
        for (const auto& block_idx : block_list) {
            const voxblox::Block<voxblox::EsdfVoxel>& block = esdf_map.getEsdfLayer().getBlockByIndex(block_idx);
            for (size_t i = 0; i < block.num_voxels(); ++i) {
                const voxblox::EsdfVoxel& voxel = block.getVoxelByLinearIndex(i);

                if (voxel.observed && std::abs(voxel.distance) > 0.1 && std::abs(voxel.distance) < 1.0) {
                    voxblox::VoxelIndex local_idx = block.computeVoxelIndexFromLinearIndex(i);
                    voxblox::GlobalIndex global_idx = voxblox::getGlobalVoxelIndexFromBlockAndVoxelIndex(
                        block_idx, local_idx, block.voxels_per_side());
                    voxblox::Point pos_origin = voxblox::getOriginPointFromGridIndex(global_idx, block.voxel_size());

                    Eigen::Vector3d pos_center = pos_origin.cast<double>() + Eigen::Vector3d(0.5, 0.5, 0.5) * block.voxel_size();

                    double dist = voxel.distance;

                    Eigen::Vector3d grad(0, 0, 0);
                    double dx = block.voxel_size();
                    double d_plus, d_minus;
                    bool interpolate = false;

                    if (esdf_map.getDistanceAtPosition(pos_center + Eigen::Vector3d(dx, 0, 0), interpolate, &d_plus) &&
                        esdf_map.getDistanceAtPosition(pos_center - Eigen::Vector3d(dx, 0, 0), interpolate, &d_minus)) {
                        grad.x() = (d_plus - d_minus) / (2.0 * dx);
                    }
                    if (esdf_map.getDistanceAtPosition(pos_center + Eigen::Vector3d(0, dx, 0), interpolate, &d_plus) &&
                        esdf_map.getDistanceAtPosition(pos_center - Eigen::Vector3d(0, dx, 0), interpolate, &d_minus)) {
                        grad.y() = (d_plus - d_minus) / (2.0 * dx);
                    }
                    if (esdf_map.getDistanceAtPosition(pos_center + Eigen::Vector3d(0, 0, dx), interpolate, &d_plus) &&
                        esdf_map.getDistanceAtPosition(pos_center - Eigen::Vector3d(0, 0, dx), interpolate, &d_minus)) {
                        grad.z() = (d_plus - d_minus) / (2.0 * dx);
                    }

                    std::cout << "[INFO] Voxel [" << printed_count << "] Pos: ["
                        << pos_center.x() << ", " << pos_center.y() << ", " << pos_center.z() << "] | "
                        << "Distance: " << dist << " | "
                        << "Observed: " << (voxel.observed ? "True" : "False") << " | "
                        << "Gradient: [" << grad.x() << ", " << grad.y() << ", " << grad.z() << "]"
                        << std::endl;

                    printed_count++;
                    if (printed_count >= 10) break;
                }
            }
            if (printed_count >= 10) break;
        }
    }

    // ================= 导出可视化 PLY 文件（包含距离属性） =================
    std::cout << "[INFO] Start generating visualization PLY file with distance attribute..." << std::endl;
    size_t num_observed_voxels = 0;
    voxblox::BlockIndexList block_list;
    esdf_map.getEsdfLayer().getAllAllocatedBlocks(&block_list);

    for (const auto& block_idx : block_list) {
        const voxblox::Block<voxblox::EsdfVoxel>& block = esdf_map.getEsdfLayer().getBlockByIndex(block_idx);
        for (size_t i = 0; i < block.num_voxels(); ++i) {
            const voxblox::EsdfVoxel& voxel = block.getVoxelByLinearIndex(i);
            if (voxel.observed && std::abs(voxel.distance) <= 1.5f) {
                num_observed_voxels++;
            }
        }
    }

    std::ofstream ply_file(output_ply);
    if (ply_file.is_open()) {
        ply_file << std::setprecision(std::numeric_limits<float>::max_digits10);
        ply_file << "ply\nformat ascii 1.0\n";
        ply_file << "element vertex " << num_observed_voxels << "\n";
        ply_file << "property float x\nproperty float y\nproperty float z\n";
        ply_file << "property float distance\n";
        ply_file << "property uchar red\nproperty uchar green\nproperty uchar blue\n";
        ply_file << "end_header\n";

        float color_max_dist = 1.5f;
        for (const auto& block_idx : block_list) {
            const voxblox::Block<voxblox::EsdfVoxel>& block = esdf_map.getEsdfLayer().getBlockByIndex(block_idx);
            for (size_t i = 0; i < block.num_voxels(); ++i) {
                const voxblox::EsdfVoxel& voxel = block.getVoxelByLinearIndex(i);
                if (voxel.observed) {
                    if (std::abs(voxel.distance) > 1.5f) continue;

                    voxblox::VoxelIndex local_idx = block.computeVoxelIndexFromLinearIndex(i);
                    voxblox::GlobalIndex global_idx = voxblox::getGlobalVoxelIndexFromBlockAndVoxelIndex(block_idx, local_idx, block.voxels_per_side());
                    voxblox::Point pos = voxblox::getCenterPointFromGridIndex(global_idx, block.voxel_size());

                    float dist = std::max(-color_max_dist, std::min(color_max_dist, voxel.distance));
                    int red = static_cast<int>(255 * (1.0f - (dist + color_max_dist) / (2.0f * color_max_dist)));
                    int blue = static_cast<int>(255 * ((dist + color_max_dist) / (2.0f * color_max_dist)));
                    int green = 0;

                    ply_file << pos.x() << " " << pos.y() << " " << pos.z() << " "
                        << voxel.distance << " "
                        << red << " " << green << " " << blue << "\n";
                }
            }
        }
        ply_file.close();
        if (!ply_file) throw std::runtime_error("Failed to write diagnostic PLY");
        std::cout << "[INFO] Visualization PLY saved to: " << output_ply << std::endl;
    }
    else {
        std::cerr << "[ERROR] Failed to open PLY file for writing: " << output_ply << std::endl;
        return -1;
    }

    std::cout << "[INFO] All tasks completed successfully!" << std::endl;
    return 0;
}

int main(int argc, char* argv[]) {
    try { return run(argc, argv); }
    catch (const std::exception& error) {
        std::cerr << "[ERROR] " << error.what() << std::endl;
        return 2;
    }
}
