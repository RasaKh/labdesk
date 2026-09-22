# LabDesk 0.2 quick guide

Install the locked direct dependencies for the verified Python 3.12 environment, or use the broader compatible requirements:

```bash
python -m pip install -r requirements.lock
python run.py
```

Open `http://127.0.0.1:5055`. Create or select a project first. Project selection is specific to the browser tab, so two tabs can work in separate projects safely.

In Data, import a source file and review its variable dictionary. The exact upload is retained and the working dataset is stored as an immutable version. Changing a type marks that variable reviewed; “Mark all variables reviewed” records a new dictionary revision. Derived transformations made through v1 create a child version.

In Analysis, choose the question shape or use the manual method library. Review the roles and assumption panel. Run creates a frozen preflight snapshot and queues a durable attempt. Changing the dataset, dictionary, or defaults invalidates the old preflight. Results and the legacy run ledger remain available after completion.

Backups are exposed at `/api/v1/backups`. Verify one with `POST /api/v1/backups/verify`. Restore into a new or empty directory without touching the live workspace:

```bash
python tools/restore_backup.py /path/to/backup.zip /path/to/new-workspace
```

Audit exports are created with `POST /api/v1/projects/{project_id}/exports`. Data is excluded unless `include_data` is explicitly true. The manifest records omissions and always labels this export mode `record_only`; it does not claim a verified replay.

Evidence search provenance is available under `/api/v1/projects/{project_id}/search-executions`. Each execution exposes its raw retrieval-hit ledger. Publication reports can be linked into study identities through `/api/v1/projects/{project_id}/studies`, while screening history remains append-only at `/api/v1/projects/{project_id}/screening-events`.
