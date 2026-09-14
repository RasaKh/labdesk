import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from labdesk import assumptions as assumptions_mod
from labdesk import analysis_guide
from labdesk.config import get
from labdesk import datasets, db, projects, reporting, screening, stats_run
from labdesk.plots_registry import REGISTRY as PLOT_REGISTRY
from labdesk.plots_run import RENDERERS
from labdesk.runners import RUNNERS
from labdesk.runners import basic, bench, models
from labdesk.schema import validate_spec
from labdesk.stats_registry import REGISTRY as STAT_REGISTRY


class TempDatabaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir()
        db.close()
        db.DB_PATH = str(self.root / "labdesk.db")
        datasets.DATA_DIR = str(self.root / "data")
        datasets._cache.clear()
        db.init()

    def tearDown(self):
        db.close()
        datasets._cache.clear()
        stats_run._RUNNERS = None
        self.tmp.cleanup()

    def project(self, pid):
        now = 1.0
        db.insert("project", {"id": pid, "name": pid, "kind": "analysis",
                              "question": "q", "created_at": now, "updated_at": now})

    def csv_dataset(self, frame, pid="p1", name="data.csv"):
        self.project(pid)
        path = self.root / name
        frame.to_csv(path, index=False)
        return datasets.import_file(str(path), project_id=pid)


class BinaryLevelTests(unittest.TestCase):

    def test_binary_positive_accepts_float_encoded_zero_one(self):
        pos, vals = models._binary_positive(pd.Series([1.0, 0.0, 1.0]), None, "Diabetes")
        self.assertEqual("1.0", pos)
        self.assertEqual({"0.0", "1.0"}, set(vals))

    def test_kaplan_meier_accepts_explicit_event_level(self):
        df = pd.DataFrame({"time": [1, 2, 3, 4], "status": ["dead", "alive", "dead", "alive"]})
        out = models.kaplan_meier(df, {"time": ["time"], "event": ["status"], "group": []},
                                  {"event_level": "dead"})
        self.assertEqual("dead", out["event_level"])



class RegistryContractTests(unittest.TestCase):
    def test_every_ready_analysis_and_plot_has_an_implementation(self):
        ready_stats = {k: v for k, v in STAT_REGISTRY.items() if v.get("status") == "ready"}
        ready_plots = {k: v for k, v in PLOT_REGISTRY.items() if v.get("status") == "ready"}
        self.assertEqual([], sorted(k for k in ready_stats if k not in RUNNERS))
        self.assertEqual([], sorted(k for k in ready_plots if k not in RENDERERS))
        missing_refs = sorted({p for v in ready_stats.values()
                               for p in v.get("plots", []) if p not in PLOT_REGISTRY})
        self.assertEqual([], missing_refs)
        missing_fallbacks = sorted({v["fallback"] for v in ready_stats.values()
                                    if v.get("fallback") and v["fallback"] not in RUNNERS})
        self.assertEqual([], missing_fallbacks)

    def test_registry_does_not_advertise_known_unimplemented_controls(self):
        def param_ids(test_id):
            return {p["id"] for p in STAT_REGISTRY[test_id].get("params", [])}
        self.assertNotIn("little_mcar", param_ids("missing_check"))
        self.assertNotIn("bootstrap", param_ids("ttest_ind"))
        self.assertNotIn("bootstrap", param_ids("ttest_paired"))
        self.assertNotIn("omega", param_ids("cronbach"))
        self.assertNotIn("interactions", param_ids("linreg"))
        self.assertNotIn("weighting", param_ids("kaplan_meier"))
        self.assertNotIn("bootstrap", param_ids("roc"))
        self.assertNotIn("input", param_ids("meta_effect"))
        bias = next(p for p in STAT_REGISTRY["meta_bias"]["params"] if p["id"] == "tests")
        values = {c[0] if isinstance(c, tuple) else c for c in bias["choices"]}
        self.assertEqual({"egger", "begg", "trimfill"}, values)

        def plot_param_ids(plot_id):
            return {p["id"] for p in PLOT_REGISTRY[plot_id].get("params", [])}
        for plot_id in ("violin", "beeswarm", "paired_lines", "pca_biplot"):
            self.assertEqual("stub", PLOT_REGISTRY[plot_id]["status"])
        self.assertNotIn("loess", {c[0] if isinstance(c, tuple) else c
                                   for c in next(p for p in PLOT_REGISTRY["scatter_fit"]["params"]
                                                 if p["id"] == "fit")["choices"]})
        self.assertNotIn("marginals", plot_param_ids("scatter_fit"))
        self.assertNotIn("colour_by", plot_param_ids("scatter_fit"))
        self.assertNotIn("ci_band", plot_param_ids("roc"))
        self.assertNotIn("trimfill", plot_param_ids("funnel"))
        self.assertEqual(set(), plot_param_ids("prisma"))


class DatasetIntegrityTests(TempDatabaseCase):
    def test_semantic_hash_changes_when_columns_change(self):
        a = pd.DataFrame({"age": [1, 2, 3], "sex": [0, 1, 0]})
        b = a.copy()
        b.columns = ["weight", "treatment"]
        self.assertNotEqual(datasets.sha256_of_frame(a), datasets.sha256_of_frame(b))

    def test_numeric_sentinel_999_is_not_destroyed_on_import(self):
        ds = self.csv_dataset(pd.DataFrame({"value": [1, 999, 3]}))
        self.assertEqual([1, 999, 3], datasets.load(ds)["value"].tolist())

    def test_columns_that_collide_after_trimming_are_rejected(self):
        self.project("p1")
        path = self.root / "collision.csv"
        path.write_text("age, age \n1,2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "collide"):
            datasets.import_file(str(path), project_id="p1")

    def test_dictionary_hash_changes_when_semantics_change(self):
        d1 = {"x": {"kind": "continuous", "label": "x"}}
        d2 = {"x": {"kind": "categorical", "label": "x"}}
        self.assertNotEqual(datasets.sha256_of_dictionary(d1),
                            datasets.sha256_of_dictionary(d2))


class SchemaTests(unittest.TestCase):
    def test_server_validates_kind_levels_and_parameter_columns(self):
        entry = {
            "roles": [{"id": "group", "label": "Group", "kind": "categorical",
                       "min": 1, "max": 1, "optional": False, "levels": 2}],
            "params": [{"id": "by", "label": "Split by", "type": "column"}],
        }
        df = pd.DataFrame({"g": [0, 1, 0, 1], "x": [1, 2, 3, 4]})
        dictionary = {"g": {"kind": "binary"}, "x": {"kind": "continuous"}}
        errors, _ = validate_spec(entry, {"roles": {"group": ["g"]},
                                          "params": {"by": "missing"}},
                                  df=df, dictionary=dictionary)
        self.assertTrue(any("not a column" in e for e in errors), errors)

        bad_dictionary = {"g": {"kind": "continuous"}, "x": {"kind": "continuous"}}
        errors, _ = validate_spec(entry, {"roles": {"group": ["g"]}, "params": {}},
                                  df=df, dictionary=bad_dictionary)
        self.assertTrue(any("requires 'categorical'" in e for e in errors), errors)


class PersistenceAndProvenanceTests(TempDatabaseCase):
    def test_transaction_rolls_back_as_a_unit(self):
        with self.assertRaises(RuntimeError):
            with db.transaction():
                db.insert("project", {"id": "rolled", "name": "rolled"})
                raise RuntimeError("stop")
        self.assertIsNone(db.one("SELECT id FROM project WHERE id='rolled'"))

    def test_runs_are_project_scoped(self):
        db.log_run(id="r1", project_id="p1", dataset_sha="same", test_id="describe",
                   status="ok")
        db.log_run(id="r2", project_id="p2", dataset_sha="same", test_id="describe",
                   status="ok")
        self.assertEqual(1, db.runs_on_dataset("same", "p1"))
        self.assertEqual(1, db.runs_on_dataset("same", "p2"))
        self.assertEqual(0, db.runs_on_dataset("same", None))

    def test_successful_run_inherits_dataset_project(self):
        ds = self.csv_dataset(pd.DataFrame({"x": np.arange(1, 21, dtype=float)}))
        result = stats_run.run({"test": "describe", "dataset": ds,
                                "project": "p1", "roles": {"vars": ["x"]},
                                "params": {"normality": False}})
        self.assertTrue(result["ok"])
        row = db.one("SELECT * FROM analysis_run WHERE id=?", (result["run_id"],))
        self.assertEqual("p1", row["project_id"])
        self.assertEqual(datasets.meta(ds)["dictionary_sha"], row["dictionary_sha"])
        self.assertIsNotNone(row["alpha"])
        self.assertIsNotNone(row["ci_level"])

    def test_execution_exception_is_written_to_ledger(self):
        ds = self.csv_dataset(pd.DataFrame({"x": np.arange(1, 21, dtype=float)}))
        original_cache = stats_run._RUNNERS
        fake = dict(stats_run.runners())
        def explode(*args, **kwargs):
            raise RuntimeError("deliberate runner failure")
        fake["describe"] = explode
        stats_run._RUNNERS = fake
        try:
            with self.assertRaisesRegex(RuntimeError, "deliberate"):
                stats_run.run({"test": "describe", "dataset": ds, "project": "p1",
                               "roles": {"vars": ["x"]}, "params": {"normality": False}})
        finally:
            stats_run._RUNNERS = original_cache
        row = db.one("SELECT * FROM analysis_run WHERE project_id='p1' "
                     "ORDER BY created_at DESC LIMIT 1")
        self.assertEqual("failed", row["status"])
        self.assertIn("deliberate runner failure", row["error"])

    def test_fallback_ledger_code_matches_method_actually_executed(self):
        x = np.r_[np.linspace(1, 10, 15), np.linspace(2, 11, 15)]
        g = ["A"] * 15 + ["B"] * 15
        ds = self.csv_dataset(pd.DataFrame({"x": x, "g": g}))
        original_gate = assumptions_mod.gate
        assumptions_mod.gate = lambda checks: (True, "fallback:mannwhitney", "forced test fallback")
        try:
            result = stats_run.run({"test": "ttest_ind", "dataset": ds, "project": "p1",
                                    "roles": {"dv": ["x"], "group": ["g"]},
                                    "params": {"welch": True, "alternative": "two-sided"}})
        finally:
            assumptions_mod.gate = original_gate
        self.assertTrue(result["ok"])
        self.assertEqual("mannwhitney", result["test_id"])
        row = db.one("SELECT * FROM analysis_run WHERE id=?", (result["run_id"],))
        self.assertEqual("mannwhitney", row["test_id"])
        self.assertIn("mannwhitneyu", row["code_python"])
        self.assertNotIn("ttest_ind", row["code_python"])


class ScreeningTests(TempDatabaseCase):
    def setUp(self):
        super().setUp()
        self.project("p1")
        self.project("p2")
        for pid, rid in (("p1", "a"), ("p2", "b")):
            db.insert("record", {"id": rid, "project_id": pid, "source": "pubmed",
                                 "source_uid": rid, "title": rid, "year": 2024})

    def test_disagreement_does_not_advance_to_full_text_until_resolved(self):
        screening.decide("a", "include", reviewer="r1")
        screening.decide("a", "exclude", reviewer="r2")
        state = screening._final_screen_states("p1", "title_abstract")["a"]
        self.assertFalse(state["final"])
        self.assertEqual(0, screening.queue("p1", "full_text", "r3")["total"])
        screening.resolve("a", "title_abstract", "include", "adjudicated", "lead")
        state = screening._final_screen_states("p1", "title_abstract")["a"]
        self.assertTrue(state["final"])
        self.assertEqual(1, screening.queue("p1", "full_text", "r3")["total"])

    def test_changed_vote_supersedes_adjudication_and_preserves_history(self):
        screening.decide("a", "include", reviewer="r1")
        screening.decide("a", "exclude", reviewer="r2")
        screening.resolve("a", "title_abstract", "include", "first resolution", "lead")
        self.assertTrue(screening._final_screen_states("p1", "title_abstract")["a"]["final"])
        screening.decide("a", "maybe", reviewer="r2")
        self.assertFalse(screening._final_screen_states("p1", "title_abstract")["a"]["final"])
        self.assertEqual(4, db.one("SELECT COUNT(*) c FROM screening_event WHERE record_id='a'")["c"])
        self.assertIsNotNone(db.one("SELECT superseded_at FROM resolution WHERE record_id='a'")["superseded_at"])

    def test_prisma_is_project_scoped_and_counts_records_once(self):
        screening.decide("a", "exclude", reviewer="r1", reason="Wrong population")
        screening.decide("b", "exclude", reviewer="r1", reason="Wrong outcome")
        p1 = screening.prisma_counts("p1")
        p2 = screening.prisma_counts("p2")
        self.assertEqual(1, p1["counts"]["screened"])
        self.assertEqual(1, p1["counts"]["excluded_ta"])
        self.assertEqual(1, p2["counts"]["screened"])
        self.assertEqual(1, p2["counts"]["excluded_ta"])

    def test_reviewer_progress_is_project_scoped(self):
        screening.ensure_reviewers()
        rid = screening.reviewers()[0]["id"]
        screening.decide("a", "include", reviewer=rid)
        screening.decide("b", "exclude", reviewer=rid)
        p1 = {r["id"]: r for r in screening.reviewers("p1")}[rid]
        p2 = {r["id"]: r for r in screening.reviewers("p2")}[rid]
        self.assertEqual(1, p1["decisions"])
        self.assertEqual(1, p2["decisions"])

    def test_newcastle_ottawa_enforces_its_nine_star_structure(self):
        with self.assertRaisesRegex(ValueError, "at most 1"):
            screening.set_rob("a", "nos", {"S1": "2"})
        domains = {"S1": "1", "S2": "1", "S3": "1", "S4": "1",
                   "C1": "2", "O1": "1", "O2": "1", "O3": "1"}
        row = screening.set_rob("a", "nos", domains)
        self.assertEqual("9/9", row["overall"])


class NumericalCorrectnessTests(unittest.TestCase):
    def test_factorial_anova_executes_declared_interaction(self):
        rows = []
        for a in ("A0", "A1"):
            for b in ("B0", "B1"):
                for i in range(6):
                    y = (10 + (2 if a == "A1" else 0) + (3 if b == "B1" else 0)
                         + (4 if a == "A1" and b == "B1" else 0) + i * 0.01)
                    rows.append({"y": y, "a": a, "b": b})
        r = basic.anova_factorial(pd.DataFrame(rows),
                                  {"dv": ["y"], "factors": ["a", "b"]},
                                  {"interactions": True, "ss_type": 2, "posthoc": "none"})
        sources = {row["source"] for row in r["table"]}
        self.assertIn('C(Q("a")):C(Q("b"))', sources)
        self.assertEqual("Factorial ANOVA (Type 2 SS)", r["test"])

    def test_dunnett_is_scipys_dunnett_not_corrected_t_tests(self):
        df = pd.DataFrame({"y": [1, 2, 3, 4, 2, 3, 4, 5, 3, 4, 5, 6],
                           "g": ["C"] * 4 + ["T1"] * 4 + ["T2"] * 4})
        rows, label = basic._posthoc(df, "y", "g", "dunnett", control="C")
        direct = stats.dunnett(np.array([2, 3, 4, 5.]), np.array([3, 4, 5, 6.]),
                               control=np.array([1, 2, 3, 4.]),
                               alternative="two-sided", random_state=get("seed", 0))
        np.testing.assert_allclose([r["p"] for r in rows], np.atleast_1d(direct.pvalue),
                                   rtol=1e-12, atol=1e-12)
        self.assertIn("Dunnett", label)

    def test_pairwise_control_filter_does_not_change_selected_test(self):
        df = pd.DataFrame({"y": [1, 2, 3, 4, 2, 3, 4, 5, 3, 4, 5, 6],
                           "g": ["C"] * 4 + ["T1"] * 4 + ["T2"] * 4})
        r = basic.pairwise(df, {"dv": ["y"], "group": ["g"]},
                           {"test": "t", "against": "control",
                            "control": "C", "correction": "holm"})
        self.assertEqual("pairwise t with holm correction", r["posthoc_label"])
        raw = [stats.ttest_ind(np.array([1, 2, 3, 4.]), np.array(v), equal_var=True).pvalue
               for v in ([2, 3, 4, 5.], [3, 4, 5, 6.])]
        np.testing.assert_allclose([x["p_raw"] for x in r["comparisons"]], raw)

    def test_qpcr_does_not_silently_turn_two_group_test_into_anova(self):
        rows = []
        for group, shift in (("A", 0), ("B", 1), ("C", 2)):
            for i in range(3):
                sample = f"{group}{i}"
                rows.extend([
                    {"ct": 18 + i * .05, "gene": "GAPDH", "sample": sample, "group": group},
                    {"ct": 20 + shift + i * .05, "gene": "TARGET", "sample": sample, "group": group},
                ])
        roles = {"ct": ["ct"], "gene": ["gene"], "sample": ["sample"], "group": ["group"]}
        with self.assertRaisesRegex(ValueError, "two-group comparison"):
            bench.qpcr(pd.DataFrame(rows), roles,
                       {"reference_genes": "GAPDH", "calibrator": "A",
                        "efficiency": "assume100", "max_replicate_sd": .5,
                        "test": "ttest", "stability": False})

    def test_descriptive_controls_change_the_output_they_name(self):
        df = pd.DataFrame({"x": np.arange(1, 11, dtype=float)})
        lean = basic.describe(df, {"vars": ["x"]}, {"robust": False, "normality": False})
        self.assertNotIn("median", lean["rows"][0])
        self.assertNotIn("shapiro_p", lean["rows"][0])
        full = basic.describe(df, {"vars": ["x"]}, {"robust": True, "normality": True})
        self.assertIn("mad", full["rows"][0])
        self.assertIn("normality_flag", full["rows"][0])

    def test_armitage_honours_the_requested_alternative(self):
        # Event prevalence increases sharply with exposure score.
        df = pd.DataFrame({"outcome": [0]*9+[1] + [0]*5+[1]*5 + [0]+[1]*9,
                           "dose": [0]*10 + [1]*10 + [2]*10})
        roles = {"outcome": ["outcome"], "ordered": ["dose"]}
        greater = basic.armitage(df, roles, {"alternative": "greater"})
        less = basic.armitage(df, roles, {"alternative": "less"})
        two = basic.armitage(df, roles, {"alternative": "two-sided"})
        self.assertLess(greater["p"], 0.01)
        self.assertGreater(less["p"], 0.99)
        self.assertAlmostEqual(two["p"], 2 * greater["p"], places=12)

    def test_cluster_adjust_report_icc_switch_is_not_cosmetic(self):
        df = pd.DataFrame({"y": [1, 1.2, 3, 3.1, 6, 6.2],
                           "cluster": ["a", "a", "b", "b", "c", "c"]})
        roles = {"outcome": ["y"], "cluster": ["cluster"]}
        hidden = bench.cluster_adjust(df, roles, {"report_icc": False})
        shown = bench.cluster_adjust(df, roles, {"report_icc": True})
        self.assertNotIn("icc", hidden)
        self.assertIn("icc", shown)
        self.assertEqual(hidden["design_effect"], shown["design_effect"])

    def test_elisa_models_are_not_label_only_options(self):
        x = np.array([1, 2, 4, 8, 16, 32, 64, 128.0])
        roles = {"od": ["od"], "conc": ["conc"], "sample_type": ["type"], "well": ["well"]}

        linear_df = pd.DataFrame({"od": 2 * x + 1, "conc": x,
                                  "type": ["standard"] * len(x),
                                  "well": [f"A{i+1}" for i in range(len(x))]})
        linear = bench.elisa(linear_df, roles,
                             {"model": "linear", "weighting": "none", "max_cv": 15,
                              "recovery_range": "99-101", "dilution": 1, "edge_effect": False})
        self.assertEqual("Linear standard curve", linear["test"])
        self.assertAlmostEqual(2.0, linear["parameters"]["slope"], places=9)
        self.assertTrue(all(abs(s["recovery"] - 100) < 1e-7 for s in linear["standards"]))

        log_df = linear_df.copy()
        log_df["od"] = 2 * np.log10(x) + 1
        logfit = bench.elisa(log_df, roles,
                             {"model": "loglinear", "weighting": "none", "max_cv": 15,
                              "recovery_range": "99-101", "dilution": 1, "edge_effect": False})
        self.assertEqual("Log-linear standard curve", logfit["test"])
        self.assertAlmostEqual(2.0, logfit["parameters"]["slope"], places=8)

    def test_elisa_sample_label_is_not_mistaken_for_standard(self):
        x = np.array([1, 2, 4, 8, 16.0])
        std = pd.DataFrame({"od": 2*x+1, "conc": x, "type": "standard",
                            "well": [f"A{i+1}" for i in range(len(x))]})
        unknown = pd.DataFrame({"od": [7.0], "conc": [np.nan], "type": ["sample"], "well": ["B1"]})
        df = pd.concat([std, unknown], ignore_index=True)
        r = bench.elisa(df, {"od": ["od"], "conc": ["conc"], "sample_type": ["type"], "well": ["well"]},
                        {"model": "linear", "weighting": "none", "max_cv": 15,
                         "recovery_range": "80-120", "dilution": 1, "edge_effect": False})
        self.assertEqual(5, len(r["standards"]))
        self.assertEqual(1, len(r["unknowns"]))
        self.assertEqual("B1", r["unknowns"][0]["label"])

    def test_pfaffl_with_efficiency_two_matches_delta_delta_ct(self):
        rows = []
        for sample, group, target_ct in (("c1", "C", 20.0), ("c2", "C", 20.2),
                                         ("t1", "T", 18.0), ("t2", "T", 18.1)):
            for gene, ct in (("GAPDH", 18.0), ("TARGET", target_ct)):
                for delta in (-0.05, 0.05):
                    rows.append({"ct": ct + delta, "gene": gene,
                                 "sample": sample, "group": group})
        df = pd.DataFrame(rows)
        roles = {"ct": ["ct"], "gene": ["gene"], "sample": ["sample"], "group": ["group"]}
        base = {"reference_genes": "GAPDH", "calibrator": "C", "max_replicate_sd": 0.5,
                "test": "ttest", "stability": False}
        dd = bench.qpcr(df, roles, {**base, "efficiency": "assume100"})
        pf = bench.qpcr(df, roles, {**base, "efficiency": "pfaffl",
                                    "efficiencies": "GAPDH=2,TARGET=2"})
        np.testing.assert_allclose(dd["genes"][0]["mean_fold_change"],
                                   pf["genes"][0]["mean_fold_change"], rtol=1e-12)
        self.assertIn("ΔCt", dd["genes"][0]["test"])

    def test_regression_design_does_not_turn_missing_values_into_observations(self):
        df = pd.DataFrame({"y": [0, 1, np.nan, 1, 0, 1],
                           "cat": ["a", "b", "a", np.nan, "b", "a"]})
        y, X, names, n = models._design(df, "y", ["cat"])
        self.assertEqual(4, n)
        self.assertFalse(any("nan" in name.lower() for name in names))
        self.assertEqual(4, len(y))
        self.assertEqual(4, len(X))

    def test_roc_drops_scores_that_become_nan_after_numeric_coercion(self):
        df = pd.DataFrame({"score": [0.1, "not measured", 0.9, 0.8],
                           "truth": [0, 1, 1, 1]})
        r = models.roc(df, {"score": ["score"], "truth": ["truth"]},
                       {"positive_level": "1", "direction": "positive",
                        "cutpoint": "youden", "ci": 0.95})
        self.assertEqual(3, r["n"])
        self.assertEqual(1, r["n_negative"])
        self.assertEqual(2, r["n_positive"])


class AnalysisGuideTests(unittest.TestCase):
    def setUp(self):
        self.dictionary = {
            "crp": {"kind": "continuous", "n_unique": 30},
            "age": {"kind": "continuous", "n_unique": 30},
            "treatment": {"kind": "binary", "n_unique": 2,
                          "levels": [["control", 15], ["active", 15]]},
            "arm3": {"kind": "categorical", "n_unique": 3,
                     "levels": [["A", 10], ["B", 10], ["C", 10]]},
            "death": {"kind": "binary", "n_unique": 2},
            "followup": {"kind": "continuous", "n_unique": 29},
        }

    def test_two_level_group_does_not_offer_three_group_omnibus_tests(self):
        r = analysis_guide.compatible_methods(self.dictionary, "compare",
                                              "crp", "treatment", limit=50)
        ids = {x["id"] for x in r["items"]}
        self.assertIn("ttest_ind", ids)
        self.assertIn("mannwhitney", ids)
        self.assertNotIn("anova_oneway", ids)
        self.assertNotIn("kruskal", ids)
        self.assertNotIn("welch_anova", ids)

    def test_three_level_group_prefills_three_group_methods(self):
        r = analysis_guide.compatible_methods(self.dictionary, "compare",
                                              "crp", "arm3", limit=50)
        items = {x["id"]: x for x in r["items"]}
        self.assertIn("anova_oneway", items)
        self.assertEqual({"dv": ["crp"], "group": ["arm3"]},
                         items["anova_oneway"]["prefill"])
        self.assertNotIn("ttest_ind", items)

    def test_binary_outcome_and_predictor_narrow_to_logistic_model(self):
        r = analysis_guide.compatible_methods(self.dictionary, "model",
                                              "death", "age", limit=50)
        self.assertEqual(["logreg"], [x["id"] for x in r["items"]])
        self.assertEqual({"dv": ["death"], "predictors": ["age"]},
                         r["items"][0]["prefill"])

    def test_association_can_prefill_two_variables_into_one_multi_role(self):
        r = analysis_guide.compatible_methods(self.dictionary, "association",
                                              "crp", "age", limit=50)
        corr = next(x for x in r["items"] if x["id"] == "correlation")
        self.assertEqual({"vars": ["crp", "age"]}, corr["prefill"])

    def test_survival_requires_time_and_event_shapes(self):
        good = analysis_guide.compatible_methods(self.dictionary, "survival",
                                                 "followup", "death", limit=50)
        self.assertEqual(["kaplan_meier", "cox"], [x["id"] for x in good["items"]])
        cox = good["items"][1]
        self.assertEqual({"time": ["followup"], "event": ["death"]}, cox["prefill"])
        self.assertIn("age", cox["role_options"]["predictors"])
        bad = analysis_guide.compatible_methods(self.dictionary, "survival",
                                                "crp", "age", limit=50)
        self.assertEqual([], bad["items"])


class CoxAncovaTests(unittest.TestCase):
    def test_cox_reproduces_r_coxph_on_rossi(self):
        from lifelines.datasets import load_rossi
        out = models.cox(load_rossi(), {
            "time": ["week"], "event": ["arrest"],
            "predictors": ["fin", "age", "race", "wexp", "mar", "paro", "prio"]}, {})
        # survival::coxph(Surv(week, arrest) ~ ., data = rossi), Efron ties.
        r_coef = {"fin_1": -0.37942, "age": -0.05744, "race_1": 0.31390,
                  "wexp_1": -0.14980, "mar_1": -0.43370, "paro_1": -0.08487,
                  "prio": 0.09150}
        got = {c["term"]: c["log_hr"] for c in out["coefficients"]}
        for term, want in r_coef.items():
            self.assertAlmostEqual(want, got[term], places=4, msg=term)
        self.assertAlmostEqual(33.27, out["statistic"], places=2)
        self.assertEqual(7, out["df"])
        self.assertEqual(114, out["n_events"])
        # The textbook proportional-hazards violations in this dataset.
        flagged = {r["term"] for r in out["ph_test"] if r["p"] < 0.05}
        self.assertEqual({"age", "wexp_1"}, flagged)

    def test_cox_event_level_and_strata(self):
        from lifelines.datasets import load_rossi
        df = load_rossi()
        df["status"] = np.where(df["arrest"] == 1, "rearrested", "censored")
        out = models.cox(df, {"time": ["week"], "event": ["status"],
                              "predictors": ["fin", "prio"], "strata": ["wexp"]},
                         {"event_level": "rearrested", "check_ph": False})
        self.assertEqual("rearrested", out["event_level"])
        self.assertEqual(114, out["n_events"])
        self.assertEqual(["fin_1", "prio"], [c["term"] for c in out["coefficients"]])

    def test_ancova_matches_extra_sum_of_squares(self):
        rng = np.random.default_rng(7)
        n = 90
        g = np.repeat(["ctrl", "low", "high"], 30)
        base = rng.normal(50, 10, n)
        y = 0.6 * base + np.select([g == "low", g == "high"], [3, 6], 0) + rng.normal(0, 5, n)
        df = pd.DataFrame({"post": y, "arm": g, "baseline": base})
        out = models.ancova(df, {"dv": ["post"], "group": ["arm"],
                                 "covariates": ["baseline"]}, {})

        def rss(X):
            b, *_ = np.linalg.lstsq(X, y, rcond=None)
            e = y - X @ b
            return e @ e
        one = np.ones(n)
        r0 = rss(np.column_stack([one, base]))
        r1 = rss(np.column_stack([one, base, g == "low", g == "high"]))
        F = ((r0 - r1) / 2) / (r1 / (n - 4))
        self.assertAlmostEqual(F, out["statistic"], places=8)
        self.assertEqual([2, 86], out["df"])
        self.assertAlmostEqual((r0 - r1) / r0, out["effects"]["partial_eta_squared"], places=8)
        adj = {r["group"]: r["adjusted_mean"] for r in out["adjusted_means"]}
        self.assertAlmostEqual(3, adj["low"] - adj["ctrl"], delta=2)
        self.assertGreater(out["slopes_test"]["p"], 0.05)
        self.assertNotIn("warning", out)

    def test_ancova_warns_when_slopes_differ(self):
        rng = np.random.default_rng(3)
        g = np.repeat(["a", "b"], 60)
        x = rng.normal(size=120)
        y = np.where(g == "a", 2 * x, -2 * x) + rng.normal(0, 0.5, 120)
        out = models.ancova(pd.DataFrame({"y": y, "g": g, "x": x}),
                            {"dv": ["y"], "group": ["g"], "covariates": ["x"]}, {})
        self.assertLess(out["slopes_test"]["p"], 0.001)
        self.assertIn("slopes differ", out["warning"])

    def test_epv_counts_real_events(self):
        # Regression: EPV read n_events from a context that never set it, so
        # every logistic model failed with "0 events".
        rng = np.random.default_rng(1)
        df = pd.DataFrame({"y": rng.integers(0, 2, 400), "x": rng.normal(size=400),
                           "arm": rng.choice(["a", "b", "c"], 400)})
        entry = STAT_REGISTRY["logreg"]
        ctx = stats_run._ctx(df, entry, {"dv": ["y"], "predictors": ["x", "arm"]}, {})
        epv = next(c for c in assumptions_mod.run_checks(["epv"], ctx))
        self.assertEqual("pass", epv["state"])
        rarer = int(df["y"].value_counts().min())
        self.assertIn(f"{rarer} events for 3 predictors", epv["detail"])

    def test_ratio_coefficient_plot_uses_null_of_one_on_log_axis(self):
        import matplotlib.pyplot as plt
        from labdesk import plots_run
        captured = {}
        original = plots_run._save
        plots_run._save = lambda fig, params, name: captured.setdefault("ax", fig.axes[0])
        try:
            plots_run.coef_forest({"ratio_scale": True, "coefficients": [
                {"term": "x", "estimate": 1.8, "ci": [1.2, 2.7]}]}, {"null_line": 0})
        finally:
            plots_run._save = original
        ax = captured["ax"]
        self.assertEqual("log", ax.get_xscale())
        self.assertIn(1.0, [line.get_xdata()[0] for line in ax.get_lines()])
        plt.close("all")

    def test_cox_does_not_advertise_unimplemented_controls(self):
        ids = {p["id"] for p in STAT_REGISTRY["cox"]["params"]}
        self.assertNotIn("ties", ids)          # lifelines implements Efron only
        self.assertNotIn("time_varying", ids)  # needs start/stop data, not built


class CountAndRepeatedMeasuresTests(unittest.TestCase):
    def counts(self, overdispersed=False, n=3000):
        rng = np.random.default_rng(4)
        x = rng.normal(size=n)
        g = rng.integers(0, 2, n)
        pt = rng.uniform(.5, 3, n)
        mu = pt * np.exp(.3 + .5 * x - .4 * g)
        y = rng.negative_binomial(2, 2 / (2 + mu)) if overdispersed else rng.poisson(mu)
        return pd.DataFrame({"y": y, "x": x, "g": g, "pt": pt})

    ROLES = {"dv": ["y"], "predictors": ["x", "g"], "offset": ["pt"]}

    def test_poisson_recovers_known_rate_ratios_with_exposure(self):
        out = models.poisson_reg(self.counts(), self.ROLES, {})
        got = {c["term"]: c["log_irr"] for c in out["coefficients"]}
        self.assertEqual("Poisson regression", out["test"])
        self.assertAlmostEqual(.3, got["(Intercept)"], delta=.06)
        self.assertAlmostEqual(.5, got["x"], delta=.05)
        self.assertAlmostEqual(-.4, got["g_1"], delta=.08)
        self.assertTrue(out["ratio_scale"])

    def test_auto_family_switches_to_negative_binomial_on_overdispersion(self):
        out = models.poisson_reg(self.counts(overdispersed=True), self.ROLES, {})
        self.assertEqual("negbin", out["family"])
        self.assertAlmostEqual(.5, out["alpha"], delta=.1)   # alpha = 1/theta
        forced = models.poisson_reg(self.counts(overdispersed=True), self.ROLES,
                                    {"family": "poisson"})
        self.assertIn("Overdispersion", forced["warning"])

    def test_poisson_rejects_non_counts_and_bad_exposure(self):
        df = self.counts()
        df["y"] = df["y"] + .5
        with self.assertRaisesRegex(ValueError, "whole-number counts"):
            models.poisson_reg(df, self.ROLES, {})
        df = self.counts()
        df["pt"] = np.log(df["pt"])   # a log-exposure column, which is the easy mistake
        with self.assertRaisesRegex(ValueError, "person-time"):
            models.poisson_reg(df, self.ROLES, {})

    def long_frame(self, n=20, seed=4):
        rng = np.random.default_rng(seed)
        y = rng.normal(10, 2, n).repeat(3) + np.tile([0, 1, 2.5], n) + rng.normal(0, 1, n * 3)
        return pd.DataFrame({"y": y, "s": np.repeat(np.arange(n), 3), "t": np.tile(["t0", "t1", "t2"], n)})

    ROLES_RM = {"dv": ["y"], "subject": ["s"], "within": ["t"]}

    def test_rm_anova_matches_sums_of_squares_by_hand(self):
        d = self.long_frame()
        n = 20
        out = basic.anova_rm(d, self.ROLES_RM, {})
        W = d["y"].to_numpy().reshape(n, 3)
        gm = W.mean()
        ss_t = n * ((W.mean(0) - gm) ** 2).sum()
        ss_s = 3 * ((W.mean(1) - gm) ** 2).sum()
        ss_e = ((W - gm) ** 2).sum() - ss_t - ss_s
        self.assertAlmostEqual((ss_t / 2) / (ss_e / 38), out["statistic"], places=8)
        self.assertEqual([2, 38], out["df"])
        self.assertAlmostEqual(ss_t / (ss_t + ss_e), out["effects"]["partial_eta_squared"], places=8)
        self.assertEqual(3, len(out["comparisons"]))

    def test_rm_anova_applies_greenhouse_geisser_when_sphericity_fails(self):
        rng = np.random.default_rng(1)
        n = 40
        z = rng.normal(0, 2, n)
        # Conditions a and b nearly coincide; c adds a lot of noise. The
        # variances of the pairwise differences are then 0.01, 25 and 25.
        W = np.column_stack([z, z + rng.normal(0, .1, n), z + rng.normal(0, 5, n)]) + [0, .5, 1]
        d = pd.DataFrame({"y": W.ravel(), "s": np.repeat(np.arange(n), 3),
                          "t": np.tile(["a", "b", "c"], n)})
        out = basic.anova_rm(d, self.ROLES_RM, {"correction": "auto"})
        self.assertFalse(out["sphericity"]["holds"])
        self.assertEqual("Greenhouse-Geisser", out["correction"])
        self.assertLess(out["df"][0], 2)
        eps = out["epsilon"]["greenhouse_geisser"]
        self.assertAlmostEqual(stats.f.sf(out["statistic"], 2 * eps, 78 * eps), out["p"], places=10)
        self.assertAlmostEqual(2 * eps, out["df"][0], places=10)
        none = basic.anova_rm(d, self.ROLES_RM, {"correction": "none"})
        self.assertEqual([2, 78], none["df"])

    def test_rm_anova_excludes_incomplete_subjects_and_says_so(self):
        d = self.long_frame()
        d = d.drop(d.index[(d["s"] == 3) & (d["t"] == "t1")])
        out = basic.anova_rm(d, self.ROLES_RM, {})
        self.assertEqual(1, out["n_dropped_subjects"])
        self.assertEqual(19, out["n_subjects"])
        self.assertIn("excluded", out["warning"])

    def test_registry_does_not_advertise_unimplemented_count_or_rm_options(self):
        family = next(p for p in STAT_REGISTRY["poisson_reg"]["params"] if p["id"] == "family")
        self.assertEqual({"auto", "poisson", "negbin"},
                         {c[0] if isinstance(c, tuple) else c for c in family["choices"]})
        post = next(p for p in STAT_REGISTRY["anova_rm"]["params"] if p["id"] == "posthoc")
        self.assertNotIn("tukey", post["choices"])


class ReportingScopeTests(TempDatabaseCase):
    def test_methods_are_scoped_to_project_and_use_recorded_alpha(self):
        db.log_run(id="a", project_id="p1", dataset_sha="sha", test_id="ttest_ind",
                   spec={"params": {"alternative": "two-sided"}}, assumptions=[], result={},
                   status="ok", alpha=0.01, seed=7,
                   versions={"python": "3.x", "scipy": "x", "pandas": "x"})
        db.log_run(id="b", project_id="p2", dataset_sha="sha", test_id="mannwhitney",
                   spec={"params": {}}, assumptions=[], result={}, status="ok", alpha=0.2,
                   seed=999, versions={"python": "3.x", "scipy": "x", "pandas": "x"})
        r = reporting.methods_paragraph("sha", project_id="p1")
        self.assertEqual(1, r["n_runs"])
        self.assertIn("0.01", r["text"])
        self.assertNotIn("0.2", r["text"])
        self.assertIn("independent-samples t tests", r["text"])
        self.assertNotIn("Mann", r["text"])


if __name__ == "__main__":
    unittest.main()
