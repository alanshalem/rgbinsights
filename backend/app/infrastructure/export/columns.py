"""Column layout shared by the xlsx and pdf renderers (one definition, S23)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.application.use_cases.export_users import ExportRow
from app.domain.traffic_light import TrafficLight

Value = str | int | None


@dataclass(frozen=True, slots=True)
class Column:
    header: str
    value: Callable[[ExportRow], Value]
    link: Callable[[ExportRow], str] | None = None  # clickable target, if any
    xlsx_width: float = 12
    pdf_width: float = 20  # mm (A4 landscape usable width ~277 mm)
    pdf_value: Callable[[ExportRow], Value] | None = None  # shorter text for the PDF
    is_status: bool = False  # the estado cell: filled with the row's semáforo color

    def pdf_text(self, row: ExportRow) -> str:
        value = (self.pdf_value or self.value)(row)
        return "—" if value is None else str(value)


COLUMNS: tuple[Column, ...] = (
    Column(
        "Usuario",
        lambda r: f"@{r.username}",
        link=lambda r: r.profile_url,
        xlsx_width=24,
        pdf_width=36,
    ),
    Column("Nombre", lambda r: r.full_name, xlsx_width=30, pdf_width=50),
    Column("Estado", lambda r: r.status_label, xlsx_width=11, pdf_width=18, is_status=True),
    Column("Te sigue", lambda r: r.follows_us, xlsx_width=10, pdf_width=15),
    Column("Seguidores", lambda r: r.follower_count, xlsx_width=12, pdf_width=19),
    Column("Likes", lambda r: r.likes, xlsx_width=8, pdf_width=12),
    Column("Comentarios", lambda r: r.comments, xlsx_width=13, pdf_width=20),
    Column("Posts", lambda r: r.posts_engaged, xlsx_width=8, pdf_width=12),
    Column(
        "Perfil",
        lambda r: r.profile_url,
        link=lambda r: r.profile_url,
        xlsx_width=38,
        pdf_width=60,
        pdf_value=lambda r: r.profile_url.removeprefix("https://"),
    ),
    Column(
        "Link DM",
        lambda r: r.dm_url,
        link=lambda r: r.dm_url,
        xlsx_width=44,
        pdf_width=35,
        pdf_value=lambda r: "Abrir DM" if r.has_thread else "Ver perfil",
    ),
)

# Soft fills per estado (Excel's "good/neutral/bad" tones).
STATUS_FILL: dict[TrafficLight, str] = {
    TrafficLight.RED: "FFC7CE",
    TrafficLight.YELLOW: "FFEB9C",
    TrafficLight.GREEN: "C6EFCE",
}
LINK_COLOR = "0563C1"
