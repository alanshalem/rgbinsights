"""S18: the dependency rule, checked on the source.

The domain depends on nothing else in the app; the application layer (use
cases, jobs, campaign sender) only on the domain and its own ports — never on
the infrastructure, the web framework or the DB/Instagram libraries. Only the
composition root (app/bootstrap.py) builds the concrete parts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"

_OUTER = ("app.infrastructure", "app.api", "app.bootstrap", "app.main")
_LIBS = ("sqlmodel", "sqlalchemy", "fastapi", "instagrapi", "requests", "pydantic")


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _violations(layer: str, forbidden: tuple[str, ...]) -> list[str]:
    out = []
    for path in sorted((APP / layer).rglob("*.py")):
        for module in _imports(path):
            if any(module == f or module.startswith(f + ".") for f in forbidden):
                out.append(f"{path.relative_to(APP)} imports {module}")
    return out


@pytest.mark.parametrize(
    ("layer", "forbidden"),
    [
        ("domain", ("app.application", *_OUTER, *_LIBS)),
        ("application", (*_OUTER, *_LIBS)),
    ],
)
def test_inner_layers_never_import_outer_ones(layer: str, forbidden: tuple[str, ...]) -> None:
    assert _violations(layer, forbidden) == []


def test_instagram_errors_live_in_the_domain() -> None:
    from app.domain import errors

    assert errors.InstagramError.__module__ == "app.domain.errors"
    assert not (APP / "infrastructure" / "instagram" / "errors.py").exists()
