"""Use cases — orchestrate the source, repos, and domain rules.

Expected failures (post not found, challenge) are returned as Result.Err, never
raised, so the API can map them to clean HTTP responses. This package keeps the
public surface flat: import everything from `app.application.use_cases`.
"""

from __future__ import annotations

from app.application.use_cases._shared import (
    KEY_DMS_SYNCED,
    KEY_RELATIONS_SYNCED,
    map_instagram_error,
    state_delta,
)
from app.application.use_cases.enrich import EnrichProfilesUseCase
from app.application.use_cases.export_users import (
    ExportRow,
    ExportUsersUseCase,
    UserExport,
)
from app.application.use_cases.list_users import (
    DEFAULT_ORDER,
    ORDER_PATTERN,
    ListUsersUseCase,
    event_counts,
)
from app.application.use_cases.scan import (
    RescanEventUseCase,
    ScanPostsUseCase,
    ScanPostUseCase,
)
from app.application.use_cases.sync import SyncDmsUseCase

__all__ = [
    "DEFAULT_ORDER",
    "KEY_DMS_SYNCED",
    "KEY_RELATIONS_SYNCED",
    "EnrichProfilesUseCase",
    "ExportRow",
    "ExportUsersUseCase",
    "ListUsersUseCase",
    "ORDER_PATTERN",
    "RescanEventUseCase",
    "ScanPostUseCase",
    "ScanPostsUseCase",
    "SyncDmsUseCase",
    "UserExport",
    "event_counts",
    "map_instagram_error",
    "state_delta",
]
