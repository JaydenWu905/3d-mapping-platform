// Real Voxblox structural reader; optional TSV enables native numerical checks.
#include <voxblox/core/esdf_map.h>
#include <voxblox/io/layer_io.h>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <fstream>
#include <iomanip>
#include "live_progress.h"
int main(int argc, char** argv) {
    try {
        if (argc != 3 && argc != 4) throw std::runtime_error("Usage: verify_esdf_layer FILE EXPECTED_VOXEL_SIZE [DUMP_TSV]");
        const double expected = std::stod(argv[2]);
        if (!std::isfinite(expected) || expected <= 0) throw std::runtime_error("Invalid voxel size");
        LiveProgress progress;progress.emit("loading_validation",0,0,"",true);
        voxblox::Layer<voxblox::EsdfVoxel>::Ptr layer;
        if (!voxblox::io::LoadLayer<voxblox::EsdfVoxel>(argv[1], &layer) || !layer)
            throw std::runtime_error("Cannot read Voxblox EsdfVoxel layer");
        if (std::abs(layer->voxel_size() - expected) > expected * 1e-6 || layer->voxels_per_side() != 16)
            throw std::runtime_error("Layer geometry mismatch");
        voxblox::BlockIndexList blocks;layer->getAllAllocatedBlocks(&blocks);
        std::ofstream dump; if(argc==4){dump.open(argv[3]);dump<<std::setprecision(9);}
        size_t observed=0, unknown=0, negative=0, checked=0;
        size_t slots=blocks.size()*size_t(16*16*16);progress.emit("verifying_outputs",0,slots,"体素槽位",true);
        voxblox::Point lo=voxblox::Point::Constant(INFINITY),hi=voxblox::Point::Constant(-INFINITY);
        double minimum=INFINITY,maximum=-INFINITY;
        for (const auto& index : blocks) {
            const auto& block=layer->getBlockByIndex(index);
            for (size_t i=0;i<block.num_voxels();++i) {
                const auto& voxel=block.getVoxelByLinearIndex(i);
                ++checked;if(checked%4096==0 || checked==slots)progress.emit("verifying_outputs",checked,slots,"体素槽位",checked==slots);
                if (!voxel.observed) {++unknown;continue;}
                if (!std::isfinite(voxel.distance)) throw std::runtime_error("Nonfinite observed distance");
                ++observed;negative+=voxel.distance<0;
                auto p=block.computeCoordinatesFromLinearIndex(i);lo=lo.cwiseMin(p);hi=hi.cwiseMax(p);
                minimum=std::min(minimum,double(voxel.distance));maximum=std::max(maximum,double(voxel.distance));
                if(argc==4)dump<<p.x()<<'\t'<<p.y()<<'\t'<<p.z()<<'\t'<<voxel.distance<<'\n';
            }
        }
        if (!observed) throw std::runtime_error("Empty observed layer");
        std::cout << "{\"kind\":\"structural_readback_only\",\"blocks\":" << blocks.size()
                  << ",\"observed\":" << observed << ",\"unobserved_in_allocated_blocks\":" << unknown
                  << ",\"negative\":" << negative << ",\"distance_min\":"<<minimum<<",\"distance_max\":"<<maximum
                  <<",\"bounds_min\":["<<lo.x()<<','<<lo.y()<<','<<lo.z()<<"],\"bounds_max\":["<<hi.x()<<','<<hi.y()<<','<<hi.z()<<"]}\n";
        if(argc==4){dump.close();if(!dump)throw std::runtime_error("Dump write failed");}
        return 0;
    } catch(const std::exception& error) {std::cerr<<error.what()<<"\n";return 2;}
}
