# Migration notes

`db.init()` creates the legacy schema and then runs `migrations.py` in version order. Applied versions and SHA-256 checksums are stored in `schema_migration`. Editing an applied migration causes startup to fail; add a new migration instead.

Current migrations:

1. Immutable artifacts, dataset/dictionary versions, preflight snapshots, attempts, durable job events, audit events, report snapshots, and legacy-column extensions.
2. Revisioned analysis drafts and hypothesis families.
3. Preservation of original dataset uploads.
4. Append-only screening events and stale-adjudication detection.
5. Search executions, retrieval hits, separate report identities, and explicit report-to-study linking.

Existing project-owned datasets receive a baseline version lazily the first time the version service accesses them. Old runs retain their original hashes and JSON. Version 0.2 does not fabricate a historical dictionary revision for runs where that history was never recorded.

Before upgrading valuable work, create a backup through Settings/API or copy the entire existing configuration directory while LabDesk is stopped. Migration failures are transactional and stop startup. Verified backups can be restored into a new or empty directory with `tools/restore_backup.py`; restore never overwrites the live workspace.
