#!/usr/bin/env python3
"""Real native conversion, atomic progress and validated publication."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.live_progress import ProgressReporter
from app.models.progress import atomic_write_json, read_json
from distance_input import inspect


def hash_files(paths, reporter, phase):
    total = sum(path.stat().st_size for path in paths)
    offset = 0
    values = []
    reporter.emit(phase,0,total,scope='step',unit='字节',force=True)
    for path in paths:
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            while chunk := handle.read(1024*1024):
                digest.update(chunk); offset += len(chunk)
                reporter.emit(phase,offset,total,scope='step',unit='字节')
        values.append(digest.hexdigest())
    reporter.emit(phase,offset,total,scope='step',unit='字节',force=True)
    return values


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--job-dir',type=Path,required=True)
    args=parser.parse_args();stage=args.job_dir/'stage3_esdf';stage.mkdir(parents=True,exist_ok=True)
    managed = bool(os.environ.get('PLATFORM_PROGRESS_RUN_ID'))
    os.environ.setdefault('PLATFORM_PROGRESS_RUN_ID',uuid.uuid4().hex)
    os.environ.setdefault('PLATFORM_ALGORITHM_PROGRESS_PATH',str(stage/'algorithm_progress.json'))
    reporter=ProgressReporter();start=time.monotonic()
    def child_env():
        snapshot=read_json(reporter.path,{}) or {}
        return {**os.environ,'PLATFORM_PROGRESS_SEQ':str(snapshot.get('seq',0))}
    try:
        reporter.emit('validating',force=True)
        from app.services.distance_readiness import distance_unavailable_reason
        if reason:=distance_unavailable_reason(): raise RuntimeError(reason)
        inp=inspect(args.job_dir,scan=False)
        if not inp['source_uniform_finest']:raise RuntimeError('Adaptive/unknown source grid unsupported')
        exe=Path(os.environ['ESDF_EXECUTABLE']);reader=exe.with_name('verify_esdf_layer');h=inp['virtual_voxel_size_m']
        hashes=hash_files([Path(inp['input_ply']),Path(inp['run_config']),exe,reader],reporter,'checking_input')
        provenance=dict(input=inp,input_sha256=hashes[0],config_sha256=hashes[1],executable=str(exe.resolve()),executable_sha256=hashes[2],reader_sha256=hashes[3])
        command=[str(exe),'--surface-esdf','--input',inp['input_ply'],'--output_dir',str(stage),'--input-grid','mrhash_integer_centers','--input-resolution','0','--source-voxel-size',str(h),'--voxel_size',str(h),'--max_esdf_distance','2.5']
        provenance['command']=command;atomic_write_json(stage/'provenance.json',provenance)
        reporter.emit('esdf_generation',force=True)
        with (stage/'resources.txt').open('w') as resource:
            subprocess.run(['/usr/bin/time','-v',*command],stderr=resource,check=True,env=child_env())
        reporter.emit('loading_validation',force=True)
        readback=subprocess.run([str(reader),str(stage/'map.esdf'),str(h)],capture_output=True,text=True,check=True,env=child_env())
        (stage/'native-readback.json').write_text(readback.stdout);validation=json.loads(readback.stdout)
        reporter.emit('loading_preview',force=True)
        subprocess.run([sys.executable,str(Path(__file__).with_name('esdf_postprocess.py')),'--input_ply',str(stage/'preview/esdf_vis.ply'),'--output_dir',str(stage/'preview'),'--resolution','480'],check=True,env=child_env())
        conversion=json.loads((stage/'conversion.json').read_text());slices=json.loads((stage/'preview/slices_meta.json').read_text())
        specs=[('esdf_map','data','map.esdf','application/octet-stream',True),('esdf_vis_ply','preview','preview/esdf_vis.ply','application/octet-stream',False),('conversion','data','conversion.json','application/json',True),('provenance','data','provenance.json','application/json',True),('native_readback','data','native-readback.json','application/json',True),('slices_meta','data','preview/slices_meta.json','application/json',True)]+[(f'slice_{plane}','preview',f'preview/slice_{plane}.png','image/png',False) for plane in slices]
        files=[stage/path for _,_,path,_,_ in specs]
        for path in files:
            if not path.is_file() or not path.stat().st_size:raise RuntimeError(f'Missing artifact {path}')
        hashes=hash_files(files,reporter,'hashing_outputs')
        artifacts=[dict(artifact_id=id,role=role,path=path,content_type=ctype,download=download,size_bytes=file.stat().st_size,sha256=digest) for (id,role,path,ctype,download),file,digest in zip(specs,files,hashes)]
        manifest=dict(schema_version='0.1',job_id=args.job_dir.name,stage='distance',backend='voxel_esdf',status='completed',frame_id='world',unit='meter',runtime_sec=time.monotonic()-start,metrics=dict(resolution_m=h,slices=list(slices),**validation),artifacts=artifacts,backend_details=dict(mock_backend=False,algorithm=conversion['algorithm'],voxel_size_m=h,max_esdf_distance_m=2.5,unknown_policy=conversion['unknown_policy'],surface_definition='piecewise linear TSDF zero isosurface, six tetrahedra/cell; exact BVH triangle distance at supported centers; sign from same linear field',input_sha256=provenance['input_sha256']))
        atomic_write_json(stage/'result_manifest.json',manifest)
        reporter.emit('finalizing',force=True)
        if not managed:atomic_write_json(stage/'progress.json',dict(stage='distance',backend='voxel_esdf',status='completed',phase='completed',progress=100))
    except Exception as exc:
        reporter.emit('conversion_failed',force=True)
        if not managed:atomic_write_json(stage/'progress.json',dict(stage='distance',backend='voxel_esdf',status='failed',phase='conversion_failed',progress=0,message=str(exc)))
        traceback.print_exc();return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
