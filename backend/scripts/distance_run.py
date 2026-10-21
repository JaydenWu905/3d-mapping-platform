#!/usr/bin/env python3
"""Real native conversion, same-Job provenance, reload before publication."""
import argparse, hashlib, json, os, subprocess, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path
from distance_input import inspect

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  while b:=f.read(8*1024*1024):h.update(b)
 return h.hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--job-dir',type=Path,required=True);a=p.parse_args();stage=a.job_dir/'stage3_esdf';stage.mkdir(parents=True,exist_ok=True);start=time.monotonic()
 def progress(status,phase,percent,message):
  (stage/'progress.json').write_text(json.dumps(dict(stage='distance',backend='voxel_esdf',status=status,phase=phase,progress=percent,current=0,total=0,unit='',message=message,updated_at=datetime.now(timezone.utc).isoformat())))
 try:
  from app.services.distance_readiness import distance_unavailable_reason
  if reason:=distance_unavailable_reason():raise RuntimeError(reason)
  inp=inspect(a.job_dir,scan=False)
  if not inp['source_uniform_finest']:raise RuntimeError('Adaptive/unknown source grid unsupported')
  exe=Path(os.environ['ESDF_EXECUTABLE']);reader=exe.with_name('verify_esdf_layer');h=inp['virtual_voxel_size_m']
  progress('running','esdf_generation',10,'Computing signed distance to TSDF zero surface')
  provenance=dict(input=inp,input_sha256=sha(inp['input_ply']),config_sha256=sha(inp['run_config']),executable=str(exe.resolve()),executable_sha256=sha(exe),reader_sha256=sha(reader))
  command=[str(exe),'--surface-esdf','--input',inp['input_ply'],'--output_dir',str(stage),'--input-grid','mrhash_integer_centers','--input-resolution','0','--source-voxel-size',str(h),'--voxel_size',str(h),'--max_esdf_distance','2.5']
  provenance['command']=command;(stage/'provenance.json').write_text(json.dumps(provenance,indent=2))
  with (stage/'resources.txt').open('w') as resource:
   subprocess.run(['/usr/bin/time','-v',*command],stderr=resource,check=True)
  readback=subprocess.run([str(reader),str(stage/'map.esdf'),str(h)],capture_output=True,text=True,check=True)
  (stage/'native-readback.json').write_text(readback.stdout);validation=json.loads(readback.stdout)
  progress('running','slice_rendering',80,'Rendering observed-support signed distance slices')
  subprocess.run([sys.executable,str(Path(__file__).with_name('esdf_postprocess.py')),'--input_ply',str(stage/'preview/esdf_vis.ply'),'--output_dir',str(stage/'preview'),'--resolution','480'],check=True)
  conversion=json.loads((stage/'conversion.json').read_text());slices=json.loads((stage/'preview/slices_meta.json').read_text())
  artifacts=[]
  for id,role,path,ctype,download in [('esdf_map','data','map.esdf','application/octet-stream',True),('esdf_vis_ply','preview','preview/esdf_vis.ply','application/octet-stream',False),('conversion','data','conversion.json','application/json',True),('provenance','data','provenance.json','application/json',True),('native_readback','data','native-readback.json','application/json',True),('slices_meta','data','preview/slices_meta.json','application/json',True)]+[(f'slice_{plane}','preview',f'preview/slice_{plane}.png','image/png',False) for plane in slices]:
   f=stage/path
   if not f.is_file() or not f.stat().st_size:raise RuntimeError(f'Missing artifact {f}')
   artifacts.append(dict(artifact_id=id,role=role,path=path,content_type=ctype,download=download,size_bytes=f.stat().st_size,sha256=sha(f)))
  manifest=dict(schema_version='0.1',job_id=a.job_dir.name,stage='distance',backend='voxel_esdf',status='completed',frame_id='world',unit='meter',runtime_sec=time.monotonic()-start,metrics=dict(resolution_m=h,slices=list(slices),**validation),artifacts=artifacts,backend_details=dict(mock_backend=False,algorithm=conversion['algorithm'],voxel_size_m=h,max_esdf_distance_m=2.5,unknown_policy=conversion['unknown_policy'],surface_definition='piecewise linear TSDF zero isosurface, six tetrahedra/cell; exact BVH triangle distance at supported centers; sign from same linear field',input_sha256=provenance['input_sha256']))
  (stage/'result_manifest.json').write_text(json.dumps(manifest,indent=2));progress('completed','completed',100,'Completed')
 except Exception as e:
  progress('failed','conversion_failed',0,str(e));traceback.print_exc();return 1
 return 0
if __name__=='__main__':raise SystemExit(main())
