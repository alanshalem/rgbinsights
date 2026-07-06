"""Use cases — orchestrate the source, repos, and domain rules.

Expected failures (post not found, challenge) are returned as Result.Err, never
raised, so the API can map them to clean HTTP responses. This package keeps the
public surface flat: import everything from `app.application.use_cases`.
"""

from __future__ import annotations

from app.application.use_cases._shared import (
    KEY_DMS_SYNCED,
    KEY_RELATIONS_SYNCED,
    ProgressFn,
    map_instagram_error,
    state_delta,
)
from app.application.use_cases.enrich import EnrichProfilesUseCase
from app.application.use_cases.list_users import ListUsersUseCase, event_counts
from app.application.use_cases.scan import (
    RescanEventUseCase,
    ScanPostsUseCase,
    ScanPostUseCase,
)
from app.application.use_cases.sync import SyncDmsUseCase

__all__ = [
    "KEY_DMS_SYNCED",
    "KEY_RELATIONS_SYNCED",
    "EnrichProfilesUseCase",
    "ListUsersUseCase",
    "ProgressFn",
    "RescanEventUseCase",
    "ScanPostUseCase",
    "ScanPostsUseCase",
    "SyncDmsUseCase",
    "event_counts",
    "map_instagram_error",
    "state_delta",
]
