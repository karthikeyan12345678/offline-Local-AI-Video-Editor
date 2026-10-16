import csv
from pathlib import Path

import pytest

from ltxps.assistant import analytics, ats, compare
from ltxps.assistant.documents import build_file, parse_markdown
from ltxps.assistant.extract import ExtractError, extract

RESUME = """# Asha K
Chennai, India | asha@example.com | +91 98765 43210 | linkedin.com/in/asha
## Summary
Program manager with 6 years delivering cloud and data platforms.
## Experience
### Program Manager - Acme
Jan 2021 – Present
- Led a team of 10 engineers and delivered 5 releases, cutting cycle time by 30%
- Built a Kubernetes and AWS platform serving 40k users
- Managed a $2M budget using Agile and Scrum
### Analyst - Beta
Jun 2017 – Dec 2020
- Automated reporting in Python and SQL, saving 200 hours per year
## Education
B.E. Computer Science, Anna University, 2017
## Skills
Python, SQL, AWS, Kubernetes, Docker, Agile, Scrum, Project Management, Risk Management, Machine Learning
"""
JD = "Technical Program Manager. Required: Kubernetes, AWS, Agile, stakeholder management, Terraform, machine learning. Lead teams and manage risk."


def test_ats_good_vs_bad(tmp_path):
    good = build_file("docx", parse_markdown(RESUME), tmp_path, "good").path
    bad = build_file("docx", parse_markdown("# me\nI worked on things. I helped with stuff. " * 5), tmp_path, "bad").path
    g, b = ats.check_file(good, JD), ats.check_file(bad, JD)
    assert g["score"] > 65 and b["score"] < 35 and g["score"] > b["score"] + 30
    matched = {m["keyword"] for m in g["categories"]["keywords"]["matched"]}
    missing = {m["keyword"] for m in g["categories"]["keywords"]["missing"]}
    assert {"kubernetes", "agile"} <= matched and "terraform" in missing and "stakeholder management" in missing
    assert all(set(i) >= {"severity", "message", "fix"} for i in g["issues"])
    assert 0 <= g["score"] <= 100 and sum(c["max"] for c in g["categories"].values()) == 100


def test_ats_without_job_description_says_so(tmp_path):
    p = build_file("pdf", parse_markdown(RESUME), tmp_path, "r").path
    r = ats.check_file(p)
    assert not r["has_job_description"] and any("job description" in i["message"].lower() for i in r["issues"])


def test_ats_rejects_non_resume(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="resume"):
        ats.check_file(p)


def test_ats_flags_tables_in_docx(tmp_path):
    md = RESUME.replace("## Skills", "| a | b |\n| --- | --- |\n| 1 | 2 |\n\n## Skills")
    r = ats.check_file(build_file("docx", parse_markdown(md), tmp_path, "t").path, JD)
    assert any("table" in i["message"].lower() for i in r["issues"])


def test_compare_text_and_table(tmp_path):
    a = build_file("docx", parse_markdown("# T\nOne.\n\nTwo is here.\n\nThree."), tmp_path, "a").path
    b = build_file("docx", parse_markdown("# T\nOne.\n\nTwo is there.\n\nFour."), tmp_path, "b").path
    r = compare.compare_files(a, b)
    assert not r["identical"] and r["similarity"] < 1
    assert compare.compare_files(a, a)["identical"]
    ca, cb = tmp_path / "a.csv", tmp_path / "b.csv"
    ca.write_text("id,qty\n1,5\n2,7\n")
    cb.write_text("id,qty\n1,5\n2,9\n3,1\n")
    t = compare.compare_files(ca, cb)
    assert not t["identical"] and "changed" in compare.headline(t)


def test_compare_across_formats(tmp_path):
    a = build_file("docx", parse_markdown("# T\nhello world again"), tmp_path, "a").path
    b = build_file("pdf", parse_markdown("# T\nhello world again"), tmp_path, "b").path
    assert compare.compare_files(a, b)["similarity"] > 0.6


def test_extract_errors_are_friendly(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"not a pdf")
    with pytest.raises(ExtractError):
        extract(p)
    q = tmp_path / "x.exe"
    q.write_bytes(b"MZ")
    with pytest.raises(ExtractError, match="not supported|support"):
        extract(q)


def test_analytics_csv(tmp_path):
    p = tmp_path / "s.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "units", "price", "total", "region"])
        for i in range(60):
            w.writerow([f"2025-01-{1 + i % 28:02d}", i + 1, 10 + i % 3, (i + 1) * (10 + i % 3), "N" if i % 4 else "S"])
        w.writerow(["2025-01-05", 5000, 10, 50000, "N"])
        w.writerow(["2025-01-05", 5000, 10, 50000, "N"])
    a = analytics.analyze_file(p)
    t = a["tables"][0]
    prof = {c["name"]: c for c in t["profiles"]}
    assert t["rows"] == 62 and prof["units"]["type"] == "number" and prof["day"]["type"] == "date" and prof["region"]["type"] == "category"
    assert prof["units"]["outliers"] >= 2 and t["duplicates"] == 1
    assert any(c["a"] == "units" and c["b"] == "total" for c in t["correlations"])
    assert "62 rows" in a["headline"].replace(",", "")
    assert "Analysis of" in analytics.to_markdown(a)


def test_analytics_xlsx_and_text(tmp_path):
    x = build_file("xlsx", parse_markdown("| a | b |\n| - | - |\n| 1 | x |\n| 2 | y |"), tmp_path, "t").path
    assert analytics.analyze_file(x)["tables"][0]["rows"] == 2
    d = build_file("docx", parse_markdown("# Hi\n" + "This is a sentence about data. " * 30), tmp_path, "d").path
    assert analytics.analyze_file(d)["text"]["words"] > 100


def test_analytics_empty_columns_do_not_crash(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("a,b\n,\n,\n")
    analytics.analyze_file(p)
