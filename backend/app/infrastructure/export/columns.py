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

    def pdf_text(self, row: ExportRow) -> str:
        value = (self.pdf_value or self.value)(row)
        return "—" if value is None else str(value)


COLUMNS: tuple[Column, ...] = (
    Column("Usuario", lambda r: f"@{r.username}", lambda r: r.profile_url, 24, 36),
    Column("Nombre", lambda r: r.full_name, None, 30, 50),
    Column("Estado", lambda r: r.status_label, None, 11, 18),
    Column("Te sigue", lambda r: r.follows_us, None, 10, 15),
    Column("Seguidores", lambda r: r.follower_count, None, 12, 19),
    Column("Likes", lambda r: r.likes, None, 8, 12),
    Column("Comentarios", lambda r: r.comments, None, 13, 20),
    Column("Posts", lambda r: r.posts_engaged, None, 8, 12),
    Column(
        "Perfil",
        lambda r: r.profile_url,
        lambda r: r.profile_url,
        38,
        60,
        lambda r: r.profile_url.removeprefix("https://"),
    ),
    Column(
        "Link DM",
        lambda r: r.dm_url,
        lambda r: r.dm_url,
        44,
        35,
        lambda r: "Abrir DM" if r.has_thread else "Ver perfil",
    ),
)

# Soft fills per estado (Excel's "good/neutral/bad" tones).
STATUS_FILL: dict[TrafficLight, str] = {
    TrafficLight.RED: "FFC7CE",
    TrafficLight.YELLOW: "FFEB9C",
    TrafficLight.GREEN: "C6EFCE",
}
LINK_COLOR = "0563C1"
