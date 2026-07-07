"""
Data workbench.

Datasets live on disk under the config directory and are cached in memory by
sha256. The variable dictionary is inferred once on import and then edited by
hand, because guessing that a 0/1 column is continuous is the single most
common way an analysis silently goes wrong.
"""

import hashlib
import csv
import io
import json
import os
import re
import time
from collections import OrderedDict

import numpy as np
import pandas as pd

from . import db
from .config import DATA_DIR, get

_cache = OrderedDict()
_CACHE_MAX = 8


# Conservative defaults. Symbols such as '-' and '?' can be real categorical
# values and therefore require an explicit import rule rather than disappearing.
MISSING_TOKENS = ["", "NA", "N/A", "n/a", "NULL", "null", "#N/A", "NaN"]
ID_HINTS = re.compile(r"(^|_)(id|uid|mrn|nhs|patient|subject|record|case)(_|$)", re.I)
TIME_HINTS = re.compile(r"(date|time|dob|birth|visit|onset|followup|follow_up)", re.I)
EVENT_HINTS = re.compile(r"(event|status|death|died|censor|outcome_event|relapse)", re.I)


def _check_delimited_header(path, delimiter=None):
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(65536)
    if not sample:
        return [], delimiter or ","
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",\t;|").delimiter
        except csv.Error:
            delimiter = ","
    header = next(csv.reader([sample.splitlines()[0]], delimiter=delimiter), [])
    trimmed = [str(c).strip() for c in header]
    duplicates = sorted({c for c in trimmed if trimmed.count(c) > 1})
    if duplicates:
        raise ValueError("Column names collide after trimming whitespace: " +
                         ", ".join(duplicates) + ". Rename them before import.")
    return trimmed, delimiter


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_of_frame(df):
    """Hash both values and the schema that gives those values meaning."""
    h = hashlib.sha256()
    meta = {
        "columns": [str(c) for c in df.columns],
        "dtypes": [str(t) for t in df.dtypes],
        "index_name": None if df.index.name is None else str(df.index.name),
    }
    h.update(json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    h.update(pd.util.hash_pandas_object(df, index=True).values.tobytes())
    return h.hexdigest()


def sha256_of_dictionary(dic):
    payload = json.dumps(dic or {}, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_put(ds_id, df):
    _cache[ds_id] = df
    _cache.move_to_end(ds_id)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


# ─────────────────────────────────────────────────────────────────────────
#  Import
# ─────────────────────────────────────────────────────────────────────────

READERS = {
    ".csv":  lambda p, **k: pd.read_csv(p, na_values=MISSING_TOKENS, keep_default_na=True, **k),
    ".tsv":  lambda p, **k: pd.read_csv(p, sep="\t", na_values=MISSING_TOKENS, **k),
    ".txt":  lambda p, **k: pd.read_csv(p, sep=None, engine="python", na_values=MISSING_TOKENS, **k),
    ".xlsx": lambda p, **k: pd.read_excel(p, na_values=MISSING_TOKENS, **k),
    ".xls":  lambda p, **k: pd.read_excel(p, na_values=MISSING_TOKENS, **k),
    ".json": lambda p, **k: pd.read_json(p, **k),
    ".parquet": lambda p, **k: pd.read_parquet(p, **k),
}


def read_any(path, **kw):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".sav", ".dta", ".por"):
        import pyreadstat  # optional
        if ext == ".sav":
            df, _ = pyreadstat.read_sav(path)
        elif ext == ".dta":
            df, _ = pyreadstat.read_dta(path)
        else:
            df, _ = pyreadstat.read_por(path)
        return df
    if ext in (".csv", ".tsv", ".txt"):
        header, delimiter = _check_delimited_header(path, "\t" if ext == ".tsv" else None)
        # Identifier-looking columns remain strings so leading zeros survive.
        # A user can change the semantic kind later without recovering lost bytes.
        dtype = {name: "string" for name in header if ID_HINTS.search(name)}
        options = {"sep": delimiter, "na_values": MISSING_TOKENS,
                   "keep_default_na": True, "dtype": dtype}
        options.update(kw)
        return pd.read_csv(path, **options)
    reader = READERS.get(ext)
    if not reader:
        raise ValueError(
            f"No reader for {ext or 'a file with no extension'}. "
            "Supported: csv, tsv, txt, xlsx, xls, json, parquet, sav, dta."
        )
    return reader(path, **kw)


def import_file(path, name=None, notes="", project_id=None, source=None):
    df = read_any(path)
    df.columns = [str(c).strip() for c in df.columns]
    dup = df.columns[df.columns.duplicated()].unique().tolist()
    if dup:
        raise ValueError(
            "Column names collide after trimming whitespace: " + ", ".join(map(str, dup)) +
            ". Rename them in the source file before import."
        )
    ds_id = db.new_id("ds_")
    store = os.path.join(DATA_DIR, ds_id + ".parquet")
    try:
        df.to_parquet(store)
    except Exception:
        store = os.path.join(DATA_DIR, ds_id + ".csv")
        df.to_csv(store, index=False)
    sha = sha256_of_frame(df)
    dic = infer_dictionary(df)
    dic_sha = sha256_of_dictionary(dic)
    db.insert("dataset", {
        "id": ds_id, "project_id": project_id,
        "name": name or os.path.basename(path), "path": store,
        "source": source or path, "sha256": sha, "n_rows": len(df), "n_cols": df.shape[1],
        "dictionary": json.dumps(dic), "dictionary_sha": dic_sha,
        "created_at": time.time(), "notes": notes,
    })
    _cache_put(ds_id, df)
    # Project-owned imports immediately gain an immutable baseline version.
    # Legacy/unfiled imports remain readable and are versioned when adopted.
    if project_id:
        from . import revisions
        revisions.ensure_baseline(ds_id)
    return ds_id


def load(ds_id):
    if ds_id in _cache:
        df = _cache[ds_id]
        _cache.move_to_end(ds_id)
        return df
    row = db.one("SELECT * FROM dataset WHERE id=?", (ds_id,))
    if not row:
        raise KeyError(f"No dataset {ds_id}. It may have been removed.")
    df = read_any(row["path"])
    _cache_put(ds_id, df)
    return df


def meta(ds_id):
    row = db.one("SELECT * FROM dataset WHERE id=?", (ds_id,))
    if not row:
        return None
    row["dictionary"] = json.loads(row["dictionary"] or "{}")
    if not row.get("dictionary_sha"):
        row["dictionary_sha"] = sha256_of_dictionary(row["dictionary"])
        db.exec_("UPDATE dataset SET dictionary_sha=? WHERE id=?",
                 (row["dictionary_sha"], ds_id))
    return row


def list_datasets(project_id=None):
    """Scoped to a project. Passing None returns the unfiled ones, which is
    what an existing database looks like before anything is assigned."""
    rows = db.query("SELECT id,name,n_rows,n_cols,sha256,created_at,project_id "
                    "FROM dataset WHERE project_id IS ? ORDER BY created_at DESC",
                    (project_id,))
    for r in rows:
        r["runs"] = db.runs_on_dataset(r["sha256"], project_id)
    return rows


# ─────────────────────────────────────────────────────────────────────────
#  Variable dictionary
# ─────────────────────────────────────────────────────────────────────────

def infer_kind(name, s):
    n = s.dropna()
    if not len(n):
        return "unknown"
    if n.nunique() == 1:
        return "constant"
    if ID_HINTS.search(name) and n.nunique() > 0.9 * max(1, len(n)):
        return "id"
    if pd.api.types.is_datetime64_any_dtype(s) or TIME_HINTS.search(name):
        try:
            pd.to_datetime(n.head(50), errors="raise")
            return "time"
        except Exception:
            pass
    nun = n.nunique()
    if pd.api.types.is_numeric_dtype(s):
        vals = set(pd.unique(n))
        if nun == 2 and vals <= {0, 1, 0.0, 1.0, True, False}:
            return "binary"
        if nun <= 2:
            return "binary"
        # Small integer sets are usually coded factors, not measurements.
        try:
            all_int = bool(n.apply(lambda v: float(v).is_integer()).all())
        except (TypeError, ValueError):
            all_int = False
        if nun <= 10 and all_int:
            return "ordinal"
        return "continuous"
    if nun == 2:
        return "binary"
    if nun <= 20:
        return "categorical"
    return "text"


def infer_dictionary(df):
    dic = {}
    for c in df.columns:
        s = df[c]
        kind = infer_kind(c, s)
        entry = {
            "column_id": "col_" + hashlib.sha256(str(c).encode("utf-8")).hexdigest()[:12],
            "label": c,
            "kind": kind,
            "unit": "",
            "dtype": str(s.dtype),
            "n_missing": int(s.isna().sum()),
            "pct_missing": round(100 * float(s.isna().mean()), 2),
            "n_unique": int(s.nunique(dropna=True)),
            "role": "",
            "notes": "",
            "reviewed": False,
            "positive_level": "",
            "reference_level": "",
            "event_level": "",
        }
        if kind in ("categorical", "binary", "ordinal"):
            vc = s.value_counts(dropna=True).head(30)
            entry["levels"] = [[str(k), int(v)] for k, v in vc.items()]
        if kind == "continuous" and pd.api.types.is_numeric_dtype(s):
            n = s.dropna()
            if len(n):
                entry["summary"] = {
                    "mean": float(n.mean()), "sd": float(n.std(ddof=1)) if len(n) > 1 else None,
                    "min": float(n.min()), "q1": float(n.quantile(.25)),
                    "median": float(n.median()), "q3": float(n.quantile(.75)),
                    "max": float(n.max()),
                }
        dic[c] = entry
    return dic


def set_dictionary(ds_id, dic):
    row = db.one("SELECT project_id,current_version_id FROM dataset WHERE id=?", (ds_id,))
    if row and row.get("project_id") and row.get("current_version_id"):
        from . import revisions
        return revisions.create_dictionary(row["project_id"], ds_id, dic)["payload"]
    db.exec_("UPDATE dataset SET dictionary=?, dictionary_sha=? WHERE id=?",
             (json.dumps(dic), sha256_of_dictionary(dic), ds_id))
    return dic


def columns_of_kind(ds_id, kinds):
    m = meta(ds_id)
    if not m:
        return []
    if isinstance(kinds, str):
        kinds = [kinds]
    if "any" in kinds:
        return list(m["dictionary"].keys())
    return [c for c, d in m["dictionary"].items() if d.get("kind") in kinds]


# ─────────────────────────────────────────────────────────────────────────
#  Missingness
# ─────────────────────────────────────────────────────────────────────────

def missingness(ds_id):
    df = load(ds_id)
    per_col = [{"column": c,
                "n_missing": int(df[c].isna().sum()),
                "pct": round(100 * float(df[c].isna().mean()), 2)}
               for c in df.columns]
    rows_complete = int(df.notna().all(axis=1).sum())
    # Pattern table: the distinct presence/absence patterns and their counts.
    pat = df.notna().astype(int).astype(str).agg("".join, axis=1).value_counts().head(15)
    return {
        "per_column": sorted(per_col, key=lambda r: -r["pct"]),
        "rows_total": len(df),
        "rows_complete": rows_complete,
        "pct_complete_case": round(100 * rows_complete / max(1, len(df)), 2),
        "patterns": [{"pattern": k, "n": int(v)} for k, v in pat.items()],
        "columns": list(df.columns),
    }


# ─────────────────────────────────────────────────────────────────────────
#  Pure transform primitives. Callers that persist a transformed dataset must
#  also persist the corresponding dataset_op; this function itself never
#  mutates a stored dataset or claims an audit entry was written.
# ─────────────────────────────────────────────────────────────────────────

TRANSFORMS = ["log", "log10", "log1p", "sqrt", "zscore", "rank", "inverse",
              "boxcox", "yeojohnson", "winsorize", "center", "minmax"]


def apply_transform(df, col, how, params=None):
    params = params or {}
    s = pd.to_numeric(df[col], errors="coerce")
    if how == "log":
        return np.log(s.where(s > 0))
    if how == "log10":
        return np.log10(s.where(s > 0))
    if how == "log1p":
        return np.log1p(s.where(s > -1))
    if how == "sqrt":
        return np.sqrt(s.where(s >= 0))
    if how == "zscore":
        if not np.isfinite(s.std(ddof=1)) or s.std(ddof=1) == 0:
            raise ValueError("Z-score needs a variable with non-zero variation.")
        return (s - s.mean()) / s.std(ddof=1)
    if how == "center":
        return s - s.mean()
    if how == "rank":
        return s.rank()
    if how == "inverse":
        return 1.0 / s.where(s != 0)
    if how == "minmax":
        if s.max() == s.min():
            raise ValueError("Min-max scaling needs a variable with non-zero range.")
        return (s - s.min()) / (s.max() - s.min())
    if how == "winsorize":
        lo = params.get("lower", 0.05)
        hi = params.get("upper", 0.95)
        return s.clip(s.quantile(lo), s.quantile(hi))
    if how in ("boxcox", "yeojohnson"):
        from scipy import stats
        clean = s.dropna()
        if how == "boxcox":
            if (clean <= 0).any():
                raise ValueError("Box-Cox needs strictly positive values. Use Yeo-Johnson.")
            vals, _lam = stats.boxcox(clean)
        else:
            vals, _lam = stats.yeojohnson(clean)
        out = pd.Series(np.nan, index=s.index)
        out.loc[clean.index] = vals
        return out
    raise ValueError(f"Unknown transform {how}.")


OUTLIER_METHODS = ["iqr", "zscore", "modified_zscore", "grubbs", "mahalanobis"]


def find_outliers(df, cols, method="iqr", threshold=None):
    idx = pd.Index([])
    if method == "mahalanobis":
        sub = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
        if sub.shape[1] < 2 or len(sub) <= sub.shape[1]:
            return []
        cov = np.cov(sub.values, rowvar=False)
        inv = np.linalg.pinv(cov)
        mu = sub.values.mean(axis=0)
        d = np.einsum("ij,jk,ik->i", sub.values - mu, inv, sub.values - mu)
        from scipy import stats
        crit = stats.chi2.ppf(threshold or 0.999, df=sub.shape[1])
        return sub.index[d > crit].tolist()
    for c in cols:
        s = pd.to_numeric(df[c], errors="coerce")
        if method == "iqr":
            k = threshold or 1.5
            q1, q3 = s.quantile(.25), s.quantile(.75)
            iqr = q3 - q1
            hit = s[(s < q1 - k * iqr) | (s > q3 + k * iqr)].index
        elif method == "zscore":
            k = threshold or 3.0
            z = (s - s.mean()) / s.std(ddof=1)
            hit = s[z.abs() > k].index
        elif method == "modified_zscore":
            k = threshold or 3.5
            med = s.median()
            mad = (s - med).abs().median()
            mz = 0.6745 * (s - med) / (mad if mad else np.nan)
            hit = s[mz.abs() > k].index
        elif method == "grubbs":
            from scipy import stats
            n = s.dropna()
            if len(n) < 3:
                hit = pd.Index([])
            else:
                z = (n - n.mean()).abs() / n.std(ddof=1)
                g = z.max()
                a = threshold or 0.05
                t = stats.t.ppf(1 - a / (2 * len(n)), len(n) - 2)
                crit = (len(n) - 1) / np.sqrt(len(n)) * np.sqrt(t**2 / (len(n) - 2 + t**2))
                hit = pd.Index([z.idxmax()]) if g > crit else pd.Index([])
        else:
            hit = pd.Index([])
        idx = idx.union(hit)
    return idx.tolist()


# ─────────────────────────────────────────────────────────────────────────
#  De-identification check
#
#  Not a substitute for a DPO, and it says so. It catches the obvious
#  things before a dataset gets copied somewhere it should not be.
# ─────────────────────────────────────────────────────────────────────────

HIPAA_PATTERNS = [
    ("Name", r"(^|_)(name|surname|firstname|lastname|fullname)(_|$)"),
    ("Geography finer than state", r"(^|_)(address|street|postcode|zip|postal|city|town)(_|$)"),
    ("Dates", r"(^|_)(dob|birth|admission|discharge|death|date)(_|$)"),
    ("Telephone", r"(^|_)(phone|tel|mobile|fax)(_|$)"),
    ("Email", r"(^|_)(email|e_mail)(_|$)"),
    ("Identifiers", r"(^|_)(ssn|nhs|mrn|insurance|policy|licence|license|passport)(_|$)"),
    ("Device or account", r"(^|_)(device|serial|account|ip|url|biometric)(_|$)"),
]


def deident_check(ds_id, quasi_identifiers=None):
    df = load(ds_id)
    flags = []
    for label, pat in HIPAA_PATTERNS:
        rx = re.compile(pat, re.I)
        hits = [c for c in df.columns if rx.search(c)]
        if hits:
            flags.append({"category": label, "columns": hits})
    out = {"flags": flags, "n_rows": len(df)}
    qi = quasi_identifiers or []
    if qi:
        sizes = df.groupby(qi, dropna=False).size()
        out["k_anonymity"] = int(sizes.min()) if len(sizes) else 0
        out["unique_rows"] = int((sizes == 1).sum())
        out["quasi_identifiers"] = qi
    out["disclaimer"] = ("Pattern matching on column names and a k-anonymity count. "
                         "It does not read cell contents and it is not a legal review.")
    return out
