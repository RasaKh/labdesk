"""Data workbench: stable identifiers through content hashing.

Before any import logic exists, datasets need identity you can trust. The sha256
of the raw file is the loading identity; the dictionary hash pins the variable
semantics; the in-memory frame is a bounded LRU keyed by that id.
"""

import csv
import hashlib
import json
import re
from collections import OrderedDict

import pandas as pd

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