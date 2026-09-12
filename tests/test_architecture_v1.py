import json
import io
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

import pandas as pd

from labdesk import attempts, backup, config, datasets, db, evidence, exports_v1, harvest, projects, revisions, workflow
from labdesk.api import create_app
from labdesk.jobs import JOBS


class ArchitectureV1Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        db.close()
        db.DB_PATH = str(self.root / "labdesk.db")
        datasets.DATA_DIR = str(self.data)
        revisions.DATA_DIR = str(self.data)
        self.backups = self.root / "backups"
        self.exports = self.root / "exports"
        self.backups.mkdir()
        self.exports.mkdir()
        backup.BACKUP_DIR = str(self.backups)
        exports_v1.EXPORT_DIR = str(self.exports)
        datasets._cache.clear()
        JOBS.cancel_all()
        JOBS.clear_finished()
        db.init()
        for pid in ("p1", "p2"):
            db.insert("project", {"id": pid, "name": pid, "kind": "analysis",
                                  "question": "q", "created_at": time.time(),
                                  "updated_at": time.time(), "revision": 1})

    def tearDown(self):
        deadline = time.time() + 3
        while any(j.status in ("queued", "running") for j in JOBS.jobs.values()) and time.time() < deadline:
            time.sleep(.02)
        db.close()
        datasets._cache.clear()
        self.tmp.cleanup()

    def make_dataset(self, pid="p1"):
        path = self.root / f"{pid}.csv"
        pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0],
                      "group": ["a", "a", "b", "b"]}).to_csv(path, index=False)
        return datasets.import_file(str(path), project_id=pid)

    def test_numbered_migrations_are_recorded(self):
        rows = db.query("SELECT version,name,checksum FROM schema_migration ORDER BY version")
        self.assertEqual([1, 2, 3, 4, 5], [r["version"] for r in rows])
        self.assertTrue(all(len(r["checksum"]) == 64 for r in rows))
        db.init()
        self.assertEqual(5, db.one("SELECT COUNT(*) c FROM schema_migration")["c"])

    def test_dataset_versions_and_dictionary_revisions_are_immutable(self):
        did = self.make_dataset()
        baseline = revisions.current("p1", did)
        old = datasets.read_any(baseline["path"])
        derived = revisions.transform("p1", did, baseline["id"], {
            "kind": "derive_transform", "source": "x", "target": "x_log",
            "transform": "log", "parameters": {},
        })
        self.assertNotEqual(baseline["id"], derived["id"])
        self.assertEqual(["x", "group"], list(old.columns))
        self.assertEqual(["x", "group", "x_log"], list(datasets.read_any(derived["path"]).columns))
        self.assertTrue(os.path.exists(baseline["path"]))
        first = revisions.dictionary("p1", did)
        payload = first["payload"]
        for value in payload.values():
            value["reviewed"] = True
        second = revisions.create_dictionary("p1", did, payload,
                                             expected_revision=first["revision"])
        self.assertTrue(second["reviewed"])
        with self.assertRaisesRegex(RuntimeError, "changed"):
            revisions.create_dictionary("p1", did, payload,
                                        expected_revision=first["revision"])

    def test_scoped_v1_preview_does_not_leak_dataset(self):
        did = self.make_dataset("p1")
        version = revisions.current("p1", did)
        app = create_app()
        app.testing = True
        client = app.test_client()
        good = client.get(f"/api/v1/projects/p1/datasets/{did}/versions/{version['id']}/preview")
        self.assertEqual(200, good.status_code)
        self.assertEqual(4, good.get_json()["total"])
        other = client.get(f"/api/v1/projects/p2/datasets/{did}/versions/{version['id']}/preview")
        self.assertEqual(404, other.status_code)
        self.assertNotIn("rows", other.get_json())

    def test_preflight_is_version_bound_and_submission_is_idempotent(self):
        did = self.make_dataset()
        pf = attempts.preflight("p1", {"test": "describe", "dataset": did,
                                       "roles": {"vars": ["x"]},
                                       "params": {"normality": False}})
        submitted = attempts.submit("p1", {"preflight_token": pf["preflight_token"]},
                                    idempotency_key="same-request")
        again = attempts.submit("p1", {"preflight_token": pf["preflight_token"]},
                                idempotency_key="same-request")
        self.assertEqual(submitted["id"], again["id"])
        deadline = time.time() + 4
        row = submitted
        while row["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(.02)
            row = attempts.detail("p1", submitted["id"])
        self.assertEqual("succeeded", row["status"])
        self.assertIsNotNone(row["run_id"])
        stored_job = db.one("SELECT * FROM job WHERE id=?", (row["job_id"],))
        self.assertEqual("done", stored_job["status"])
        self.assertIsNotNone(stored_job["result"])

    def test_attempt_is_never_terminal_before_its_job(self):
        # Regression: the attempt used to be marked succeeded inside the job
        # body, so a poller could see a finished attempt with a running job.
        did = self.make_dataset()
        for i in range(10):
            pf = attempts.preflight("p1", {"test": "describe", "dataset": did,
                                           "roles": {"vars": ["x"]},
                                           "params": {"normality": False}})
            row = attempts.submit("p1", {"preflight_token": pf["preflight_token"]})
            deadline = time.time() + 4
            while time.time() < deadline:
                row = attempts.detail("p1", row["id"])
                if row["status"] not in ("queued", "running"):
                    job = db.one("SELECT status FROM job WHERE id=?", (row["job_id"],))
                    self.assertEqual("done", job["status"], f"iteration {i}")
                    break
                time.sleep(.001)
            self.assertEqual("succeeded", row["status"])

    def test_attempt_cancelled_before_start_is_settled(self):
        did = self.make_dataset()
        pf = attempts.preflight("p1", {"test": "describe", "dataset": did,
                                       "roles": {"vars": ["x"]},
                                       "params": {"normality": False}})
        gate = threading.Event()
        blockers = [JOBS.submit("test", "hold worker", lambda ctl: gate.wait(3))
                    for _ in range(max(1, int(config.get("max_concurrent_jobs", 2))))]
        try:
            row = attempts.submit("p1", {"preflight_token": pf["preflight_token"]})
            JOBS.get(row["job_id"]).cancel()
        finally:
            gate.set()
        deadline = time.time() + 4
        while row["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(.02)
            row = attempts.detail("p1", row["id"])
        self.assertEqual("cancelled", row["status"])
        self.assertIsNotNone(row["ended_at"])
        self.assertTrue(all(b.status == "done" for b in blockers))

    def test_path_import_refuses_proxied_requests(self):
        app = create_app()
        app.testing = True
        client = app.test_client()
        missing = str(self.root / "missing.csv")
        direct = client.post("/api/datasets/path", json={"path": missing})
        self.assertEqual(400, direct.status_code)  # passed the guard, no file
        for header in ("X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP"):
            proxied = client.post("/api/datasets/path", json={"path": missing},
                                  headers={header: "203.0.113.7"})
            self.assertEqual(403, proxied.status_code, header)

    def test_changed_execution_defaults_invalidate_preflight(self):
        did = self.make_dataset()
        pf = attempts.preflight("p1", {"test": "describe", "dataset": did,
                                       "roles": {"vars": ["x"]},
                                       "params": {"normality": False}})
        old = config.CONFIG["alpha"]
        try:
            config.CONFIG["alpha"] = 0.01
            with self.assertRaisesRegex(attempts.Conflict, "defaults changed"):
                attempts.submit("p1", {"preflight_token": pf["preflight_token"]})
        finally:
            config.CONFIG["alpha"] = old

    def test_api_config_never_returns_secret(self):
        app = create_app()
        app.testing = True
        client = app.test_client()
        old = config.CONFIG.get("ncbi_api_key", "")
        try:
            response = client.post("/api/config", json={"ncbi_api_key": "secret-value"})
            self.assertEqual(200, response.status_code)
            self.assertEqual("", response.get_json()["ncbi_api_key"])
            self.assertEqual("secret-value", config.CONFIG["ncbi_api_key"])
        finally:
            config.CONFIG["ncbi_api_key"] = old

    def test_v1_import_preserves_original_upload(self):
        app = create_app()
        app.testing = True
        client = app.test_client()
        response = client.post("/api/v1/projects/p1/imports", data={
            "file": (io.BytesIO(b"subject_id,value\n001,3\n002,-\n"), "source.csv")
        }, content_type="multipart/form-data")
        self.assertEqual(201, response.status_code, response.get_json())
        did = response.get_json()["dataset"]["id"]
        source = db.one("SELECT * FROM dataset_source WHERE dataset_id=?", (did,))
        artifact = db.one("SELECT * FROM artifact WHERE id=?", (source["artifact_id"],))
        self.assertEqual(b"subject_id,value\n001,3\n002,-\n", Path(artifact["path"]).read_bytes())
        self.assertEqual(["001", "002"], datasets.load(did)["subject_id"].tolist())
        # '-' is preserved unless an import plan explicitly calls it missing.
        self.assertEqual("-", str(datasets.load(did)["value"].iloc[1]))

    def test_drafts_families_and_reports_are_revisioned_and_scoped(self):
        first = workflow.save_draft("p1", "primary", {"test": "describe"})
        with self.assertRaises(workflow.RevisionConflict):
            workflow.save_draft("p1", "primary", {"test": "ttest_ind"}, 0)
        second = workflow.save_draft("p1", "primary", {"test": "ttest_ind"},
                                     first["revision"])
        self.assertEqual(2, second["revision"])
        family1 = workflow.create_family("p1", "primary outcomes", .05, "holm",
                                         [{"hypothesis": "H1"}], True)
        family2 = workflow.create_family("p1", "primary outcomes", .05, "holm",
                                         [{"hypothesis": "H1"}, {"hypothesis": "H2"}], True)
        self.assertEqual(1, family1["revision"])
        self.assertEqual(2, family2["revision"])
        db.log_run(id="run1", project_id="p1", dataset_sha="x",
                   test_id="describe", status="ok", result={})
        report = workflow.create_report_snapshot("p1", "Results", {"run_ids": ["run1"]})
        self.assertEqual(["run1"], report["selection"]["run_ids"])
        with self.assertRaisesRegex(ValueError, "inaccessible"):
            workflow.create_report_snapshot("p2", "Leak", {"run_ids": ["run1"]})

    def test_backup_and_audit_export_have_verified_manifests(self):
        self.make_dataset()
        exported = exports_v1.create_audit_bundle("p1", include_data=True)
        self.assertTrue(Path(exported["path"]).is_file())
        self.assertEqual("record_only", exported["reproducibility_status"])
        made = backup.create()
        self.assertTrue(made["verified"])
        checked = backup.verify(made["path"])
        self.assertTrue(checked["ok"], checked["errors"])
        restored = backup.restore(made["path"], str(self.root / "restored"))
        self.assertTrue(restored["verified"])
        self.assertTrue(Path(restored["database"]).is_file())
        restored_db = db.sqlite3.connect(restored["database"])
        try:
            artifact = restored_db.execute("SELECT path FROM artifact LIMIT 1").fetchone()
            self.assertIsNotNone(artifact)
            self.assertTrue(Path(artifact[0]).is_file())
        finally:
            restored_db.close()

    def test_project_updates_use_optimistic_revision(self):
        p = projects.get("p1")
        changed = projects.update("p1", {"question": "new"}, p["revision"])
        self.assertEqual(p["revision"] + 1, changed["revision"])
        with self.assertRaisesRegex(RuntimeError, "changed"):
            projects.update("p1", {"question": "stale"}, p["revision"])

    def test_harvest_retains_every_hit_and_separates_reports(self):
        original = harvest.CLIENTS.get("pubmed")
        harvest.CLIENTS["pubmed"] = lambda params, ctl: {"records": [
            {"source": "pubmed", "source_uid": "1", "doi": "10.1/example",
             "title": "Trial report", "fetched_at": time.time()},
            {"source": "pubmed", "source_uid": "2", "doi": "10.1/example",
             "title": "Trial report duplicate", "fetched_at": time.time()},
        ]}
        try:
            result = harvest.harvest("pubmed", {"query": "trial"}, "p1")
        finally:
            harvest.CLIENTS["pubmed"] = original
        self.assertEqual(1, result["stored"])
        self.assertEqual(1, result["duplicates_skipped"])
        self.assertEqual(2, db.one("SELECT COUNT(*) c FROM retrieval_hit WHERE project_id='p1'")["c"])
        self.assertEqual(1, db.one("SELECT COUNT(*) c FROM evidence_report WHERE project_id='p1'")["c"])
        search = db.one("SELECT * FROM search_execution WHERE id=?",
                        (result["search_execution_id"],))
        self.assertEqual("completed", search["status"])

        record = db.one("SELECT id FROM record WHERE project_id='p1' AND dedup_of IS NULL")
        report = evidence.ensure_report("p1", record["id"])
        study = evidence.create_study("p1", "Example trial", [report["id"]])
        self.assertEqual(report["id"], study["reports"][0]["id"])
        with self.assertRaisesRegex(ValueError, "belong"):
            evidence.create_study("p2", "Cross-project leak", [report["id"]])

        app = create_app()
        app.testing = True
        client = app.test_client()
        executions = client.get("/api/v1/projects/p1/search-executions")
        self.assertEqual(200, executions.status_code)
        hits = client.get(f"/api/v1/projects/p1/search-executions/{search['id']}/hits")
        self.assertEqual(2, len(hits.get_json()["items"]))
        listed = client.get("/api/v1/projects/p1/studies")
        self.assertEqual(study["id"], listed.get_json()["items"][0]["id"])


if __name__ == "__main__":
    unittest.main()
