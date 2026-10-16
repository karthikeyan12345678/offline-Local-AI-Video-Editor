"""Creates PDF, Word, PowerPoint, CSV and Excel files from one neutral document model.

Input is Markdown (what people and language models write naturally) or a JSON `Doc`. A design theme (see themes.py)
decides colours and fonts, and is checked for readable contrast before anything is drawn.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from .themes import Palette, contrast, document_palette, get_theme, hex_to_rgb


# ------------------------------------------------------------------ model
class Block(BaseModel):
    type: Literal["heading", "paragraph", "bullets", "table", "quote", "code", "image", "divider", "pagebreak"]
    text: str = ""
    level: int = Field(1, ge=1, le=3)
    items: list[str] = Field(default_factory=list)
    ordered: bool = False
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    path: str = ""  # image file
    start: int = 1  # first number of an ordered list (continued lists on later slides)


class Doc(BaseModel):
    title: str = "Untitled"
    subtitle: str = ""
    author: str = ""
    blocks: list[Block] = Field(default_factory=list)
    notes: dict[int, str] = Field(default_factory=dict)  # speaker notes by slide index (PowerPoint only)


class RenderResult(BaseModel):
    path: str
    format: str
    pages: int | None = None
    warnings: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ markdown -> Doc
_INLINE = re.compile(r"(\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|`[^`]+`)")
ROW = re.compile(r"^\s*\|.*\|\s*$")
SEP = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def runs(text: str) -> list[tuple[str, str]]:
    """Splits inline Markdown into (text, style) where style is '', 'b', 'i' or 'c'."""
    out: list[tuple[str, str]] = []
    for part in _INLINE.split(text):
        if not part:
            continue
        if part.startswith(("**", "__")) and part.endswith(("**", "__")) and len(part) > 4:
            out.append((part[2:-2], "b"))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            out.append((part[1:-1], "c"))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            out.append((part[1:-1], "i"))
        else:
            out.append((part, ""))
    return out


def plain(text: str) -> str:
    return "".join(t for t, _ in runs(text))


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_markdown(md: str, title: str = "") -> Doc:
    lines = md.replace("\r\n", "\n").split("\n")
    doc = Doc(title=title or "Untitled")
    i, para, found_title = 0, [], False

    def flush() -> None:
        if para:
            doc.blocks.append(Block(type="paragraph", text=" ".join(s.strip() for s in para)))
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            doc.blocks.append(Block(type="code", text="\n".join(code)))
            i += 1
            continue
        if not stripped:
            flush(); i += 1; continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*$", stripped)
        if m:
            flush()
            level, text = len(m.group(1)), m.group(2)
            if level == 1 and not found_title and not doc.blocks:
                doc.title, found_title = plain(text), True
            else:
                doc.blocks.append(Block(type="heading", level=min(3, max(1, level - (1 if found_title else 0) if level > 1 else 1)), text=text))
            i += 1; continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            flush(); doc.blocks.append(Block(type="divider")); i += 1; continue
        if stripped.lower() in {"\\pagebreak", "<pagebreak>", "---pagebreak---"}:
            flush(); doc.blocks.append(Block(type="pagebreak")); i += 1; continue
        if ROW.match(line) and i + 1 < len(lines) and SEP.match(lines[i + 1]):
            flush()
            cols = _cells(line)
            rows, i = [], i + 2
            while i < len(lines) and ROW.match(lines[i]):
                r = _cells(lines[i])
                rows.append((r + [""] * len(cols))[: len(cols)])
                i += 1
            doc.blocks.append(Block(type="table", columns=cols, rows=rows))
            continue
        bm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
        if bm:
            flush()
            ordered = bm.group(2)[0].isdigit()
            items = []
            while i < len(lines):
                m2 = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
                if not m2 or m2.group(2)[0].isdigit() != ordered:
                    break
                items.append(("  " * (len(m2.group(1)) // 2 if len(m2.group(1)) >= 2 else 0)) + m2.group(3).strip())
                i += 1
            doc.blocks.append(Block(type="bullets", items=items, ordered=ordered))
            continue
        if stripped.startswith(">"):
            flush()
            q = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q.append(lines[i].strip().lstrip(">").strip()); i += 1
            doc.blocks.append(Block(type="quote", text=" ".join(q)))
            continue
        im = re.match(r"^!\[[^\]]*\]\(([^)]+)\)$", stripped)
        if im:
            flush(); doc.blocks.append(Block(type="image", path=im.group(1))); i += 1; continue
        para.append(stripped)
        i += 1
    flush()
    return doc


def split_deck(doc: Doc) -> list[dict]:
    """Turns blocks into slides: a heading starts a slide; level-1 headings with nothing under them become section slides."""
    slides: list[dict] = []
    cur: dict | None = None
    for b in doc.blocks:
        if b.type == "heading":
            cur = {"title": plain(b.text), "level": b.level, "blocks": []}
            slides.append(cur)
        else:
            if b.type in {"divider", "pagebreak"}:
                cur = None
                continue
            if cur is None:
                cur = {"title": "", "level": 2, "blocks": []}
                slides.append(cur)
            cur["blocks"].append(b)
    for s in slides:
        notes = [b for b in s["blocks"] if b.type == "paragraph" and b.text.lower().startswith(("notes:", "speaker notes:"))]
        s["notes"] = " ".join(n.text.split(":", 1)[1].strip() for n in notes)
        s["blocks"] = [b for b in s["blocks"] if b not in notes]
    return [s for s in slides if s["title"] or s["blocks"]]


# ------------------------------------------------------------------ fonts for PDF
FONT_FILES = {
    "serif": [("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"), ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
              ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSerif-Italic.ttf", "DejaVuSerif-BoldItalic.ttf")],
    "sans": [("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"), ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
             ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"), ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf")],
    "mono": [("consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"), ("DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf", "DejaVuSansMono-BoldOblique.ttf")],
}
FONT_DIRS = [Path(p) for p in ("C:/Windows/Fonts", "/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/msttcorefonts", "/Library/Fonts", "/System/Library/Fonts/Supplemental")]
INDIC = re.compile(r"[\u0900-\u0DFF]")


def _find(name: str) -> Path | None:
    for d in FONT_DIRS:
        p = d / name
        if p.exists():
            return p
        if d.exists():  # Linux file names are case-sensitive
            for q in d.glob("*"):
                if q.name.lower() == name.lower():
                    return q
    return None


_registered: dict[str, str] = {}


def pdf_font_family(kind: str) -> str:
    """Registers a Unicode TrueType family with reportlab and returns its name; falls back to built-in Helvetica/Times/Courier."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if kind in _registered:
        return _registered[kind]
    for files in FONT_FILES.get(kind, FONT_FILES["sans"]):
        paths = [_find(f) for f in files]
        if paths[0] is None:
            continue
        fam = f"Doc{kind.title()}{len(_registered)}"
        names = [f"{fam}", f"{fam}-B", f"{fam}-I", f"{fam}-BI"]
        for n, p in zip(names, paths):
            pdfmetrics.registerFont(TTFont(n, str(p or paths[0])))
        addMapping(fam, 0, 0, names[0]); addMapping(fam, 1, 0, names[1]); addMapping(fam, 0, 1, names[2]); addMapping(fam, 1, 1, names[3])
        _registered[kind] = fam
        return fam
    base = {"serif": "Times-Roman", "mono": "Courier"}.get(kind, "Helvetica")
    _registered[kind] = base
    return base


# ------------------------------------------------------------------ PDF
def render_pdf(doc: Doc, pal: Palette, out: Path) -> RenderResult:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Image, KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

    C = lambda h: colors.HexColor(h)  # noqa: E731
    body_f = pdf_font_family("sans" if pal.font_kind == "sans" else pal.font_kind)
    disp_f = pdf_font_family("serif" if pal.font_display in ("Georgia", "Cambria", "Times New Roman") else "sans")
    mono_f = pdf_font_family("mono")
    warnings: list[str] = []
    alltext = doc.title + doc.subtitle + " ".join(b.text + " ".join(b.items) + " ".join(b.columns) + " ".join(" ".join(r) for r in b.rows) for b in doc.blocks)
    if INDIC.search(alltext):
        warnings.append("This PDF contains Indian-language text. PDFs cannot join letters correctly for Tamil, Hindi and similar scripts; use the Word (.docx) version for those.")
    if body_f in ("Helvetica", "Times-Roman") and re.search(r"[^\x00-\xff]", alltext):
        warnings.append("No Unicode font was found on this PC, so some characters in the PDF may be missing.")

    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def markup(s: str) -> str:
        parts = []
        for t, st in runs(s):
            t = esc(t)
            parts.append({"b": f"<b>{t}</b>", "i": f"<i>{t}</i>", "c": f'<font name="{mono_f}" color="{pal.accent if contrast(pal.accent, pal.paper) >= 4.5 else pal.heading}">{t}</font>'}.get(st, t))
        return "".join(parts)

    base = ParagraphStyle("base", fontName=body_f, fontSize=10.5, leading=16, textColor=C(pal.text), alignment=TA_LEFT, spaceAfter=6)
    st = {
        "title": ParagraphStyle("title", parent=base, fontName=disp_f, fontSize=28, leading=33, textColor=C(pal.heading), spaceAfter=4),
        "subtitle": ParagraphStyle("sub", parent=base, fontSize=13, leading=18, textColor=C(pal.muted), spaceAfter=10),
        1: ParagraphStyle("h1", parent=base, fontName=disp_f, fontSize=19, leading=24, textColor=C(pal.heading), spaceBefore=14, spaceAfter=6),
        2: ParagraphStyle("h2", parent=base, fontName=disp_f, fontSize=15, leading=20, textColor=C(pal.heading), spaceBefore=10, spaceAfter=4),
        3: ParagraphStyle("h3", parent=base, fontName=disp_f, fontSize=12.5, leading=17, textColor=C(pal.text), spaceBefore=8, spaceAfter=3),
        "quote": ParagraphStyle("q", parent=base, fontSize=11, leftIndent=14, textColor=C(pal.muted), borderPadding=(2, 2, 2, 8), spaceBefore=4, spaceAfter=8),
        "cell": ParagraphStyle("cell", parent=base, fontSize=9.5, leading=13, spaceAfter=0),
        "cellh": ParagraphStyle("cellh", parent=base, fontSize=9.5, leading=13, spaceAfter=0, textColor=C(pal.accent_on), fontName=body_f),
        "code": ParagraphStyle("code", parent=base, fontName=mono_f, fontSize=8.8, leading=12, textColor=C(pal.text)),
    }

    from reportlab.platypus.doctemplate import BaseDocTemplate  # noqa: F401  (kept for clarity of the import graph)

    def on_page(canv, d):  # noqa: ANN001
        canv.saveState()
        canv.setFillColor(C(pal.paper)); canv.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
        canv.setFillColor(C(pal.accent)); canv.rect(0, A4[1] - 6 * mm, A4[0], 6 * mm, stroke=0, fill=1)
        canv.setFont(body_f, 8.5); canv.setFillColor(C(pal.muted))
        canv.drawString(20 * mm, 10 * mm, doc.title[:80])
        canv.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {d.page}")
        canv.restoreState()

    story: list = [Paragraph(esc(plain(doc.title)), st["title"])]
    if doc.subtitle:
        story.append(Paragraph(esc(doc.subtitle), st["subtitle"]))
    if doc.author:
        story.append(Paragraph(esc(doc.author), st["subtitle"]))
    story += [HRFlowable(width="100%", thickness=2, color=C(pal.accent), spaceBefore=2, spaceAfter=10)]
    usable = A4[0] - 40 * mm

    for b in doc.blocks:
        if b.type == "heading":
            p = Paragraph(markup(b.text), st[b.level])
            p.outline = plain(b.text)  # type: ignore[attr-defined]
            story.append(p)
        elif b.type == "paragraph":
            story.append(Paragraph(markup(b.text), base))
        elif b.type == "bullets":
            items = [ListItem(Paragraph(markup(it.strip()), base), leftIndent=14 + 12 * ((len(it) - len(it.lstrip())) // 2)) for it in b.items]
            story.append(ListFlowable(items, bulletType="1" if b.ordered else "bullet", start=None if b.ordered else "•", bulletFontName=body_f, bulletColor=C(pal.accent), leftIndent=14, spaceAfter=6))
        elif b.type == "table" and b.columns:
            data = [[Paragraph(markup(c), st["cellh"]) for c in b.columns]] + [[Paragraph(markup(c), st["cell"]) for c in r] for r in b.rows]
            lens = [max([len(plain(b.columns[j]))] + [len(plain(r[j])) for r in b.rows] or [1]) for j in range(len(b.columns))]
            tot = sum(min(max(n, 6), 40) for n in lens)
            widths = [usable * min(max(n, 6), 40) / tot for n in lens]
            t = Table(data, colWidths=widths, repeatRows=1)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), C(pal.accent)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C(pal.paper), C(pal.surface)]), ("LINEBELOW", (0, 0), (-1, -1), 0.4, C(pal.rule)),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]))
            story += [t, Spacer(1, 8)]
        elif b.type == "quote":
            q = Paragraph(markup(b.text), st["quote"])
            story.append(Table([[q]], colWidths=[usable], style=TableStyle([("LINEBEFORE", (0, 0), (0, -1), 3, C(pal.accent)), ("LEFTPADDING", (0, 0), (-1, -1), 10)])))
        elif b.type == "code":
            story.append(Table([[Preformatted(b.text, st["code"])]], colWidths=[usable], style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), C(pal.surface)), ("BOX", (0, 0), (-1, -1), 0.5, C(pal.rule)), ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)])))
            story.append(Spacer(1, 8))
        elif b.type == "image" and b.path and Path(b.path).exists():
            from PIL import Image as PILImage

            with PILImage.open(b.path) as im:
                w, h = im.size
            scale = min(usable / w, 110 * mm / h, 1.0 if w < usable else usable / w)
            story.append(KeepTogether([Image(b.path, width=w * scale, height=h * scale), Spacer(1, 8)]))
        elif b.type == "divider":
            story.append(HRFlowable(width="100%", thickness=0.6, color=C(pal.rule), spaceBefore=6, spaceAfter=8))
        elif b.type == "pagebreak":
            story.append(PageBreak())

    out.parent.mkdir(parents=True, exist_ok=True)
    pdf = SimpleDocTemplate(str(out), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=20 * mm, bottomMargin=18 * mm, title=plain(doc.title), author=doc.author or "")
    pdf.build(story, onFirstPage=on_page, onLaterPages=on_page)
    from pypdf import PdfReader

    return RenderResult(path=str(out), format="pdf", pages=len(PdfReader(str(out)).pages), warnings=warnings)


# ------------------------------------------------------------------ DOCX
def render_docx(doc: Doc, pal: Palette, out: Path) -> RenderResult:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    rgb = lambda h: RGBColor(*hex_to_rgb(h))  # noqa: E731
    d = Document()
    sec = d.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(2.2)
    sec.top_margin, sec.bottom_margin = Cm(2.2), Cm(2.0)

    def set_font(style, name: str, size: float | None = None, color: str | None = None, bold: bool | None = None) -> None:
        style.font.name = name
        rpr = style.element.get_or_add_rPr()
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts"); rpr.append(rf)
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(a), name)
        if size:
            style.font.size = Pt(size)
        if color:
            style.font.color.rgb = rgb(color)
        if bold is not None:
            style.font.bold = bold

    set_font(d.styles["Normal"], pal.font_body, 11, pal.text)
    d.styles["Normal"].paragraph_format.space_after = Pt(6)
    d.styles["Normal"].paragraph_format.line_spacing = 1.25
    set_font(d.styles["Title"], pal.font_display, 28, pal.heading, True)
    for lvl, size in ((1, 19), (2, 15), (3, 12.5)):
        set_font(d.styles[f"Heading {lvl}"], pal.font_display, size, pal.heading if lvl < 3 else pal.text, True)
        d.styles[f"Heading {lvl}"].paragraph_format.space_before = Pt(14 if lvl == 1 else 10)
    for name in ("List Bullet", "List Number", "List Bullet 2", "List Number 2"):
        set_font(d.styles[name], pal.font_body, 11, pal.text)

    def shade(cell_or_par, fill: str) -> None:
        el = cell_or_par._tc.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") else cell_or_par._p.get_or_add_pPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill.lstrip("#"))
        el.append(shd)

    def border(par, side: str, color: str, size: int = 12) -> None:
        ppr = par._p.get_or_add_pPr()
        pb = ppr.find(qn("w:pBdr"))
        if pb is None:
            pb = OxmlElement("w:pBdr"); ppr.append(pb)
        e = OxmlElement(f"w:{side}")
        e.set(qn("w:val"), "single"); e.set(qn("w:sz"), str(size)); e.set(qn("w:space"), "6"); e.set(qn("w:color"), color.lstrip("#"))
        pb.append(e)

    def add_runs(par, text: str, size: float | None = None, color: str | None = None) -> None:
        for t, stl in runs(text):
            r = par.add_run(t)
            if stl == "b":
                r.bold = True
            elif stl == "i":
                r.italic = True
            elif stl == "c":
                r.font.name = "Consolas"
                r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            if size:
                r.font.size = Pt(size)
            if color:
                r.font.color.rgb = rgb(color)

    d.core_properties.title = plain(doc.title)
    d.core_properties.author = doc.author or ""
    t = d.add_paragraph(style="Title")
    t.add_run(plain(doc.title))
    border(t, "bottom", pal.accent, 18)
    if doc.subtitle:
        p = d.add_paragraph(); add_runs(p, doc.subtitle, 13, pal.muted)
    if doc.author:
        p = d.add_paragraph(); add_runs(p, doc.author, 11, pal.muted)

    for b in doc.blocks:
        if b.type == "heading":
            p = d.add_paragraph(style=f"Heading {b.level}"); add_runs(p, b.text)
        elif b.type == "paragraph":
            add_runs(d.add_paragraph(), b.text)
        elif b.type == "bullets":
            for it in b.items:
                depth = (len(it) - len(it.lstrip())) // 2
                base = "List Number" if b.ordered else "List Bullet"
                p = d.add_paragraph(style=base + (" 2" if depth else "")); add_runs(p, it.strip())
        elif b.type == "table" and b.columns:
            tbl = d.add_table(rows=1, cols=len(b.columns))
            tbl.style = "Table Grid"
            tblpr = tbl._tbl.tblPr
            borders = OxmlElement("w:tblBorders")
            for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
                e = OxmlElement(f"w:{side}")
                e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:color"), pal.rule.lstrip("#"))
                borders.append(e)
            tblpr.append(borders)
            for j, c in enumerate(b.columns):
                cell = tbl.rows[0].cells[j]; shade(cell, pal.accent)
                cell.paragraphs[0].text = ""
                add_runs(cell.paragraphs[0], f"**{plain(c)}**", 10, pal.accent_on)
            for ri, r in enumerate(b.rows):
                cells = tbl.add_row().cells
                for j, v in enumerate(r):
                    cells[j].paragraphs[0].text = ""
                    add_runs(cells[j].paragraphs[0], v, 10)
                    if ri % 2 == 1:
                        shade(cells[j], pal.surface)
            # header row repeats on each page
            trpr = tbl.rows[0]._tr.get_or_add_trPr(); th = OxmlElement("w:tblHeader"); th.set(qn("w:val"), "true"); trpr.append(th)
            d.add_paragraph()
        elif b.type == "quote":
            p = d.add_paragraph(); add_runs(p, b.text, 11, pal.muted); p.paragraph_format.left_indent = Cm(0.8); border(p, "left", pal.accent, 24)
        elif b.type == "code":
            p = d.add_paragraph(); r = p.add_run(b.text); r.font.name = "Consolas"; r.font.size = Pt(9); shade(p, pal.surface)
        elif b.type == "image" and b.path and Path(b.path).exists():
            d.add_picture(b.path, width=Cm(15.5))
        elif b.type == "divider":
            p = d.add_paragraph(); border(p, "bottom", pal.rule, 6)
        elif b.type == "pagebreak":
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # footer with page number
    fp = sec.footer.paragraphs[0]
    fp.text = f"{plain(doc.title)[:60]}  ·  Page "
    for r in fp.runs:
        r.font.size = Pt(8.5); r.font.color.rgb = rgb(pal.muted)
    run = fp.add_run(); run.font.size = Pt(8.5); run.font.color.rgb = rgb(pal.muted)
    for kind, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), kind); run._r.append(fc)
        else:
            it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = txt; run._r.append(it)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(out))
    return RenderResult(path=str(out), format="docx")


# ------------------------------------------------------------------ PPTX
def render_pptx(doc: Doc, pal: Palette, out: Path) -> RenderResult:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    rgb = lambda h: RGBColor(*hex_to_rgb(h))  # noqa: E731
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    W, H = prs.slide_width, prs.slide_height
    warnings: list[str] = []

    def bg(slide, color: str) -> None:
        f = slide.background.fill
        f.solid(); f.fore_color.rgb = rgb(color)

    def rect(slide, x, y, w, h, color: str):
        s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
        s.fill.solid(); s.fill.fore_color.rgb = rgb(color); s.line.fill.background(); s.shadow.inherit = False
        return s

    def style_runs(par, text: str, size: float, color: str, font: str, bold: bool = False) -> None:
        for t, stl in runs(text):
            r = par.add_run(); r.text = t
            r.font.size = Pt(size); r.font.name = font; r.font.color.rgb = rgb(color)
            r.font.bold = bold or stl == "b"; r.font.italic = stl == "i"

    def footer(slide, n: int) -> None:
        tb = slide.shapes.add_textbox(W - Inches(1.5), H - Inches(0.55), Inches(1.0), Inches(0.35))
        p = tb.text_frame.paragraphs[0]; p.alignment = PP_ALIGN.RIGHT
        style_runs(p, str(n), 11, pal.muted, pal.font_body)

    def title_box(slide, text: str, top=Inches(0.55)) -> None:
        tb = slide.shapes.add_textbox(Inches(0.8), top, W - Inches(1.6), Inches(1.1))
        tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        style_runs(tf.paragraphs[0], text, 32 if len(text) < 48 else 26, pal.heading, pal.font_display, True)
        rect(slide, Inches(0.8), top + Inches(1.12), Inches(1.2), Emu(45720), pal.accent)

    blank = prs.slide_layouts[6]
    n = 0
    # title slide
    s = prs.slides.add_slide(blank); n += 1
    bg(s, pal.paper)
    rect(s, 0, 0, Inches(0.35), H, pal.accent)
    tb = s.shapes.add_textbox(Inches(1.0), Inches(2.1), W - Inches(2.2), Inches(2.0)); tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.BOTTOM
    style_runs(tf.paragraphs[0], plain(doc.title), 48 if len(doc.title) < 40 else 36, pal.heading, pal.font_display, True)
    sub = " · ".join(x for x in (doc.subtitle, doc.author) if x)
    if sub:
        tb2 = s.shapes.add_textbox(Inches(1.0), Inches(4.3), W - Inches(2.2), Inches(1.0)); tb2.text_frame.word_wrap = True
        style_runs(tb2.text_frame.paragraphs[0], sub, 20, pal.muted, pal.font_body)

    for sd in split_deck(doc):
        blocks: list[Block] = sd["blocks"]
        if not blocks and sd["level"] == 1:  # section divider
            s = prs.slides.add_slide(blank); n += 1
            bg(s, pal.accent)
            tb = s.shapes.add_textbox(Inches(1.0), Inches(2.8), W - Inches(2), Inches(1.6)); tb.text_frame.word_wrap = True
            style_runs(tb.text_frame.paragraphs[0], sd["title"], 44, pal.accent_on, pal.font_display, True)
            if sd["notes"]:
                s.notes_slide.notes_text_frame.text = sd["notes"]
            continue
        # chunk bullets so no slide overflows
        chunks: list[list[Block]] = [[]]
        weight = 0
        for b in blocks:
            if b.type == "bullets":
                items = list(b.items)
                while items:
                    room = max(1, 6 - weight)
                    take, items = items[:room], items[room:]
                    chunks[-1].append(Block(type="bullets", items=take, ordered=b.ordered, start=b.start + (len(b.items) - len(items) - len(take))))
                    weight += len(take)
                    if items:
                        chunks.append([]); weight = 0
            elif b.type == "table":
                if chunks[-1]:
                    chunks.append([])
                chunks[-1].append(b); chunks.append([]); weight = 0
            else:
                chunks[-1].append(b); weight += 2
        chunks = [c for c in chunks if c] or [[]]
        for ci, chunk in enumerate(chunks):
            s = prs.slides.add_slide(blank); n += 1
            bg(s, pal.paper)
            rect(s, 0, 0, W, Inches(0.12), pal.accent)
            title_box(s, sd["title"] + (" (cont.)" if ci else ""))
            y = Inches(2.05)
            for b in chunk:
                avail = H - y - Inches(0.8)
                if b.type == "bullets":
                    total = sum(len(plain(i)) for i in b.items)
                    size = 26 if len(b.items) <= 3 and total < 160 else 22 if len(b.items) <= 5 and total < 300 else 18
                    tb = s.shapes.add_textbox(Inches(0.8), y, W - Inches(1.6), avail); tf = tb.text_frame; tf.word_wrap = True
                    for k, it in enumerate(b.items):
                        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                        depth = (len(it) - len(it.lstrip())) // 2
                        mark = f"{k + b.start}. " if b.ordered else "•  "
                        p.level = min(depth, 4)
                        p.space_after = Pt(10)
                        style_runs(p, ("      " * depth) + mark + it.strip(), size - 2 * depth, pal.text, pal.font_body)
                    y += Inches(0.5) * len(b.items) + Inches(0.3)
                elif b.type == "table" and b.columns:
                    rows, cols = len(b.rows[:8]) + 1, len(b.columns)
                    shape = s.shapes.add_table(rows, cols, Inches(0.8), y, W - Inches(1.6), Inches(0.6) * rows)
                    tbl = shape.table
                    for j, c in enumerate(b.columns):
                        cell = tbl.cell(0, j); cell.fill.solid(); cell.fill.fore_color.rgb = rgb(pal.accent)
                        cell.text_frame.paragraphs[0].text = ""
                        style_runs(cell.text_frame.paragraphs[0], plain(c), 18, pal.accent_on, pal.font_body, True)
                    for i2, r in enumerate(b.rows[:8], start=1):
                        for j, v in enumerate(r):
                            cell = tbl.cell(i2, j); cell.fill.solid(); cell.fill.fore_color.rgb = rgb(pal.surface if i2 % 2 == 0 else pal.paper)
                            cell.text_frame.paragraphs[0].text = ""
                            style_runs(cell.text_frame.paragraphs[0], plain(v), 16, pal.text, pal.font_body)
                    if len(b.rows) > 8:
                        warnings.append(f"Slide “{sd['title']}”: table shortened to 8 rows to fit.")
                    y += Inches(0.6) * rows + Inches(0.3)
                elif b.type == "image" and b.path and Path(b.path).exists():
                    from PIL import Image as PILImage

                    with PILImage.open(b.path) as im:
                        iw, ih = im.size
                    maxw, maxh = W - Inches(1.6), avail
                    sc = min(maxw / iw, maxh / ih)
                    s.shapes.add_picture(b.path, Inches(0.8) + int((maxw - iw * sc) / 2), y, int(iw * sc), int(ih * sc))
                    y += int(ih * sc) + Inches(0.2)
                elif b.type in {"paragraph", "quote", "code"}:
                    tb = s.shapes.add_textbox(Inches(0.8), y, W - Inches(1.6), Inches(1.2)); tf = tb.text_frame; tf.word_wrap = True
                    style_runs(tf.paragraphs[0], b.text if b.type != "code" else b.text.replace("\n", "  "), 20 if b.type != "code" else 16, pal.muted if b.type == "quote" else pal.text, "Consolas" if b.type == "code" else pal.font_body)
                    y += Inches(0.5) + Inches(0.35) * (len(b.text) // 90)
            if sd["notes"]:
                s.notes_slide.notes_text_frame.text = sd["notes"]
            footer(s, n)

    out.parent.mkdir(parents=True, exist_ok=True)
    prs.core_properties.title = plain(doc.title)
    prs.core_properties.author = doc.author or ""
    prs.save(str(out))
    return RenderResult(path=str(out), format="pptx", pages=n, warnings=warnings)


# ------------------------------------------------------------------ CSV / XLSX
@dataclass
class Table:
    columns: list[str]
    rows: list[list[str]] = field(default_factory=list)


def tables_of(doc: Doc) -> list[Table]:
    return [Table(b.columns, b.rows) for b in doc.blocks if b.type == "table" and b.columns]


def render_csv(table: Table, out: Path) -> RenderResult:
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow([plain(c) for c in table.columns])
    for r in table.rows:
        w.writerow([plain(c) for c in r])
    out.write_bytes(b"\xef\xbb\xbf" + buf.getvalue().encode("utf-8"))  # BOM so Excel opens Tamil/Hindi/accents correctly
    return RenderResult(path=str(out), format="csv")


def _num(v: str):  # noqa: ANN202
    s = v.strip().replace(",", "")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d*\.\d+", s):
        return float(s)
    return v


def render_xlsx(tables: list[Table], pal: Palette, out: Path, names: list[str] | None = None) -> RenderResult:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    for k, t in enumerate(tables or [Table(["Empty"], [])]):
        ws = wb.create_sheet((names[k] if names and k < len(names) else f"Sheet{k + 1}")[:31])
        ws.append([plain(c) for c in t.columns])
        for r in t.rows:
            ws.append([_num(plain(c)) for c in r])
        for c in ws[1]:
            c.font = Font(bold=True, color=pal.accent_on.lstrip("#"), name=pal.font_body)
            c.fill = PatternFill("solid", fgColor=pal.accent.lstrip("#"))
            c.alignment = Alignment(vertical="center", wrap_text=True)
        for j, col in enumerate(t.columns, start=1):
            width = max([len(plain(col))] + [len(plain(r[j - 1])) for r in t.rows[:200] if j - 1 < len(r)] or [8])
            ws.column_dimensions[get_column_letter(j)].width = min(max(10, width + 2), 60)
        ws.freeze_panes = "A2"
        if t.rows:
            ws.auto_filter.ref = ws.dimensions
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out))
    return RenderResult(path=str(out), format="xlsx")


# ------------------------------------------------------------------ entry point
FORMATS = ("pdf", "docx", "pptx", "csv", "xlsx")


def build_file(fmt: str, doc: Doc, out_dir: Path, name: str, theme_id: str | None = None) -> RenderResult:
    fmt = fmt.lower()
    if fmt not in FORMATS:
        raise ValueError(f"Unknown format '{fmt}'. Choose one of: {', '.join(FORMATS)}.")
    theme = get_theme(theme_id)
    pal = document_palette(theme, on_slides=(fmt == "pptx"))
    safe = re.sub(r"[^\w .-]+", "_", name, flags=re.UNICODE).strip(" ._") or "document"
    out = out_dir / f"{safe}.{fmt}"
    n = 1
    while out.exists():
        n += 1
        out = out_dir / f"{safe} ({n}).{fmt}"
    if fmt == "pdf":
        return render_pdf(doc, pal, out)
    if fmt == "docx":
        return render_docx(doc, pal, out)
    if fmt == "pptx":
        return render_pptx(doc, pal, out)
    tables = tables_of(doc)
    if not tables:
        raise ValueError("There is no table to export. Provide a Markdown table (| a | b |) or rows and columns.")
    if fmt == "csv":
        r = render_csv(tables[0], out)
        if len(tables) > 1:
            r.warnings.append(f"The content has {len(tables)} tables; CSV holds one, so only the first was saved. Use Excel (.xlsx) to keep all of them.")
        return r
    return render_xlsx(tables, pal, out)
