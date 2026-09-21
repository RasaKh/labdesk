# LabDesk 0.2 architecture

LabDesk remains a local Flask and SQLite application. Version 0.2 adds an explicit `/api/v1` boundary while retaining legacy endpoints as adapters for the current interface.

The core invariants are:

- Every v1 resource carries a project ID in its URL and is checked again in the database query.
- A dataset import creates an immutable artifact, dataset version, and dictionary revision. Transformations create child versions and never overwrite their parents.
- Analysis preflight binds the method, roles, parameters, current dataset version, dictionary revision, and execution settings. Submission consumes that snapshot and records a durable attempt and job.
- Job state and events persist in SQLite. A restart marks callable work interrupted rather than reporting success or pretending to resume it.
- Reports and audit exports select explicit immutable records. Audit bundles are always labelled `record_only`; including data does not claim that a replay was verified.
- Evidence searches retain every retrieval hit, including duplicates. Publication reports can be grouped into explicit study identities without losing source-level provenance.
- Browser project selection is stored per tab and sent with project-owned requests. It no longer depends on the process-wide active project setting.

Main additions:

| Module | Purpose |
| --- | --- |
| `migrations.py` | Numbered migrations with checksums |
| `revisions.py` | Artifacts, dataset versions, dictionary revisions, transforms |
| `attempts.py` | Bound preflight and durable analysis attempts |
| `api_v1.py` | Explicitly project-scoped API |
| `workflow.py` | Drafts, hypothesis-family revisions, report snapshots |
| `evidence.py` | Search provenance, report identities, and report-to-study grouping |
| `backup.py` | SQLite online snapshots and verified artifact bundles |
| `exports_v1.py` | Isolated project audit exports |
| `static/` | Ordinary browser assets served by Flask |

Existing statistical runners remain the calculation implementation. `config.execution_settings()` uses context-local overrides so queued analyses retain the values reviewed at preflight without changing defaults for other jobs.

The v1 runner adapter intentionally executes only the dataset's current immutable version. Historical versions remain inspectable and exportable, but replay against an arbitrary old version is not yet claimed. Audit exports likewise preserve the record without claiming a verified rerun.
