# LabDesk hardening pass

The original hardening pass intentionally avoided product expansion and tightened the contracts already implied by LabDesk: project isolation, reproducible provenance, faithful statistical method selection, and safe persistence. Subsequent UI work added one deliberately bounded workflow improvement: a deterministic analysis compatibility guide built from those same contracts.

## What changed

- **Project isolation:** datasets, analysis runs, figures, screening, PRISMA counts, harvesting, reports, resets, and destructive API operations are now consistently scoped to the owning project.
- **Provenance:** successful, blocked, and failed analyses all leave ledger entries. Automatic fallbacks regenerate code for the method that actually ran. Run records now retain project ownership, dictionary hash, alpha, confidence level, seed, and software versions.
- **Dataset identity:** hashes now include column names/order, dtypes, index metadata, and values. The reviewed data dictionary has a separate hash. Numeric values such as `999` are no longer globally destroyed as missing sentinels, and post-trim duplicate column names are rejected.
- **Schema enforcement:** server-side validation now checks column existence, role cardinality/type/levels, duplicate role assignments, and parameter types/ranges/choices against the actual dataset and reviewed dictionary.
- **Statistical fidelity:** corrected method/label mismatches including Dunn, Dunnett, factorial ANOVA, Fisher RxC handling, correlation intervals/partial methods, paired Hedges' g, non-inferiority degrees of freedom, and qPCR group-comparison semantics. Unsupported or incompatible choices fail explicitly instead of silently substituting another procedure.
- **qPCR:** Pfaffl normalization was corrected, inference is performed on ΔCt rather than exponentiated fold-change, and declared options now correspond to implemented behavior.
- **ELISA:** 4PL, 5PL, linear, and log-linear choices now execute their named models; curve-fit weighting semantics were corrected; standard recovery is based on back-calculated concentration; existing replicate-CV QC is enforced.
- **Regression/ROC:** missing values remain missing through design-matrix construction and outcome encoding; ROC numeric coercion occurs before complete-case filtering; positive outcome levels are resolved explicitly rather than lexicographically.
- **Screening/RoB:** disagreements no longer advance records until adjudicated; PRISMA final counts are project-scoped and record-level; RoB aggregation is instrument-aware; Newcastle-Ottawa's nine-star structure is enforced.
- **Persistence:** logical uniqueness is enforced in SQLite; generic `INSERT OR REPLACE` was replaced by explicit insert/upsert behavior; multi-statement destructive operations can run transactionally.
- **Runtime structure:** job workers start lazily, job retention is genuinely bounded, cancellation follows the same finalization path, and the in-memory dataset cache is bounded.
- **File/API safety:** uploads use safe temporary names, filesystem containment uses resolved paths, secret API keys are not returned in bootstrap config, and arbitrary path imports are limited to loopback clients.
- **Reporting:** methods and bundles derive facts from project-scoped immutable run records. Reproduction documentation no longer overstates emitted snippets as universally standalone scripts.
- **Registry/plot truthfulness:** READY analyses and plots are contract-checked against real implementations. Controls that were no-ops or named unsupported methods were removed or wired to their existing behavior; distinct plot types that were only aliases for another renderer are now explicitly marked as stubs rather than mislabeled output.

## Regression suite

Run from the project root:

```bash
python -m unittest discover -s tests -v
```

The suite focuses on the failure modes fixed in this pass: registry integrity, project leakage, transactional rollback, provenance/fallback correctness, data hashing and missingness, screening adjudication, RoB rules, ELISA/qPCR behavior, regression/ROC missingness, factorial ANOVA, Dunnett, and pairwise-method identity.

## UI/navigation follow-up

- Reassigned pane keyboard shortcuts in rail order: Projects `1`, Data `2`, Analysis `3`, Harvest `4`, Screening `5`, Synthesis `6`, Report `7`, Run ledger `8`, Settings `9`, Handbook `0`.
- Projects is now the default pane on application launch.
- Handbook moved to the final navigation position; Settings precedes it.
- Added visible separators between rail sections and assigned distinct stain tints to Project, Workbench, Evidence, Output, and Reference headings.
- Panel headers now show only a tint dot; internal stain token names such as `iodine` and `methylene` are no longer rendered as UI text.
- Project progress stages now include navigation shortcuts to the pane where the work is performed. Screening shortcuts preserve title/abstract vs full-text stage context.
- Added editable active-project Question and Registration fields using the already-existing project PATCH API, so the corresponding progress shortcuts have actionable destinations.
- Removed Advanced from the masthead and placed its Show/Hide control under Settings → Appearance.


## Deterministic analysis guide follow-up

- Added `analysis_guide.py`, a constraint-matching layer between the reviewed dataset dictionary and the existing statistics registry. It does not score scientific merit or choose a test.
- Analysis now opens with question-shape intents such as group comparison, paired/repeated measurements, association, modelling, survival, diagnostic accuracy, meta-analysis, and bench/omics.
- Optional primary/secondary variable selections narrow compatible methods and prefill the method's declared roles; the existing manual method library remains immediately available underneath.
- Compatibility wording is explicit: the guide cannot infer the scientific question, estimand, causal structure, or preregistration.
- Three-or-more-group methods now declare their 3+ factor-level requirement in the registry itself, so the guide and server-side validation share the same rule.
- Added regression tests for two-vs-three-level group matching, logistic-outcome narrowing, correlation multi-role prefilling, and survival time/event matching.
