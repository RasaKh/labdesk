"""
Figure rendering.

The heart of this module is `layout_brackets`: significance brackets are
stacked so they never collide or overlap the data.
"""

import math
import os
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .config import FIG_DIR, get
from .plots_registry import JOURNAL_PRESETS
from .stats_run import fmt_p, stars


MM = 1 / 25.4

PALETTE_DEFS = {
    "okabe_ito": ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9",
                  "#D55E00", "#F0E442", "#000000"],
    "viridis": ["#440154", "#414487", "#2a788e", "#22a884", "#7ad151", "#fde725"],
    "grey": ["#222222", "#555555", "#888888", "#aaaaaa", "#cccccc"],
    "hne": ["#7b6ef6", "#f0518a", "#4bbf9a", "#f2b134", "#5aa9f8", "#b06ef6"],
    "nejm": ["#20854E", "#BC3C29", "#0072B5", "#E18727", "#7876B1", "#6F99AD"],
}

THEMES = {
    "publication": {"face": "white", "fg": "#111111", "grid": "#dddddd", "font": 8},
    "minimal": {"face": "white", "fg": "#333333", "grid": "#eeeeee", "font": 8},
    "dark": {"face": "#12141a", "fg": "#e2e6eb", "grid": "#2a2f39", "font": 8},
}

def _preset(name):
    for pid, _label, cfg in JOURNAL_PRESETS:
        if pid == name:
            return cfg
    return {"width_mm": 89, "dpi": 300}

def _figure(params, aspect=0.75, panels=1):
    cfg = _preset(params.get("preset", "single_89"))
    dpi = int(params.get("dpi") or cfg["dpi"])
    w = cfg["width_mm"] * MM
    h = w * aspect
    theme = THEMES.get(params.get("theme", "publication"), THEMES["publication"])
    plt.rcParams.update({
        "font.size": theme["font"],
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "axes.labelsize": theme["font"],
        "axes.titlesize": theme["font"] + 1,
        "xtick.labelsize": theme["font"] - 1,
        "ytick.labelsize": theme["font"] - 1,
        "legend.fontsize": theme["font"] - 1,
        "axes.linewidth": 0.7,
        "xtick.major.width": 0.7,
        "ytick.major.width": 0.7,
        "figure.dpi": dpi,
        "savefig.dpi": dpi,
        "text.color": theme["fg"],
        "axes.labelcolor": theme["fg"],
        "xtick.color": theme["fg"],
        "ytick.color": theme["fg"],
        "axes.edgecolor": theme["fg"],
    })
    fig, ax = plt.subplots(panels, 1, figsize=(w, h * panels), facecolor=theme["face"])
    axes = ax if panels > 1 else [ax]
    for a in axes:
        a.set_facecolor(theme["face"])
        if params.get("despine", True):
            a.spines["top"].set_visible(False)
            a.spines["right"].set_visible(False)
        g = params.get("grid", "y")
        if g in ("y", "both"):
            a.yaxis.grid(True, color=theme["grid"], lw=0.5, zorder=0)
        if g == "both":
            a.xaxis.grid(True, color=theme["grid"], lw=0.5, zorder=0)
        a.set_axisbelow(True)
    return fig, (axes if panels > 1 else axes[0]), theme

def _colours(params, n):
    pal = PALETTE_DEFS.get(params.get("palette", "okabe_ito"), PALETTE_DEFS["okabe_ito"])
    return [pal[i % len(pal)] for i in range(n)]

def _save(fig, params, name):
    fmt = params.get("format", "png")
    fname = f"{name}_{int(time.time()*1000)}.{fmt}"
    path = os.path.join(FIG_DIR, fname)
    fig.savefig(path, format=fmt, bbox_inches="tight",
                facecolor=fig.get_facecolor(), transparent=False)
    plt.close(fig)
    return path

# ─────────────────────────────────────────────────────────────────────────
#  Significance bracket layout
# ─────────────────────────────────────────────────────────────────────────

def layout_brackets(comparisons, positions, heights, only_significant=True,
                    alpha=None):
    """Assign a non-overlapping stacking level to every comparison.

    comparisons: [{"a": label, "b": label, "p": float}]
    positions:   {label: x coordinate}
    heights:     {label: top of that group's drawn element}

    Returns [{"x1","x2","level","p","label_text"}] sorted for drawing.

    Levels are assigned greedily from the widest span down. A bracket may
    share a level with another only if their horizontal extents do not
    intersect, and it must clear the tallest bar underneath it.
    """
    alpha = alpha if alpha is not None else get("alpha", 0.05)
    items = []
    for c in comparisons or []:
        p = c.get("p", c.get("p_raw"))
        if p is None:
            continue
        if only_significant and p >= alpha:
            continue
        if c["a"] not in positions or c["b"] not in positions:
            continue
        x1, x2 = sorted((positions[c["a"]], positions[c["b"]]))
        items.append({"x1": x1, "x2": x2, "p": p, "span": x2 - x1,
                      "a": c["a"], "b": c["b"]})
    # Narrow spans first so adjacent pairs sit low and wide pairs bridge above.
    items.sort(key=lambda d: (d["span"], d["x1"]))

    occupied = []   # per level: list of (x1, x2)
    for it in items:
        level = 0
        while True:
            if level >= len(occupied):
                occupied.append([])
            # Strict overlap only. Two adjacent comparisons that merely share an
            # endpoint (A-B and B-C) belong on the same level, which is how these
            # are drawn in practice; only a bracket that spans another gets lifted.
            clash = any(it["x1"] < e - 0.02 and it["x2"] > s + 0.02
                        for s, e in occupied[level])
            if not clash:
                occupied[level].append((it["x1"], it["x2"]))
                it["level"] = level
                break
            level += 1
    # A bracket must also clear whatever is drawn under its span.
    for it in items:
        under = [h for lab, h in heights.items()
                 if it["x1"] - 0.01 <= positions[lab] <= it["x2"] + 0.01]
        it["floor"] = max(under) if under else 0
    return items

def draw_brackets(ax, items, params, ymax_data):
    if not items:
        return ymax_data
    mode = params.get("annotate", "stars")
    if mode == "none":
        return ymax_data
    rng = max(1e-9, ymax_data - min(0, ax.get_ylim()[0]))
    gap = float(params.get("bracket_gap", 0.06)) * rng
    tick = float(params.get("bracket_tick", 0.02)) * rng
    size = float(params.get("star_size", 10))
    top = ymax_data
    for it in items:
        y = max(it["floor"], ymax_data) + gap * (it["level"] + 1)
        ax.plot([it["x1"], it["x1"], it["x2"], it["x2"]],
                [y, y + tick, y + tick, y], lw=0.8, c=plt.rcParams["text.color"],
                solid_capstyle="butt", clip_on=False, zorder=5)
        if mode == "stars":
            txt = stars(it["p"])
        elif mode == "p":
            txt = fmt_p(it["p"]).replace("p = ", "P = ").replace("p ", "P ")
        else:
            txt = f"{stars(it['p'])} {fmt_p(it['p'])}"
        va = "bottom"
        ax.text((it["x1"] + it["x2"]) / 2, y + tick * 1.2, txt,
                ha="center", va=va, fontsize=size * 0.8, clip_on=False, zorder=6)
        top = max(top, y + tick * 3)
    ax.set_ylim(ax.get_ylim()[0], top * 1.05)
    return top

# ─────────────────────────────────────────────────────────────────────────
#  Renderers
# ─────────────────────────────────────────────────────────────────────────

def _series(result):
    """Pull group labels, centres and error from any comparison-like result."""
    labels = [str(x) for x in (result.get("levels") or [])]
    if result.get("mean"):
        centre = list(result["mean"])
        kind = "mean"
    elif result.get("median"):
        centre = list(result["median"])
        kind = "median"
    elif result.get("mean_fold_change"):
        centre = list(result["mean_fold_change"])
        kind = "mean"
    else:
        centre = []
        kind = "mean"
    return labels, centre, kind

def _err(result, params, n_groups):
    mode = params.get("error", get("error_bar_default", "ci95"))
    if mode == "none":
        return None, ""
    sd = result.get("sd") or []
    sem = result.get("sem") or []
    n = result.get("n") or []
    if mode == "sd" and sd:
        return list(sd), "SD"
    if not sem and sd and n:
        sem = [s / math.sqrt(max(1, k)) for s, k in zip(sd, n)]
    if mode == "sem" and sem:
        return list(sem), "SEM"
    if mode == "ci95" and sem:
        from scipy import stats as st
        return [s * st.t.ppf(0.975, max(1, k - 1)) for s, k in zip(sem, n or [30] * len(sem))], \
               "95% CI"
    if sem:
        return list(sem), "SEM"
    return None, ""

def bar_sig(result, params, data=None):
    labels, centre, ckind = _series(result)
    if not labels:
        raise ValueError("This result has no group summaries to plot.")
    err, err_label = _err(result, params, len(labels))
    fig, ax, theme = _figure(params)
    x = np.arange(len(labels))
    colours = _colours(params, len(labels))
    w = float(params.get("bar_width", 0.6))
    base = float(params.get("baseline", 0) or 0)
    ax.bar(x, centre, width=w, color=colours, edgecolor="none", zorder=2, bottom=base)
    if err:
        ax.errorbar(x, np.array(centre) + base, yerr=err, fmt="none",
                    ecolor=theme["fg"], elinewidth=0.8, capsize=2.5, zorder=3)
    heights = {}
    tops = []
    for i, lab in enumerate(labels):
        h = centre[i] + (err[i] if err else 0)
        heights[lab] = h
        tops.append(h)
    if params.get("points", "jitter") != "none" and data is not None:
        rng = np.random.default_rng(get("seed", 0))
        for i, lab in enumerate(labels):
            vals = data.get(lab, [])
            if not len(vals):
                continue
            jit = rng.uniform(-w * 0.28, w * 0.28, len(vals))
            ax.scatter(x[i] + jit, vals, s=5, c="none",
                       edgecolors=theme["fg"], linewidths=0.5, zorder=4, alpha=0.75)
            heights[lab] = max(heights[lab], float(np.max(vals)))
            tops.append(float(np.max(vals)))
    if params.get("log_y"):
        ax.set_yscale("log")
    if params.get("hline") not in (None, ""):
        ax.axhline(float(params["hline"]), lw=0.7, ls="--", c=theme["fg"], alpha=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel(params.get("ylabel") or result.get("dv") or
                  ("Fold change" if result.get("kind") == "qpcr" else "Value"))
    if params.get("xlabel"):
        ax.set_xlabel(params["xlabel"])
    if params.get("title"):
        ax.set_title(params["title"])
    items = layout_brackets(result.get("comparisons"),
                            {l: i for i, l in enumerate(labels)}, heights,
                            params.get("only_significant", True))
    draw_brackets(ax, items, params, max(tops) if tops else 1)
    if err_label:
        ax.text(1.0, -0.16, f"Error bars: {err_label}", transform=ax.transAxes,
                ha="right", va="top", fontsize=plt.rcParams["font.size"] - 2,
                color=theme["fg"], alpha=0.75)
    return _save(fig, params, "bar_sig")

def box(result, params, data=None):
    labels, centre, _ = _series(result)
    fig, ax, theme = _figure(params)
    arrays = [np.asarray(data.get(l, [])) for l in labels] if data else []
    if not any(len(a) for a in arrays):
        raise ValueError("Box plots need the raw values; re-run the test with the "
                         "dataset attached.")
    whisk = {"1.5iqr": 1.5, "minmax": 0, "p5p95": (5, 95)}.get(
        params.get("whisker", "1.5iqr"), 1.5)
    bp = ax.boxplot(arrays, positions=np.arange(len(labels)), widths=0.55,
                    patch_artist=True, notch=bool(params.get("notch")),
                    whis=whisk if whisk else (0, 100),
                    medianprops=dict(color=theme["fg"], lw=1.1),
                    flierprops=dict(marker="o", ms=2, mfc="none",
                                    mec=theme["fg"], alpha=0.6))
    for patch, c in zip(bp["boxes"], _colours(params, len(labels))):
        patch.set_facecolor(c)
        patch.set_alpha(0.55)
        patch.set_edgecolor(theme["fg"])
        patch.set_linewidth(0.7)
    heights = {}
    if params.get("points", "jitter") != "none":
        rng = np.random.default_rng(get("seed", 0))
        for i, (l, a) in enumerate(zip(labels, arrays)):
            if not len(a):
                continue
            ax.scatter(i + rng.uniform(-0.15, 0.15, len(a)), a, s=5, c="none",
                       edgecolors=theme["fg"], linewidths=0.45, alpha=0.7, zorder=4)
    for i, (l, a) in enumerate(zip(labels, arrays)):
        heights[l] = float(np.max(a)) if len(a) else 0
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel(params.get("ylabel") or result.get("dv") or "Value")
    if params.get("title"):
        ax.set_title(params["title"])
    items = layout_brackets(result.get("comparisons"),
                            {l: i for i, l in enumerate(labels)}, heights,
                            params.get("only_significant", True))
    draw_brackets(ax, items, params, max(heights.values()) if heights else 1)
    return _save(fig, params, "box")

def raincloud(result, params, data=None):
    labels, _, _ = _series(result)
    arrays = [np.asarray(data.get(l, [])) for l in labels] if data else []
    if not any(len(a) for a in arrays):
        raise ValueError("Raincloud plots need the raw values.")
    fig, ax, theme = _figure(params, aspect=0.8)
    cols = _colours(params, len(labels))
    rng = np.random.default_rng(get("seed", 0))
    heights = {}
    for i, (lab, a) in enumerate(zip(labels, arrays)):
        if not len(a):
            continue
        v = ax.violinplot([a], positions=[i], widths=0.8, showextrema=False)
        for b in v["bodies"]:
            verts = b.get_paths()[0].vertices
            verts[:, 0] = np.clip(verts[:, 0], i, np.inf)
            b.set_facecolor(cols[i]); b.set_alpha(0.45); b.set_edgecolor("none")
        ax.boxplot([a], positions=[i - 0.12], widths=0.1, patch_artist=True,
                   showfliers=False,
                   boxprops=dict(facecolor="white", edgecolor=theme["fg"], lw=0.6),
                   medianprops=dict(color=theme["fg"], lw=1.0),
                   whiskerprops=dict(color=theme["fg"], lw=0.6),
                   capprops=dict(color=theme["fg"], lw=0.6))
        ax.scatter(i - 0.28 + rng.uniform(-0.06, 0.06, len(a)), a, s=4, c=cols[i],
                   alpha=0.7, edgecolors="none", zorder=4)
        heights[lab] = float(np.max(a))
    ax.set_xticks(np.arange(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_ylabel(params.get("ylabel") or result.get("dv") or "Value")
    items = layout_brackets(result.get("comparisons"),
                            {l: i for i, l in enumerate(labels)}, heights,
                            params.get("only_significant", True))
    draw_brackets(ax, items, params, max(heights.values()) if heights else 1)
    return _save(fig, params, "raincloud")

def means_ci(result, params, data=None):
    labels, centre, _ = _series(result)
    err, err_label = _err(result, params, len(labels))
    fig, ax, theme = _figure(params)
    x = np.arange(len(labels))
    ax.errorbar(x, centre, yerr=err, fmt="o", ms=4, capsize=3, lw=0.9,
                color=_colours(params, 1)[0], ecolor=theme["fg"])
    if params.get("connect"):
        ax.plot(x, centre, lw=0.8, color=_colours(params, 1)[0], alpha=0.6)
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_xlim(-0.5, len(labels) - 0.5)
    ax.set_ylabel(params.get("ylabel") or result.get("dv") or "Value")
    ax.text(1.0, -0.16, f"Error bars: {err_label}", transform=ax.transAxes,
            ha="right", va="top", fontsize=plt.rcParams["font.size"] - 2, alpha=0.75)
    return _save(fig, params, "means_ci")
