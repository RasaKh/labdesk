# Changelog

## 0.4

- Added Poisson and negative binomial regression for count outcomes: incidence rate ratios, optional person-time exposure, and an automatic choice of family from the Pearson overdispersion statistic. Zero-inflated families were removed from the options because they are not implemented.
- Added repeated-measures ANOVA: Greenhouse-Geisser or Huynh-Feldt correction (automatic on a failed Mauchly test), partial and generalized eta squared, and Holm or Bonferroni paired post-hoc tests whose brackets plot on the means figure. Subjects missing a condition are excluded and the result says how many. The unimplemented Tukey post-hoc option was removed.
- A failed sphericity check is now a caution rather than a failure when the analysis applies a correction, so a "block" policy no longer stops a design the runner handles.
- Report sentences format fractional degrees of freedom to two decimals.

## 0.3.1

- Fixed the Sidik-Jonkman between-study variance estimator, which omitted its initial-variance scale factor and returned about 0.46 when the true tau² was 0. DL, REML and PM were unaffected.
- Added `tests/test_validation.py`: reference-value tests for the README's validation claims (power values, tau² recovery by simulation, ELISA four-parameter EC50 recovery, Cohen's kappa against a hand calculation).

## 0.3

- Added Cox proportional hazards regression: hazard ratios, concordance, likelihood-ratio test, stratification, event-level selection, and a per-covariate Schoenfeld proportional-hazards test. Coefficients match R's `coxph` on the Rossi data.
- Added ANCOVA: type II table, partial eta squared, covariate-adjusted means, and a homogeneity-of-slopes test that warns when slopes differ.
- Removed the Cox "tie handling" and "time-varying covariates" controls, which were advertised but not implemented (lifelines supports Efron ties only).
- Ratio coefficient plots (hazard and odds ratios) now use a log axis with the null line at 1.
- Fixed the events-per-variable check, which read an event count that was never set and so reported 0 events for every logistic regression.
- Fixed a race where an analysis attempt could report success before its job had finished. Attempts are now settled from the job's final state, and a job cancelled before it starts ends as `cancelled`.
- Server-side path import now refuses requests that arrive through a reverse proxy, where the client address is always loopback.
- Worker threads now reopen the database connection when the database path changes.

## 0.2

- Added numbered, checksummed SQLite migrations.
- Added immutable dataset artifacts and versions, reviewed dictionary revisions, source-upload preservation, and typed transforms.
- Added project-scoped v1 routes, preflight snapshots, frozen settings, idempotent durable attempts, persisted jobs, and replayable job events.
- Made browser project context tab-specific and project-scoped old job/event routes.
- Added optimistic project/draft/dictionary edits, hypothesis-family revisions, and explicit report snapshots.
- Added verified database/artifact backups and isolated audit exports with manifests.
- Added security headers, same-origin mutation checks, upload limits, typed setting allowlists, and secret redaction on config writes.
- Moved CSS and JavaScript into normal static assets.
- Made missing-token defaults more conservative, preserved identifier leading zeros in delimited files, caught duplicate headers before parser renaming, and blocked invalid constant transforms.
- Added architecture acceptance tests and restored the optional scientific dependencies required by the baseline numerical suite.
- Added append-only screening history; changed or undone votes supersede prior adjudications until resolved again.
- Added search execution and retrieval-hit provenance, plus distinct report and study identity tables.
- Added project-scoped evidence provenance/study endpoints and screening-event history queries.
- Added verified restore into a separate workspace, with artifact-path rewriting and post-restore integrity checks.
