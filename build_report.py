#!/usr/bin/env python3
"""Render report.pdf from REPORT.md (lightweight Markdown subset).

Run with the project venv (has reportlab):
    .venv/bin/python build_report.py
The comparison section is rendered exactly as written in REPORT.md -
while it still contains <<placeholders>>, the PDF is a DRAFT and says so
on the cover. Once REPORT.md is filled from a live results.csv, rebuild.
"""
import os
import re

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)
from reportlab.lib import colors

ROOT = os.path.dirname(os.path.abspath(__file__))


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("`", "").replace("**", ""))


def build():
    src = open(os.path.join(ROOT, "REPORT.md")).read()
    draft = "<<" in src
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=19, leading=23)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13.5,
                        leading=17, spaceBefore=12)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.3,
                          leading=14.5, spaceAfter=6)
    quote = ParagraphStyle("quote", parent=body, leftIndent=10,
                           textColor=colors.HexColor("#555555"))
    story = []
    if draft:
        story.append(Paragraph(
            "DRAFT — comparison section contains placeholders to be filled "
            "from the live results.csv", quote))
        story.append(Spacer(1, 6))
    lines = src.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            header = [c.strip() for c in line.strip("|").split("|")]
            rows = [header]
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            data = [[Paragraph(esc(c), body) for c in r] for r in rows]
            t = Table(data, hAlign="LEFT", repeatRows=1,
                      colWidths=[(A4[0] - 36 * mm) / len(header)] * len(header))
            t.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEEEEE")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(t)
            story.append(Spacer(1, 6))
            continue
        if line.startswith("# "):
            story.append(Paragraph(esc(line[2:]), h1))
        elif line.startswith("## "):
            story.append(Paragraph(esc(line[3:]), h2))
        elif line.startswith("---"):
            story.append(Spacer(1, 4))
        elif line.startswith("> "):
            story.append(Paragraph(esc(line[2:]), quote))
        elif line.strip():
            story.append(Paragraph(esc(line), body))
        i += 1
    out = os.path.join(ROOT, "report.pdf")
    SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=16 * mm, bottomMargin=16 * mm,
                      title="YGF AI Security POC Report").build(story)
    print(f"wrote {out} (draft={draft})")


if __name__ == "__main__":
    build()
