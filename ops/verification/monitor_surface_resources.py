import argparse,json,os,subprocess,time
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('job_id');args=parser.parse_args();root=Path(__file__).resolve().parents[2];job_id=args.job_id;job=root/'jobs'/job_id;out=job/'verification';samples=out/'resource_samples.jsonl';t0=time.monotonic();seen=False;peaks={'rss_sum_kib':0,'gpu_memory_used_mib':0,'gpu_util_percent':0,'cpu_percent_aggregate':0};last_cpu=None;last_t=None;tracked_cpu={};count=0
with samples.open('w',buffering=1) as f:
 while True:
  procs={}
  for p in Path('/proc').iterdir():
   if not p.name.isdigit():continue
   try:
    cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace');stat=(p/'stat').read_text().rsplit(')',1)[1].split();procs[int(p.name)]={'ppid':int(stat[1]),'cpu_sec':(int(stat[11])+int(stat[12]))/os.sysconf('SC_CLK_TCK'),'rss_kib':int(stat[21])*os.sysconf('SC_PAGE_SIZE')//1024,'cmd':cmd}
   except (OSError,ValueError,IndexError):pass
  roots={pid for pid,p in procs.items() if job_id in p['cmd'] and 'mrhash_surface_adapter.py' in p['cmd']}
  descendants=set(roots)
  while True:
   more={pid for pid,p in procs.items() if p['ppid'] in descendants}
   if more <= descendants:break
   descendants|=more
  selected={pid:procs[pid] for pid in descendants};seen|=bool(selected)
  now=time.monotonic();cpu=sum(p['cpu_sec'] for p in selected.values());rss=sum(p['rss_kib'] for p in selected.values());cpu_rate=0
  if last_t:
   cpu_rate=sum(max(0,p['cpu_sec']-tracked_cpu.get(pid,p['cpu_sec'])) for pid,p in selected.items())/(now-last_t)*100
  tracked_cpu={pid:p['cpu_sec'] for pid,p in selected.items()};last_t=now
  try:
   vals=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=3).splitlines()[0].split(',');gpu_mem,gpu_util=map(int,vals)
  except Exception:gpu_mem=gpu_util=0
  entry={'elapsed_sec':round(now-t0,2),'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'rss_sum_kib':rss,'cpu_percent_aggregate':round(cpu_rate,2),'gpu_memory_used_mib':gpu_mem,'gpu_util_percent':gpu_util,'processes':selected};f.write(json.dumps(entry)+'\n');count+=1
  for k in peaks:peaks[k]=max(peaks[k],entry[k])
  state=json.loads((job/'job.json').read_text())['stages']['surface']['status']
  if state in ('completed','failed','cancelled') and seen:break
  if now-t0>1200:break
  time.sleep(1)
summary={'sampling_interval_sec':1,'samples':count,'elapsed_observed_sec':round(time.monotonic()-t0,3),'peaks':peaks,'gpu_metric_scope':'device-wide; idle before launch; samples include fusion and packaging','rss_metric_scope':'sum of resident memory of adapter process tree, may double-count shared pages','cpu_metric_scope':'process-tree sampled CPU rate; 100% equals one CPU core','final_surface_status':state};(out/'resource_summary.json').write_text(json.dumps(summary,indent=2));print(summary)
