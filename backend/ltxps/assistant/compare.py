"""Compares two files: readable differences, a similarity score, and cell-level changes for tables."""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

from .extract import Extracted, extract

MAX_DIFF_ITEMS = 400


def _words(s: str) -> list[str]:
    return re.findall(r"\S+\s*", s)


def inline_diff(a: str, b: str) -> list[dict[str, str]]:
    """Word-level segments: [{'t': 'equal'|'del'|'ins', 'x': text}] so the UI can highlight what changed inside a line."""
    wa, wb = _words(a), _words(b)
    out: list[dict[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        if op == "equal":
            out.append({"t": "equal", "x": "".join(wa[i1:i2])})
        else:
            if i2 > i1:
                out.append({"t": "del", "x": "".join(wa[i1:i2])})
            if j2 > j1:
                out.append({"t": "ins", "x": "".join(wb[j1:j2])})
    return out


def text_diff(a_units: list[str], b_units: list[str]) -> dict[str, Any]:
    """Aligns paragraphs (or slides/pages) and classifies each as same, added, removed or changed."""
    a_norm = [re.sub(r"\s+", " ", u).strip() for u in a_units]
    b_norm = [re.sub(r"\s+", " ", u).strip() for u in b_units]
    sm = difflib.SequenceMatcher(None, a_norm, b_norm, autojunk=False)
    items: list[dict[str, Any]] = []
    stats = {"added": 0, "removed": 0, "changed": 0, "same": 0}
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            stats["same"] += i2 - i1
            continue
        if op == "delete":
            for k in range(i1, i2):
                items.append({"type": "removed", "a_index": k, "a": a_norm[k]}); stats["removed"] += 1
        elif op == "insert":
            for k in range(j1, j2):
                items.append({"type": "added", "b_index": k, "b": b_norm[k]}); stats["added"] += 1
        else:  # replace: pair up similar units, the rest are pure add/remove
            ai, bj = list(range(i1, i2)), list(range(j1, j2))
            while ai and bj:
                best = max(((difflib.SequenceMatcher(None, a_norm[x], b_norm[y]).ratio(), x, y) for x in ai[:6] for y in bj[:6]), default=(0, 0, 0))
                if best[0] < 0.45:
                    break
                _, x, y = best
                for k in [k for k in ai if k < x]:
                    items.append({"type": "removed", "a_index": k, "a": a_norm[k]}); stats["removed"] += 1; ai.remove(k)
                for k in [k for k in bj if k < y]:
                    items.append({"type": "added", "b_index": k, "b": b_norm[k]}); stats["added"] += 1; bj.remove(k)
                items.append({"type": "changed", "a_index": x, "b_index": y, "a": a_norm[x], "b": b_norm[y], "segments": inline_diff(a_norm[x], b_norm[y])})
                stats["changed"] += 1
                ai.remove(x); bj.remove(y)
            for k in ai:
                items.append({"type": "removed", "a_index": k, "a": a_norm[k]}); stats["removed"] += 1
            for k in bj:
                items.append({"type": "added", "b_index": k, "b": b_norm[k]}); stats["added"] += 1
    items.sort(key=lambda it: (it.get("a_index", it.get("b_index", 0)) if it["type"] != "added" else it["b_index"]))
    total = max(len(a_norm), len(b_norm), 1)
    return {"stats": stats, "items": items[:MAX_DIFF_ITEMS], "truncated": len(items) > MAX_DIFF_ITEMS, "units_a": len(a_norm), "units_b": len(b_norm), "unit_similarity": round(stats["same"] / total, 4)}


def _key_column(cols_a: list[str], cols_b: list[str], rows_a: list[list[str]], rows_b: list[list[str]]) -> int | None:
    """Picks a column that identifies rows (unique, filled, present in both files). None means 'compare by position'."""
    shared = [c for c in cols_a if c in cols_b]
    for c in shared:
        ia, ib = cols_a.index(c), cols_b.index(c)
        va, vb = [r[ia] for r in rows_a], [r[ib] for r in rows_b]
        if va and vb and all(v.strip() for v in va + vb) and len(set(va)) == len(va) and len(set(vb)) == len(vb):
            overlap = len(set(va) & set(vb)) / max(1, min(len(set(va)), len(set(vb))))
            if overlap >= 0.3:
                return ia
    return None


def table_diff(ta: dict[str, Any], tb: dict[str, Any], max_changes: int = 500) -> dict[str, Any]:
    ca, cb = ta["columns"], tb["columns"]
    out: dict[str, Any] = {"name_a": ta["name"], "name_b": tb["name"], "columns_added": [c for c in cb if c not in ca], "columns_removed": [c for c in ca if c not in cb],
                           "rows_a": len(ta["rows"]), "rows_b": len(tb["rows"])}
    shared = [c for c in ca if c in cb]
    key = _key_column(ca, cb, ta["rows"], tb["rows"])
    changes: list[dict[str, Any]] = []
    added = removed = changed_rows = changed_cells = same = 0
    partial = 0.0
    numeric: dict[str, list[float]] = {}

    def num(v: str):  # noqa: ANN202
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None

    if key is not None:
        kname = ca[key]
        kb = cb.index(kname)
        ra = {r[key]: r for r in ta["rows"]}
        rb = {r[kb]: r for r in tb["rows"]}
        out["matched_by"] = f"column “{kname}”"
        for k, r in rb.items():
            if k not in ra:
                added += 1
                if len(changes) < max_changes:
                    changes.append({"type": "added_row", "key": k, "row": dict(zip(cb, r))})
        for k, r in ra.items():
            if k not in rb:
                removed += 1
                if len(changes) < max_changes:
                    changes.append({"type": "removed_row", "key": k, "row": dict(zip(ca, r))})
                continue
            diffs = []
            for c in shared:
                x, y = r[ca.index(c)], rb[k][cb.index(c)]
                if x != y:
                    diffs.append({"column": c, "old": x, "new": y})
                    nx, ny = num(x), num(y)
                    if nx is not None and ny is not None:
                        numeric.setdefault(c, []).append(ny - nx)
            if diffs:
                changed_rows += 1; changed_cells += len(diffs); partial += 1 - len(diffs) / max(1, len(shared))
                if len(changes) < max_changes:
                    changes.append({"type": "changed_row", "key": k, "cells": diffs})
            else:
                same += 1
    else:
        out["matched_by"] = "row position (no unique ID column found)"
        for i in range(max(len(ta["rows"]), len(tb["rows"]))):
            if i >= len(ta["rows"]):
                added += 1
                if len(changes) < max_changes:
                    changes.append({"type": "added_row", "key": str(i + 1), "row": dict(zip(cb, tb["rows"][i]))})
            elif i >= len(tb["rows"]):
                removed += 1
                if len(changes) < max_changes:
                    changes.append({"type": "removed_row", "key": str(i + 1), "row": dict(zip(ca, ta["rows"][i]))})
            else:
                diffs = [{"column": c, "old": ta["rows"][i][ca.index(c)], "new": tb["rows"][i][cb.index(c)]} for c in shared if ta["rows"][i][ca.index(c)] != tb["rows"][i][cb.index(c)]]
                if diffs:
                    changed_rows += 1; changed_cells += len(diffs); partial += 1 - len(diffs) / max(1, len(shared))
                    if len(changes) < max_changes:
                        changes.append({"type": "changed_row", "key": str(i + 1), "cells": diffs})
                    for d in diffs:
                        nx, ny = num(d["old"]), num(d["new"])
                        if nx is not None and ny is not None:
                            numeric.setdefault(d["column"], []).append(ny - nx)
                else:
                    same += 1
    denom = same + changed_rows + added + removed
    out["similarity"] = round((same + partial) / denom, 4) if denom else 1.0
    out.update(rows_added=added, rows_removed=removed, rows_changed=changed_rows, cells_changed=changed_cells, rows_same=same, changes=changes,
               numeric_shifts=[{"column": c, "cells": len(v), "total_change": round(sum(v), 4), "average_change": round(sum(v) / len(v), 4)} for c, v in numeric.items()],
               truncated=(added + removed + changed_rows) > len(changes))
    return out


def compare_files(path_a: str | Path, path_b: str | Path) -> dict[str, Any]:
    a, b = extract(path_a), extract(path_b)
    return compare_extracted(a, b)


def compare_extracted(a: Extracted, b: Extracted) -> dict[str, Any]:
    result: dict[str, Any] = {"a": {"name": a.name, "kind": a.kind}, "b": {"name": b.name, "kind": b.kind}, "warnings": a.warnings + b.warnings}
    tabular = bool(a.tables and b.tables and a.kind in {"csv", "tsv", "xlsx"} and b.kind in {"csv", "tsv", "xlsx"})
    if tabular:
        names_b = {t["name"]: t for t in b.tables}
        pairs = []
        for i, ta in enumerate(a.tables):
            tb = names_b.get(ta["name"]) or (b.tables[i] if i < len(b.tables) else None)
            if tb:
                pairs.append((ta, tb))
        result["mode"] = "table"
        result["tables"] = [table_diff(x, y) for x, y in pairs]
        result["sheets_only_in_a"] = [t["name"] for t in a.tables if t["name"] not in {p[0]["name"] for p in pairs}]
        result["sheets_only_in_b"] = [t["name"] for t in b.tables if t["name"] not in {p[1]["name"] for p in pairs}]
        weights = [max(1, t["rows_a"], t["rows_b"]) for t in result["tables"]]
        sim = sum(t["similarity"] * w for t, w in zip(result["tables"], weights)) / max(1, sum(weights)) if result["tables"] else 0.0
        if any(t["columns_added"] or t["columns_removed"] for t in result["tables"]):
            sim *= 0.9
        result["similarity"] = round(sim, 4)
    else:
        mode = "slides" if a.kind == "pptx" and b.kind == "pptx" else "pages" if a.kind == "pdf" and b.kind == "pdf" else "paragraphs"
        ua, ub = a.units or [a.text], b.units or [b.text]
        result["mode"] = mode
        result["diff"] = text_diff(ua, ub)
        wa, wb = re.findall(r"\w+", a.text.lower()), re.findall(r"\w+", b.text.lower())
        result["similarity"] = round(difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio(), 4) if len(wa) + len(wb) < 60000 else round(result["diff"]["unit_similarity"], 4)
        result["words"] = {"a": len(wa), "b": len(wb), "difference": len(wb) - len(wa)}
        if a.tables or b.tables:
            result["table_counts"] = {"a": len(a.tables), "b": len(b.tables)}
    result["identical"] = result["similarity"] >= 0.9999 and not (result.get("diff", {}).get("stats", {}).get("changed") or result.get("diff", {}).get("stats", {}).get("added") or result.get("diff", {}).get("stats", {}).get("removed"))
    result["headline"] = headline(result)
    return result


def headline(r: dict[str, Any]) -> str:
    pct = round(r["similarity"] * 100)
    if r.get("identical"):
        return "The two files have the same content."
    if r["mode"] == "table":
        t = r["tables"][0] if r["tables"] else None
        if not t:
            return f"{pct}% similar. The files have no sheet in common."
        bits = [f"{t['rows_changed']} rows changed ({t['cells_changed']} cells)", f"{t['rows_added']} rows added", f"{t['rows_removed']} rows removed"]
        if t["columns_added"] or t["columns_removed"]:
            bits.append(f"{len(t['columns_added'])} columns added, {len(t['columns_removed'])} removed")
        return f"{pct}% similar: " + ", ".join(bits) + "."
    s = r["diff"]["stats"]
    unit = {"slides": "slides", "pages": "pages", "paragraphs": "paragraphs"}[r["mode"]]
    return f"{pct}% similar: {s['changed']} {unit} changed, {s['added']} added, {s['removed']} removed."


def to_markdown(r: dict[str, Any], limit: int = 60) -> str:
    """A text report used for Word/PDF export and for giving a language model the findings."""
    out = [f"# Comparison: {r['a']['name']} vs {r['b']['name']}", "", f"**{r['headline']}**", ""]
    if r["mode"] == "table":
        for t in r["tables"]:
            out += [f"## Sheet {t['name_a']}", f"Matched by {t['matched_by']}. Rows: {t['rows_a']} → {t['rows_b']}.", ""]
            if t["columns_added"]:
                out.append(f"- Columns added: {', '.join(t['columns_added'])}")
            if t["columns_removed"]:
                out.append(f"- Columns removed: {', '.join(t['columns_removed'])}")
            if t["numeric_shifts"]:
                out += ["", "| Column | Cells changed | Total change | Average change |", "|---|---|---|---|"]
                out += [f"| {s['column']} | {s['cells']} | {s['total_change']:g} | {s['average_change']:g} |" for s in t["numeric_shifts"]]
            out += ["", "| Type | Key | Detail |", "|---|---|---|"]
            for c in t["changes"][:limit]:
                if c["type"] == "changed_row":
                    detail = "; ".join(f"{d['column']}: {d['old']} → {d['new']}" for d in c["cells"][:6])
                    out.append(f"| Changed | {c['key']} | {detail} |")
                else:
                    out.append(f"| {'Added' if c['type'] == 'added_row' else 'Removed'} | {c['key']} | {', '.join(f'{k}={v}' for k, v in list(c['row'].items())[:5])} |")
            out.append("")
    else:
        out += [f"Words: {r['words']['a']} → {r['words']['b']} ({r['words']['difference']:+d})", ""]
        for it in r["diff"]["items"][:limit]:
            if it["type"] == "changed":
                new = "".join(f"**{s['x'].strip()}** " if s["t"] == "ins" else ("" if s["t"] == "del" else s["x"]) for s in it["segments"]).strip()
                out.append(f"- *Changed*: {new}")
            elif it["type"] == "added":
                out.append(f"- *Added*: {it['b'][:300]}")
            else:
                out.append(f"- *Removed*: {it['a'][:300]}")
    return "\n".join(out)
