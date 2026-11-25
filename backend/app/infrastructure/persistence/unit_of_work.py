"""SqlUnitOfWork: the application's UnitOfWork port over one SQLModel session."""

from __future__ import annotations

from types import TracebackType

from sqlmodel import Session

from app.infrastructure.persistence.repositories import (
    ActivityRepository,
    AppStateRepository,
    DmThreadRepository,
    EngagementRepository,
    EventRepository,
    FollowGraphRepository,
    PostRepository,
    UserRepository,
)
from app.infrastructure.persistence.user_list import UserListQuery


class SqlUnitOfWork:
    """Every repository over the same session. As a context manager it closes
    the session on exit (uncommitted changes are rolled back)."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.posts = PostRepository(session)
        self.engagements = EngagementRepository(session)
        self.dm_threads = DmThreadRepository(session)
        self.follow_graph = FollowGraphRepository(session)
        self.events = EventRepository(session)
        self.app_state = AppStateRepository(session)
        self.activity = ActivityRepository(session)
        self.user_list = UserListQuery(session)

    def commit(self) -> None:
        self.session.commit()

    def __enter__(self) -> SqlUnitOfWork:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.session.close()
