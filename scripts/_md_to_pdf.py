"""One-shot Markdown -> PDF using PySide6 (no extra deps).

Renders FEATURE_AND_CODE_REVIEW.md to FEATURE_AND_CODE_REVIEW.pdf using a
minimal Markdown -> HTML conversion (QTextDocument.setMarkdown) and
QPagedPaintDevice / QPdfWriter pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPdfWriter, QTextDocument
from PySide6.QtWidgets import QApplication


def main(src: Path, dst: Path) -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    _ = app

    md = src.read_text(encoding="utf-8")

    doc = QTextDocument()
    doc.setDefaultStyleSheet(
        """
        body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 10pt; color: #1a1a1a; }
        h1 { color: #0a3d62; font-size: 22pt; margin-top: 18pt; margin-bottom: 8pt; border-bottom: 2px solid #0a3d62; padding-bottom: 4pt; }
        h2 { color: #0a3d62; font-size: 16pt; margin-top: 14pt; margin-bottom: 6pt; }
        h3 { color: #1e5a8a; font-size: 13pt; margin-top: 10pt; margin-bottom: 4pt; }
        h4 { color: #1e5a8a; font-size: 11pt; margin-top: 8pt; }
        p  { line-height: 1.45; margin: 4pt 0; }
        ul, ol { margin: 4pt 0 6pt 0; }
        li { margin: 2pt 0; line-height: 1.4; }
        code { font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 9pt; background: #f0f4f8; padding: 1pt 3pt; border-radius: 2pt; }
        pre  { background: #f6f8fa; padding: 8pt; font-family: 'SF Mono', Menlo, Consolas, monospace; font-size: 9pt; }
        table { border-collapse: collapse; margin: 6pt 0; }
        th, td { border: 1px solid #c8d2dc; padding: 4pt 8pt; font-size: 9.5pt; vertical-align: top; }
        th { background: #e7eef5; color: #0a3d62; font-weight: bold; text-align: left; }
        blockquote { border-left: 3px solid #0a3d62; margin: 6pt 0; padding: 2pt 10pt; color: #555; }
        hr { border: 0; border-top: 1px solid #c8d2dc; margin: 12pt 0; }
        strong { color: #0a3d62; }
        """
    )
    doc.setMarkdown(md, QTextDocument.MarkdownDialectGitHub)

    writer = QPdfWriter(str(dst))
    writer.setResolution(96)
    page = QPageLayout(
        QPageSize(QPageSize.Letter),
        QPageLayout.Portrait,
        QMarginsF(18, 18, 18, 18),
        QPageLayout.Millimeter,
    )
    writer.setPageLayout(page)
    writer.setTitle("Sea Lyon Media Manager - Feature & Code Review")
    writer.setCreator("Sea Lyon Media Manager engineering review")

    page_size_px = QSizeF(
        page.paintRectPixels(writer.resolution()).width(),
        page.paintRectPixels(writer.resolution()).height(),
    )
    doc.setPageSize(page_size_px)
    doc.print_(writer)
    print(f"Wrote {dst}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    src = root / "FEATURE_AND_CODE_REVIEW.md"
    dst = root / "FEATURE_AND_CODE_REVIEW.pdf"
    main(src, dst)
