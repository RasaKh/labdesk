"""The handbook.

Reference material that travels with the tool, so the thing that tells you
how to run a review sits next to the thing that runs it. Two halves: doing a
review, and statistics. Entries are plain data the client renders: headings,
bold, code, bullets, callouts, pane links and tables. This stage adds reading
what comes back and producing the output."""

SECTIONS = [
    ("Start here", "haem"),
    ("Doing a review", "trypan"),
    ("Choosing and running a test", "methylene"),
    ("Reading what comes back", "eosin"),
    ("Producing the output", "fastgreen"),
]


def E(id, title, section, summary, body, reading=None, panes=None):
    return {"id": id, "title": title, "section": section, "summary": summary,
            "body": body.strip(), "reading": reading or "", "panes": panes or []}


ENTRIES = [

# ═══════════════════════════════════════════════════════════════════════
E("overview", "How the pieces fit together", "Start here",
  "Nine panes, two workflows, one ledger underneath both.",
  """
There are two jobs this tool does, and they meet in the middle.

**The evidence workflow** starts with a question and ends with a pooled
estimate: search the literature, screen what comes back, extract numbers from
what survives, judge how much to trust it, and synthesise. That runs left to
right through Harvest, Screening and Synthesis.

**The analysis workflow** starts with a dataset and ends with a figure and a
paragraph: import, check the variables, run a test, draw it, report it. That
runs through Data, Statistics and Figures.

They meet at **Synthesis**, where extracted arm-level numbers become effect
sizes and standard errors, and those go straight into the meta-analysis in the
Statistics pane like any other data.

## What holds it together

Underneath both sits the **run ledger**. Every analysis writes one row: a hash
of the data, the exact specification, the random seed, the package versions,
the assumption checks, and the result. Nothing runs without leaving that trace.

Three things fall out of it that are hard to get any other way.

- The **methods paragraph** is assembled from the ledger, so it describes what
  was actually executed rather than what you meant to do.
- The **multiplicity audit** knows how many tests have been run against a given
  dataset, and can say what that does to your alpha.
- The **reproducibility bundle** contains the data hash, every spec, every
  result, the figures, and generated Python and R that re-runs all of it.

> The ledger is the reason this is a research tool rather than a calculator.
> A calculator gives you a number. This also records that you asked.

## The panes

| Pane | What it is for |
|---|---|
| Data | Import, and get the variable types right before anything else |
| Statistics | The test library, with an assumption gate in front of it |
| Figures | Publication figures built from a result, not from raw data |
| Harvest | Live searches against PubMed, Europe PMC, registries and more |
| Screening | Title/abstract and full-text screening, with agreement stats |
| Synthesis | Extraction forms, risk of bias, conversion to effect sizes |
| Report | Methods text, checklists, pre-registration, the bundle |
| Run ledger | Everything that has been executed, and what to delete |
| Settings | Statistical defaults, API keys, scale, and the danger zone |

[Open the Data pane](#pane:data) to start an analysis, or
[Harvest](#pane:harvest) to start a review.
""", reading="3 min", panes=["data", "harvest"]),

# ═══════════════════════════════════════════════════════════════════════
E("first-analysis", "Your first analysis, end to end", "Start here",
  "Import, check types, run, draw, report. About ten minutes.",
  """
## 1. Import

[Data pane](#pane:data). Drop in a CSV, or give a path on the server. One row
per observation, one column per variable, a header row. Missing cells can be
empty, `NA`, `.`, `999`, or a dozen other conventions; they are all recognised.

## 2. Fix the dictionary

This is the step people skip, and it is the one that quietly ruins results.

Each column gets an inferred type: continuous, ordinal, categorical, binary,
time, or id. That type decides which tests will accept the variable. The
classic failure is a 0/1 outcome read as continuous, which then happily goes
into a t-test as if it were a measurement.

Look down the **type** column and correct anything wrong before you go further.
Also glance at **missing %**, which is flagged in amber above 20%.

## 3. Pick a test

[Statistics pane](#pane:stats). The library is grouped by what you are asking,
not by test name. If you are unsure, read
[Choosing a test](#entry:choosing).

Assign your variables to the test's **roles**. Only variables of the right type
are offered, which is the dictionary paying off.

## 4. Read the gate

Before anything runs, the assumptions the test rests on are checked against
your actual data, and shown as a row of lozenges.

- **Green** the assumption holds
- **Amber** it is borderline, or untestable and worth thinking about
- **Red** it fails, and the tool names the test that does not need it

Red does not always mean stop. It means make a decision and be able to defend
it. See [When an assumption fails](#entry:assumptions).

## 5. Run

The result shows the statistic, the p value, effect sizes with intervals, and a
sentence formatted correctly for a manuscript. Click the sentence to copy it.

The right-hand inspector shows the equivalent **Python and R**, so the analysis
is auditable by someone who does not have this installed.

## 6. Draw it

[Figures pane](#pane:figures). Figures are built from the result, so the
significance annotation can never disagree with the statistics that produced
it. Pick a size preset that matches your target journal: 89 mm single column,
183 mm double.

## 7. Report

[Report pane](#pane:report). Generate the methods paragraph, tick through the
relevant checklist, and build the bundle.
""", reading="5 min", panes=["data", "stats", "figures", "report"]),

# ═══════════════════════════════════════════════════════════════════════
E("review-arc", "A systematic review, start to finish", "Doing a review",
  "The whole arc in order, with the pane that handles each step.",
  """
A review has an order, and most of the pain in doing one comes from doing the
steps out of order. This is the order.

## 0. Write the protocol first

Before any searching. Define the question in PICO form, the inclusion and
exclusion criteria, the outcomes, and the analysis plan. Register it on
PROSPERO.

This is not bureaucracy. A protocol written after the search is a protocol
written knowing what the literature contains, which is how reviews end up
answering the question the evidence happens to fit.

> Search PROSPERO from [Harvest](#pane:harvest) first. If your review already
> exists and is in progress, better to find out now.

Draft the analysis plan from [Report](#pane:report), which produces a
pre-registration skeleton.

## 1. Build the search

[Harvest](#pane:harvest). One database is never enough for a review. The
conventional minimum is MEDLINE (via PubMed), Embase, and CENTRAL, plus trial
registries. Here you have PubMed, Europe PMC, OpenAlex, Crossref, bioRxiv and
medRxiv, ClinicalTrials.gov and openFDA.

Run each source separately and let the corpus accumulate. See
[Building a search](#entry:search) for the syntax.

Record the date you searched. You will need it for the PRISMA diagram, and you
will need to re-run the search before submission if enough time passes.

## 2. Deduplicate

One click in the corpus panel. Duplicates are caught by DOI first, then by
fuzzy title match within publication year. Cross-source overlap is heavy;
expect 20-40% of a multi-source corpus to be duplicates.

## 3. Trim, if the search over-reached

If a search came back far wider than intended, the **trim panel** narrows the
corpus with a preview: it counts what it would remove and shows a sample before
anything goes. Common trims are records with no abstract, records before a
cut-off year, and animal-only work.

Be careful here. Trimming after seeing titles is a form of screening, and
should be done with the same criteria you wrote in the protocol, not by feel.

## 4. Screen titles and abstracts

[Screening](#pane:screen). Keyboard-driven: `i` include, `e` exclude, `m`
maybe, `s` skip, `u` undo. Undo genuinely deletes the judgement.

Screen liberally at this stage. The cost of wrongly including something is one
full text to read. The cost of wrongly excluding it is a missing study nobody
will ever find.

Two reviewers should screen independently. See
[Dual screening and agreement](#entry:dual).

## 5. Screen full texts

Switch the stage selector to **Full text**. Only records included or marked
maybe at title/abstract appear.

Now record a **reason** for every exclusion. PRISMA requires reasons at this
stage and not before, and the reason list feeds straight into the flow diagram.

## 6. Extract

[Synthesis](#pane:synthesis). Pick a form: randomised trial, observational, or
diagnostic accuracy. Extract into structured fields rather than notes, because
structured fields convert into effect sizes and notes do not.

Extract in duplicate if you can. If you cannot, extract once and have a second
person check a sample.

## 7. Judge risk of bias

Same pane. Pick the instrument that matches the design:

| Design | Instrument |
|---|---|
| Randomised trial | RoB 2 |
| Non-randomised intervention study | ROBINS-I |
| Cohort or case-control | Newcastle-Ottawa |
| Diagnostic accuracy | QUADAS-2 |

Judge per domain with a written rationale. The overall judgement is derived
from the domains, not decided separately.

## 8. Synthesise

Convert extractions to effect sizes in the Synthesis pane, then run
[Meta-analysis](#entry:meta) from the Statistics pane. Or decide not to pool:
see when that is the right call in the same entry.

## 9. Report

[Report](#pane:report). The PRISMA diagram is drawn from the screening
database, so it cannot disagree with what you actually did. Work through the
PRISMA checklist. Export the bundle.
""", reading="8 min", panes=["harvest", "screen", "synthesis", "report"]),

# ═══════════════════════════════════════════════════════════════════════
E("search", "Building a search that finds things", "Doing a review",
  "PICO, field tags, MeSH, and why sensitivity beats precision here.",
  """
A search for a review is not a search for a paper to read. You are trying not
to miss anything, which means accepting a lot of irrelevant results.

## Start from PICO

Break the question into concepts, then build each concept as a block of
synonyms joined by `OR`, and join the blocks with `AND`.

```
(spinal cord injury OR SCI OR myelopathy)
AND (olfactory ensheathing cell* OR OEC OR olfactory glia)
AND (transplant* OR graft* OR implant*)
```

Three or four concept blocks is usually right. More than that and you are
almost certainly excluding relevant work.

## Use both free text and controlled vocabulary

PubMed indexes with MeSH terms. Controlled vocabulary catches papers whose
title and abstract use different words; free text catches papers too new to
have been indexed yet. You want both.

```
("Spinal Cord Injuries"[Mesh] OR spinal cord injur*[tiab])
```

- `[tiab]` title and abstract
- `[Mesh]` indexed subject heading
- `[Mesh:noexp]` that heading without narrower terms
- `[pt]` publication type
- `[dp]` date of publication

## What the controls do

The Harvest pane's fields write into the query for you:

- **Publication types** appends `"Randomized Controlled Trial"[Publication Type]`
- **Species** appends the human or animal MeSH filter
- **Abstract only** appends `hasabstract`, which is a reasonable default but
  will drop conference abstracts and some older records
- **From / to year** appends a date range

The query actually sent back is shown in the result, so you can paste it into
the manuscript. You will need it: PRISMA requires the full strategy for at
least one database.

## Then go wider

Databases are not enough on their own.

- **Trial registries** catch studies that were run and never published, which
  is exactly the population publication bias removes
- **Preprints** via bioRxiv and medRxiv
- **Backward citation chasing** take the reference lists of your included
  studies. Crossref returns them
- **Forward citation chasing** who has cited your included studies since.
  OpenAlex and Europe PMC both give citation counts and links

## Then check what you found is real

Run the **retraction check** in the corpus panel. It queries Crossref, which
carries the Retraction Watch data, and flags retractions and expressions of
concern. Citing a retracted trial in a meta-analysis is a real and recurring
failure, and it is entirely avoidable.

Run **resolve open access** to turn DOIs into legal full-text links via
Unpaywall, which needs only an email address in Settings.
""", reading="6 min", panes=["harvest"]),

# ═══════════════════════════════════════════════════════════════════════
E("dual", "Dual screening and agreement", "Doing a review",
  "Two reviewers, blind to each other, then resolve the conflicts.",
  """
Single-reviewer screening misses studies. The error rate is not small, and it
is not random: a tired reviewer at record 400 excludes differently from the
same reviewer at record 40.

## How it works here

The Screening pane has a **reviewer selector**. Each reviewer screens the same
queue independently under their own name. Decisions are stored per reviewer, so
neither overwrites the other.

Switch on **blind mode** and you will not see whether the other reviewer has
already judged a record, which is the point of doing it twice.

## Agreement

Once two reviewers have overlapping decisions, the agreement panel reports:

- **Percentage agreement**, which always looks good and means little, because
  two reviewers excluding 95% of records agree 90% of the time by chance alone
- **Cohen's kappa**, which corrects for that chance agreement

| Kappa | Conventional reading |
|---|---|
| below 0.20 | poor |
| 0.21 to 0.40 | fair |
| 0.41 to 0.60 | moderate |
| 0.61 to 0.80 | substantial |
| above 0.80 | almost perfect |

Below about 0.6 at title and abstract, stop and re-read the inclusion criteria
together. Low kappa nearly always means the criteria are ambiguous, not that
one reviewer is careless.

## Conflicts

The conflicts list shows every record the two reviewers judged differently.
Resolve them by discussion, and record the resolution. A third reviewer
adjudicates if discussion does not settle it.

Report in the manuscript: how many reviewers, whether independently, the kappa,
and how disagreements were resolved. All four are PRISMA items.

## A note on effort

Full dual screening of a 4000-record corpus is genuinely expensive. Accepted
compromises, in descending order of rigour:

1. Both reviewers screen everything, independently
2. Both screen everything at full text, one screens title and abstract with the
   second checking a random 20%
3. One screens, a second checks all exclusions

Anything less than option 3 should be declared as a limitation.
""", reading="4 min", panes=["screen"]),

# ═══════════════════════════════════════════════════════════════════════
E("rob", "Risk of bias, and what to do with it", "Doing a review",
  "Which instrument, judged how, and how it enters the synthesis.",
  """
Risk of bias is about the **study**, not the paper. A beautifully written paper
can report a badly randomised trial. Judge what was done.

## Pick the right instrument

| Design | Instrument | Judgements |
|---|---|---|
| Randomised trial | RoB 2 | low / some concerns / high |
| Non-randomised intervention | ROBINS-I | low / moderate / serious / critical |
| Cohort, case-control | Newcastle-Ottawa | stars, out of 9 |
| Diagnostic accuracy | QUADAS-2 | low / high / unclear, bias and applicability separately |

ROBINS-I benchmarks against a hypothetical target trial, so a non-randomised
study can at best be low risk, never "as good as randomised".

## Judge per domain

Each domain gets its own judgement with a written rationale. The overall
judgement is then **derived**: RoB 2 is high overall if any domain is high;
ROBINS-I takes the worst domain. It is not an average and it is not a vibe.

Write the rationale even when it is "not reported", because "not reported" is
itself the finding and reviewers will ask.

## Then actually use it

Assessing risk of bias and then ignoring it is the most common thing reviews
do with it. Options, in rough order of preference:

- **Stratify** the meta-analysis by risk of bias and see whether the estimate
  moves. If low-risk studies show a smaller effect, say so prominently
- **Sensitivity analysis** excluding high-risk studies
- **Downgrade the certainty** of the evidence in GRADE terms
- **Do not pool at all** if most studies are at high risk

The traffic-light plot in the Synthesis pane goes in the manuscript. The
summary bar goes next to it.

> A meta-analysis of six badly conducted trials is a precise estimate of a
> biased quantity. Precision is not accuracy, and pooling does not launder
> bias.
""", reading="4 min", panes=["synthesis"]),

# ═══════════════════════════════════════════════════════════════════════
E("extraction", "From extracted numbers to effect sizes", "Doing a review",
  "What to extract so it converts, and what the conversion does.",
  """
Extraction fails at synthesis time when the numbers extracted are not the
numbers the effect size needs. Extract for the conversion you intend.

## For a continuous outcome

Per arm: **n**, **mean**, **standard deviation**. That is it. From those the
tool computes:

- **Mean difference** when every study used the same scale
- **Standardised mean difference** (Hedges' g, with the small-sample
  correction) when they used different scales

If a paper reports median and IQR, or a standard error, or a confidence
interval, note it in the notes field rather than guessing. Conversion formulas
exist but they make assumptions, and the assumption should be visible in the
manuscript.

## For a binary outcome

Per arm: **events** and **total**. From those:

- **Odds ratio**, pooled on the log scale
- **Risk ratio**, also on the log scale
- **Risk difference**, on the natural scale

Zero cells get a continuity correction of 0.5, which is the convention and is
also a distortion; if several studies have zero events, that is a reason to
consider a different model rather than a bigger correction.

## For diagnostic accuracy

The 2x2: **TP, FP, FN, TN**, at a stated threshold. If a study reports only
sensitivity, specificity and n, you can usually reconstruct the table.

## Always extract

Regardless of design: the population, the intervention, the comparator, the
outcome definition, follow-up duration, funding source, and declared conflicts.
The last two are not decoration; funding source is a documented predictor of
result direction in several fields.

## The conversion

In Synthesis, choose a measure and press convert. Ratio measures come out on
the **log scale**, which is what the meta-analysis expects, and are
exponentiated again for display. The output columns are `study`, `effect`,
`se`, and that is exactly what [Meta-analysis](#entry:meta) takes as input.
""", reading="4 min", panes=["synthesis"]),

# ═══════════════════════════════════════════════════════════════════════
E("meta", "Meta-analysis, and when not to", "Doing a review",
  "Fixed versus random, heterogeneity, and the pooling decision.",
  """
## Should you pool at all?

Ask before you ask anything else. Pooling is only meaningful if the studies
estimate something close to the same quantity.

Do not pool when:

- The populations, interventions or outcomes are not comparable in a way a
  clinician would recognise
- I² is very high and you cannot explain why
- There are fewer than about three studies, where the between-study variance is
  essentially unestimable
- Most studies are at high risk of bias

A narrative synthesis with a forest plot showing individual estimates and **no
pooled diamond** is a perfectly respectable output, and is often the honest one.

## Fixed effect or random effects

**Fixed effect** assumes every study estimates one identical true effect and
differences are sampling error alone. Rarely plausible in clinical research.

**Random effects** assumes true effects vary across studies and estimates that
variance as τ². This is the default here, and should be your default.

Random effects gives smaller studies relatively more weight. That is the
correct behaviour given its assumptions, and it is also why a random-effects
pooled estimate is more vulnerable to small-study bias.

## Heterogeneity

| Statistic | What it tells you |
|---|---|
| **Q** | A test of whether heterogeneity exceeds chance. Underpowered with few studies, over-powered with many. Do not read its p value as presence or absence |
| **I²** | The percentage of variability due to real differences rather than chance. A proportion, not an amount |
| **τ²** | The actual variance of true effects, on the outcome's own scale. This is the one that matters |

Rough I² reading: below 40% probably unimportant, 30-60% moderate, 50-90%
substantial, above 75% considerable. These overlap deliberately, because the
number means less than the reason behind it.

**I² does not measure how much the effects differ.** With very large studies,
tiny real differences produce a high I². Read τ² alongside it.

## The prediction interval

The confidence interval tells you where the **average** effect lies. The
**prediction interval** tells you where the effect in a new study would
plausibly fall. If your CI excludes the null and your prediction interval does
not, the honest summary is that the average effect is positive but a new trial
could easily find nothing.

It is on by default here. It is often the most informative line on the plot.

## Hartung-Knapp

With few studies, the standard interval is too narrow, because it treats τ² as
if it were known when it was estimated from five numbers. The Hartung-Knapp
adjustment widens it appropriately. On by default, and it should stay on below
about twenty studies.

## Small-study effects

Run the bias panel. Egger's regression, Begg's rank test, trim-and-fill, and a
contour-enhanced funnel plot.

All of them are underpowered below ten studies. If you have eight studies, a
non-significant Egger test is not evidence of no publication bias; it is no
evidence either way, and should be reported as such.

Funnel asymmetry has causes other than publication bias: true heterogeneity,
smaller studies being conducted differently, or chance. "Asymmetric funnel"
does not mean "suppressed studies".
""", reading="7 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("choosing", "Choosing a test", "Choosing and running a test",
  "A decision path from what you have to what to run.",
  """
Start from the **outcome**, then the **predictor**, then the **design**.

## Continuous outcome

| Groups | Design | Parametric | Rank-based |
|---|---|---|---|
| 2 | Independent | Welch t-test | Mann-Whitney U |
| 2 | Paired | Paired t-test | Wilcoxon signed-rank |
| 3+ | Independent | One-way ANOVA | Kruskal-Wallis |
| 3+ | Repeated | Repeated-measures ANOVA | Friedman |
| 2+ factors | Factorial | Factorial ANOVA | Aligned rank transform |
| With covariates | Any | ANCOVA | Quantile regression |
| Clustered or repeated | Any | Mixed-effects model | GEE |

Use **Welch by default** for two independent groups. It costs almost nothing
when variances are equal and is correct when they are not.

## Binary outcome

| Question | Test |
|---|---|
| Association with another category | Chi-square, or Fisher when cells are sparse |
| Paired before and after | McNemar |
| Ordered exposure, is there a trend | Cochran-Armitage |
| Effect of several predictors | Logistic regression |
| Risk in two groups | Risk ratio, odds ratio, risk difference, NNT |

## Time to event

Kaplan-Meier with log-rank for unadjusted comparison. Cox for adjusted. If
hazards are not proportional, use restricted mean survival time, which is
interpretable in months and does not need the assumption. If competing events
are common, Kaplan-Meier overestimates risk; use cumulative incidence and
Fine-Gray.

## Relationship between two continuous variables

Correlation if you want the strength of association. Regression if you want to
predict, or to adjust for something. They answer different questions and it is
worth being clear which you are asking.

For **agreement** between two methods measuring the same thing, correlation is
the wrong tool entirely. Use Bland-Altman and ICC. Two methods that differ by a
constant 10 units correlate at r = 1.0.

## Diagnostic test performance

ROC and AUC for discrimination. Calibration for whether the probabilities are
right. Decision curve analysis for whether it is clinically useful. A model can
have excellent AUC and be useless at every threshold anyone would act on.

## Parametric or rank-based

The old rule was to test for normality and switch. That is not quite right.

- With **n above roughly 30 per group**, the central limit theorem covers the
  mean, and t-tests are fine on non-normal data
- With **small n and visible skew**, use the rank-based test
- With **outliers you cannot justify removing**, rank-based is more robust
- If you want a **confidence interval on a difference in means**, the
  parametric test or a bootstrap gives you one; the rank test does not

A rank test is not a free lunch. Mann-Whitney tests whether one group tends to
exceed the other, which is a test of medians **only if the two distributions
have the same shape**.

## Still unsure

Run **Descriptives** and draw a **raincloud** plot first. Looking at the data
answers this question faster than any flowchart.
""", reading="6 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("assumptions", "When an assumption fails", "Choosing and running a test",
  "What the gate is telling you and what to do about each colour.",
  """
Every test declares what it rests on. Those are checked against your data
before it runs, and shown as lozenges above the run button.

## The policy setting

In Settings, **when an assumption fails** has three options:

- **Warn and run anyway** run it, record the violation in the ledger
- **Block and offer the fallback** refuse, and offer the right test in one click
- **Switch automatically** run the fallback and note it on the result

Blocking is the honest default when working alone. Automatic is faster, but you
must read the note it leaves, because it changes what your result means.

## What each failure actually means

**Normality.** Shapiro-Wilk is downgraded to a caution above n = 5000, because
at that size it rejects departures too small to matter. Read the Q-Q plot
instead. Below n = 30 with real skew, switch to the rank-based test or
transform: log for right skew, which is most biological data.

**Equal variances.** Levene failing means the standard t-test or ANOVA has the
wrong denominator. Switch on Welch. This is nearly free even when variances are
equal, which is why it is on by default for two groups.

**Cell sizes.** A group below n = 3 cannot support the test. Groups more than
three times different in size make variance violations much more damaging.

**Independence.** Cannot be tested from a data frame, so it is always shown as
a caution and never as a pass. If a subject contributed more than one row, or
subjects came in clusters such as wards, litters or centres, then almost every
test in the two-group and ANOVA sections is the wrong one and you want a
mixed-effects model. This is the most commonly violated assumption in the
literature and the one that most inflates false positives.

**Expected cell counts.** Chi-square needs expected counts of at least 5 in
most cells. Cochran's rule tolerates up to 20% below that. Beyond it, use
Fisher's exact test or collapse sparse categories on a principled basis.

**Sphericity.** For repeated measures with three or more levels. When Mauchly
fails, apply the Greenhouse-Geisser correction, which adjusts the degrees of
freedom downward.

**Multicollinearity.** VIF above 5 is worth noting, above 10 means that
coefficient is not interpretable. Two predictors measuring nearly the same
thing will split the effect between them unpredictably.

**Events per variable.** Logistic and Cox models need roughly 10 events per
predictor. Below that, coefficients are unstable and the model has partly
memorised the data. Reduce predictors or use a penalised model.

**Proportional hazards.** For Cox. If hazards cross, the hazard ratio is an
average over a period during which the effect reversed, which is not a useful
summary. Use restricted mean survival time.

## The thing to remember

A failed assumption is not a verdict, it is a decision point. What is not
acceptable is running the test, seeing the assumption failed, and reporting the
result without saying so. That decision is recorded in the ledger either way.
""", reading="5 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("multiplicity", "Multiplicity", "Choosing and running a test",
  "Why the ledger counts, and which correction to use.",
  """
Run twenty independent tests at alpha 0.05 with nothing going on, and you
expect one significant result. Run forty and you expect two.

This is not a hypothetical problem in a tool that makes running one more test
this cheap, which is why the run ledger counts them and the interface starts
saying so after ten.

## What counts as a family

A **family** is the set of tests over which you want to control error. There is
no formula for this; it is a judgement you should be able to defend.

Reasonable families:

- All pairwise comparisons following one omnibus test. Definitely
- All tests of the same hypothesis on different outcomes. Usually
- Every test in the paper. Rarely required, sometimes appropriate
- Pre-specified primary outcome, alone. Common in trials, and the reason
  trials pre-specify one

Secondary and exploratory analyses can be reported uncorrected as long as they
are **labelled exploratory** and not presented as confirmatory findings.

## Which correction

| Method | Controls | Use when |
|---|---|---|
| **Bonferroni** | Family-wise error | Few comparisons. Simple, conservative, over-corrects at scale |
| **Holm** | Family-wise error | Almost always better than Bonferroni. Uniformly more powerful, no extra assumptions. The default here |
| **Šidák** | Family-wise error | Slightly less conservative than Bonferroni, assumes independence |
| **Tukey HSD** | Family-wise error | All pairwise comparisons after ANOVA, equal variances |
| **Games-Howell** | Family-wise error | All pairwise, unequal variances |
| **Dunnett** | Family-wise error | Every group against one control, and nothing else. More power because fewer comparisons |
| **Benjamini-Hochberg** | False discovery rate | Many tests where some false positives are tolerable. Screening, omics |
| **Benjamini-Yekutieli** | False discovery rate | As above, under arbitrary dependence. More conservative |

**Family-wise** control asks: what is the chance of any false positive at all.
**False discovery rate** control asks: what proportion of my significant
results are false. For 20,000 genes the first is paralysing and the second is
right; for four clinical outcomes it is the other way round.

## The honest version

The correction that matters most is the one you make before seeing the data:
pre-specify the primary outcome and the analysis. Everything else is repair
work.

The **multiplicity audit** in the Statistics pane shows every test run against
each dataset and the family-wise error rate that implies. It exists to be
uncomfortable.
""", reading="4 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("power", "Sample size and power", "Choosing and running a test",
  "Before the study, not after.",
  """
Power is the probability of detecting an effect that is really there. The
calculation belongs in the protocol, before recruitment.

## Solve for whatever you left blank

The power tools solve in any direction: give three of sample size, effect,
power and alpha, and get the fourth.

- **Sample size**, the normal use. How many do I need
- **Power**, when the sample is fixed by circumstance. What can I detect
- **Minimum detectable effect**, the most useful of the three when you have a
  fixed cohort. It answers "what is the smallest thing this study could find"

## Where the effect size comes from

This is the whole difficulty, and it is not a statistical question.

- Best: the **minimum clinically important difference**. The smallest change
  that would alter what anyone does
- Acceptable: a meta-analysis of prior work, discounted, since published
  effects are inflated by publication bias
- Poor: your own pilot. Pilot studies systematically overestimate effects, and
  powering a trial from one is a well-documented route to an underpowered trial

## Dropout

Power calculations give the number you need to **analyse**. Recruitment needs
to be higher. The dropout field inflates the target so the analysable n is what
you asked for.

## Post-hoc power

Observed power computed after the fact is a deterministic function of the p
value. It adds no information: a non-significant result always has low observed
power, by arithmetic.

It is available here because reviewers ask for it, with the caveat attached. If
you want to say something about a null result, report the **confidence interval
on the effect** instead. An interval that excludes everything clinically
important is informative; low observed power is not.

## Clustering

If randomisation or sampling happened at a group level, the effective sample
size is smaller than the row count. The design effect is `1 + (m - 1) × ICC`
where m is the average cluster size. With 20 per cluster and an ICC of 0.05,
that is 1.95: you need nearly twice the participants.

The cluster adjustment tool computes this from your data.
""", reading="4 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("effects", "Effect sizes and intervals", "Reading what comes back",
  "The p value is the least interesting number on the screen.",
  """
A p value answers one question: how surprising is this data if nothing is going
on. It says nothing about how large the effect is, and with a large enough
sample any trivial difference becomes significant.

Every result here reports effect sizes alongside, and they are what you should
lead with.

## Standardised differences

| Measure | Reading |
|---|---|
| **Cohen's d** | Difference in standard deviations. 0.2 small, 0.5 medium, 0.8 large, and these benchmarks are arbitrary conventions, not laws |
| **Hedges' g** | d with a small-sample correction. Prefer it below n = 20 per group; identical above |
| **Cohen's dz** | The paired version. Not comparable to d across designs, and confusing the two is a common error |
| **Glass's delta** | Uses only the control group's SD. For when the intervention changes the variance |

## Variance explained

| Measure | Reading |
|---|---|
| **η²** | Proportion of total variance explained by the factor |
| **partial η²** | Proportion of variance explained after removing other factors. Larger, and not comparable across designs |
| **ω²** | Less biased than η². Prefer it |
| **R²** | For regression. Adjusted R² penalises extra predictors |

## Rank-based

| Measure | Reading |
|---|---|
| **Rank-biserial r** | -1 to 1, the rank equivalent of a correlation |
| **Common language effect size** | The probability a random member of group A exceeds a random member of group B. The most intuitive number in this whole list |
| **Hodges-Lehmann** | The median of all pairwise differences. A location estimate in the original units |

## Clinical measures

| Measure | Reading |
|---|---|
| **Risk ratio** | How many times more likely. Intuitive, needs the baseline risk to be meaningful |
| **Odds ratio** | Ratio of odds. Approximates the risk ratio only when the outcome is rare, and is routinely over-interpreted when it is not |
| **Risk difference** | Absolute difference. Often the number that should drive a decision |
| **NNT** | How many treated for one to benefit. Depends entirely on baseline risk, so an NNT from one population does not transfer to another |

## The interval matters more than the point

Report the confidence interval always. It carries everything the p value does,
plus the magnitude, plus the precision.

- An interval excluding the null is a significant result
- A **narrow** interval around a small effect means "there is really nothing
  much here"
- A **wide** interval spanning the null means "this study could not tell", which
  is a very different statement and is usually reported wrongly as "no effect"

> "No significant difference" and "no difference" are not the same claim. If
> you want to claim equivalence, run an equivalence test with a pre-specified
> margin. It is in the Bayesian and equivalence group.
""", reading="5 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("misreading", "Common ways to misread a result", "Reading what comes back",
  "The failure modes worth checking yourself against.",
  """
## p = 0.06 does not mean no effect

It means the evidence did not clear a conventional and arbitrary threshold.
Report the estimate and its interval. "Trending towards significance" is not a
thing; either report it as inconclusive or report the magnitude.

## A significant p does not mean a large effect

With n = 10,000, a correlation of 0.03 is significant and explains 0.09% of the
variance. Check the effect size before writing the sentence.

## Mann-Whitney is not a test of medians

It tests whether values in one group tend to exceed the other. It equals a test
of medians only when the two distributions have the same shape. Two groups with
identical medians and different shapes will come out significant.

## Correlation is not agreement

Two methods that read consistently 10 units apart correlate perfectly. For
agreement use Bland-Altman and ICC, and state which of the six ICC forms.

## AUC is not usefulness

A model can discriminate well and be badly calibrated, or well calibrated and
useless at every threshold anyone would act on. Check calibration and run a
decision curve.

## Predictive values depend on prevalence

Sensitivity and specificity are properties of the test. PPV and NPV are
properties of the test **in a population**. A test with 95% sensitivity and 95%
specificity has a PPV of 16% when prevalence is 1%. The ROC tool makes the
prevalence used explicit for exactly this reason.

## Subgroup findings are not findings

An unplanned subgroup difference is a hypothesis, not a result. Subgroup
analyses in meta-analysis are observational even when every included study was
randomised, because studies were not randomly assigned to subgroups.

## Kaplan-Meier overestimates risk under competing events

If patients can die of something else, they are not simply censored, and
treating them as censored inflates the cumulative incidence. Use competing
risks.

## A truncated y axis exaggerates everything

The survival plot defaults to a y axis from zero for this reason. If you turn
it off because events are rare, say so in the caption.

## Baseline p values in a randomised trial mean nothing

Any imbalance is by definition chance, so testing it tests a hypothesis you
know is true. Report standardised mean differences instead, which is why the
Table 1 generator offers them.
""", reading="4 min", panes=["stats"]),

# ═══════════════════════════════════════════════════════════════════════
E("figures", "Figures for publication", "Producing the output",
  "Sizing, honesty, and the significance bracket.",
  """
Figures here are built from a **result**, not from raw data, so the annotation
cannot disagree with the statistics that produced it.

## Size for the journal, not the screen

Most journals take 89 mm single column and 183 mm double. Both are presets. Set
this before you draw rather than scaling afterwards, because scaling a raster
figure ruins the type and scaling type separately from the plot ruins the
proportions.

- **Vector** PDF, SVG or EPS for anything with lines and text
- **Raster** TIFF at 300 dpi minimum, 600 for figures with fine detail
- Fonts are embedded

## Error bars must be labelled

SD, SEM and 95% CI look similar and mean different things. SEM bars are always
the shortest, which is why they are the most popular and the least informative.
Every figure prints which one it used in the corner. Keep that.

## Show the data

Overlay individual points on bar and box plots. It is the single cheapest way
to make a figure honest: it shows n, spread, outliers and any bimodality that a
mean and an error bar conceal entirely.

If points would be too dense, use a raincloud, which shows the distribution,
the summary and the raw values together.

## Significance brackets

Brackets are sorted by span and assigned the lowest free level that does not
overlap. Adjacent comparisons share a level, a bracket spanning another is
lifted above it. Nothing collides regardless of how many comparisons there are.

- **Asterisks** or **exact p values**, or both
- **Only annotate significant** is on by default. Turning it off shows the
  non-significant comparisons too, which is more honest and much busier

## Colour

Okabe-Ito is the default palette and is safe for all common forms of colour
blindness. Viridis for continuous scales. Check the greyscale version if the
journal prints in black and white.

Never encode a variable by colour alone. Add a shape, a pattern or a label.

## Figure types worth knowing about

- **Raincloud** distribution, summary and raw data in one panel
- **Bland-Altman** agreement, with limits and their intervals
- **Forest** individual estimates, weight-proportional markers, pooled diamond
  and the prediction interval
- **Funnel** small-study effects, with significance contours
- **Kaplan-Meier** with the number-at-risk table, which reviewers will ask for
- **Decision curve** net benefit across thresholds
- **PRISMA and CONSORT** flow diagrams drawn from the database
""", reading="4 min", panes=["figures"]),

# ═══════════════════════════════════════════════════════════════════════
E("reproducibility", "Reproducibility and the ledger", "Producing the output",
  "What gets recorded, and what you can hand to someone else.",
  """
## What every run records

- A **sha256 of the data** as analysed, after cleaning
- The **full specification**: test, variables, every parameter
- The **random seed**, so resampling reproduces exactly
- The **package versions** of Python, SciPy, statsmodels and the rest
- Every **assumption check** and what it said
- The **result**, and the wall-clock duration

Blocked runs are recorded too. You cannot quietly try eight tests and report
the ninth.

## The methods paragraph

Generated from the ledger, so it names the tests that were actually executed,
the corrections applied, the number of assumption checks and the number that
failed, and the software versions.

It is a **draft**. Read it before pasting it. It cannot know why you chose a
test, and that reasoning is what a methods section is for.

## The bundle

The Report pane builds a zip containing:

```
manifest.json     data hash, seed, alpha, package versions
methods.txt       the generated paragraph
runs/             every spec, result and assumption check as JSON
figures/          every rendered figure
reproduce.py      a standalone Python script
reproduce.R       the R equivalent
data.csv          the data as analysed
```

Someone with the zip and neither this tool nor your machine can re-run the
analysis. That is the bar.

## Pre-registration

The Report pane produces an OSF-style skeleton. The field people leave blank is
**what happens if an assumption fails**, and it is the one that matters most,
because deciding that after seeing the data is exactly how a p-hack ends up
looking principled.

## The reporting checklists

CONSORT, STROBE, PRISMA, STARD, TRIPOD, ARRIVE and SPIRIT, tickable in the
Report pane. Most journals require the relevant one at submission. Working
through it before writing is faster than retrofitting it afterwards, and it
routinely surfaces something that should have been decided months earlier.
""", reading="3 min", panes=["report", "runs"]),

# ═══════════════════════════════════════════════════════════════════════
E("gotchas", "Things that will bite you", "Producing the output",
  "Practical failures, in the order they usually happen.",
  """
**A binary column typed as continuous.** Check the dictionary first. Everything
downstream depends on it and nothing will warn you.

**Excel dates.** A column of dates imported as numbers, or worse, gene names
converted to dates. Check the preview.

**Missing codes as data.** 999 and -999 are recognised on import; unusual
sentinels are not. A mean age of 340 is the symptom.

**Repeated measures analysed as independent.** The most common serious error in
the literature. If a subject appears in more than one row, you need a mixed
model. The independence lozenge is amber on every relevant test for this
reason.

**Excluding outliers after seeing the result.** Decide the rule first, apply it
blind, record it. The outlier screen logs every exclusion so it reaches the
methods text.

**Optional stopping.** Checking significance as data accumulates, and stopping
when it appears, inflates the false positive rate substantially. If you need
interim looks, use alpha spending.

**Baseline testing in a randomised trial.** Report standardised mean
differences, not p values.

**Pooling incomparable studies.** A precise estimate of a meaningless average.

**Citing a retracted study.** Run the retraction check before you submit, and
again if review takes months.

**Reporting a subgroup finding as a result.** Label it exploratory.

**Reporting "no difference" from a non-significant test.** Run an equivalence
test or report the interval.

**Losing the search date.** PRISMA needs it. The harvest log records it.

**Screening alone and not saying so.** Declare it as a limitation.
""", reading="3 min", panes=[]),

]
