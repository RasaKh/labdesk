# Validation

Run:

```bash
python -m unittest discover -s tests -v
```

The 73-test suite covers existing registry/statistical hardening plus the 0.2 architecture contracts: migration checksums, immutable dataset parents, typed Parquet transforms, dictionary optimistic concurrency, project-scoped previews, bound preflight, frozen settings, idempotent submission, durable job results, secret redaction, original-upload preservation, revisioned drafts/families, report ownership, retrieval provenance, report-to-study grouping, backup verification and restore, and audit exports.

Generate the release inventory with:

```bash
python tools/generate_capabilities.py
```

A green suite verifies the tested software contracts. It is not blanket statistical certification of every method. `CAPABILITIES.json` separates declared stubs, missing dependencies, implementation mismatches, and capabilities available in the environment where it was generated. The release also requires `node --check labdesk/static/app.js` and an HTTP smoke test of the shell, static assets, health endpoint, and v1 API.
