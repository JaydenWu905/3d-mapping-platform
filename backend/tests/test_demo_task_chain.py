import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import STAGES
from app.models.progress import atomic_write_json
from app.services.job_service import JobService
from app.services.runner_service import RunnerService, StartStageError


class Events:
    def __init__(self):
        self.messages = []

    async def publish(self, job_id, event, data):
        self.messages.append((event, data))

    async def job_status(self, job_id, data):
        await self.publish(job_id, 'job.status', data)


class DemoTaskChainTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.jobs = JobService(Path(self.tmp.name) / 'jobs')
        self.events = Events()
        with patch.dict('os.environ', {'MAPPING_MOCK_STAGE_DURATION_SEC': '0.06'}):
            self.runner = RunnerService(self.jobs, self.events)
        self.job = await self.jobs.create_job('demo_room', {
            'pose': 'registered_pose_import', 'surface': 'mrhash_lidar', 'distance': 'voxel_esdf',
        })
        self.jid = self.job['job_id']

    async def asyncTearDown(self):
        tasks = list(self.runner._job_tasks.values()) + list(self.runner._stage_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def complete_pose(self):
        self.jobs.set_stage_status(self.jobs.load_job(self.jid), 'pose', 'completed')

    async def test_mock_surface_skips_real_input_preparation(self):
        self.complete_pose()
        with patch('app.services.runner_service.prepare_surface_input', side_effect=AssertionError('mock must not prepare real input')) as prepare:
            self.runner.start_stage(self.jid, 'surface')
            result = await self.runner._stage_tasks[(self.jid, 'surface')]
        self.assertEqual(result.status, 'completed')
        prepare.assert_not_called()

    async def test_chain_finishes_all_stages_and_writes_loadable_artifacts(self):
        with patch('app.services.runner_service.prepare_surface_input', side_effect=AssertionError('mock must not prepare real input')) as prepare:
            self.runner.start_run_all(self.jid)
            await self.runner._job_tasks[self.jid]
        prepare.assert_not_called()
        job = self.jobs.load_job(self.jid)
        self.assertEqual(job['status'], 'completed')
        for stage in STAGES:
            self.assertEqual(job['stages'][stage]['status'], 'completed')
            root = self.jobs.stage_dir(self.jid, stage)
            manifest = json.loads((root / 'result_manifest.json').read_text())
            self.assertTrue(manifest['backend_details']['mock_backend'])
            self.assertTrue(manifest['artifacts'])
            for artifact in manifest['artifacts']:
                self.assertTrue((root / artifact['path']).is_file())
            self.assertEqual(json.loads((root / 'progress.json').read_text())['progress'], 100)

    async def test_failure_retry_and_cancel_preserve_valid_prior_results(self):
        job = self.jobs.load_job(self.jid)
        job['fail_stage'] = 'surface'
        self.jobs.save_job(job)
        self.runner.start_run_all(self.jid)
        await self.runner._job_tasks[self.jid]
        await asyncio.sleep(0)
        failed = self.jobs.load_job(self.jid)
        self.assertEqual(failed['stages']['pose']['status'], 'completed')
        self.assertEqual(failed['stages']['surface']['status'], 'failed')
        self.assertEqual(failed['stages']['distance']['status'], 'waiting')
        failed['fail_stage'] = None
        self.jobs.save_job(failed)
        self.runner.retry_stage(self.jid, 'surface')
        self.assertEqual((await self.runner._stage_tasks[(self.jid, 'surface')]).status, 'completed')
        self.runner.start_stage(self.jid, 'distance')
        await asyncio.sleep(0)
        self.runner.cancel_stage(self.jid, 'distance')
        self.assertEqual((await self.runner._stage_tasks[(self.jid, 'distance')]).status, 'cancelled')
        self.assertTrue((self.jobs.stage_dir(self.jid, 'surface') / 'result_manifest.json').exists())

    async def test_upstream_retry_invalidates_all_dependent_results(self):
        self.runner.start_run_all(self.jid)
        await self.runner._job_tasks[self.jid]
        await asyncio.sleep(0)
        self.runner.retry_stage(self.jid, 'pose')
        for dependent in ('surface', 'distance'):
            self.assertFalse((self.jobs.stage_dir(self.jid, dependent) / 'result_manifest.json').exists())
            self.assertEqual(self.jobs.load_job(self.jid)['stages'][dependent]['status'], 'waiting')
        await self.runner._stage_tasks[(self.jid, 'pose')]

    async def test_real_surface_still_rejects_missing_pose_semantics(self):
        from dataclasses import replace
        from app.services.dataset_service import get_dataset_service
        definition = replace(get_dataset_service().get('demo_room'), execution='real')
        self.complete_pose()
        atomic_write_json(self.jobs.stage_dir(self.jid, 'pose') / 'result_manifest.json', {'status': 'completed', 'backend_details': {}})
        with patch.object(self.jobs.datasets, 'get', return_value=definition), patch.object(self.jobs, 'stage_detail', return_value={'can_run': True}):
            with self.assertRaisesRegex(StartStageError, 'missing required semantics'):
                self.runner.start_stage(self.jid, 'surface')
        self.assertNotIn((self.jid, 'surface'), self.runner._stage_tasks)

    async def test_surface_retry_keeps_pose_but_invalidates_distance(self):
        self.runner.start_run_all(self.jid)
        await self.runner._job_tasks[self.jid]
        await asyncio.sleep(0)
        pose_path = self.jobs.stage_dir(self.jid, 'pose') / 'result_manifest.json'
        pose_before = pose_path.read_bytes()
        self.runner.retry_stage(self.jid, 'surface')
        self.assertEqual(pose_path.read_bytes(), pose_before)
        self.assertFalse((self.jobs.stage_dir(self.jid, 'distance') / 'result_manifest.json').exists())
        await self.runner._stage_tasks[(self.jid, 'surface')]

    async def test_mock_glim_reports_input_then_waits_for_export(self):
        self.runner.mock_adapter._duration_sec = 0.6
        job = self.jobs.load_job(self.jid)
        job['backends']['pose'] = 'glim'
        job['stages']['pose']['backend'] = 'glim'
        self.jobs.save_job(job)
        self.runner.start_stage(self.jid, 'pose')
        await self.runner._stage_tasks[(self.jid, 'pose')]
        progress = [data for name, data in self.events.messages if name == 'stage.progress']
        self.assertTrue(any(data['phase'] == 'input_publishing' for data in progress))
        waiting = [data for data in progress if data['phase'] in ('waiting_glim_export', 'associating')]
        self.assertTrue(waiting)
        self.assertTrue(all(data['status'] == 'running' and data['lidar_published'] == data['lidar_total'] for data in waiting))

    async def test_mock_duration_configuration_does_not_accept_invalid_values(self):
        from app.services.mock_runner import MockRunnerAdapter
        for value in ('0', '-1', 'nan', 'inf', '3601'):
            with self.subTest(value=value), patch.dict('os.environ', {'MAPPING_MOCK_STAGE_DURATION_SEC': value}):
                with self.assertRaises(ValueError):
                    MockRunnerAdapter(self.jobs, self.events)
        with patch.dict('os.environ', {'MAPPING_MOCK_STAGE_DURATION_SEC': '30'}):
            self.assertEqual(MockRunnerAdapter(self.jobs, self.events)._duration_sec, 30)


if __name__ == '__main__':
    unittest.main()
