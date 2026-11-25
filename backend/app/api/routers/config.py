"""The in-app "Configuración" (S25): read, change and restore the behaviour
settings. Never talks to Instagram.

  - GET  /config         every setting: value, default, bounds, Spanish label/help.
  - PUT  /config         partial update; 422 (Spanish, naming the limit) for a
                         value outside the safety bounds or an unknown key.
  - POST /config/reset   one setting (`key`) or all of them back to the default.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import runtime_config_dep
from app.api.schemas import (
    ConfigEntryOut,
    ConfigOut,
    ConfigResetIn,
    ConfigUpdateIn,
)
from app.application.runtime_config import ConfigEntry, RuntimeConfigService
from app.domain.config import ConfigValueError

router = APIRouter(prefix="/config", tags=["config"])

# A body these routes can't even read (A1): the Spanish 422 instead of FastAPI's.
_BAD_BODY = {
    ("PUT", "/config"): 'Mandá los ajustes a cambiar así: {"values": {"clave": número}}.',
    ("POST", "/config/reset"): (
        'Mandá {"key": "clave"} para restaurar un ajuste, o {} para restaurar todos.'
    ),
}


def bad_body_message(method: str, path: str) -> str | None:
    """The Spanish message for an unreadable body of a /config route, else None."""
    return _BAD_BODY.get((method, path.rstrip("/") or "/"))


def _entry_out(entry: ConfigEntry) -> ConfigEntryOut:
    spec = entry.spec
    return ConfigEntryOut(
        key=spec.key,
        kind=spec.kind.value,
        value=entry.value,
        default=entry.default,
        min=spec.min,
        max=spec.max,
        unit=spec.unit,
        group=spec.group,
        label=spec.label,
        help=spec.help,
        overridden=entry.overridden,
        at_most=spec.at_most,
        clamped_from=entry.clamped_from,
    )


def _out(entries: list[ConfigEntry]) -> ConfigOut:
    return ConfigOut(entries=[_entry_out(e) for e in entries])


@router.get("", response_model=ConfigOut)
def get_config(runtime: RuntimeConfigService = Depends(runtime_config_dep)) -> ConfigOut:
    return _out(runtime.entries())


@router.put("", response_model=ConfigOut)
def update_config(
    body: ConfigUpdateIn, runtime: RuntimeConfigService = Depends(runtime_config_dep)
) -> ConfigOut:
    """Save only the given settings (all or nothing). Applies from the next
    Instagram request on."""
    try:
        entries = runtime.update(body.values)
    except ConfigValueError as exc:
        raise HTTPException(422, detail={"code": "bad_request", "message": str(exc)}) from exc
    return _out(entries)


@router.post("/reset", response_model=ConfigOut)
def reset_config(
    body: ConfigResetIn, runtime: RuntimeConfigService = Depends(runtime_config_dep)
) -> ConfigOut:
    try:
        entries = runtime.reset(body.key)
    except ConfigValueError as exc:
        raise HTTPException(422, detail={"code": "bad_request", "message": str(exc)}) from exc
    return _out(entries)
