"""Resume (ATS) checker.

This is an estimate built from the checks applicant-tracking systems commonly make: can the file be read, are the usual
sections present, do the words in the job description appear, and is the writing specific. It is not any vendor's real score.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from .extract import Extracted, extract

STOP = set("""a an the and or but if of to in on at by for with from as is are was were be been being this that these those it its into over under
about across after before between during through up down out off per via within without we you your our their they he she his her i my me will would
can could should may might must shall do does did done have has had having not no nor so than then too very also just more most other some such
only own same both each few any all etc eg ie including include includes experience years year work working required requirements preferred ability
strong good great excellent knowledge understanding responsibilities role team join looking seeking candidate candidates company position job
etc plus using use used able skills skill must need needs new well within""".split())

SYNONYMS = {
    "js": "javascript", "ts": "typescript", "k8s": "kubernetes", "ml": "machine learning", "ai": "artificial intelligence", "nlp": "natural language processing",
    "llm": "large language model", "llms": "large language model", "aws": "amazon web services", "gcp": "google cloud", "ci/cd": "cicd", "ci cd": "cicd",
    "pm": "project management", "tpm": "technical program management", "ux": "user experience", "ui": "user interface", "qa": "quality assurance",
    "sql": "sql", "postgres": "postgresql", "mongo": "mongodb", "node": "nodejs", "node.js": "nodejs", "react.js": "react", "reactjs": "react",
    "vr": "virtual reality", "ar": "augmented reality", "xr": "extended reality", "api": "api", "apis": "api", "rest": "rest", "agile": "agile", "scrum": "scrum",
    "kpi": "kpi", "kpis": "kpi", "okr": "okr", "okrs": "okr", "roi": "roi", "saas": "saas", "b2b": "b2b", "iot": "internet of things", "devops": "devops",
}

SKILLS = """python java javascript typescript c++ c# go golang rust kotlin swift php ruby scala r matlab sql nosql postgresql mysql mongodb redis elasticsearch
react angular vue nodejs django flask fastapi spring dotnet .net unity unreal blender docker kubernetes terraform ansible jenkins git github gitlab cicd
linux windows macos bash powershell amazon web services azure google cloud lambda serverless microservices rest api graphql grpc kafka rabbitmq spark hadoop
airflow tableau power bi excel looker snowflake bigquery databricks tensorflow pytorch keras scikit-learn pandas numpy machine learning deep learning
natural language processing computer vision large language model prompt engineering rag generative ai artificial intelligence data science data analysis
data engineering etl analytics statistics a/b testing agile scrum kanban jira confluence project management program management product management
stakeholder management risk management budgeting roadmap strategy leadership mentoring communication negotiation presentation okr kpi roi saas b2b
virtual reality augmented reality extended reality hololens quest vision pro openxr arkit arcore webxr figma sketch adobe photoshop illustrator
user experience user interface wireframing prototyping accessibility seo content marketing crm salesforce hubspot sap erp quality assurance testing
selenium cypress jest pytest junit security cybersecurity encryption compliance gdpr iso 27001 soc 2 networking tcp/ip cloud architecture devops sre
internet of things embedded firmware plc scada cad solidworks autocad six sigma lean supply chain logistics finance accounting audit forecasting""".split("\n")
SKILL_SET = {w for line in SKILLS for w in [line]}  # placeholder for the multiword scan below
_skill_tokens = " ".join(SKILLS).split()
MULTI = ["machine learning", "deep learning", "natural language processing", "computer vision", "large language model", "prompt engineering", "generative ai",
         "artificial intelligence", "data science", "data analysis", "data engineering", "power bi", "amazon web services", "google cloud", "project management",
         "program management", "product management", "stakeholder management", "risk management", "virtual reality", "augmented reality", "extended reality",
         "user experience", "user interface", "quality assurance", "internet of things", "supply chain", "six sigma", "a/b testing", "cloud architecture", "content marketing"]
SINGLE = {t for t in _skill_tokens if len(t) > 1} - {"and", "web", "cloud", "learning", "language", "model", "vision", "science", "data", "analysis", "management", "reality",
                                                      "experience", "interface", "assurance", "things", "chain", "sigma", "engineering", "testing", "marketing", "architecture",
                                                      "processing", "natural", "large", "prompt", "generative", "artificial", "intelligence", "power", "amazon", "google", "deep",
                                                      "computer", "stakeholder", "risk", "project", "program", "product", "virtual", "augmented", "extended", "user", "quality",
                                                      "internet", "supply", "lean", "content", "iso", "soc", "go", "r", "c", "bi"}
SINGLE |= {"go", "r"}  # kept: real skills, matched only as whole words below

ACTION_VERBS = set("""led managed built designed developed delivered launched created implemented improved increased reduced optimized automated architected
established drove owned spearheaded coordinated directed streamlined negotiated analyzed resolved migrated deployed integrated mentored trained scaled
shipped founded initiated generated saved achieved transformed modernized secured executed produced presented partnered collaborated engineered
researched evaluated planned orchestrated championed consolidated redesigned simplified accelerated expanded won earned grew cut boosted""".split())
WEAK = ["responsible for", "duties included", "worked on", "helped with", "assisted with", "involved in", "participated in", "tasked with", "in charge of"]
SECTIONS = {
    "summary": ["summary", "professional summary", "profile", "objective", "career objective", "about me", "about"],
    "experience": ["experience", "work experience", "professional experience", "employment", "employment history", "work history", "career history"],
    "education": ["education", "academic background", "qualifications", "academics", "education and training"],
    "skills": ["skills", "technical skills", "core competencies", "key skills", "competencies", "technologies", "skills and tools"],
    "projects": ["projects", "key projects", "selected projects", "personal projects"],
    "certifications": ["certifications", "certificates", "licenses", "licences", "courses", "training", "certifications and licenses"],
}
MONTHS = "jan feb mar apr may jun jul aug sep sept oct nov dec january february march april june july august september october november december".split()
DATE_RE = re.compile(r"\b(?:(?:" + "|".join(MONTHS) + r")\.?\s+)?(?:19|20)\d{2}\b|\b\d{1,2}/(?:19|20)\d{2}\b", re.I)
RANGE_RE = re.compile(r"((?:(?:" + "|".join(MONTHS) + r")\.?\s+)?(?:19|20)\d{2}|\d{1,2}/(?:19|20)\d{2})\s*(?:-|–|—|to)\s*((?:(?:" + "|".join(MONTHS) + r")\.?\s+)?(?:19|20)\d{2}|present|current|now|till date|\d{1,2}/(?:19|20)\d{2})", re.I)


def stem(w: str) -> str:
    w = w.lower()
    for suf in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ied", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def norm_text(t: str) -> str:
    t = t.lower().replace("c++", "cplusplus").replace("c#", "csharp").replace("ci/cd", "cicd").replace("node.js", "nodejs").replace(".net", "dotnet").replace("a/b", "ab")
    for k in sorted(SYNONYMS, key=len, reverse=True):
        if k in ("ci/cd", "node.js"):
            continue
        t = re.sub(rf"(?<![\w]){re.escape(k)}(?![\w])", SYNONYMS[k], t)
    return t


def terms(text: str) -> Counter[str]:
    """Candidate keywords: known skills (single and multi-word) plus meaningful single words and two-word phrases."""
    t = norm_text(text)
    out: Counter[str] = Counter()
    for m in MULTI:
        n = len(re.findall(rf"(?<!\w){re.escape(m)}(?!\w)", t))
        if n:
            out[m] += n
            t = re.sub(rf"(?<!\w){re.escape(m)}(?!\w)", " ", t)  # don't also count its parts as separate words
    words = re.findall(r"[a-z][a-z0-9+#.-]*[a-z0-9+#]|[a-z]", t)
    for w in words:
        if w in STOP or len(w) < 2 and w not in ("r", "c"):
            continue
        out[stem(w) if w not in SINGLE else w] += 1
    return out


def jd_keywords(jd: str, limit: int = 40) -> list[dict[str, Any]]:
    t = terms(jd)
    scored = []
    for k, n in t.items():
        if k in STOP or len(k) < 3 and k not in ("go",):
            continue
        weight = n + (3 if (k in SINGLE or k in MULTI) else 0) + (1 if " " in k else 0)
        if n == 1 and k not in SINGLE and k not in MULTI:
            weight -= 0.5  # one-off ordinary words are rarely required skills
        scored.append((weight, k, n))
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = [s for s in scored if s[0] >= 2][:limit]
    return [{"keyword": k, "weight": round(w, 1), "count": n, "is_skill": k in SINGLE or k in MULTI} for w, k, n in top]


def find_sections(text: str) -> dict[str, str | None]:
    lines = [l.strip() for l in text.splitlines()]
    found: dict[str, str | None] = {k: None for k in SECTIONS}
    for l in lines:
        bare = re.sub(r"[^a-z& ]", "", l.lower()).replace("&", "and").strip()
        if not bare or len(bare) > 40:
            continue
        for key, names in SECTIONS.items():
            if bare in names and found[key] is None:
                found[key] = l
    return found


def contact_info(text: str) -> dict[str, Any]:
    head = "\n".join(text.splitlines()[:25])
    email = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", head)
    phone = re.search(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,5}\)?[\s.-]?)?\d{3,5}[\s.-]?\d{3,5}", re.sub(r"[A-Za-z]", " ", head))
    return {"email": bool(email), "phone": bool(phone and len(re.sub(r"\D", "", phone.group(0))) >= 8), "linkedin": bool(re.search(r"linkedin\.com/in/", text, re.I)),
            "github": bool(re.search(r"github\.com/", text, re.I)), "website": bool(re.search(r"https?://|www\.", head)),
            "location": bool(re.search(r"\b[A-Z][a-z]+,\s*(?:[A-Z]{2}|[A-Z][a-z]+)\b", head))}


def bullets_of(text: str) -> list[str]:
    out = []
    for l in text.splitlines():
        m = re.match(r"^\s*(?:[-•●▪◦*–·‣]|\d+[.)])\s+(.+)$", l)
        if m:
            out.append(m.group(1).strip())
    return out


def level(score: float) -> str:
    return "Excellent" if score >= 85 else "Good" if score >= 70 else "Needs work" if score >= 50 else "Poor"


def check_resume(ex: Extracted, job_description: str = "") -> dict[str, Any]:
    text = ex.text
    words = re.findall(r"\w+", text)
    issues: list[dict[str, str]] = []
    cats: dict[str, dict[str, Any]] = {}

    def add(sev: str, cat: str, msg: str, fix: str) -> None:
        issues.append({"severity": sev, "category": cat, "message": msg, "fix": fix})

    # ---- parseability / formatting (15)
    fmt, notes = 15.0, []
    f = ex.facts
    if ex.kind == "pdf":
        if not f.get("text_extractable"):
            fmt = 0; add("high", "format", "No text could be read from the PDF. ATS software will see an empty resume.", "Export the resume from Word or Google Docs as a text-based PDF, not a scan or picture.")
        elif f.get("images", 0) > 2:
            fmt -= 3; add("medium", "format", "The PDF contains several images. ATS cannot read text inside images.", "Remove logos, icons and picture-based skill bars.")
        if f.get("pages", 1) > 2:
            fmt -= 3; add("medium", "format", f"The resume is {f['pages']} pages long.", "Keep to 1 page (early career) or 2 pages. Cut older or less relevant roles.")
    elif ex.kind == "docx":
        if f.get("tables", 0):
            fmt -= 4; add("high", "format", f"The resume uses {f['tables']} table(s). Many ATS read tables in the wrong order or skip them.", "Use plain paragraphs and bullet lists instead of tables.")
        if f.get("textboxes", 0):
            fmt -= 4; add("high", "format", "Text boxes are used. ATS often ignores text inside text boxes.", "Move the content into the normal page body.")
        if f.get("columns", 1) > 1:
            fmt -= 3; add("medium", "format", "A multi-column layout is used. Text may be read in the wrong order.", "Use one column.")
        if f.get("images", 0):
            fmt -= 2; add("low", "format", "The resume contains pictures.", "Remove photos and graphics; ATS cannot read them.")
        if f.get("header_text") and (re.search(r"@|\d{6,}", f["header_text"])):
            fmt -= 2; add("medium", "format", "Contact details are in the page header. Some ATS skip headers and footers.", "Repeat your name, email and phone at the top of the page body.")
    elif ex.kind in {"txt", "md"}:
        notes.append("Plain text is the safest format for ATS but looks plain to people. Consider a clean Word or PDF version too.")
    else:
        fmt -= 4; add("medium", "format", f"A .{ex.kind} file is an unusual resume format.", "Submit the resume as .docx or a text-based .pdf.")
    n_words = len(words)
    if n_words < 200:
        fmt -= 4; add("high", "format", f"Only {n_words} words were found. That is too little for an ATS to judge.", "Add detail: responsibilities, tools used and results for each role.")
    elif n_words > 1100:
        fmt -= 2; add("medium", "format", f"{n_words} words is long.", "Aim for 400–800 words; remove duties that are not relevant to the job.")
    if re.search(r"[☀-➿\U0001F300-\U0001FAFF]", text):
        fmt -= 1; add("low", "format", "Emoji or decorative symbols were found.", "Use standard characters.")
    cats["format"] = {"label": "File and layout", "score": max(0, fmt), "max": 15, "notes": notes}

    # ---- contact (10)
    c = contact_info(text)
    cs = 4 * c["email"] + 3 * c["phone"] + 1.5 * (c["linkedin"] or c["github"] or c["website"]) + 1.5 * c["location"]
    if not c["email"]:
        add("high", "contact", "No email address found near the top.", "Put your email on the first lines of the page body.")
    if not c["phone"]:
        add("medium", "contact", "No phone number found near the top.", "Add a phone number.")
    if not (c["linkedin"] or c["github"] or c["website"]):
        add("low", "contact", "No LinkedIn, GitHub or portfolio link.", "Add a LinkedIn URL.")
    if not c["location"]:
        add("low", "contact", "No city/location found.", "Add your city and country (e.g. “Chennai, India”).")
    cats["contact"] = {"label": "Contact details", "score": cs, "max": 10, "detail": c}

    # ---- sections (15)
    secs = find_sections(text)
    weights = {"experience": 5, "education": 3.5, "skills": 3.5, "summary": 2, "projects": 0.5, "certifications": 0.5}
    ss = sum(w for k, w in weights.items() if secs[k])
    for k, label in (("experience", "Experience"), ("education", "Education"), ("skills", "Skills")):
        if not secs[k]:
            add("high" if k == "experience" else "medium", "sections", f"No “{label}” heading was found.", f"Add a clearly named “{label}” section. ATS looks for standard headings.")
    if not secs["summary"]:
        add("low", "sections", "No summary or profile section.", "Add a 2–3 line professional summary with your title, years of experience and top skills.")
    cats["sections"] = {"label": "Standard sections", "score": ss, "max": 15, "detail": {k: bool(v) for k, v in secs.items()}}

    # ---- content quality (20)
    bl = bullets_of(text)
    body = bl or [l.strip() for l in text.splitlines() if len(l.split()) >= 6]
    q = 0.0
    if body:
        starts = [re.sub(r"[^a-z]", "", (b.split() or [""])[0].lower()) for b in body]
        verb_share = sum(1 for s in starts if s in ACTION_VERBS) / len(body)
        metric_share = sum(1 for b in body if re.search(r"\d+\s*%|[$₹€£]\s*\d|\b\d{2,}\b|\b\d+[kKmMbB]\b|\b\d+x\b", b)) / len(body)
        weak = sum(1 for b in body if any(w in b.lower() for w in WEAK))
        long_b = sum(1 for b in body if len(b.split()) > 38)
        q = 20 * (0.35 * min(1, verb_share / 0.6) + 0.35 * min(1, metric_share / 0.4) + 0.15 * (1 - min(1, weak / max(1, len(body) * 0.25))) + 0.15 * (1 - min(1, long_b / max(1, len(body) * 0.3))))
        if verb_share < 0.4:
            add("medium", "content", f"Only {round(verb_share * 100)}% of your bullet points start with a strong action verb.", "Start bullets with verbs such as Led, Built, Delivered, Reduced, Launched.")
        if metric_share < 0.25:
            add("high", "content", f"Only {round(metric_share * 100)}% of bullets contain numbers or results.", "Add measurable results: “Cut release time by 35%”, “Managed a team of 8”, “₹2 Cr budget”.")
        if weak:
            add("low", "content", f"{weak} bullet(s) use weak phrases like “responsible for” or “worked on”.", "Replace with what you achieved: “Led…”, “Delivered…”.")
        if long_b:
            add("low", "content", f"{long_b} bullet(s) run longer than ~35 words.", "Keep each bullet to one or two lines.")
        if not bl:
            q *= 0.7; add("medium", "content", "No bullet points were detected.", "Use short bullet points under each role.")
        pron = len(re.findall(r"\b(?:i|my|me)\b", text.lower()))
        if pron > 6:
            q = max(0, q - 2); add("low", "content", "The resume uses first-person words (I, my).", "Write in implied first person: “Led a team of 5”, not “I led my team”.")
    else:
        add("high", "content", "No descriptive lines were found.", "Describe each role in bullet points with actions and results.")
    cats["content"] = {"label": "Writing quality", "score": q, "max": 20}

    # ---- dates (5)
    ranges = RANGE_RE.findall(text)
    dates = DATE_RE.findall(text)
    ds = 0.0
    if len(ranges) >= 2:
        ds = 5.0
    elif len(dates) >= 2:
        ds = 3.0
        add("low", "dates", "Few clear date ranges (e.g. “Jan 2021 – Mar 2023”).", "Put a start and end date on every role.")
    else:
        add("medium", "dates", "Employment dates were not found.", "Add dates like “Jan 2021 – Present” for each role.")
    styles = {("month-name" if re.search(r"[A-Za-z]{3}", r[0]) else "numeric") for r in ranges}
    if len(styles) > 1:
        ds = max(0, ds - 1.5); add("low", "dates", "Dates mix different formats.", "Use one format everywhere, e.g. “Jan 2021 – Mar 2023”.")
    cats["dates"] = {"label": "Dates", "score": ds, "max": 5}

    # ---- keywords (35 with a job description, otherwise skills coverage)
    resume_terms = terms(text)
    resume_norm = norm_text(text)
    kw_detail: dict[str, Any] = {}
    if job_description.strip():
        want = jd_keywords(job_description)
        matched, missing = [], []
        for w in want:
            k = w["keyword"]
            hit = resume_terms.get(k, 0) > 0 or (" " in k and k in resume_norm)
            (matched if hit else missing).append({**w, "in_resume": resume_terms.get(k, 0)})
        tot = sum(w["weight"] for w in want) or 1
        cov = sum(m["weight"] for m in matched) / tot
        ks = 35 * cov
        kw_detail = {"mode": "job", "matched": matched, "missing": missing, "coverage": round(cov, 3)}
        if cov < 0.5:
            add("high", "keywords", f"Only {round(cov * 100)}% of the job description's key terms appear in your resume.", "Work the missing terms into your skills and bullet points where they are truthful: " + ", ".join(m["keyword"] for m in missing[:8]) + ".")
        elif cov < 0.75:
            add("medium", "keywords", f"{round(cov * 100)}% of the job's key terms appear.", "Add the remaining relevant terms: " + ", ".join(m["keyword"] for m in missing[:6]) + ".")
        stuffed = [k for k, n in resume_terms.items() if n >= 12 and k in SINGLE]
        if stuffed:
            ks = max(0, ks - 3); add("low", "keywords", "Some keywords repeat very often: " + ", ".join(stuffed[:4]) + ".", "Mention each skill naturally a few times; repetition can look like keyword stuffing.")
    else:
        found = sorted({k for k in resume_terms if k in SINGLE or k in MULTI})
        ks = 35 * min(1, len(found) / 15)
        kw_detail = {"mode": "general", "skills_found": found[:60], "count": len(found)}
        if len(found) < 8:
            add("medium", "keywords", f"Only {len(found)} recognised skills were found.", "Add a Skills section listing your tools, technologies and methods.")
        add("low", "keywords", "No job description was given, so keywords were scored on general skill coverage.", "Paste the job description to see exactly which of its terms are missing.")
    cats["keywords"] = {"label": "Keywords" if job_description.strip() else "Skills coverage", "score": ks, "max": 35, **kw_detail}

    total = round(sum(min(c["score"], c["max"]) for c in cats.values()), 1)
    for c in cats.values():
        c["score"] = round(min(c["score"], c["max"]), 1)
    order = {"high": 0, "medium": 1, "low": 2}
    issues.sort(key=lambda i: order[i["severity"]])
    return {"score": total, "level": level(total), "categories": cats, "issues": issues, "words": n_words, "file": ex.name, "has_job_description": bool(job_description.strip()),
            "disclaimer": "An estimate based on common ATS checks. Real systems differ, so treat it as guidance, not a guarantee."}


def check_file(path: str | Path, job_description: str = "") -> dict[str, Any]:
    ex = extract(path)
    if ex.kind in {"csv", "xlsx", "tsv", "pptx", "json"}:
        raise ValueError(f"A .{ex.kind} file does not look like a resume. Upload a PDF, Word or text file.")
    return check_resume(ex, job_description)
