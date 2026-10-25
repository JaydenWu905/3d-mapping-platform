#!/usr/bin/env python3
"""Run actual converter input tests only when a real compiled binary is supplied.

No mock/fallback. Optional legacy diagnostic remains explicitly unaccepted ESDF.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

PROPS = [('float',n) for n in ['x','y','z','sdf','weight']] + [('uchar',n) for n in ['red','green','blue','alpha']]


def write_ply(path, records):
    header='ply\nformat binary_little_endian 1.0\nelement vertex '+str(len(records))+'\n'
    header+=''.join(f'property {t} {n}\n' for t,n in PROPS)+'end_header\n'
    path.write_bytes(header.encode()+b''.join(struct.pack('<5f4B',*row) for row in records))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--executable',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--legacy-diagnostic',action='store_true')
    p.add_argument('--reader',type=Path)
    args=p.parse_args()
    exe=args.executable.resolve()
    if not exe.is_file():raise SystemExit(f'Actual converter missing: {exe}; no fallback')
    if not os.access(exe,os.X_OK) or exe.open('rb').read(4)!=b'\x7fELF':
        raise SystemExit('A compiled ELF converter is required; scripts/test doubles are not native acceptance')
    root=Path(__file__).resolve().parents[2]
    report_path=args.report.resolve()
    for protected in [root/'jobs',root/'uploads']:
        if report_path.is_relative_to(protected.resolve()):
            raise SystemExit('Diagnostic reports must be outside shared historical Job/upload data')
    args.report.mkdir(parents=True,exist_ok=False)
    records=[(x,.05,.05,.2-x,2.,255,0,0,0) for x in (.05,.15,.25)]
    cases=[('signed_plane_input',records,[],True),
           ('duplicate',records+[records[0]],[],False),
           ('empty',[],[],False),
           ('truncated_payload',records,[],False),
           ('trailing_payload',records,[],False),
           ('ascii_header',records,[],False),
           ('zero_weight',[(.05,.05,.05,.2,0,0,0,0,0)],[],False),
           ('negative_weight',[(.05,.05,.05,.2,-1,0,0,0,0)],[],False),
           ('low_weight_only',[(.05,.05,.05,.2,1,0,0,0,0)],[],False),
           ('nan_sdf',[(.05,.05,.05,float('nan'),2,0,0,0,0)],[],False),
           ('infinite_coordinate',[(float('inf'),.05,.05,.2,2,0,0,0,0)],[],False),
           ('native_mrhash_center',[(0.,0.,0.,.2,2,255,0,0,0)],[],False),
           ('coarse_level',records,['--input-resolution','1'],False),
           ('different_resolution',records,['--source-voxel-size','.05'],False)]
    results=[]
    base=['--input-grid','voxblox_centers','--source-voxel-size','.1','--voxel_size','.1']
    for name,rows,extra,ok in cases:
        ply=args.report/f'{name}.ply';write_ply(ply,rows)
        if name=='truncated_payload':ply.write_bytes(ply.read_bytes()[:-1])
        if name=='trailing_payload':ply.write_bytes(ply.read_bytes()+b'x')
        if name=='ascii_header':ply.write_bytes(ply.read_bytes().replace(b'binary_little_endian',b'ascii'))
        command=[str(exe),'--validate-only' ,'--input',str(ply),*base,*extra]
        result=subprocess.run(command,text=True,capture_output=True,timeout=20)
        results.append(dict(name=name,expected_accept=ok,returncode=result.returncode,stdout=result.stdout,stderr=result.stderr))
        (args.report/'input-checks-progress.json').write_text(json.dumps(results,indent=2))
        if (result.returncode==0)!=ok:raise SystemExit(f'Native input check failed: {name}: {results[-1]}')
    if args.legacy_diagnostic:
        if not args.reader or not args.reader.is_file():raise SystemExit('Actual Voxblox reader required for diagnostic readback')
        out=args.report/'UNACCEPTED_LEGACY_DIAGNOSTIC'
        command=[str(exe),'--legacy-diagnostic','--input',str(args.report/'signed_plane_input.ply'),
                 '--output_dir',str(out),*base,'--max_esdf_distance','.2']
        diag=subprocess.run(command,capture_output=True,text=True,timeout=60)
        if diag.returncode:raise SystemExit(diag.stderr)
        readback=subprocess.run([str(args.reader.resolve()),str(out/'diagnostic-unaccepted.esdf'),'.1'],capture_output=True,text=True,timeout=20)
        if readback.returncode:raise SystemExit(readback.stderr)
        results.append(dict(name='unaccepted_legacy_diagnostic',stdout=diag.stdout,stderr=diag.stderr,readback=readback.stdout))
        if (out/'map.esdf').exists():raise SystemExit('Diagnostic must never masquerade as production map.esdf')
    report=dict(kind='ACTUAL_BINARY_INPUT_CHECKS_ONLY',executable=str(exe),sha256=hashlib.sha256(exe.read_bytes()).hexdigest(),
                cases=results,real_signed_euclidean_field_accepted=False,
                warning='Plane values validated as input, NOT verified as computed Euclidean output. Unknown policy still unresolved.')
    (args.report/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
