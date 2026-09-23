"""Step 4 tests: XWiki change discovery (list_changed_pages).

The transport uses the Solr query endpoint ordered by modification date
descending, paginates with ``start``/``number``, filters client-side by
``since`` (the endpoint cannot filter by modification timestamp), and stops
pagination early once a page older than ``since`` is seen.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime, timedelta

from brain.adapters.documentation.xwiki import XWikiDocumentationAdapter
from brain.adapters.documentation.xwiki_http import XWikiHTTPTransport


def _page(name: str, space: str, modified: datetime) -> dict[str, object]:
    return {
        "pageFullName": name,
        "space": space,
        "title": name.split(".")[-1],
        "version": "1.1",
        "modified": int(modified.timestamp() * 1000),
    }


class _FakeSolrServer:
    """Serves paged Solr query responses for monkeypatched urlopen."""

    def __init__(self, pages: list[dict[str, object]]) -> None:
        # Newest first, like orderField=date&order=desc.
        self._pages = sorted(
            pages,
            key=lambda p: int(p["modified"]),
            reverse=True,  # type: ignore[arg-type]
        )
        self.requests: list[dict[str, list[str]]] = []

    def __call__(self, request, timeout=None):  # noqa: ARG002
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        self.requests.append(query)
        space = str(query.get("q", [""])[0]).removeprefix("space:")
        start = int(query.get("start", ["0"])[0])
        number = int(query.get("number", ["50"])[0])
        selected = [p for p in self._pages if p["space"] == space]
        window = selected[start : start + number]

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def read(self) -> bytes:
                return json.dumps({"searchResults": window}).encode("utf-8")

        return _Response()


def _transport() -> XWikiHTTPTransport:
    return XWikiHTTPTransport("http://xwiki.test", user="u", password="p", wiki="xwiki")


def _now() -> datetime:
    return datetime.now(UTC)


async def test_gate_pagination_discovers_all_pages(monkeypatch) -> None:
    import urllib.request

    base = _now()
    pages = [_page(f"ADAS.Page{i:03d}", "ADAS", base - timedelta(minutes=i)) for i in range(120)]
    server = _FakeSolrServer(pages)
    monkeypatch.setattr(urllib.request, "urlopen", server)

    result = await _transport().list_changed_pages(["ADAS"], since=None, page_size=50)
    assert len(result) == 120
    # 3 pages of 50/50/20.
    assert len(server.requests) == 3
    assert [r["start"][0] for r in server.requests] == ["0", "50", "100"]
    # Deterministic ordering by (space, page reference).
    assert [p["id"] for p in result] == sorted(p["id"] for p in result)


async def test_gate_since_filter_excludes_old_pages(monkeypatch) -> None:
    import urllib.request

    base = _now()
    pages = [
        _page("ADAS.New", "ADAS", base - timedelta(minutes=1)),
        _page("ADAS.Old", "ADAS", base - timedelta(days=2)),
    ]
    server = _FakeSolrServer(pages)
    monkeypatch.setattr(urllib.request, "urlopen", server)

    since = base - timedelta(hours=1)
    result = await _transport().list_changed_pages(["ADAS"], since=since, page_size=50)
    assert [p["id"] for p in result] == ["ADAS.New"]


async def test_gate_since_stops_pagination_early(monkeypatch) -> None:
    import urllib.request

    base = _now()
    # Newest 10 pages are recent; the rest are old. With page_size=5 the first
    # old page appears on request 3 and must stop the scan.
    pages = [_page(f"ADAS.P{i:02d}", "ADAS", base - timedelta(minutes=i)) for i in range(10)]
    pages += [
        _page(f"ADAS.Old{i:02d}", "ADAS", base - timedelta(days=10, minutes=i)) for i in range(20)
    ]
    server = _FakeSolrServer(pages)
    monkeypatch.setattr(urllib.request, "urlopen", server)

    since = base - timedelta(hours=1)
    result = await _transport().list_changed_pages(["ADAS"], since=since, page_size=5)
    assert len(result) == 10
    # Requests: pages [0:5], [5:10], [10:15] -> stopped on the third.
    assert len(server.requests) == 3


async def test_gate_multiple_spaces_merged_and_sorted(monkeypatch) -> None:
    import urllib.request

    base = _now()
    pages = [
        _page("Zulu.Page", "Zulu", base),
        _page("ADAS.Page", "ADAS", base),
        _page("ADAS.Other", "ADAS", base - timedelta(minutes=1)),
    ]
    server = _FakeSolrServer(pages)
    monkeypatch.setattr(urllib.request, "urlopen", server)

    result = await _transport().list_changed_pages(["Zulu", "ADAS"], since=None, page_size=50)
    assert [p["id"] for p in result] == ["ADAS.Other", "ADAS.Page", "Zulu.Page"]
    queried_spaces = {r["q"][0] for r in server.requests}
    assert queried_spaces == {"space:Zulu", "space:ADAS"}


async def test_gate_adapter_requires_spaces(monkeypatch) -> None:
    adapter = XWikiDocumentationAdapter(transport=_FakeTransport())
    assert await adapter.list_changed_documents(_now(), spaces=None) == []
    refs = await adapter.list_changed_documents(_now(), spaces=["ADAS"])
    assert [ref.external_id for ref in refs] == ["ADAS.Page"]
    assert refs[0].provider == "xwiki"
    assert refs[0].external_type == "page"


class _FakeTransport:
    async def list_changed_pages(self, spaces, since=None, *, page_size=50):
        return [{"id": "ADAS.Page", "space": "ADAS", "modified": _now().isoformat()}]

    # unused surface
    async def get_page(self, page_id):
        raise NotImplementedError

    async def get_page_version(self, page_id, version):
        raise NotImplementedError

    async def list_page_changes(self, page_id):
        raise NotImplementedError

    async def get_attachments(self, page_id):
        raise NotImplementedError

    async def get_children(self, page_id):
        raise NotImplementedError

    async def get_links(self, page_id):
        raise NotImplementedError

    async def create_space(self, space):
        raise NotImplementedError
