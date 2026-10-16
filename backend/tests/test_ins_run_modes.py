import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.services.job_service import JobService
from app.services.runner_adapter import SubprocessRunnerAdapter, StageResult
from app.services.runner_service import RunnerService
from backend.tests.test_glim_dataset_and_dispatch import FakeRegistry, real_dataset
from backend.tests.test_surface_input import Jobs
from app.services.surface_input_service import prepare_mrhash_lidar_input, SurfaceInputError


class InsRunModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_jobs_persist_full_and_short_without_changing_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            definition = real_dataset(runtime={}, surface={'backend':'mrhash_lidar','mrhash_profile':'ins_livox_mid360_custom','integration_end_frame':100})
            definition.source_file = lambda key: root / 'bag.bag'
            service = JobService(root/'jobs', SimpleNamespace(get=lambda _:definition))
            for mode, limit in [('full',None),('short',100)]:
                job = await service.create_job('ins',{'pose':'glim','surface':'mrhash_lidar'},registry=FakeRegistry(),run_mode=mode)
                restored = service.load_job(job['job_id'])
                self.assertEqual(restored['run_scope']['surface_end_frame'],limit)
                self.assertEqual(restored['run_scope']['pose'],'full')
                adapter=SubprocessRunnerAdapter(service,SimpleNamespace(),mode='demo')
                for stage in ('pose','surface'):
                    self.assertEqual(adapter._build_command(job['job_id'],stage,job['backends'][stage])[-1],'full')
            self.assertEqual(definition.surface['integration_end_frame'],100)

    async def test_surface_manifest_honors_scope_and_rejects_inconsistent_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            jobs=Jobs(Path(tmp));jobs.definition.surface.update(topic='/livox_mid360/livox/lidar',mrhash_profile='ins_livox_mid360_custom',integration_end_frame=100)
            for mode,limit in [('full',None),('short',100)]:
                jobs.job.update(run_mode=mode,run_scope={'surface_end_frame':limit})
                self.assertEqual(prepare_mrhash_lidar_input('j',jobs)['integration_end_frame'],limit)
            jobs.job.update(run_mode='full',run_scope={'surface_end_frame':100})
            with self.assertRaises(SurfaceInputError):prepare_mrhash_lidar_input('j',jobs)

    async def test_failure_and_cancellation_stop_chain_and_input_failure_propagates(self):
        for terminal in ('failed','cancelled','input_failed','surface_failed','completed'):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                job={'status':'created','job_id':'x','dataset':'ins','requested_stages':['pose','surface'],'backends':{'pose':'glim','surface':'mrhash_lidar'},'stages':{s:{'status':'waiting'} for s in ('pose','surface')}}
                messages=[];calls=[]
                class Events:
                    async def publish(self,job_id,event,data):messages.append((event,data))
                    async def job_status(self,*args):pass
                def status(j,s,value,**kw):
                    from app.models.job import derive_job_status
                    j['stages'][s]['status']=value
                    j['status']=derive_job_status(j)
                jobs=SimpleNamespace(load_job=lambda _:job,stage_dir=lambda _,s:root/s,set_stage_status=status,stage_detail=lambda *a:{'can_run':True})
                runner=RunnerService(jobs,Events())
                def launch(jid,stage):
                    async def run():
                        calls.append(stage)
                        state='failed' if stage=='surface' and terminal=='surface_failed' else terminal if stage=='pose' and terminal in ('failed','cancelled') else 'completed'
                        status(job,stage,state)
                        return StageResult(stage,state)
                    runner._stage_tasks[(jid,stage)]=asyncio.create_task(run())
                runner._launch=launch
                prepare=patch('app.services.runner_service.prepare_surface_input',side_effect=ValueError('timestamp association below 98%') if terminal=='input_failed' else None,return_value={'compatibility':{'warnings':[]}})
                with prepare:
                    runner.start_run_planned('x');task=runner._job_tasks['x'];await task
                self.assertEqual(calls,['pose','surface'] if terminal in ('completed','surface_failed') else ['pose'])
                if terminal=='input_failed':self.assertEqual(job['stages']['surface']['status'],'failed')
                expected='failed' if terminal in ('failed','input_failed','surface_failed') else terminal
                self.assertEqual(job['status'],expected)
