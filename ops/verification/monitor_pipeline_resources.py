import argparse
import json,os,subprocess,time,urllib.request
from pathlib import Path
r=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('job_id');args=parser.parse_args();jid=args.job_id;job=r/'jobs'/jid;out=job/'verification';out.mkdir(exist_ok=True);started=time.monotonic();history=[];last=None;peaks={'rss_sum_kib':0,'gpu_memory_used_mib':0,'gpu_util_percent':0};overlaps=[];count=0;algorithms_seen=set()
with (out/'pipeline_resource_samples.jsonl').open('w',buffering=1) as stream:
 while True:
  procs={}
  for p in Path('/proc').iterdir():
   if not p.name.isdigit():continue
   try:
    cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace');stat=(p/'stat').read_text().rsplit(')',1)[1].split();procs[int(p.name)]={'ppid':int(stat[1]),'rss_kib':int(stat[21])*os.sysconf('SC_PAGE_SIZE')//1024,'cmd':cmd}
   except (OSError,ValueError,IndexError):pass
  roots={pid for pid,p in procs.items() if jid in p['cmd'] and any(x in p['cmd'] for x in ['glim_pose_adapter.py','mrhash_surface_adapter.py'])};desc=set(roots)
  while True:
   more={pid for pid,p in procs.items() if p['ppid'] in desc}
   if more<=desc:break
   desc|=more
  selected={pid:procs[pid] for pid in desc};algos=set()
  for p in selected.values():
   if 'glim_rosnode' in p['cmd'] and '/bin/bash' not in p['cmd']:algos.add('GLIM')
   if 'rosbag_runner.py' in p['cmd'] and '/bin/pixi' not in p['cmd']:algos.add('MrHash')
  algorithms_seen|=algos
  try:
   values=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=3).splitlines()[0].split(',');mem,util=map(int,values)
   gpu_processes=subprocess.check_output(['nvidia-smi','--query-compute-apps=pid,process_name,used_memory','--format=csv,noheader,nounits'],text=True,timeout=3).strip()
  except Exception:mem=util=0;gpu_processes='query failed'
  state=json.loads((job/'job.json').read_text());statuses={s:state['stages'][s]['status'] for s in ['pose','surface']};entry={'elapsed_sec':round(time.monotonic()-started,2),'statuses':statuses,'algorithms':sorted(algos),'rss_sum_kib':sum(p['rss_kib'] for p in selected.values()),'gpu_memory_used_mib':mem,'gpu_util_percent':util,'gpu_processes':gpu_processes,'processes':selected};stream.write(json.dumps(entry)+'\n');count+=1
  if len(algos)>1:overlaps.append(entry['elapsed_sec'])
  for k in peaks:peaks[k]=max(peaks[k],entry[k])
  if statuses!=last:history.append({'elapsed_sec':entry['elapsed_sec'],**statuses});last=statuses
  if state['status'] in ['completed','failed','cancelled']:break
  if time.monotonic()-started>1600:break
  time.sleep(1)
summary={'job_id':jid,'sample_interval_sec':1,'samples':count,'peaks':peaks,'observed_algorithm_overlap_samples':overlaps,'algorithms_seen':sorted(algorithms_seen),'status_transitions':history,'final_status':state['status'],'scope':'process tree RSS sum may duplicate shared pages; GPU metrics device-wide; startup sampling follows browser job creation'};(out/'pipeline_resource_summary.json').write_text(json.dumps(summary,indent=2));print(summary)
