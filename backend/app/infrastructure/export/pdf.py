"""PDF renderer for the semáforo export: A4 landscape, one table, page numbers.

Uses fpdf2's built-in Helvetica (latin-1): Spanish accents and ñ render as-is.
Characters outside latin-1 are folded where Unicode allows ("𝓜𝓲𝓪" -> "Mia",
curly quotes -> straight), unknown letters become "?" and emoji/symbols are
dropped, so a fancy Instagram name never breaks the export. The Excel export
keeps the original text untouched.
"""

from __future__ import annotations

import unicodedata

from fpdf import FPDF
from fpdf.enums import Align, TableCellFillMode, WrapMode
from fpdf.fonts import FontFace

from app.application.use_cases.export_users import UserExport
from app.infrastructure.export.columns import COLUMNS, LINK_COLOR, STATUS_FILL

MEDIA_TYPE = "application/pdf"
_FONT = "Helvetica"
_PUNCT = str.maketrans(
    {
        "—": "-",
        "–": "-",
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
        "•": "·",
    }
)


def latin1(text: str) -> str:
    out: list[str] = []
    for ch in unicodedata.normalize("NFKC", text).translate(_PUNCT):
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf") and ch not in "\t\n":
            continue
        if ord(ch) < 256:
            out.append(ch)
        elif cat[0] in "LN":
            out.append("?")
        # else: emoji / symbol / combining mark outside latin-1 -> dropped
    return " ".join("".join(out).split())


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return (int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16))


class _Doc(FPDF):
    def footer(self) -> None:
        self.set_y(-10)
        self.set_font(_FONT, size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, f"Página {self.page_no()} de {{nb}}", align=Align.C)


def render_pdf(export: UserExport) -> bytes:
    pdf = _Doc(orientation="L", unit="mm", format="A4")
    pdf.set_title(latin1(f"Semáforo - {export.title}"))
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.set_font(_FONT, style="B", size=15)
    pdf.cell(0, 8, latin1(f"Semáforo · {export.title}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_FONT, size=9)
    pdf.set_text_color(90, 90, 90)
    summary = f"Exportado {export.generated_at:%d/%m/%Y %H:%M} · Total: {export.total}"
    if export.posts_total:
        summary += f" · Posts de la fiesta: {export.posts_total}"
    pdf.cell(0, 5, latin1(summary), new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 5, latin1("Filtros: " + " · ".join(export.filters)))
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    if not export.rows:
        pdf.set_font(_FONT, size=11)
        pdf.cell(0, 8, "Sin resultados para estos filtros.")
        return bytes(pdf.output())

    link_style = FontFace(color=_rgb(LINK_COLOR))
    status_style = {
        light: FontFace(emphasis="BOLD", fill_color=_rgb(fill))
        for light, fill in STATUS_FILL.items()
    }
    pdf.set_font(_FONT, size=8)
    with pdf.table(
        col_widths=tuple(c.pdf_width for c in COLUMNS),
        width=sum(c.pdf_width for c in COLUMNS),
        text_align=Align.L,
        line_height=4.5,
        headings_style=FontFace(emphasis="BOLD", fill_color=(235, 235, 235)),
        cell_fill_mode=TableCellFillMode.NONE,
        repeat_headings=1,
        wrapmode=WrapMode.CHAR,
    ) as table:
        header = table.row()
        for c in COLUMNS:
            header.cell(c.header)
        for row in export.rows:
            cells = table.row()
            for c in COLUMNS:
                text = latin1(c.pdf_text(row))
                if c.is_status:
                    cells.cell(text, style=status_style[row.status])
                elif c.link is not None:
                    cells.cell(text, style=link_style, link=c.link(row))
                else:
                    cells.cell(text)
    return bytes(pdf.output())
