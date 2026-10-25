from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI

from app.api.jobs import router
from app.models.job import normalize_job_name
from app.services.job_service import JobService
from backend.tests.test_jobs_api_errors import Datasets


class LocalApiClient:
    """Exercise the ASGI routes without optional HTTP client dependencies."""
    def __init__(self, app):
        self.app = app

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def call(self, method, path, payload=None):
        messages = []
        async def run():
            async def receive():
                return {"type":"http.request", "body":json.dumps(payload).encode() if payload is not None else b"", "more_body":False}
            async def send(message):
                messages.append(message)
            await self.app({"type":"http", "asgi":{"version":"3.0"}, "http_version":"1.1", "method":method, "scheme":"http", "path":path, "raw_path":path.encode(), "query_string":b"", "root_path":"", "headers":[(b"content-type",b"application/json")], "server":("test",80), "client":("test",1)}, receive, send)
        asyncio.run(run())
        from types import SimpleNamespace
        body=b"".join(m.get("body",b"") for m in messages if m['type']=='http.response.body').decode()
        return SimpleNamespace(status_code=messages[0]['status'],text=body,json=lambda:json.loads(body))

    def get(self,path): return self.call('GET',path)
    def post(self,path,json): return self.call('POST',path,json)
    def patch(self,path,json): return self.call('PATCH',path,json)


class JobNameTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.datasets = Datasets(self.root)
        self.service = JobService(self.root / "jobs", self.datasets)

    def client(self, service=None):
        app = FastAPI()
        app.state.jobs = service or self.service
        app.include_router(router, prefix="/api")
        return LocalApiClient(app)

    def create(self, client, **extra):
        return client.post("/api/jobs", json={"dataset":"oxford_mrhash_lidar", "backends":{"pose":"registered_pose_import","surface":"mrhash_lidar"}, **extra})

    def test_name_survives_api_calls_and_service_restart_duplicates_are_distinct(self):
        with self.client() as client:
            first = self.create(client, name="  走廊  扫描测试（A-1） ").json()
            second = self.create(client, name="走廊 扫描测试（A-1）").json()
            self.assertNotEqual(first["job_id"], second["job_id"])
            self.assertEqual(first["name"], "走廊 扫描测试（A-1）")
            self.assertNotIn(first["name"], str(self.service.job_dir(first["job_id"])))
        # New service and FastAPI lifecycle, using the same persisted directory.
        restored = JobService(self.root / "jobs", self.datasets)
        with self.client(restored) as client:
            self.assertEqual(client.get(f"/api/jobs/{first['job_id']}").json()["name"], first["name"])
            self.assertEqual([j["name"] for j in client.get("/api/jobs").json()], [first["name"], first["name"]])

    def test_legacy_rename_changes_only_name_and_keeps_artifacts_and_status(self):
        with self.client() as client:
            job = self.create(client).json()
            jid = job["job_id"]
            path = self.service.job_dir(jid) / "job.json"
            legacy = json.loads(path.read_text()); legacy.pop("name", None)
            legacy["validation_scope"] = "keep-exactly"
            legacy["stages"]["pose"]["status"] = "completed"
            path.write_text(json.dumps(legacy))
            artifact = self.service.stage_dir(jid,"pose") / "original.bin"
            artifact.parent.mkdir(parents=True); artifact.write_bytes(b"original-unaltered")
            self.assertIsNone(client.get(f"/api/jobs/{jid}").json()["name"])
            response = client.patch(f"/api/jobs/{jid}", json={"name":"历史任务：2026/10"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["job_id"], jid)
            self.assertEqual(json.loads(path.read_text()), legacy)
            self.assertEqual(artifact.read_bytes(), b"original-unaltered")
            self.assertEqual(client.get("/api/jobs").json()[0]["name"], "历史任务：2026/10")
            # A runner holding an old snapshot cannot overwrite the display name.
            self.service.save_job(legacy)
            self.assertEqual(client.get(f"/api/jobs/{jid}").json()["name"], "历史任务：2026/10")
            self.assertEqual(client.patch(f"/api/jobs/{jid}",json={"name":"x","job_id":"other"}).status_code,422)
        with self.client(JobService(self.root / "jobs", self.datasets)) as restarted:
            self.assertEqual(restarted.get(f"/api/jobs/{jid}").json()["name"], "历史任务：2026/10")

    def test_invalid_names_rejected_without_creating_or_renaming_jobs(self):
        with self.client() as client:
            for value in ["", "   ", "中"*81, "bad\nname", "bad\x00name", "bad\u202ename", "<script>", "a\\b", 123, ["x"]]:
                with self.subTest(value=repr(value)):
                    self.assertEqual(self.create(client,name=value).status_code,422)
            self.assertEqual(client.get("/api/jobs").json(), [])
            job=self.create(client,name="valid").json();jid=job['job_id']
            for value in [None,"", "\t", "x"*81]:
                self.assertEqual(client.patch(f"/api/jobs/{jid}",json={"name":value}).status_code,422)
            self.assertEqual(client.get(f"/api/jobs/{jid}").json()['name'],'valid')
            self.assertEqual(client.patch('/api/jobs/missing',json={'name':'valid'}).status_code,404)

    def test_unicode_normalization_and_old_clients_without_name(self):
        self.assertEqual(normalize_job_name('Cafe\u0301 — 走廊 #2（东侧）'), 'Café — 走廊 #2（东侧）')
        with self.client() as client:
            response=self.create(client)
            self.assertEqual(response.status_code,201)
            self.assertIsNone(response.json()['name'])
            self.assertEqual(response.json()['status'],'created')


if __name__ == '__main__':
    unittest.main()
