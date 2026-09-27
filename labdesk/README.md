# LabDesk

A workbench for clinical research. Search the literature, screen it, extract
from it, hold your own data alongside it, run the statistics, draw the figures,
and produce something a reviewer can re-run.

```bash
pip install -r requirements.txt
python run.py            # http://127.0.0.1:5055
```

---

## The problem it solves

A single study passes through six or seven programs. The search lives in a
browser, the references in a reference manager, the screening in a spreadsheet,
the extraction in a second spreadsheet, the analysis in SPSS or R, the figures
in whatever drew them, and the manuscript somewhere else again. Every boundary
between those is a place for a number to change without anyone noticing.

The specific failures that follow are familiar:

- The PRISMA diagram is drawn by hand at the end and does not match the
  spreadsheet
- Nobody can say how many tests were run before the one that got reported
- A t-test was used on data that failed its assumptions, and the paper does not
  mention it
- The methods section says "SPSS v26" and nothing else, because nobody recorded
  what was actually run
- Six months later, the analysis cannot be reproduced from the files that remain

LabDesk puts the whole path in one place and writes down what happens along
it. Every analysis leaves a row containing a hash of the data, the exact
specification, the seed, the package versions, the assumption checks and the
result. The PRISMA counts are queried from the screening database. The methods
paragraph is assembled from the ledger rather than from memory.

---

## What it does

### Find the evidence

Live searches against PubMed, Europe PMC, OpenAlex, Crossref, ClinicalTrials.gov,
bioRxiv and medRxiv, openFDA and UniProt, with fifteen more sources declared
and ready to fill in. Results land in one shared corpus and are deduplicated
across sources by DOI and by fuzzy title within year.

Two things happen there that reference managers do not do. Every DOI is checked
against Crossref's retraction register, so a retracted trial is flagged before
it reaches your reference list. And every DOI is resolved through Unpaywall, so
full-text screening is not a scavenger hunt.

### Screen it properly

Keyboard-driven screening: `i` include, `e` exclude, `m` maybe, `s` skip, `u`
undo, where undo genuinely deletes the judgement rather than stepping over it.

Reviewers are stored identities rather than a name typed into a box, so
decisions attach to a stable id and progress is tracked per person. **Blind
mode** hides what the other reviewer decided, which is the only thing that
makes screening twice worth the effort. Cohen's kappa and a conflict list come
out of it, and conflicts are adjudicated with a recorded rationale that sits
alongside the original votes rather than overwriting them.

The PRISMA 2020 diagram is generated from that database. It cannot drift out of
step with what you actually did, because it is counting what you actually did.

### Extract and appraise

Structured extraction forms for randomised, observational and diagnostic
accuracy designs. Risk of bias with RoB 2, ROBINS-I, Newcastle-Ottawa and
QUADAS-2, judged per domain with the overall rating derived rather than
guessed, and rendered as a traffic-light plot.

Extracted arm-level numbers convert straight into effect sizes and standard
errors, on the log scale for ratio measures, ready for the meta-analysis.

### Run the statistics

103 tests across 15 groups, 58 implemented. Two-group and factorial comparisons,
rank-based equivalents, post-hoc families, categorical and proportion measures,
correlation and agreement, regression from linear through mixed-effects,
survival, diagnostic accuracy, meta-analysis with heterogeneity and bias
diagnostics, causal and epidemiological methods, power in any direction, and
bench assays including qPCR and ELISA curve fitting.

Everything declared but not yet implemented appears in the interface, validates
its inputs, and returns the exact function signature to write. The shape of the
tool is complete even where the arithmetic is not.

The Analysis pane starts with a **deterministic compatibility guide** rather than
forcing the researcher to begin from a test name. The guide connects the reviewed
variable dictionary to the role requirements already declared in the statistics
registry: for example, a continuous outcome plus a two-level grouping variable can
expose the compatible two-group methods, while a binary outcome can narrow the
regression family. Selecting variables can prefill those roles. This is constraint
matching, not an AI statistician: it does not infer the scientific question, causal
structure, estimand, or the method that should be reported. The complete method
library remains available as the manual/expert route.

### Refuse to run the wrong test

Every test declares the assumptions it rests on. Those are checked against your
actual data before anything runs, and shown as a row of lit indicators:

```
[pass   ] Cell sizes: OEC high n = 57, OEC low n = 68, Sham n = 55
[pass   ] Normality in OEC low: Shapiro-Wilk W = 0.980, p = 0.336
[pass   ] Equal variances: Levene W = 1.632, p = 0.199, SD ratio 1.38
[caution] Independence: not testable from the data. If subjects contributed
          more than one row, this test is the wrong one
```

On a failure the tool names the test that does not need that assumption, and
one setting decides whether it warns, blocks and offers the fallback, or
switches automatically. The violation is recorded either way.

Some of the calibration matters: Shapiro-Wilk is downgraded to a caution above
n = 5000, because at that size it rejects departures too small to matter.
Independence is stated rather than silently assumed, because no data frame can
test it and it is the assumption most often violated in the literature.

### Draw publication figures

Figures are built from a result rather than from raw data, so the significance
annotation cannot disagree with the statistics that produced it.

Significance brackets stack themselves: sorted by span, each assigned the
lowest level it does not overlap, adjacent pairs sharing a level and spanning
comparisons lifted above. Ten comparisons across five groups resolve to six
levels with zero collisions.

Journal export is built in: 89 mm single column and 183 mm double, 300 or 600
dpi, vector PDF, SVG and EPS with fonts embedded, Okabe-Ito and viridis
palettes, and a greyscale check. Error bars always print which kind they are,
because SD, SEM and 95% CI look alike and mean different things.

### Report it

The methods paragraph is generated from the ledger: the tests actually
executed, the corrections applied, how many assumption checks ran and how many
failed, and the software versions. It is a draft, and it says so.

Results sentences come out correctly formatted in APA or Vancouver. Table 1
generates itself with the right test per variable type and standardised mean
differences alongside. Seven reporting checklists are built in: CONSORT,
STROBE, PRISMA, STARD, TRIPOD, ARRIVE and SPIRIT.

The reproducibility bundle is a zip containing the manifest with the data and
dictionary hashes, recorded seeds and software versions, every specification
and result as JSON, the assumption checks, the figures, and reviewer-facing
Python/R snippets for supported methods. The immutable run JSON is the
canonical record of what LabDesk executed; emitted snippets may require the
corresponding data-preparation variables before they can be run independently.

### Tell you when you have run too many tests

Because every run is recorded, the tool knows how many tests have been run
against a dataset and what that does to your alpha. After ten it starts saying
so. The multiplicity audit shows the family-wise error rate implied by the
count.

This exists to be uncomfortable. Running one more test has never been cheaper,
and the ledger is the only honest way to keep alpha meaning something.

### Look like it belongs

Two themes. **Daylight** is the default and is built from the palette at
dr.khosrofar.me: the same #e9eaec ground, white panels, #c7cbd1 rules, the navy
masthead with its ink underline, square edges and striped table rows, set in
Georgia and Arial. Moving between the site and the tool should not
feel like moving between two programs. **Bench** is the dark theme for long
sessions and for judging figures without a white field around them.

The stain palette carries across both. Hematoxylin violet marks anything
active, eosin pink is reserved for statistical significance, and nine other
tints stay bound to their content families. Each has a light variant darkened
for a white ground; every one clears WCAG AA in both themes. Typeface is
switchable independently, and interface scale is a slider.

### Explain itself

A built-in handbook, seventeen articles across five sections, covering the
review workflow in the order the steps belong in, and the statistics: choosing
a test, what the numbers mean, and the ways results get misread. Links inside
an article jump to the pane being described.

---

## Install

Only `flask numpy pandas scipy matplotlib` are hard requirements. Everything
else is optional, and a test that needs a missing package is greyed out in the
interface with the exact pip line shown, rather than failing at run time.

```bash
pip install -r requirements.txt
```

`statsmodels`, `pingouin`, `lifelines` and `scikit-learn` unlock most of the
registry. `pyreadstat` adds SPSS and Stata import. `rapidfuzz` makes
deduplication considerably faster on large corpora.

Config, database, figures and exports live in `~/.config/labdesk/`. Nothing
leaves the machine except the API calls you ask for.

Set an email address in Settings before harvesting: Unpaywall requires it and
OpenAlex will rate-limit you without it. An NCBI API key raises the PubMed
limit from 3 to 10 requests per second.

---

## Coverage

| | Declared | Implemented |
|---|---|---|
| Statistical tests | 103 in 15 groups | 58 |
| Figure types | 47 in 6 groups | 33 |
| Literature and data sources | 25 in 5 groups | 10 |
| Risk of bias instruments | 4 | 4 |
| Reporting checklists | 7 | 7 |
| Handbook articles | 17 in 5 sections | 17 |

---

## How it is built

The browser never sends a command, a query or a line of code. It sends a
**specification**: the id of a registry entry, plus values for the fields that
entry declares. The server validates that specification against the same
definitions the interface was generated from, then compiles and runs it.

Which means the entire option surface exists in exactly one place. Adding a
test is one dictionary and one function:

```python
T("ancova", "ANCOVA", "Three or more groups",
  roles=[R("dv", "Outcome", "continuous"),
         R("group", "Factor", "categorical"),
         R("covariates", "Covariates", "continuous", 1, 6)],
  params=[P("emmeans", "Estimated marginal means", "bool", default=True)],
  assumptions=["normality_by_group", "homogeneity", "linearity"],
  effects=["partial_eta_squared"], plots=["ancova_lines", "means_ci"],
  status=READY)
```

Then `def ancova(df, roles, params, ctl) -> dict` in `runners/`. The interface
picks it up with correct controls, the right variable pickers, its assumption
gate and its suggested figures, with no JavaScript written at all.

The same pattern covers figures (`plots_registry.py`) and data sources
(`harvest.py`).

```
run.py
labdesk/
  config.py            paths, settings, optional-dependency probing
  db.py                SQLite, provenance ledger
  schema.py            the declarative primitives, spec validation
  jobs.py              worker pool, event bus, live logs
  datasets.py          import, variable dictionary, missingness, de-identification
  assumptions.py       preflight checks and the gate policy
  stats_registry.py    the test registry, data only
  stats_run.py         resolve, preflight, dispatch, effect sizes, code emission
  runners/             basic, models, meta, bench, power
  plots_registry.py    the figure registry
  plots_run.py         renderers and the bracket layout
  harvest.py           source registry and API clients
  screening.py         reviewers, dedup, screening, PRISMA, risk of bias
  library.py           the handbook
  reporting.py         sentences, methods text, checklists, bundle
  api.py               all routes
  ui/                  css.py, html.py, js.py
```

---

## Validation

- Power routines reproduce the standard values: d = 0.5 at 80% power gives 64
  per group; 0.30 against 0.45 proportions gives 163 per group; four-group
  ANOVA at f = 0.25 gives 45 per group; r = 0.25 gives n = 124
- Between-study variance estimators recover known τ² across 900 simulated
  meta-analyses at τ² = 0, 0.05 and 0.20, with REML closest as expected
- ELISA four-parameter fitting recovers the generating EC50 to within 3% at
  R² = 0.9998
- Live harvest verified against PubMed, Europe PMC, ClinicalTrials.gov and
  Crossref; cross-source deduplication caught 6 title duplicates in 84 records
- The assumption gate blocks a t-test on lognormal data, offers Mann-Whitney,
  and switches automatically under the fallback policy
- Bracket layout resolves all ten pairwise comparisons across five groups into
  six levels with zero within-level collisions
- Dual screening produces the expected kappa and conflict list, blind mode
  withholds the other reviewer's decisions, and adjudication resolves without
  overwriting the original votes

---

## Deliberate choices

**Error bars are always labelled in the figure.** SEM bars are the shortest and
the most popular, and they mean something different from SD.

**Kaplan-Meier y axes start at zero** by default, because truncating them
exaggerates separation.

**Predictive values carry a prevalence caveat**, because they are properties of
a test in a population, not properties of a test.

**Observed power is available but discouraged**, with the reason attached: it
is a deterministic function of the p value and adds nothing.

**Table 1 offers standardised mean differences**, because baseline p values in
a randomised trial test a hypothesis you already know is true.

**Every run is logged, including blocked ones.** You cannot quietly try eight
tests and report the ninth.

**Deleting is easy and never silent.** Rows, filtered subsets and whole
categories can all be cleared, but each says what it will remove and what will
survive first. Removing a dataset asks whether the analyses go with it and
defaults to keeping them, because the data going away should not erase the
record that the work happened.
