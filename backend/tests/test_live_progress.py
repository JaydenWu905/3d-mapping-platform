import asyncio
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.models.job import new_job
from app.models.progress import atomic_write_json, read_json
from app.models.live_progress import ProgressReporter, accept_algorithm_snapshot
from app.services.job_service import JobService, collect_backend_labels
from app.services.registry_service import get_registry
from app.services.event_service import EventService
from app.services.runner_adapter import SubprocessRunnerAdapter
from app.api.events import stream_job_events
from app.api.jobs import get_job


def snapshot(seq=1,**fields):
    return dict(protocol=1,run_id='run-a',seq=seq,phase='mapping',current=2,total=10,
                selected_frames=10,visited_frames=3,matched_frames=2,fused_frames=2,
                skipped_frames=1,progress_scope='input',unit='帧',**fields)


class LiveProgressTests(unittest.TestCase):
    def test_old_run_old_sequence_and_regression_rejected(self):
        base={'progress_run_id':'run-a','progress_seq':0}
        current=accept_algorithm_snapshot(base,snapshot())
        self.assertEqual(current['fused_frames'],2)
        for bad in [{**snapshot(2),'run_id':'old'},snapshot(1),{**snapshot(2),'current':1},
                    {**snapshot(2),'fused_frames':11},{**snapshot(2),'current':float('nan')},
                    {**snapshot(2),'total':1},{**snapshot(2),'matched_frames':20}]:
            self.assertIs(accept_algorithm_snapshot(current,bad),current)
        exported=accept_algorithm_snapshot(current,{**snapshot(2),'phase':'exporting_native','current':0,'total':0,'progress_scope':'none'})
        self.assertEqual(exported['phase'],'exporting_native')
        self.assertEqual(exported['fused_frames'],2)
        self.assertEqual(exported['progress'],0)

    def test_writer_continues_sequence_between_parent_and_child(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'PLATFORM_PROGRESS_RUN_ID':'run-a'}):
            path=Path(temp)/'algorithm_progress.json'
            first=ProgressReporter(path);first.emit('reading_input',1,10,scope='step',force=True)
            second=ProgressReporter(path);second.emit('reading_input',2,10,scope='step',force=True)
            first.emit('hashing_outputs',0,20,scope='step',force=True)
            self.assertEqual(read_json(path)['seq'],3)

    def test_compute_count_increments_only_after_success_and_skips_are_kept(self):
        file=Path(__file__).parents[1]/'scripts/mrhash_live_runner.py'
        spec=importlib.util.spec_from_file_location('live_mrhash',file);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Reader:
            def __init__(self):self.num_messages=10;self.start_frame=2;self.end_frame=6;self.selected_count=0;self.matched_count=0;self.skip=0
            def __next__(self):self.selected_count+=1;self.matched_count+=1;return 'unchanged-input'
        class Geometry:
            fail=False
            def compute(self):
                if self.fail:raise RuntimeError('compute failed')
                return 'unchanged-result'
            def streamAllOut(self):return 'export'
        events=[]
        reporter=SimpleNamespace(emit=lambda *a,**k:events.append((a,k)))
        target=SimpleNamespace(Ros1Reader=Reader,GeoWrapper=Geometry)
        module.instrument(target,reporter)
        reader=target.Ros1Reader();geometry=target.GeoWrapper()
        self.assertEqual(next(reader),'unchanged-input')
        self.assertEqual(geometry.compute(),'unchanged-result')
        reader.skip+=1;reader.selected_count+=1
        next(reader);geometry.target.fail=True
        with self.assertRaises(RuntimeError):geometry.compute()
        geometry.streamAllOut()
        self.assertEqual(events[-1][0][0],'exporting_native')
        self.assertEqual(events[-1][1]['fused_frames'],1)
        self.assertEqual(events[-1][1]['selected_frames'],5)
        self.assertEqual(events[-1][1]['matched_frames'],2)
        self.assertEqual(events[-1][1]['skipped_frames'],1)


class CapturedEvents(EventService):
    def __init__(self):super().__init__();self.items=[]
    async def publish(self,jid,kind,payload):
        self.items.append((kind,dict(payload)))
        await super().publish(jid,kind,payload)


class Producer(SubprocessRunnerAdapter):
    def __init__(self,jobs,events,code):super().__init__(jobs,events,mode='full');self.code=code
    def _build_command(self,jid,stage,backend):return [sys.executable,'-c',self.code,str(self._jobs.stage_dir(jid,stage))]


class PipelineProgressTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        guard=patch('app.services.runner_adapter.PROJECT_ROOT',self.root);guard.start();self.addCleanup(guard.stop)
        self.jobs=JobService(self.root/'jobs');self.events=CapturedEvents()

    def job(self,key):
        job=new_job('demo_room',{'pose':'glim','surface':'mrhash_lidar','distance':'voxel_esdf'},job_id='controlled_'+key)
        job['stages']['pose']['status']='completed'
        if key=='distance':job['stages']['surface']['status']='completed'
        self.jobs.save_job(job);return job['job_id']

    async def exercise(self,key,fail=False):
        jid=self.job(key)
        code='''
import sys,os,time,json
from pathlib import Path
from app.models.live_progress import ProgressReporter
from app.models.progress import atomic_write_json
p=ProgressReporter();stage=Path(sys.argv[1]);key=KEY
for i in [0,2,5,8]:
 if key=='surface':p.emit('mapping',i,10,scope='input',unit='帧',force=True,selected_frames=10,visited_frames=i+1,matched_frames=i,fused_frames=i,skipped_frames=1)
 else:p.emit('distance_computation',i,10,scope='step',unit='支撑中心',force=True)
 print('processing: 99%|misleading log| 999/1000',flush=True)
 time.sleep(.6)
p.emit('building_preview' if key=='surface' else 'writing_outputs',force=True)
time.sleep(.6)
if FAIL:sys.exit(7)
atomic_write_json(stage/'result_manifest.json',{'status':'completed','metrics':{'selected_frames':10,'matched_pose_frames':8,'fused_frames':8,'skipped_no_pose_frames':2}})
'''.replace('KEY',repr(key)).replace('FAIL',repr(fail))
        runner=Producer(self.jobs,self.events,code)
        request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(jobs=self.jobs,events=self.events)))
        response=await stream_job_events(jid,request);stream=response.body_iterator
        initial=await anext(stream);self.assertIn('event: snapshot',initial)
        task=asyncio.create_task(runner.run_stage(jid,key,'mrhash_lidar' if key=='surface' else 'voxel_esdf'))
        frames=[];details=[]
        while not task.done():
            try:
                frames.append(await asyncio.wait_for(anext(stream),timeout=2))
            except asyncio.TimeoutError:break
            details.append(await get_job(jid,request))
            if any('event: stage.result' in frame for frame in frames):break
        result=await task;await stream.aclose()
        live=[d['stages'][key] for d in details if d['stages'][key].get('progress_scope') in ('input','step')]
        self.assertGreaterEqual(len(set(d['current'] for d in live)),3)
        self.assertTrue(all(d['progress']==0 and d['status']=='running' for d in live))
        self.assertTrue(all(d['current']<=10 for d in live))
        final=await get_job(jid,request)
        self.assertEqual(final['stages'][key]['status'],'failed' if fail else 'completed')
        self.assertEqual(final['stages'][key]['progress'],0 if fail else 100)
        self.assertTrue(any('progress_seq' in frame for frame in frames))
        if os.environ.get('PROGRESS_CAPTURE_DIR') and not fail:
            out=Path(os.environ['PROGRESS_CAPTURE_DIR']);out.mkdir(parents=True,exist_ok=True)
            (out/(key+'-pipeline.json')).write_text(json.dumps({'job':next(d for d in details if d['stages'][key].get('progress_run_id')),'events':[p for kind,p in self.events.items if kind=='stage.progress']},ensure_ascii=False,indent=2))
        return final

    async def test_surface_process_file_api_and_real_sse_stream(self):await self.exercise('surface')
    async def test_distance_process_file_api_and_real_sse_stream(self):await self.exercise('distance')
    async def test_failure_cannot_turn_partial_counters_into_complete(self):await self.exercise('surface',True)

    async def test_zero_exit_without_manifest_is_not_completion(self):
        jid=self.job('distance')
        code="from app.models.live_progress import ProgressReporter;ProgressReporter().emit('distance_computation',3,10,scope='step',force=True)"
        result=await Producer(self.jobs,self.events,code).run_stage(jid,'distance','voxel_esdf')
        self.assertEqual(result.status,'failed')
        state=read_json(self.jobs.stage_dir(jid,'distance')/'progress.json');self.assertEqual(state['progress'],0)

    async def test_restart_marks_stale_progress_failed_and_preserves_counters(self):
        jid=self.job('surface');job=self.jobs.load_job(jid);self.jobs.set_stage_status(job,'surface','running')
        atomic_write_json(self.jobs.stage_dir(jid,'surface')/'progress.json',{'progress_run_id':'run-a','progress_seq':9,'fused_frames':3,'selected_frames':10,'progress':0})
        self.assertEqual(self.jobs.reconcile_interrupted_jobs(),1)
        progress=read_json(self.jobs.stage_dir(jid,'surface')/'progress.json')
        self.assertEqual((progress['status'],progress['phase'],progress['progress_seq'],progress['fused_frames']),('failed','interrupted',10,3))

    async def test_cancel_preserves_direct_counts_without_completing(self):
        jid=self.job('surface')
        code="""
import time
from app.models.live_progress import ProgressReporter
ProgressReporter().emit('mapping',3,10,scope='input',force=True,selected_frames=10,visited_frames=3,matched_frames=3,fused_frames=3,skipped_frames=0)
time.sleep(30)
"""
        runner=Producer(self.jobs,self.events,code)
        runner._TERMINATE_GRACE_SEC=.2
        task=asyncio.create_task(runner.run_stage(jid,'surface','mrhash_lidar'))
        for _ in range(100):
            await asyncio.sleep(.02)
            if read_json(self.jobs.stage_dir(jid,'surface')/'progress.json',{}).get('fused_frames')==3:break
        runner.cancel(jid,'surface');result=await asyncio.wait_for(task,5)
        state=read_json(self.jobs.stage_dir(jid,'surface')/'progress.json')
        self.assertEqual((result.status,state['fused_frames'],state['progress']),('cancelled',3,0))
        self.assertFalse((self.jobs.stage_dir(jid,'surface')/'result_manifest.json').exists())

    async def test_quiet_counter_does_not_advance_and_reports_age(self):
        jid=self.job('distance');stage=self.jobs.stage_dir(jid,'distance');stage.mkdir(parents=True)
        runner=Producer(self.jobs,self.events,'');runner._progress_states[(jid,'distance')]={'progress_run_id':'run-a','progress_seq':2,'current':3,'total':10,'phase':'distance_computation','counter_updated_at':'2020-01-01T00:00:00+00:00'}
        atomic_write_json(stage/'progress.json',{'phase':'old','current':99,'total':100})
        process=SimpleNamespace(returncode=None)
        task=asyncio.create_task(runner._poll_progress(jid,'distance','voxel_esdf',process,time.monotonic()))
        await asyncio.sleep(.05);process.returncode=0;await task
        progress=read_json(stage/'progress.json');self.assertEqual(progress['current'],3);self.assertGreater(progress['counter_age_sec'],15)

    async def test_queued_cancellation_has_fresh_identity_and_terminal_sequence(self):
        jid=self.job('surface');runner=Producer(self.jobs,self.events,'')
        path=self.root/'runtime/locks/gpu_pipeline.lock';path.parent.mkdir(parents=True)
        with path.open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            task=asyncio.create_task(runner.run_stage(jid,'surface','mrhash_lidar'))
            for _ in range(100):
                await asyncio.sleep(.01)
                state=read_json(self.jobs.stage_dir(jid,'surface')/'progress.json',{})
                if state.get('status')=='queued':break
            self.assertEqual(state['status'],'queued');self.assertTrue(state['progress_run_id'])
            runner.cancel(jid,'surface');result=await asyncio.wait_for(task,3)
            final=read_json(self.jobs.stage_dir(jid,'surface')/'progress.json')
            self.assertEqual(result.status,'cancelled');self.assertGreater(final['progress_seq'],state['progress_seq'])

    async def test_retry_marker_invalidates_stale_completed_manifest(self):
        from app.services.runner_service import RunnerService
        jid=self.job('distance');job=self.jobs.load_job(jid)
        self.jobs.set_stage_status(job,'distance','completed')
        path=self.jobs.stage_dir(jid,'distance');path.mkdir(parents=True)
        atomic_write_json(path/'result_manifest.json',{'status':'completed'})
        self.jobs.datasets=SimpleNamespace(get=lambda _:SimpleNamespace(execution='real'))
        runner=RunnerService(self.jobs,self.events);runner._reset_progress(jid,'distance')
        detail=self.jobs.job_detail(jid,get_registry(),collect_backend_labels(get_registry()))['stages']['distance']
        self.assertEqual(detail['status'],'waiting');self.assertTrue(detail['progress_run_id'])

    async def test_mock_retry_keeps_legacy_progress_protocol(self):
        from app.services.runner_service import RunnerService
        jid=self.job('distance');RunnerService(self.jobs,self.events)._reset_progress(jid,'distance')
        state=read_json(self.jobs.stage_dir(jid,'distance')/'progress.json')
        self.assertNotIn('progress_run_id',state)

    async def test_cancel_control_is_persisted_and_carries_progress_version(self):
        from app.services.runner_service import RunnerService
        jid=self.job('surface');job=self.jobs.load_job(jid);self.jobs.set_stage_status(job,'surface','running')
        atomic_write_json(self.jobs.stage_dir(jid,'surface')/'progress.json',{'progress_run_id':'current','progress_seq':12,'current':3,'total':10})
        runner=RunnerService(self.jobs,self.events)
        waiting=asyncio.create_task(asyncio.sleep(30));runner._stage_tasks[(jid,'surface')]=waiting
        try:
            runner.cancel_stage(jid,'surface');await asyncio.sleep(.01)
            detail=self.jobs.job_detail(jid,get_registry(),collect_backend_labels(get_registry()))
            self.assertEqual(detail['status'],'running');self.assertEqual(detail['stages']['surface']['status'],'cancelling')
            control=[p for k,p in self.events.items if k=='stage.status'][-1]
            self.assertEqual((control['status'],control['progress_run_id'],control['progress_seq']),('cancelling','current',12))
        finally:waiting.cancel();await asyncio.gather(waiting,return_exceptions=True)


if __name__=='__main__':unittest.main()
