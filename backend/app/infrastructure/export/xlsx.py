"""Excel renderer for the semáforo export.

Sheet "Semáforo" keeps the table at A1 (header row bold, frozen, autofilter) so
publicas can sort/filter straight away; the fiesta, date, filters and total go
on a separate "Info" sheet instead of rows above the table.
"""

from __future__ import annotations

import re
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, Cell
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.application.use_cases.export_users import UserExport
from app.infrastructure.export.columns import COLUMNS, LINK_COLOR, STATUS_FILL, Value

MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_STATUS_COL = next(i for i, c in enumerate(COLUMNS, 1) if c.header == "Estado")
# XML 1.0 also forbids U+FFFE/U+FFFF and lone surrogates; openpyxl's regex
# misses them and the workbook would not open.
_NON_XML_RE = re.compile("[￾￿\ud800-\udfff]")


def _set(cell: Cell, value: Value) -> None:
    if isinstance(value, str):
        value = _NON_XML_RE.sub("", ILLEGAL_CHARACTERS_RE.sub("", value))
    cell.value = value
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"  # a name like "=HYPERLINK(...)" stays text, never a formula


def render_xlsx(export: UserExport) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Semáforo"

    bold = Font(bold=True)
    link_font = Font(color=LINK_COLOR, underline="single")
    ws.append([c.header for c in COLUMNS])
    for cell in ws[1]:
        cell.font = bold

    for r, row in enumerate(export.rows, start=2):
        for col, spec in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=r, column=col)
            _set(cell, spec.value(row))
            if spec.link is not None:
                cell.hyperlink = spec.link(row)
                cell.font = link_font
        fill = "FF" + STATUS_FILL[row.status]  # opaque ARGB
        ws.cell(row=r, column=_STATUS_COL).fill = PatternFill(
            "solid", start_color=fill, end_color=fill
        )

    last = get_column_letter(len(COLUMNS))
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{last}{export.total + 1}"
    for col, spec in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(col)].width = spec.xlsx_width

    info = wb.create_sheet("Info")
    meta: tuple[tuple[str, Value], ...] = (
        ("Fiesta", export.title),
        ("Exportado", f"{export.generated_at:%Y-%m-%d %H:%M}"),
        ("Filtros", " · ".join(export.filters)),
        ("Total", export.total),
        ("Posts de la fiesta", export.posts_total),
    )
    for r, (label, value) in enumerate(meta, start=1):
        info.cell(row=r, column=1, value=label).font = bold
        _set(info.cell(row=r, column=2), value)
    info.column_dimensions["A"].width = 20
    info.column_dimensions["B"].width = 70

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
