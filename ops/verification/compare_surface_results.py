"""Read-only geometry/accounting verification for a baseline and full Surface Job."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import trimesh
import yaml
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def geometry(path):
    loaded = trimesh.load(path, process=False)
    if isinstance(loaded, trimesh.Scene):
        meshes = list(loaded.geometry.values())
        assert len(meshes) == 1, 'expected a single mesh'
        mesh = meshes[0]
    else:
        mesh = loaded
    vertices, inverse = np.unique(mesh.vertices, axis=0, return_inverse=True)
    faces = inverse[mesh.faces]
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    graph = coo_matrix((np.ones(len(edges), dtype=np.uint8), (edges[:, 0], edges[:, 1])),
                       shape=(len(vertices), len(vertices)))
    count, labels = connected_components(graph, directed=False)
    component_faces = np.bincount(labels[faces[:, 0]], minlength=count)
    used = component_faces[component_faces > 0]
    ordered = sorted(map(int, used), reverse=True)
    top = [{'faces': n, 'face_share': n / len(faces)} for n in ordered[:10]]
    return {
        'vertices': len(mesh.vertices), 'exact_unique_vertices': len(vertices),
        'faces': len(faces), 'bounds': mesh.bounds.tolist(),
        'extent_m': mesh.extents.tolist(), 'components_with_faces': len(used),
        'isolated_vertices': int((component_faces == 0).sum()),
        'top10_components': top, 'top5_face_share': sum(ordered[:5]) / len(faces),
        'components_under_10_faces': int((used < 10).sum()),
        'faces_in_components_under_10': int(used[used < 10].sum()),
        'face_share_in_components_under_10': float(used[used < 10].sum() / len(faces)),
        'components_under_100_faces': int((used < 100).sum()),
        'faces_in_components_under_100': int(used[used < 100].sum()),
        'face_share_in_components_under_100': float(used[used < 100].sum() / len(faces)),
        'connectedness_method': 'exact coordinate weld in memory only; undirected vertex-edge adjacency; face shares, no deletion',
        'sha256': sha(path), 'size_bytes': path.stat().st_size,
    }


def stage_info(root):
    stage = root / 'stage2_surface'
    manifest = json.loads((stage / 'result_manifest.json').read_text())
    artifacts = {a['artifact_id']: stage / a['path'] for a in manifest['artifacts']}
    return manifest, artifacts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline_job_id')
    parser.add_argument('full_job_id')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    baseline = root / 'jobs' / args.baseline_job_id
    full = root / 'jobs' / args.full_job_id
    out = full / 'verification'
    bm, ba = stage_info(baseline)
    fm, fa = stage_info(full)
    report = {'baseline_job_id': args.baseline_job_id, 'full_job_id': args.full_job_id,
              'scope': 'full Surface only; calibration and IMU-unit basis pending confirmation'}
    for name, manifest, artifacts in [('baseline', bm, ba), ('full', fm, fa)]:
        report[name] = {'native': geometry(artifacts['surface_mesh']),
                        'glb': geometry(artifacts['surface_model']),
                        'preview_method': manifest['metrics']['preview_method'],
                        'preview_target_faces': manifest['metrics']['preview_target_faces'],
                        'simplification_applied': manifest['metrics']['preview_simplification_applied']}
    # Algorithm config equality, ignoring only output/input paths and selected range.
    bc = yaml.safe_load(ba['run_config'].read_text())
    fc = yaml.safe_load(fa['run_config'].read_text())
    changed = {k: {'baseline': bc.get(k), 'full': fc.get(k)}
               for k in set(bc) | set(fc) if bc.get(k) != fc.get(k)}
    assert set(changed) <= {'data_path', 'results_path', 'end_frame'}
    assert fc['start_frame'] == 1 and fc['end_frame'] == -1
    report['config_changes'] = changed
    before = json.loads((out / 'baseline_sha256_before.json').read_text())
    now_files = {str(p.relative_to(baseline)) for p in baseline.rglob('*') if p.is_file() and not p.is_symlink()}
    mismatch = [name for name, value in before.items() if sha(baseline / name) != value]
    assert not mismatch and now_files == set(before)
    report['baseline_preserved'] = {'files_checked': len(before), 'all_sha256_unchanged': True, 'file_set_unchanged': True}
    # Actual-run accounting and successful-compute ledger, checked against the
    # previously verified bag index (the bag is hash-identical).
    accounting = json.loads(fa['frame_accounting'].read_text())
    ledger = [json.loads(line) for line in (fa['frame_accounting'].parent / 'fused_frames.jsonl').read_text().splitlines()]
    index = [list(map(int, line.split())) for line in (full / 'stage1_pose/native/bag_index.tsv').read_text().splitlines() if not line.startswith('#')]
    fused = [x['raw_frame_1based'] for x in ledger]
    skipped = [x['raw_frame_1based'] for x in accounting['skipped_frames']]
    total = accounting['bag_lidar_messages']
    assert total == len(index) == accounting['selected'] == accounting['raw_messages_visited']
    assert len(fused) == len(set(fused)) == accounting['fused'] == accounting['matched_pose']
    assert len(skipped) == len(set(skipped)) == accounting['skipped_no_pose']
    assert set(fused).isdisjoint(skipped)
    assert set(fused) | set(skipped) == set(range(1, total + 1))
    assert fused == sorted(fused)
    for frame in ledger:
        assert frame['timestamp_ns'] == index[frame['raw_frame_1based'] - 1][0]
        assert abs(frame['timestamp_ns'] - frame['pose_timestamp_ns']) <= 1000
        assert frame['compute_returned'] and frame['filtered_points'] > 0
    for frame in accounting['skipped_frames']:
        assert frame['timestamp_ns'] == index[frame['raw_frame_1based'] - 1][0]
        assert frame['delta_ns'] > 1000
    head = [i for i in skipped if i < min(fused)]
    tail = [i for i in skipped if i > max(fused)]
    interior = [i for i in skipped if min(fused) <= i <= max(fused)]
    accounting.update(head_unmatched_frames=head, tail_unmatched_frames=tail,
                      interior_unmatched_frames=interior, internal_missing_frame_count=len(interior),
                      ledger_rows=len(ledger), unique_fused_frames=len(set(fused)),
                      ledger_partition_covers_full_bag=True, actual_timestamps_agree_with_bag_index=True)
    report['accounting'] = accounting
    (out / 'geometry_and_accounting.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
