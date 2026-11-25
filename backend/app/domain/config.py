"""In-app configuration (S25): the behaviour settings the user can change from
the "Configuración" screen, their factory defaults and their safety bounds (S0).

Pure rules, no I/O. Every anti-ban setting may only move to the SAFER side of
its factory default: waits, rests, cooldown and cache times only get longer;
request budgets and read caps only get lower. The bounds are enforced here, so
no caller (API, UI, an old stored value) can make the app ask Instagram for
more, or faster, than the factory values.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """The effective behaviour settings. The field defaults are the factory
    values (what the app always shipped with)."""

    # Human pacing before every Instagram request.
    scan_min_delay_seconds: float = 2.0
    scan_max_delay_seconds: float = 6.0
    ig_rest_every_requests: int = 25
    ig_rest_min_seconds: float = 45.0
    ig_rest_max_seconds: float = 150.0
    # Request budget (every HTTP request, pages included; Argentina hours/days).
    ig_max_requests_per_hour: int = 200
    ig_max_requests_per_day: int = 1500
    # Brakes.
    ig_throttle_cooldown_minutes: float = 60.0
    ig_lock_wait_seconds: float = 600.0
    # How much each read brings.
    recent_posts_limit: int = 50
    dm_threads_limit: int = 60
    scan_comments_limit: int = 200
    relationship_fetch_max: int = 0  # 0 = everyone
    enrich_profiles_per_run: int = 60
    enrich_profiles_per_day: int = 150
    # Reuse what is stored instead of asking again.
    relationship_cache_hours: float = 12.0
    rescan_skip_hours: float = 6.0
    relationship_full_refresh_days: float = 7.0


FACTORY = RuntimeConfig()


class ConfigKind(StrEnum):
    INT = "int"
    FLOAT = "float"


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    kind: ConfigKind
    group: str
    label: str
    help: str
    unit: str = ""
    min: float | None = None
    max: float | None = None
    # The setting this one may not exceed (the max of a min/max pair).
    at_most: str | None = None
    # Which bound is the factory value (S0: only the safer side is allowed):
    # "min" for waits/rests/caches, "max" for budgets/caps, "" for neither.
    factory_bound: str = ""

    @property
    def factory(self) -> Any:
        return getattr(FACTORY, self.key)


class ConfigValueError(ValueError):
    """A value the configuration refuses; the message is Spanish, for the UI."""


GROUP_PACE = "Ritmo humano"
GROUP_BUDGET = "Presupuesto de pedidos"
GROUP_BRAKES = "Frenos"
GROUP_READS = "Lectura de datos"
GROUP_CACHE = "Caché"

_SAFER = "solo se permite ir hacia lo más seguro"


def _longer(key: str, upper: float, **kw: Any) -> dict[str, Any]:
    """Bounds of a wait/rest/cache time: the factory value up to `upper`."""
    return {"key": key, "min": getattr(FACTORY, key), "max": upper, "factory_bound": "min", **kw}


def _lower(key: str, **kw: Any) -> dict[str, Any]:
    """Bounds of a budget/cap: 1 up to the factory value."""
    return {"key": key, "min": 1, "max": getattr(FACTORY, key), "factory_bound": "max", **kw}


SPECS: tuple[SettingSpec, ...] = tuple(
    SettingSpec(**spec)
    for spec in (
        _longer(
            "scan_min_delay_seconds",
            60,
            kind=ConfigKind.FLOAT,
            group=GROUP_PACE,
            unit="s",
            label="Espera mínima entre pedidos",
            help="Antes de cada pedido a Instagram la app espera un rato al azar entre la "
            "espera mínima y la máxima, como haría una persona. Más larga: más seguro y más lento.",
            at_most="scan_max_delay_seconds",
        ),
        _longer(
            "scan_max_delay_seconds",
            60,
            kind=ConfigKind.FLOAT,
            group=GROUP_PACE,
            unit="s",
            label="Espera máxima entre pedidos",
            help="El otro extremo de la espera al azar. Tiene que ser igual o mayor que la mínima.",
        ),
        {
            "key": "ig_rest_every_requests",
            "min": 5,
            "max": FACTORY.ig_rest_every_requests,
            "factory_bound": "max",
            "kind": ConfigKind.INT,
            "group": GROUP_PACE,
            "unit": "pedidos",
            "label": "Descanso largo cada",
            "help": "Cada tantos pedidos la app hace un descanso largo, como alguien que deja "
            "el celu. Un número más chico descansa más seguido (más seguro).",
        },
        _longer(
            "ig_rest_min_seconds",
            900,
            kind=ConfigKind.FLOAT,
            group=GROUP_PACE,
            unit="s",
            label="Descanso mínimo",
            help="Lo menos que dura cada descanso largo.",
            at_most="ig_rest_max_seconds",
        ),
        _longer(
            "ig_rest_max_seconds",
            900,
            kind=ConfigKind.FLOAT,
            group=GROUP_PACE,
            unit="s",
            label="Descanso máximo",
            help="Lo más que dura cada descanso largo. Tiene que ser igual o mayor que el mínimo.",
        ),
        _lower(
            "ig_max_requests_per_hour",
            kind=ConfigKind.INT,
            group=GROUP_BUDGET,
            unit="pedidos",
            label="Tope de pedidos por hora",
            help="Cuenta cada pedido a Instagram (cada página también). Al llegar al tope se "
            "frena todo hasta la hora siguiente (hora argentina). Si lo bajás por debajo de lo "
            "que ya se usó en esta hora, espera a que empiece la próxima.",
        ),
        _lower(
            "ig_max_requests_per_day",
            kind=ConfigKind.INT,
            group=GROUP_BUDGET,
            unit="pedidos",
            label="Tope de pedidos por día",
            help="Lo mismo, por día argentino. Al llegar al tope no se hace ningún pedido "
            "hasta la medianoche.",
        ),
        _longer(
            "ig_throttle_cooldown_minutes",
            1440,
            kind=ConfigKind.FLOAT,
            group=GROUP_BRAKES,
            unit="min",
            label="Pausa si Instagram pide frenar",
            help="Si Instagram contesta «esperá unos minutos» (o algo parecido), la app no le "
            "pide nada durante este tiempo.",
        ),
        {
            "key": "ig_lock_wait_seconds",
            "min": 30,
            "max": 3600,
            "kind": ConfigKind.FLOAT,
            "group": GROUP_BRAKES,
            "unit": "s",
            "label": "Espera si Instagram está ocupado",
            "help": "La app hace una sola cosa con Instagram a la vez. Si ya hay otra en curso "
            "(por ejemplo, una campaña), espera hasta este tiempo y después avisa que está "
            "ocupado. No cambia cuántos pedidos se hacen.",
        },
        _lower(
            "recent_posts_limit",
            kind=ConfigKind.INT,
            group=GROUP_READS,
            unit="posts",
            label="Posts recientes a revisar",
            help="Al escanear por rango de fechas, cuántos de tus últimos posts mira como máximo.",
        ),
        _lower(
            "dm_threads_limit",
            kind=ConfigKind.INT,
            group=GROUP_READS,
            unit="chats",
            label="Chats por sincronización",
            help="Cuántos chats trae como máximo cada sincronización de DMs (20 por pedido). "
            "Menos chats: menos pedidos, pero los chats más viejos con mensajes nuevos pueden "
            "quedar sin sincronizar.",
        ),
        _lower(
            "scan_comments_limit",
            kind=ConfigKind.INT,
            group=GROUP_READS,
            unit="comentarios",
            label="Comentarios por post",
            help="Tope de comentarios que se leen de cada post. Sin tope, un post viral serían "
            "cientos de pedidos.",
        ),
        {
            "key": "relationship_fetch_max",
            "min": 0,
            "max": 1_000_000,
            "kind": ConfigKind.INT,
            "group": GROUP_READS,
            "unit": "personas",
            "label": "Tope de seguidores/seguidos a leer",
            "help": "0 = todos (lo correcto, pero lo más pesado). Con un número, lee como "
            "máximo esa cantidad: menos pedidos, pero en cuentas grandes el «te sigue» puede "
            "quedar incompleto.",
        },
        _lower(
            "enrich_profiles_per_run",
            kind=ConfigKind.INT,
            group=GROUP_READS,
            unit="perfiles",
            label="Perfiles por corrida",
            help="Cuántos perfiles lee como máximo «Relación + perfiles» cada vez que lo usás. "
            "Los que falten siguen en la próxima.",
        ),
        _lower(
            "enrich_profiles_per_day",
            kind=ConfigKind.INT,
            group=GROUP_READS,
            unit="perfiles",
            label="Perfiles por día",
            help="Tope de perfiles leídos por día argentino, sumando todas las corridas.",
        ),
        _longer(
            "relationship_cache_hours",
            168,
            kind=ConfigKind.FLOAT,
            group=GROUP_CACHE,
            unit="h",
            label="Reusar tus seguidores durante",
            help="Tu lista de seguidores/seguidos se reusa este tiempo antes de volver a "
            "leerla. «Traer todo de cero» lo saltea.",
        ),
        _longer(
            "rescan_skip_hours",
            168,
            kind=ConfigKind.FLOAT,
            group=GROUP_CACHE,
            unit="h",
            label="No releer un post escaneado hace menos de",
            help="Al actualizar una fiesta, los posts escaneados hace menos que esto se "
            "saltean. «Traer todo de cero» lo saltea.",
        ),
        _longer(
            "relationship_full_refresh_days",
            90,
            kind=ConfigKind.FLOAT,
            group=GROUP_CACHE,
            unit="días",
            label="Lectura completa de seguidores cada",
            help="Entre lecturas completas solo se suman los seguidores nuevos; la completa "
            "también detecta a los que dejaron de seguirte.",
        ),
    )
)

SPEC_BY_KEY: dict[str, SettingSpec] = {s.key: s for s in SPECS}

assert set(SPEC_BY_KEY) == {f.name for f in fields(RuntimeConfig)}, "every setting has a spec"


def format_number(value: float) -> str:
    """2.0 -> '2', 1.5 -> '1,5' (Argentina decimal comma)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}".replace(".", ",")


# Singular of each plural unit: "1 pedido", "2 pedidos" (s, min, h stay as they are).
_ONE = {
    "pedidos": "pedido",
    "posts": "post",
    "chats": "chat",
    "comentarios": "comentario",
    "personas": "persona",
    "perfiles": "perfil",
    "días": "día",
}


def unit_for(spec: SettingSpec, value: float) -> str:
    return _ONE.get(spec.unit, spec.unit) if value == 1 else spec.unit


def _with_unit(spec: SettingSpec, value: float) -> str:
    return f"{format_number(value)} {unit_for(spec, value)}".strip()


def parse_value(spec: SettingSpec, raw: object) -> int | float:
    """Type-check one value (no bounds). Raises ConfigValueError."""
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise ConfigValueError(f"«{spec.label}» tiene que ser un número.")
    if spec.kind is ConfigKind.INT:
        if not float(raw).is_integer():
            raise ConfigValueError(f"«{spec.label}» tiene que ser un número entero.")
        return int(raw)
    return float(raw)


def check_bounds(spec: SettingSpec, value: int | float) -> None:
    """Refuse a value outside the safety bounds, naming the limit."""
    if spec.min is not None and value < spec.min:
        why = f" (el valor de fábrica): {_SAFER}" if spec.factory_bound == "min" else ""
        raise ConfigValueError(
            f"«{spec.label}» no puede ser menor que {_with_unit(spec, spec.min)}{why}."
        )
    if spec.max is not None and value > spec.max:
        why = (
            f" (el valor de fábrica): {_SAFER}; más pedidos a Instagram suben el riesgo de bloqueo"
            if spec.factory_bound == "max"
            else ""
        )
        raise ConfigValueError(
            f"«{spec.label}» no puede ser mayor que {_with_unit(spec, spec.max)}{why}."
        )


def validate(key: str, raw: object) -> int | float:
    """One user-entered value: known key, right type, within bounds."""
    spec = SPEC_BY_KEY.get(key)
    if spec is None:
        raise ConfigValueError(f"«{key}» no es un ajuste que se pueda cambiar.")
    value = parse_value(spec, raw)
    check_bounds(spec, value)
    return value


def check_pairs(config: RuntimeConfig, keys: Collection[str]) -> None:
    """The min of every min/max pair touching `keys` is at most its max."""
    for spec in SPECS:
        if spec.at_most is None or not {spec.key, spec.at_most} & set(keys):
            continue
        low, high = getattr(config, spec.key), getattr(config, spec.at_most)
        if low > high:
            other = SPEC_BY_KEY[spec.at_most]
            raise ConfigValueError(
                f"«{spec.label}» ({_with_unit(spec, low)}) no puede ser mayor que "
                f"«{other.label}» ({_with_unit(other, high)})."
            )


def clamp(spec: SettingSpec, raw: object) -> int | float | None:
    """A value from a lenient source (an old .env, a stored override): typed and
    kept on the safe side of the factory value, or None if it can't be read.

    S0 (L30): only the unsafe side moves. A wait/rest/cache shorter than the
    factory value becomes the factory value, a budget/cap above it becomes the
    factory value; a value on the SAFE side is kept as is, even beyond the
    screen's editable range (a slower old setting is never made faster). A
    budget/cap/rest spacing never goes below 1 (0 means "no cap" or "no rests").
    Settings with no safe side (lock wait, relationship cap) stay in their range.
    """
    try:
        value = parse_value(spec, raw)
    except ConfigValueError:
        return None
    if spec.factory_bound == "min":
        value = max(value, spec.factory)
    elif spec.factory_bound == "max":
        value = max(min(value, spec.factory), 1)
    else:
        if spec.min is not None:
            value = max(value, spec.min)
        if spec.max is not None:
            value = min(value, spec.max)
    return float(value) if spec.kind is ConfigKind.FLOAT else int(value)


def _fix_pairs(config: RuntimeConfig) -> RuntimeConfig:
    """A max below its min is raised to the min (the longer, safer side)."""
    for spec in SPECS:
        if spec.at_most is not None and getattr(config, spec.key) > getattr(config, spec.at_most):
            config = replace(config, **{spec.at_most: getattr(config, spec.key)})
    return config


def safe_defaults(raw: RuntimeConfig) -> RuntimeConfig:
    """Defaults from the environment (an older .env may set them), on the safe
    side: an old value faster than the factory one becomes the factory one, a
    slower one is kept (see clamp)."""
    values: dict[str, Any] = {}
    for spec in SPECS:
        value = clamp(spec, getattr(raw, spec.key))
        values[spec.key] = spec.factory if value is None else value
    return _fix_pairs(RuntimeConfig(**values))


def overlay(defaults: RuntimeConfig, overrides: Mapping[str, object]) -> RuntimeConfig:
    """The defaults with the overrides on top. An override that can't be read, or
    for a setting that no longer exists (e.g. the L25 demo/real mode, removed in
    L27), is ignored; one on the unsafe side is moved to the factory value (see
    clamp). Pairs are left as they are."""
    values: dict[str, Any] = {}
    for key, raw in overrides.items():
        spec = SPEC_BY_KEY.get(key)
        value = clamp(spec, raw) if spec is not None else None
        if value is not None:
            values[key] = value
    return replace(defaults, **values)


def clamped_defaults(raw: RuntimeConfig) -> dict[str, float]:
    """The raw defaults (an older .env) that safe_defaults had to move to the safe
    side, by key: what the environment asked for, so the screen and the log can
    say so. A kept (slower) value is not listed."""
    safe = safe_defaults(raw)
    return {
        spec.key: getattr(raw, spec.key)
        for spec in SPECS
        if getattr(raw, spec.key) != getattr(safe, spec.key)
    }


def readable(key: str, raw: object) -> bool:
    """A stored override that is used (a known setting with a usable number)."""
    spec = SPEC_BY_KEY.get(key)
    return spec is not None and clamp(spec, raw) is not None


def effective(defaults: RuntimeConfig, overrides: Mapping[str, object]) -> RuntimeConfig:
    """The effective configuration: the (already safe) defaults with the stored
    overrides on top, every pair's max at least its min."""
    return _fix_pairs(overlay(defaults, overrides))
