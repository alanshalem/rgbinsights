"""S23: export of the on-screen semáforo list (Excel + PDF), local DB only (S0).

Reuses the board fixture from `test_list_users` so the export is checked against
exactly what `/users` returns for the same params.
"""

from __future__ import annotations

import asyncio
import re
import zlib
from collections.abc import Iterator, MutableMapping
from datetime import UTC, datetime, timedelta, timezone
from io import BytesIO
from typing import Any
from urllib.parse import urlencode

import pytest
from app.api.deps import session_dep, source_dep
from app.application.use_cases import (
    ExportRow,
    ExportUsersUseCase,
    ListUsersUseCase,
    UserExport,
)
from app.domain.traffic_light import TrafficLight
from app.infrastructure.export import render_pdf, render_xlsx
from app.infrastructure.persistence import models
from app.main import app
from openpyxl import load_workbook
from sqlmodel import Session

from tests.test_list_users import FIESTA, _dt, _seed

AR = datetime(2026, 11, 25, 1, 30, tzinfo=UTC)  # 2026-11-24 22:30 in Argentina (UTC-3)
AR_TZ = timezone(timedelta(hours=-3))
HEADERS = [
    "Usuario",
    "Nombre",
    "Estado",
    "Te sigue",
    "Seguidores",
    "Likes",
    "Comentarios",
    "Posts",
    "Perfil",
    "Link DM",
]
ACCENTS = "Ñ á é í ó ú ü"


@pytest.fixture
def seeded(session: Session) -> Session:
    _seed(session)
    return session


def _export(session: Session, **kwargs: Any) -> UserExport:
    return ExportUsersUseCase(session, tz=AR_TZ).execute(now=AR, **kwargs)


def _names(session: Session, **kwargs: Any) -> list[str]:
    return [v.username for v in ListUsersUseCase(session).execute(**kwargs)]


# -- use case: scope ---------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"event": FIESTA},
        {"event": FIESTA, "order": "fans"},
        {"event": FIESTA, "order": "followers", "follows": True},
        {"event": FIESTA, "status": TrafficLight.RED},
        {"status": TrafficLight.GREEN, "order": "username"},
        {"search": "dup"},
        {"search": "ángeles"},
        {"post": "1000"},
        {"post": "300", "event": FIESTA},
        {"event": 12345},
    ],
)
def test_table_scope_matches_users_for_same_params(seeded: Session, params: dict[str, Any]) -> None:
    out = _export(seeded, **params)
    assert [r.username for r in out.rows] == _names(seeded, **params)


def test_board_scope_groups_by_color_then_current_order(seeded: Session) -> None:
    for order in ("status", "fans", "followers", "username"):
        expected = [
            name
            for light in (TrafficLight.RED, TrafficLight.YELLOW, TrafficLight.GREEN)
            for name in _names(seeded, event=FIESTA, order=order, status=light)
        ]
        out = _export(seeded, event=FIESTA, order=order, by_status=True)
        assert [r.username for r in out.rows] == expected
    # fans order: ungrouped differs from the board's color grouping.
    grouped = [r.username for r in _export(seeded, event=FIESTA, order="fans", by_status=True).rows]
    assert grouped == ["ana", "bob", "dup", "DUP", "zoe", "mia"]
    assert grouped != _names(seeded, event=FIESTA, order="fans")
    # A status given alongside by_status keeps just that color.
    red = _export(seeded, event=FIESTA, status=TrafficLight.RED, by_status=True)
    assert [r.username for r in red.rows] == _names(seeded, event=FIESTA, status=TrafficLight.RED)


def test_exports_all_rows_without_pagination(session: Session) -> None:
    now = _dt(6, 1)
    session.add(models.Post(media_pk="p1", shortcode="P1", url="https://instagram.com/p/P1/"))
    session.add_all(
        models.User(pk=str(i), username=f"user{i:04d}", first_seen_at=now, last_seen_at=now)
        for i in range(620)  # > the 500 /users page cap
    )
    session.flush()
    session.add_all(
        models.Engagement(user_pk=str(i), post_media_pk="p1", type="like") for i in range(620)
    )
    session.commit()
    out = _export(session, order="username")
    assert len(out.rows) == 620
    assert out.rows[0].username == "user0000" and out.rows[-1].username == "user0619"


# -- use case: columns/values -------------------------------------------------


def test_row_values(seeded: Session) -> None:
    rows = {r.username: r for r in _export(seeded, event=FIESTA).rows}
    zoe = rows["zoe"]
    assert zoe == ExportRow(
        username="zoe",
        profile_url="https://instagram.com/zoe/",
        dm_url="https://instagram.com/direct/t/t-zoe/",
        has_thread=True,
        full_name="ÁNGELES Zoe",
        status=TrafficLight.YELLOW,
        status_label="Amarillo",
        follows_us="Sí",
        follower_count=500,
        likes=1,
        comments=1,
        posts_engaged=2,
    )
    ana = rows["ana"]
    assert (ana.status_label, ana.follows_us, ana.follower_count) == ("Rojo", "No", None)
    assert (ana.likes, ana.comments, ana.posts_engaged) == (1, 1, 2)
    dup = rows["dup"]  # relation never synced, no DM thread
    assert dup.follows_us == "—"
    assert (dup.has_thread, dup.dm_url) == (False, "https://instagram.com/dup/")
    assert rows["mia"].status_label == "Verde"
    # Global view counts every engagement of the user.
    g = {r.username: r for r in _export(seeded).rows}
    assert (g["zoe"].likes, g["zoe"].comments, g["zoe"].posts_engaged) == (2, 1, 3)


def test_title_filters_and_filename(seeded: Session) -> None:
    seeded.add(
        models.Event(
            id=5,
            name="Fiesta Ñandú: Año 2026!",
            promo_start=_dt(6, 1),
            event_date=_dt(7, 1),
            created_at=_dt(6, 1),
        )
    )
    seeded.commit()
    out = _export(seeded, event=5)
    assert out.title == "Fiesta Ñandú: Año 2026!"
    assert out.filename("xlsx") == "semaforo-fiesta-nandu-ano-2026-2026-11-24.xlsx"
    assert out.generated_at.strftime("%Y-%m-%d %H:%M") == "2026-11-24 22:30"

    f = _export(seeded, event=FIESTA)
    assert (f.title, f.posts_total, f.total) == ("F", 2, 6)
    assert f.filename("pdf") == "semaforo-f-2026-11-24.pdf"
    assert f.filters == ("Vista: tabla", "Orden: estado")

    g = _export(seeded, search="dup", follows=True, status=TrafficLight.RED, order="fans")
    assert g.title == "Todas las fiestas"
    assert g.filename("xlsx") == "semaforo-todas-las-fiestas-2026-11-24.xlsx"
    assert g.filters == (
        "Vista: tabla",
        "Estado: Rojo",
        'Búsqueda: "dup"',
        "Solo seguidores",
        "Orden: fans",
    )
    b = _export(seeded, event=FIESTA, by_status=True, order="followers", post="300")
    assert b.filters == ("Vista: tablero (por color)", "Post: S300", "Orden: seguidores")
    assert _export(seeded, event=999).title == "Fiesta #999"


# -- renderers ---------------------------------------------------------------


def _sample(n: int = 3, full_name: str = f"Ñandú Pérez {ACCENTS}") -> UserExport:
    lights = [TrafficLight.RED, TrafficLight.YELLOW, TrafficLight.GREEN]
    labels = {
        TrafficLight.RED: "Rojo",
        TrafficLight.YELLOW: "Amarillo",
        TrafficLight.GREEN: "Verde",
    }
    rows = tuple(
        ExportRow(
            username=f"user{i}",
            profile_url=f"https://instagram.com/user{i}/",
            dm_url=(
                f"https://instagram.com/direct/t/t{i}/"
                if i % 2
                else f"https://instagram.com/user{i}/"
            ),
            has_thread=bool(i % 2),
            full_name=full_name if i == 0 else f"Nombre {i}",
            status=lights[i % 3],
            status_label=labels[lights[i % 3]],
            follows_us=("Sí", "No", "—")[i % 3],
            follower_count=None if i % 3 == 2 else 100 + i,
            likes=i % 4,
            comments=i % 2,
            posts_engaged=1 + i % 3,
        )
        for i in range(n)
    )
    return UserExport(
        title="Fiesta Ñandú",
        slug="fiesta-nandu",
        generated_at=datetime(2026, 11, 24, 22, 30),
        filters=("Vista: tabla", 'Búsqueda: "ñ"', "Orden: estado"),
        posts_total=4,
        rows=rows,
    )


def test_xlsx_layout_links_and_fills() -> None:
    data = render_xlsx(_sample(3))
    wb = load_workbook(BytesIO(data))
    ws = wb.worksheets[0]
    assert ws.title == "Semáforo"
    assert [c.value for c in ws[1]] == HEADERS
    assert all(c.font.b for c in ws[1])
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:J4"
    assert ws.max_row == 4  # header + 3 rows
    assert ws.column_dimensions["A"].width >= 15 and ws.column_dimensions["I"].width >= 30

    r1 = [c.value for c in ws[2]]
    assert r1 == [
        "@user0",
        f"Ñandú Pérez {ACCENTS}",
        "Rojo",
        "Sí",
        100,
        0,
        0,
        1,
        "https://instagram.com/user0/",
        "https://instagram.com/user0/",
    ]
    assert ws["A2"].hyperlink.target == "https://instagram.com/user0/"
    assert ws["I2"].hyperlink.target == "https://instagram.com/user0/"
    assert ws["J3"].hyperlink.target == "https://instagram.com/direct/t/t1/"
    assert ws["J3"].value == "https://instagram.com/direct/t/t1/"
    assert ws["E4"].value is None  # unknown follower count stays empty
    fills = {ws[f"C{r}"].value: ws[f"C{r}"].fill.fgColor.rgb for r in (2, 3, 4)}
    assert fills == {"Rojo": "FFFFC7CE", "Amarillo": "FFFFEB9C", "Verde": "FFC6EFCE"}

    info = wb["Info"]
    values = [row[1] for row in info.iter_rows(values_only=True)]
    assert "Fiesta Ñandú" in values and "2026-11-24 22:30" in values and 3 in values
    assert 'Vista: tabla · Búsqueda: "ñ" · Orden: estado' in values


def test_xlsx_keeps_formula_like_names_as_text_and_handles_empty() -> None:
    wb = load_workbook(BytesIO(render_xlsx(_sample(1, full_name='=HYPERLINK("x")\x07'))))
    cell = wb.worksheets[0]["B2"]
    assert cell.data_type == "s" and cell.value == '=HYPERLINK("x")'
    empty = load_workbook(BytesIO(render_xlsx(_sample(0)))).worksheets[0]
    assert [c.value for c in empty[1]] == HEADERS and empty.max_row == 1


def _pdf_streams(data: bytes) -> bytes:
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out


def _page_count(data: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b(?!s)", data))


def test_pdf_structure_accents_links_and_pages() -> None:
    data = render_pdf(_sample(3, full_name=f"Ñandú Pérez {ACCENTS} 🎉 𝓜𝓲𝓪"))
    assert data.startswith(b"%PDF-")
    assert _page_count(data) == 1
    text = _pdf_streams(data)
    assert f"Ñandú Pérez {ACCENTS}".encode("latin-1") in text  # accents survive
    assert "Mia".encode("latin-1") in text  # styled letters folded, emoji dropped
    assert b"Fiesta \xd1and\xfa" in text and b"Total: 3" in text
    assert b"(P\xe1gina 1 de " in text  # footer; the total is filled in at output
    assert b"/URI (https://instagram.com/user0/)" in data
    assert b"/URI (https://instagram.com/direct/t/t1/)" in data

    many = render_pdf(_sample(200))
    pages = _page_count(many)
    assert pages > 3
    # The header row and the page number repeat on every page.
    assert _pdf_streams(many).count(b"(Comentarios) Tj") == pages
    assert _pdf_streams(many).count(b"(P\xe1gina ") == pages


def test_pdf_empty_export() -> None:
    data = render_pdf(_sample(0))
    assert data.startswith(b"%PDF-") and _page_count(data) == 1
    assert b"Sin resultados" in _pdf_streams(data)


# -- HTTP endpoint -----------------------------------------------------------


@pytest.fixture
def client_session(seeded: Session) -> Iterator[Session]:
    app.dependency_overrides[session_dep] = lambda: seeded
    try:
        yield seeded
    finally:
        app.dependency_overrides.pop(session_dep, None)


def _get(path: str, **params: Any) -> tuple[int, dict[str, str], bytes]:
    """Drive the ASGI app directly (no extra HTTP client dependency)."""
    messages: list[MutableMapping[str, Any]] = []
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": urlencode(params).encode(),
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: MutableMapping[str, Any]) -> None:
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in messages if m["type"] == "http.response.start")
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], headers, body


def test_endpoint_xlsx_download(client_session: Session) -> None:
    status, headers, body = _get(
        "/users/export", format="xlsx", event=FIESTA, order="fans", by_status="true"
    )
    assert status == 200
    assert headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert re.fullmatch(
        r'attachment; filename="semaforo-f-\d{4}-\d{2}-\d{2}\.xlsx"',
        headers["content-disposition"],
    )
    ws = load_workbook(BytesIO(body)).worksheets[0]
    assert [ws[f"A{r}"].value for r in range(2, ws.max_row + 1)] == [
        "@ana",
        "@bob",
        "@dup",
        "@DUP",
        "@zoe",
        "@mia",
    ]


def test_endpoint_pdf_download_with_filters(client_session: Session) -> None:
    status, headers, body = _get(
        "/users/export", format="pdf", search="dup", follows="false", status="red"
    )
    assert status == 200
    assert headers["content-type"] == "application/pdf"
    assert re.fullmatch(
        r'attachment; filename="semaforo-todas-las-fiestas-\d{4}-\d{2}-\d{2}\.pdf"',
        headers["content-disposition"],
    )
    assert body.startswith(b"%PDF-") and b"Total: 2" in _pdf_streams(body)


@pytest.mark.parametrize(
    "params",
    [{"format": "csv"}, {}, {"format": "xlsx", "order": "bogus"}, {"format": "pdf", "event": "x"}],
)
def test_endpoint_rejects_bad_params(client_session: Session, params: dict[str, Any]) -> None:
    status, _, _ = _get("/users/export", **params)
    assert status == 422


def test_users_endpoint_unchanged_by_export_route(client_session: Session) -> None:
    status, headers, _ = _get("/users", event=FIESTA, limit=2)
    assert status == 200 and headers["content-type"] == "application/json"
    status, _, _ = _get("/users/counts", event=FIESTA)
    assert status == 200


# -- S0: zero Instagram requests ---------------------------------------------


def test_export_never_touches_instagram(
    client_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import requests
    from app.api import deps
    from app.infrastructure.instagram import fake_source, shared

    def boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("export must not touch Instagram")

    monkeypatch.setattr(shared, "get_shared_source", boom)
    monkeypatch.setattr(deps, "get_shared_source", boom)
    monkeypatch.setattr(fake_source.FakeInstagramSource, "__init__", boom)
    monkeypatch.setattr(requests.Session, "request", boom)

    for fmt in ("xlsx", "pdf"):
        status, _, _ = _get("/users/export", format=fmt, event=FIESTA, by_status="true")
        assert status == 200

    from app.api.routers.users import router

    route = next(r for r in router.routes if getattr(r, "path", None) == "/users/export")

    def calls(dependant: Any) -> Iterator[Any]:
        for d in dependant.dependencies:
            yield d.call
            yield from calls(d)

    assert source_dep not in set(calls(route.dependant))  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "full_name",
    ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "=cmd|' /C calc'!A0", "a\x00b\x1fc", "x￾y", "x￿y"],
)
def test_xlsx_never_stores_formulas_and_always_opens(full_name: str) -> None:
    """S23 safety: hostile names stay plain text and never corrupt the workbook."""
    import zipfile

    data = render_xlsx(_sample(full_name=full_name))
    load_workbook(BytesIO(data))  # must not raise "not well-formed"
    with zipfile.ZipFile(BytesIO(data)) as z:
        sheets = [n for n in z.namelist() if n.startswith("xl/worksheets/sheet")]
        assert sheets
        for name in sheets:
            assert b"<f>" not in z.read(name)
        rels = z.read("xl/worksheets/_rels/sheet1.xml.rels").decode()
    targets = re.findall(r'Target="([^"]+)"', rels)
    assert targets and all(t.startswith("https://instagram.com/") for t in targets)
    assert 'TargetMode="External"' in rels
