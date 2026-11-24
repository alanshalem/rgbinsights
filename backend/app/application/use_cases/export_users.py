"""Read-side use case: the on-screen semáforo list as plain export rows (S23).

Scope is "lo que está en pantalla": the same params `/users` takes, but every
matching row (no limit/offset). The board view shows one column per color, so
`by_status=True` concatenates the red, yellow and green lists, each in the
current order, exactly as the three board columns query them. Reads only the
local DB: never touches Instagram (S0). Rendering (xlsx/pdf) lives in
`app.infrastructure.export`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo

from sqlmodel import Session

from app.application.dto import UserView
from app.application.use_cases.list_users import ListUsersUseCase
from app.domain.entities import EngagementType
from app.domain.traffic_light import TrafficLight
from app.infrastructure.persistence.repositories import EventRepository, PostRepository
from app.infrastructure.persistence.user_list import UserFilter, UserListQuery

STATUS_LABEL: dict[TrafficLight, str] = {
    TrafficLight.RED: "Rojo",
    TrafficLight.YELLOW: "Amarillo",
    TrafficLight.GREEN: "Verde",
}
_BOARD_ORDER = (TrafficLight.RED, TrafficLight.YELLOW, TrafficLight.GREEN)
_ORDER_LABEL = {
    "status": "estado",
    "fans": "fans",
    "followers": "seguidores",
    "username": "usuario",
}
ALL_EVENTS_TITLE = "Todas las fiestas"


@dataclass(frozen=True, slots=True)
class ExportRow:
    username: str
    profile_url: str
    dm_url: str  # the app's action link: the DM thread, or the profile if none
    has_thread: bool
    full_name: str
    status: TrafficLight
    status_label: str  # Rojo / Amarillo / Verde
    follows_us: str  # "Sí" / "No" / "—" (relation not synced yet)
    follower_count: int | None
    likes: int  # within the exported fiesta/post
    comments: int
    posts_engaged: int  # distinct posts engaged within the fiesta/post


@dataclass(frozen=True, slots=True)
class UserExport:
    title: str  # fiesta name, or "Todas las fiestas"
    slug: str
    generated_at: datetime  # local (Argentina) time
    filters: tuple[str, ...]  # human-readable filters applied
    posts_total: int  # posts in the fiesta (1 with a post filter, 0 globally)
    rows: tuple[ExportRow, ...]

    @property
    def total(self) -> int:
        return len(self.rows)

    def filename(self, ext: str) -> str:
        return f"semaforo-{self.slug}-{self.generated_at:%Y-%m-%d}.{ext}"


def slugify(text: str) -> str:
    """ASCII, lowercase, dash-separated ("Fiesta Ñandú!" -> "fiesta-nandu")."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


class ExportUsersUseCase:
    def __init__(self, session: Session, tz: tzinfo = UTC) -> None:
        self._session = session
        self._tz = tz
        self._users = ListUsersUseCase(session)

    def execute(
        self,
        event: int | None = None,
        post: str | None = None,
        status: TrafficLight | None = None,
        search: str | None = None,
        order: str = "status",
        follows: bool | None = None,
        by_status: bool = False,
        now: datetime | None = None,
    ) -> UserExport:
        groups: tuple[TrafficLight | None, ...] = (
            _BOARD_ORDER if by_status and status is None else (status,)
        )
        views = [
            view
            for light in groups
            for view in self._users.execute(
                event=event,
                post=post,
                status=light,
                search=search,
                order=order,
                follows=follows,
            )
        ]
        title = self._title(event)
        posts_total = UserListQuery(self._session).event_posts_total(
            UserFilter(event=event, post=post)
        )
        return UserExport(
            title=title,
            slug=slugify(title) or "semaforo",
            generated_at=(now or datetime.now(UTC)).astimezone(self._tz),
            filters=self._filters(post, status, search, order, follows, by_status),
            posts_total=posts_total,
            rows=tuple(_to_row(v) for v in views),
        )

    def _title(self, event: int | None) -> str:
        if event is None:
            return ALL_EVENTS_TITLE
        found = EventRepository(self._session).get(event)
        return found.name if found is not None else f"Fiesta #{event}"

    def _filters(
        self,
        post: str | None,
        status: TrafficLight | None,
        search: str | None,
        order: str,
        follows: bool | None,
        by_status: bool,
    ) -> tuple[str, ...]:
        out = ["Vista: tablero (por color)" if by_status else "Vista: tabla"]
        if post is not None:
            found = PostRepository(self._session).get(post)
            out.append(f"Post: {found.shortcode if found is not None else post}")
        if status is not None:
            out.append(f"Estado: {STATUS_LABEL[status]}")
        if search:
            out.append(f'Búsqueda: "{search}"')
        if follows is True:
            out.append("Solo seguidores")
        out.append(f"Orden: {_ORDER_LABEL.get(order, _ORDER_LABEL['status'])}")
        return tuple(out)


def _follows_label(follows_us: bool | None) -> str:
    if follows_us is None:
        return "—"
    return "Sí" if follows_us else "No"


def _to_row(view: UserView) -> ExportRow:
    likes = sum(1 for e in view.engagements if e.type is EngagementType.LIKE)
    return ExportRow(
        username=view.username,
        profile_url=f"https://instagram.com/{view.username}/",
        dm_url=view.action_url,
        has_thread=view.thread_id is not None,
        full_name=view.full_name,
        status=view.traffic_light,
        status_label=STATUS_LABEL[view.traffic_light],
        follows_us=_follows_label(view.follows_us),
        follower_count=view.follower_count,
        likes=likes,
        comments=len(view.engagements) - likes,
        posts_engaged=view.event_engaged,
    )
