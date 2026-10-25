#!/usr/bin/env python3
"""Strict, bounded-memory inspection of this Job's Surface→Distance input.

No mesh fallback and no guess of the physical grid size of adaptive voxels.
"""
from pathlib import Path
import argparse
import json
import math
import re
import struct

PROPERTIES = ['property float ' + n for n in ('x', 'y', 'z', 'sdf', 'weight')] + [
    'property uchar ' + n for n in ('red', 'green', 'blue', 'alpha')]


def inspect(job_dir: Path, scan: bool = False) -> dict:
    stage = job_dir.resolve() / 'stage2_surface'
    manifest = json.loads((stage / 'result_manifest.json').read_text())
    if manifest.get('status') != 'completed' or manifest.get('job_id') != job_dir.name:
        raise ValueError('Surface must be completed and belong to this Job')
    if manifest.get('unit') != 'meter' or manifest.get('frame_id') != 'world':
        raise ValueError('Expected world frame and meter units')
    if manifest.get('backend_details', {}).get('mock_backend') is not False:
        raise ValueError('Real Distance requires native, non-mock Surface output')
    def artifact(name):
        items = [a for a in manifest.get('artifacts', []) if a.get('artifact_id') == name]
        if len(items) != 1:
            raise ValueError(f'Exactly one {name} artifact is required; Mesh is not a TSDF')
        path = (stage / items[0]['path']).resolve()
        if not path.is_relative_to(stage.resolve()) or not path.is_file():
            raise ValueError(f'Invalid {name} path')
        return path
    ply = artifact('voxel_points')
    config = artifact('run_config')
    text = config.read_text()
    values = re.findall(r'^\s*virtual_voxel_size\s*:\s*([0-9.eE+-]+)\s*(?:#.*)?$', text, re.M)
    if len(values) != 1 or not math.isfinite(float(values[0])) or float(values[0]) <= 0:
        raise ValueError('Unique positive virtual_voxel_size required in this run config')
    with ply.open('rb') as fh:
        lines = []
        for _ in range(100):
            line = fh.readline(4096).decode('ascii').strip()
            lines.append(line)
            if line == 'end_header': break
        else: raise ValueError('Invalid PLY header')
        if lines[:2] != ['ply', 'format binary_little_endian 1.0']:
            raise ValueError('Converter requires binary_little_endian PLY')
        if [l for l in lines if l.startswith('property ')] != PROPERTIES:
            raise ValueError('Converter requires exact packed x y z sdf weight rgba layout')
        elements = [l for l in lines if l.startswith('element ')]
        if len(elements) != 1 or not elements[0].startswith('element vertex '):
            raise ValueError('Only vertex records are allowed')
        count = int(elements[0].split()[-1])
        if count <= 0 or ply.stat().st_size - fh.tell() != count * 24:
            raise ValueError('Empty or truncated PLY payload')
        valid = None
        if scan:
            valid = 0
            for _ in range(count):
                x,y,z,sdf,weight,*_ = struct.unpack('<5f4B', fh.read(24))
                if not all(map(math.isfinite, (x,y,z,sdf,weight))) or weight <= 0:
                    raise ValueError('Nonfinite or unknown/invalid voxel')
                valid += weight >= 2
            if not valid:
                raise ValueError('No voxels survive converter weight >= 2 rule')
    def config_number(name):
        found = re.findall(r'^\s*' + name + r'\s*:\s*([0-9.eE+-]+)\s*(?:#.*)?$', text, re.M)
        if len(found) != 1 or not math.isfinite(float(found[0])):
            return None
        return float(found[0])
    threshold = config_number('sdf_var_threshold')
    extents = config_number('voxel_extents_scale')
    # Fixed MrHash integrate(): reallocBlocks only under sdf_var_threshold > 0.
    source_uniform = threshold is not None and threshold <= 0 and extents == 1
    grid = manifest.get('backend_details', {}).get('distance_grid')
    result = dict(input_ply=str(ply), vertices=count, virtual_voxel_size_m=float(values[0]),
                  run_config=str(config), surviving_weight_ge_2=valid, grid=grid, grid_ready=False,
                  source_uniform_finest=source_uniform,
                  surface_esdf_supported=source_uniform,
                  surface_esdf_mapping='native integer corners -> supported target centers, six-tetrahedron zero-surface distance; no coordinate shift',
                  source_grid_evidence='config gates adaptive reallocation off; fixed source audit, not full payload proof' if source_uniform else 'adaptive/unknown configuration needs per-sample levels',
                  source_sample_convention='mrhash_integer_lattice',
                  mapping_blocker='Define native-sample to Voxblox-center interpolation/aggregation and TSDF-to-ESDF policy; never shift or copy projected sdf as Euclidean distance')
    if grid:
        size = grid.get('voxel_size_m')
        if grid.get('uniform') is not True or isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
            raise ValueError('Invalid explicit uniform Distance grid metadata')
        # An assertion in a JSON object cannot certify interpolation or redefine
        # coordinates of the existing native artifact. No automatic ready=True.
        result['declared_target_voxel_size_m'] = size
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--job-dir', required=True, type=Path)
    p.add_argument('--scan', action='store_true', help='Stream all records; do not use on large data in CPU preparation')
    p.add_argument('--require-grid', action='store_true')
    args = p.parse_args()
    result = inspect(args.job_dir, args.scan)
    if args.require_grid and not result['grid_ready']:
        raise ValueError(result['mapping_blocker'])
    print(json.dumps(result, ensure_ascii=False, indent=2))
