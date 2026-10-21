#!/usr/bin/env python3
"""Actual ELF + native Voxblox reload acceptance; analytic surfaces, no mocks."""
import argparse, hashlib, itertools, json, math, subprocess
from pathlib import Path
from distance_native_checks import write_ply

def main():
 p=argparse.ArgumentParser();p.add_argument('--executable',type=Path,required=True);p.add_argument('--reader',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
 a.report.mkdir(parents=True,exist_ok=False)
 for exe in [a.executable,a.reader]:
  if exe.open('rb').read(4)!=b'\x7fELF':raise RuntimeError('Actual native ELF required')
 results=[];h=.1
 def run(name,rows,ok=True,out_setup=None):
  ply=a.report/(name+'.ply');write_ply(ply,rows);out=a.report/name
  if out_setup:out_setup(out)
  cmd=[str(a.executable),'--surface-esdf','--input',str(ply),'--output_dir',str(out),'--input-grid','mrhash_integer_centers','--input-resolution','0','--source-voxel-size',str(h),'--voxel_size',str(h),'--max_esdf_distance','2.5']
  r=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
  record=dict(name=name,command=cmd,returncode=r.returncode,stdout=r.stdout,stderr=r.stderr,expected_success=ok);results.append(record)
  (a.report/'progress.json').write_text(json.dumps(results,indent=2))
  if (r.returncode==0)!=ok:raise AssertionError(record)
  if ok:
   dump=out/'native.tsv';r=subprocess.run([str(a.reader),str(out/'map.esdf'),str(h),str(dump)],capture_output=True,text=True,check=True);record['readback']=json.loads(r.stdout)
   return [[float(x) for x in l.split()] for l in dump.read_text().splitlines()],record
 grid=list(itertools.product(range(-6,7),repeat=3))
 def rows(normal,offset,scale=1):
  return [(i*h,j*h,k*h,(offset-(normal[0]*i+normal[1]*j+normal[2]*k)*h)*scale,3,255,0,0,0) for i,j,k in grid]
 for name,n,c,scale in [('axis',(1,0,0),.05,1),('tilted_projective',(.6,.8,0),.03,1/.6),('oblique_projective',(1/math.sqrt(3),)*3,.05,2)]:
  records=rows(n,c,scale);data,rec=run(name,records)
  errors=[];signed=zero=0
  for x,y,z,d in data:
   for q in [x,y,z]:assert abs(q/h-.5-round(q/h-.5))<1e-5
   # Interior closest point must lie inside finite reconstructed plane patch.
   expected=c-sum(v*t for v,t in zip(n,[x,y,z]));foot=[v+expected*t for v,t in zip([x,y,z],n)]
   if max(map(abs,foot))<.45:
    errors.append(abs(d-expected));signed+=int(d*expected>0);zero+=int(abs(expected)<1e-8)
  assert errors and max(errors)<2e-6,(name,max(errors))
  assert any(d<0 for *_,d in data) and any(d>0 for *_,d in data)
  rec.update(samples_compared=len(errors),tolerance_m=2e-6,max_error_m=max(errors),signed_samples=signed,zero_samples=zero)
  if name=='axis':assert zero>0
 # Curved surface: tetra interpolation curvature bound, fixed before measurement.
 radius=.35
 sphere=[(i*h,j*h,k*h,radius-math.sqrt(i*i+j*j+k*k)*h,3,255,0,0,0) for i,j,k in grid]
 data,rec=run('sphere',sphere)
 bound=3*h*h/(8*(radius-math.sqrt(3)*h))
 errors=[abs(d-(radius-math.sqrt(x*x+y*y+z*z))) for x,y,z,d in data]
 assert max(errors)<bound,(max(errors),bound)
 rec.update(tolerance_m=bound,max_error_m=max(errors),tolerance_basis='linear interpolation Hessian bound: 3*h^2/(8*(R-sqrt(3)*h))')
 # Explicit finite calculation radius; supported cells beyond it remain unknown.
 radius_rows=[(i*h,j*h,k*h,.023-i*h,3,255,0,0,0) for i in range(-30,31) for j in [0,1] for k in [0,1]]
 data,rec=run('calculation_radius',radius_rows)
 got={tuple(round(v/h-.5) for v in row[:3]) for row in data}
 assert got=={(i,0,0) for i in range(-25,25)},got
 rec.update(observed_expected=50,observed_actual=len(got),outside_radius_preserved_unknown=True)
 # Unknown corner hole and low weight eliminate exactly incident cells; no propagation.
 base=rows((1,0,0),.05);hole=(0.,0.,0.)
 for name,rr in [('missing_corner',[r for r in base if r[:3]!=hole]),('low_weight',[(*r[:4],1,*r[5:]) if r[:3]==hole else r for r in base])]:
  data,rec=run(name,rr);got={tuple(round(v/h-.5) for v in row[:3]) for row in data};expected=set(itertools.product(range(-6,6),repeat=3))-set(itertools.product([-1,0],repeat=3));assert got==expected,(name,len(got),len(expected));rec['unknown_cells_verified']=8;rec['support_exact_match']=True
 for name,rr in [('duplicate',base+[base[0]]),('empty',[]),('nan',[(*base[0][:3],float('nan'),*base[0][4:])]),('zero_weight',[(*base[0][:4],0,*base[0][5:])]),('low_only',[(*r[:4],1,*r[5:]) for r in base]),('no_zero_crossing',[(r[0],r[1],r[2],.1,*r[4:]) for r in base])]:run(name,rr,False)
 run('save_failure',base,False,lambda out:(out/'map.esdf').mkdir(parents=True))
 report=dict(kind='REAL_NATIVE_SURFACE_ESDF_ACCEPTANCE',accepted=True,algorithm='native_tsdf_zero_surface_tetra_bvh_v1',h_m=h,executable_sha256=hashlib.sha256(a.executable.read_bytes()).hexdigest(),reader_sha256=hashlib.sha256(a.reader.read_bytes()).hexdigest(),cases=results)
 (a.report/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
