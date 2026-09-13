"""Reference-value checks for the claims made in README.md "Validation".

These run the real implementations against values that come from theory,
published tables or a simulation with a known truth, so that a regression in
the arithmetic cannot hide behind tests that only check the plumbing.
"""
import unittest

import numpy as np
import pandas as pd

from labdesk import db, screening
from labdesk.runners import bench, meta, power
from test_hardening import TempDatabaseCase


def solve(fn, **params):
    params.setdefault("dropout", 0)
    return fn(None, {}, params, None)


class PowerReferenceValues(unittest.TestCase):
    def test_two_means_d_half_gives_64_per_group(self):
        r = solve(power.power_ttest, solve_for="n", effect=.5, power=.8, alpha=.05)
        self.assertEqual(64, r["n_per_group"])

    def test_two_proportions_30_vs_45_gives_163_per_group(self):
        r = solve(power.power_prop, solve_for="n", p1=.3, p2=.45, power=.8, alpha=.05)
        self.assertEqual(163, r["n_per_group"])

    def test_four_group_anova_f_quarter_gives_45_per_group(self):
        r = solve(power.power_anova, solve_for="n", k=4, effect=.25, power=.8, alpha=.05)
        self.assertEqual(45, r["n_per_group"])

    def test_correlation_r_quarter_gives_124(self):
        r = solve(power.power_corr, solve_for="n", r=.25, power=.8, alpha=.05)
        self.assertEqual(124, r["n_total"])


class BetweenStudyVariance(unittest.TestCase):
    """Mean estimate over simulated meta-analyses with a known tau^2."""

    def mean_tau2(self, method, true_tau2, sims=400, k=15):
        rng = np.random.default_rng(11)
        out = []
        for _ in range(sims):
            vi = rng.uniform(.02, .1, k)
            yi = rng.normal(.3, np.sqrt(vi + true_tau2))
            out.append(meta._tau2(yi, vi, method))
        return float(np.mean(out))

    def test_dl_reml_and_pm_recover_known_tau2(self):
        for method in ("DL", "REML", "PM"):
            for truth in (0.0, 0.05, 0.20):
                self.assertAlmostEqual(truth, self.mean_tau2(method, truth), delta=0.02,
                                       msg=f"{method} at tau2={truth}")

    def test_sidik_jonkman_is_not_off_by_a_scale_factor(self):
        # Regression: SJ omitted the initial-variance scale and returned ~0.46
        # when the truth was 0. It is known to run a little high at small tau^2.
        self.assertLess(self.mean_tau2("SJ", 0.0), 0.06)
        self.assertAlmostEqual(0.20, self.mean_tau2("SJ", 0.20), delta=0.04)


class ElisaFit(unittest.TestCase):
    def test_four_parameter_fit_recovers_generating_ec50(self):
        rng = np.random.default_rng(5)
        a, b, c, d = 0.05, 1.2, 50.0, 2.4
        conc = np.repeat([1, 3, 10, 30, 100, 300, 1000, 3000.], 2)
        od = (d + (a - d) / (1 + (conc / c) ** b)) * (1 + rng.normal(0, .01, len(conc)))
        df = pd.concat([
            pd.DataFrame({"od": od, "conc": conc, "type": "standard"}),
            pd.DataFrame({"od": [0.8, 1.5], "conc": [np.nan] * 2, "type": "sample"}),
        ])
        out = bench.elisa(df, {"od": ["od"], "conc": ["conc"], "sample_type": ["type"]},
                          {"model": "4pl"})
        self.assertAlmostEqual(c, out["parameters"]["c_ec50"], delta=0.03 * c)


class ScreeningAgreement(TempDatabaseCase):
    def test_cohens_kappa_matches_hand_calculation(self):
        # 20 both-include, 70 both-exclude, 5 + 5 disagreements:
        # observed 0.90, chance 0.25*0.25 + 0.75*0.75 = 0.625, kappa = 0.7333.
        self.project("p1")
        r1 = screening.add_reviewer("Reviewer One")["id"]
        r2 = screening.add_reviewer("Reviewer Two")["id"]
        plan = [("include", "include")] * 20 + [("exclude", "exclude")] * 70 \
            + [("include", "exclude")] * 5 + [("exclude", "include")] * 5
        for i, (d1, d2) in enumerate(plan):
            rid = f"rec{i}"
            db.insert("record", {"id": rid, "project_id": "p1", "source": "pubmed",
                                 "source_uid": rid, "title": rid, "year": 2024})
            screening.decide(rid, d1, reviewer=r1)
            screening.decide(rid, d2, reviewer=r2)
        out = screening.agreement("p1", a=r1, b=r2)
        self.assertEqual(100, out["n_overlap"])
        self.assertEqual(90.0, out["percent_agreement"])
        self.assertAlmostEqual(0.733, out["kappa"], places=3)
        self.assertEqual(10, len(out["conflicts"]))


if __name__ == "__main__":
    unittest.main()
