"""The in-app configuration (S25): what the "Configuración" screen reads and
saves, and the one place every other part reads the effective values from.

Effective value = the stored override if the user set one, else the default
(an older .env value, else the factory value), always inside the safety bounds
of app.domain.config (S0). The overrides live in the DB; this service keeps
them in memory too, so the Instagram guard and the adapter read them on every
request without touching the DB (it never waits on a use case's transaction).
All changes go through this service: a saved value applies from the next
Instagram request on — never in the middle of one.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from app.application.ports import ConfigStore
from app.domain import config as cfg
from app.domain.config import RuntimeConfig, SettingSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfigEntry:
    """One setting as the screen shows it."""

    spec: SettingSpec
    value: Any
    default: Any
    overridden: bool  # a stored value that is used (an unreadable one is ignored)
    # What an older .env asked for when it had to be pulled inside the bounds.
    clamped_from: float | None = None


class RuntimeConfigService:
    def __init__(self, store: ConfigStore, defaults: Callable[[], RuntimeConfig]) -> None:
        """`defaults` gives the raw defaults (environment or factory values; they
        are pulled inside the bounds here)."""
        self._store = store
        self._defaults = defaults
        self._lock = threading.Lock()
        self._overrides: dict[str, object] = {}

    def load(self) -> None:
        """Read the stored overrides (on startup, after the tables exist)."""
        stored = self._store.load()
        with self._lock:
            self._overrides = dict(stored)
        for key, asked in cfg.clamped_defaults(self._defaults()).items():
            logger.warning(
                "%s=%s in the environment is faster than allowed: using %s",
                key,
                asked,
                getattr(self.defaults(), key),
            )
        for key, value in stored.items():
            if not cfg.readable(key, value):
                logger.warning("ignoring the stored %s=%r: not a usable setting", key, value)

    # -- reads ----------------------------------------------------------------

    def defaults(self, raw: RuntimeConfig | None = None) -> RuntimeConfig:
        return cfg.safe_defaults(raw if raw is not None else self._defaults())

    def current(self) -> RuntimeConfig:
        """The effective configuration (memory only, safe on every request)."""
        return self.effective()

    def effective(self, raw_defaults: RuntimeConfig | None = None) -> RuntimeConfig:
        """The effective values over these raw defaults (the configured ones by
        default)."""
        with self._lock:
            overrides = dict(self._overrides)
        return cfg.effective(self.defaults(raw_defaults), overrides)

    def entries(self) -> list[ConfigEntry]:
        with self._lock:
            overrides = dict(self._overrides)
        raw = self._defaults()
        defaults = self.defaults(raw)
        clamped = cfg.clamped_defaults(raw)
        current = cfg.effective(defaults, overrides)
        return [
            ConfigEntry(
                spec=spec,
                value=getattr(current, spec.key),
                default=getattr(defaults, spec.key),
                overridden=spec.key in overrides and cfg.readable(spec.key, overrides[spec.key]),
                clamped_from=clamped.get(spec.key),
            )
            for spec in cfg.SPECS
        ]

    # -- writes ---------------------------------------------------------------

    def update(self, changes: Mapping[str, object]) -> list[ConfigEntry]:
        """Validate and save a partial update; all or nothing.

        Raises ConfigValueError: a value outside the bounds, a min above its max,
        or an unknown key (the removed demo/real mode included)."""
        values = {key: cfg.validate(key, raw) for key, raw in changes.items()}
        with self._lock:
            merged = {**self._overrides, **values}
            cfg.check_pairs(cfg.overlay(self.defaults(), merged), values)
            self._store.save(values)
            self._overrides = merged
        return self.entries()

    def reset(self, key: str | None = None) -> list[ConfigEntry]:
        """Back to the default: one setting, or all of them (None; this also
        drops any stored row of a removed setting)."""
        if key is not None and key not in cfg.SPEC_BY_KEY:
            raise cfg.ConfigValueError(f"«{key}» no es un ajuste que se pueda cambiar.")
        with self._lock:
            self._store.delete(None if key is None else [key])
            self._overrides = {
                k: v for k, v in self._overrides.items() if key is not None and k != key
            }
        return self.entries()
