"""Quick analytics for an uploaded file: per-column statistics and plain-language findings (standard library only)."""

from __future__ import annotations

import math
import re
import statistics as st
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .extract import Extracted, extract

MISSING = {"", "na", "n/a", "nan", "null", "none", "-", "--", "?"}
DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")
MAX_ROWS_PROFILE = 200_000


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v) if math.isfinite(v) else None
    s = str(v).strip().replace(",", "").replace("₹", "").replace("$", "").replace("€", "").replace("£", "")
    if s.endswith("%"):
        s = s[:-1]
    if not re.fullmatch(r"[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", s):
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def _date(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    if len(s) < 6 or not re.search(r"\d", s) or not re.search(r"[-/ ,]", s):
        return None
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(s, f)
        except ValueError:
            continue
    return None


def _fmt(x: float) -> float | int:
    if x == int(x) and abs(x) < 1e15:
        return int(x)
    return round(x, 4) if abs(x) < 1 else round(x, 2)


def _pct(vals: list[float], p: float) -> float:
    k = (len(vals) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def histogram(vals: list[float], bins: int = 10) -> list[dict[str, Any]]:
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return [{"from": _fmt(lo), "to": _fmt(hi), "count": len(vals)}]
    bins = max(3, min(bins, int(math.sqrt(len(vals))) + 1, 12))
    w = (hi - lo) / bins
    counts = [0] * bins
    for v in vals:
        counts[min(bins - 1, int((v - lo) / w))] += 1
    return [{"from": _fmt(lo + i * w), "to": _fmt(lo + (i + 1) * w), "count": c} for i, c in enumerate(counts)]


def profile_column(name: str, raw: list[Any]) -> dict[str, Any]:
    total = len(raw)
    vals = [v for v in raw if str(v).strip().lower() not in MISSING]
    missing = total - len(vals)
    out: dict[str, Any] = {"name": name, "count": total, "missing": missing, "missing_pct": round(100 * missing / total, 1) if total else 0}
    if not vals:
        out["type"] = "empty"
        return out
    nums = [_num(v) for v in vals]
    n_ok = [x for x in nums if x is not None]
    if len(n_ok) / len(vals) >= 0.9:
        out["type"] = "number"
        s = sorted(n_ok)
        mean = st.fmean(s)
        sd = st.pstdev(s) if len(s) > 1 else 0.0
        q1, med, q3 = _pct(s, 0.25), _pct(s, 0.5), _pct(s, 0.75)
        iqr = q3 - q1
        lo_f, hi_f = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        outliers = [x for x in s if iqr > 0 and (x < lo_f or x > hi_f)]
        out.update(min=_fmt(s[0]), max=_fmt(s[-1]), mean=_fmt(mean), median=_fmt(med), std=_fmt(sd), q1=_fmt(q1), q3=_fmt(q3), sum=_fmt(sum(s)),
                   outliers=len(outliers), outlier_examples=[_fmt(x) for x in (outliers[:3] + outliers[-3:] if len(outliers) > 6 else outliers)],
                   histogram=histogram(s), unique=len(set(s)), zeros=sum(1 for x in s if x == 0), negatives=sum(1 for x in s if x < 0),
                   skew=_fmt(sum(((x - mean) / sd) ** 3 for x in s) / len(s)) if sd > 0 and len(s) > 2 else 0)
        return out
    dates = [_date(v) for v in vals[:5000]]
    d_ok = [d for d in dates if d]
    if vals and len(d_ok) / len(dates) >= 0.9:
        out["type"] = "date"
        all_d = sorted(d for d in (_date(v) for v in vals) if d)
        by_month = Counter(d.strftime("%Y-%m") for d in all_d)
        out.update(min=all_d[0].strftime("%Y-%m-%d"), max=all_d[-1].strftime("%Y-%m-%d"), span_days=(all_d[-1] - all_d[0]).days,
                   by_month=[{"month": k, "count": c} for k, c in sorted(by_month.items())[-24:]])
        return out
    low = [str(v).strip().lower() for v in vals]
    if set(low) <= {"true", "false", "yes", "no", "y", "n", "0", "1"} and len(set(low)) <= 2:
        out["type"] = "boolean"
        c = Counter(low)
        out["values"] = [{"value": k, "count": n} for k, n in c.most_common()]
        return out
    sv = [str(v).strip() for v in vals]
    c = Counter(sv)
    lens = [len(x) for x in sv]
    out.update(type="category" if len(c) <= max(20, total * 0.5) else "text", unique=len(c), avg_length=round(st.fmean(lens), 1), longest=max(lens),
               top=[{"value": k[:60], "count": n, "pct": round(100 * n / len(sv), 1)} for k, n in c.most_common(8)])
    if len(c) == len(sv) and len(sv) > 5:
        out["looks_unique_id"] = True
    return out


def correlations(cols: dict[str, list[float | None]], limit: int = 6) -> list[dict[str, Any]]:
    names = list(cols)[:25]
    found = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pairs = [(x, y) for x, y in zip(cols[a], cols[b]) if x is not None and y is not None]
            if len(pairs) < 8:
                continue
            xs, ys = zip(*pairs)
            if len(set(xs)) < 2 or len(set(ys)) < 2:
                continue
            try:
                r = st.correlation(xs, ys)
            except st.StatisticsError:
                continue
            if abs(r) >= 0.5:
                found.append({"a": a, "b": b, "r": round(r, 3), "n": len(pairs)})
    found.sort(key=lambda d: -abs(d["r"]))
    return found[:limit]


def analyze_table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    truncated = len(rows) > MAX_ROWS_PROFILE
    rows = rows[:MAX_ROWS_PROFILE]
    width = len(columns)
    cols_raw = [[(r[i] if i < len(r) else "") for r in rows] for i in range(width)]
    names: list[str] = []
    for i, c in enumerate(columns):
        base = str(c).strip() or f"column {i + 1}"
        n, k = base, 2
        while n in names:
            n, k = f"{base} ({k})", k + 1
        names.append(n)
    profiles = [profile_column(n, raw) for n, raw in zip(names, cols_raw)]
    num_cols = {p["name"]: [_num(v) if str(v).strip().lower() not in MISSING else None for v in raw] for p, raw in zip(profiles, cols_raw) if p.get("type") == "number"}
    dup = len(rows) - len({tuple(map(str, r)) for r in rows})
    corr = correlations(num_cols)
    insights: list[dict[str, str]] = []

    def note(kind: str, msg: str) -> None:
        insights.append({"kind": kind, "message": msg})

    note("info", f"{len(rows):,} rows and {width} columns" + (" (first 200,000 rows profiled)" if truncated else "") + ".")
    if dup:
        note("warning", f"{dup:,} duplicate row(s) ({round(100 * dup / max(1, len(rows)), 1)}%).")
    for p in profiles:
        if p["type"] == "empty":
            note("warning", f"“{p['name']}” is completely empty.")
        elif p["missing_pct"] >= 20:
            note("warning", f"“{p['name']}” is missing in {p['missing_pct']}% of rows.")
        elif p["missing"]:
            note("info", f"“{p['name']}” has {p['missing']} missing value(s).")
        if p["type"] == "number":
            if p["outliers"]:
                note("warning", f"“{p['name']}” has {p['outliers']} unusual value(s), e.g. {', '.join(map(str, p['outlier_examples'][:3]))} (typical range {p['q1']} to {p['q3']}).")
            if p["negatives"] and p["min"] < 0 and re.search(r"price|amount|qty|quantity|count|age|salary|revenue|cost", p["name"], re.I):
                note("warning", f"“{p['name']}” has {p['negatives']} negative value(s), which is unusual for this kind of field.")
            if abs(p["skew"]) > 1.5:
                note("info", f"“{p['name']}” is heavily skewed {'high' if p['skew'] > 0 else 'low'}: the median ({p['median']}) is far from the mean ({p['mean']}).")
            if p["unique"] == 1:
                note("info", f"“{p['name']}” has the same value ({p['min']}) in every row.")
        if p["type"] == "category" and p.get("top"):
            t = p["top"][0]
            if t["pct"] >= 70 and p["unique"] > 1:
                note("info", f"“{p['name']}”: “{t['value']}” makes up {t['pct']}% of rows.")
        if p["type"] == "date":
            note("info", f"“{p['name']}” runs from {p['min']} to {p['max']} ({p['span_days']:,} days).")
    for c in corr[:3]:
        note("finding", f"“{c['a']}” and “{c['b']}” move {'together' if c['r'] > 0 else 'in opposite directions'} (correlation {c['r']}). Correlation alone does not show cause.")
    return {"rows": len(rows), "columns": width, "duplicates": dup, "profiles": profiles, "correlations": corr, "insights": insights, "truncated": truncated,
            "preview": {"columns": names, "rows": [[str(c)[:80] for c in r[:width]] for r in rows[:10]]}}


def text_stats(text: str) -> dict[str, Any]:
    words = re.findall(r"[^\W\d_][\w'’-]*", text, re.UNICODE)
    sents = [s for s in re.split(r"(?<=[.!?])\s+|\n{2,}", text) if s.strip()]
    stop = set("the a an and or of to in on at for with is are was were be been it this that as by from not but have has had will can we you i they he she its their our your which who what when where how than then also more most all any".split())
    c = Counter(w.lower() for w in words if len(w) > 2 and w.lower() not in stop)
    n = len(words)
    avg_s = n / max(1, len(sents))
    syll = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in words)
    flesch = 206.835 - 1.015 * avg_s - 84.6 * (syll / max(1, n))
    return {"words": n, "characters": len(text), "sentences": len(sents), "paragraphs": len([p for p in re.split(r"\n\s*\n", text) if p.strip()]),
            "avg_sentence_words": round(avg_s, 1), "reading_minutes": max(1, round(n / 220)), "readability": round(max(0, min(100, flesch)), 1),
            "unique_words": len({w.lower() for w in words}), "top_words": [{"word": w, "count": k} for w, k in c.most_common(12)],
            "numbers_mentioned": len(re.findall(r"\b\d[\d,.]*\b", text)), "emails": sorted(set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)))[:10],
            "urls": sorted(set(re.findall(r"https?://[^\s)>\]]+", text)))[:10]}


def analyze_extracted(ex: Extracted) -> dict[str, Any]:
    out: dict[str, Any] = {"file": ex.name, "kind": ex.kind, "warnings": ex.warnings, "tables": [], "facts": ex.facts}
    for t in ex.tables:
        if not t.get("columns") and not t.get("rows"):
            continue
        a = analyze_table(list(t["columns"]), list(t["rows"]))
        a["name"] = t.get("name", "Table")
        out["tables"].append(a)
    if ex.kind not in {"csv", "tsv", "xlsx"} and ex.text.strip():
        out["text"] = text_stats(ex.text)
    out["headline"] = headline(out)
    return out


def headline(a: dict[str, Any]) -> str:
    if a["tables"]:
        t = a["tables"][0]
        extra = f" (+{len(a['tables']) - 1} more table(s))" if len(a["tables"]) > 1 else ""
        warn = sum(1 for i in t["insights"] if i["kind"] == "warning")
        return f"{a['file']}: {t['rows']:,} rows × {t['columns']} columns{extra}; {warn} thing(s) to check."
    if "text" in a:
        s = a["text"]
        return f"{a['file']}: {s['words']:,} words, about {s['reading_minutes']} min read."
    return f"{a['file']}: nothing to analyse."


def analyze_file(path: str | Path) -> dict[str, Any]:
    return analyze_extracted(extract(path))


def to_markdown(a: dict[str, Any]) -> str:
    L = [f"# Analysis of {a['file']}", "", a["headline"], ""]
    for t in a["tables"]:
        L += [f"## {t['name']}", ""] + [f"- {i['message']}" for i in t["insights"]] + ["", "| Column | Type | Missing | Summary |", "| --- | --- | --- | --- |"]
        for p in t["profiles"]:
            if p["type"] == "number":
                s = f"min {p['min']}, median {p['median']}, mean {p['mean']}, max {p['max']}"
            elif p["type"] == "date":
                s = f"{p['min']} to {p['max']}"
            elif p.get("top"):
                s = ", ".join(f"{x['value']} ({x['count']})" for x in p["top"][:3])
            else:
                s = ""
            L.append(f"| {p['name']} | {p['type']} | {p['missing']} | {s} |")
        L.append("")
    if "text" in a:
        s = a["text"]
        L += ["## Text", "", f"- {s['words']:,} words, {s['sentences']} sentences, about {s['reading_minutes']} min read", f"- Readability (Flesch): {s['readability']}",
              "- Most used words: " + ", ".join(w["word"] for w in s["top_words"][:8])]
    return "\n".join(L)
