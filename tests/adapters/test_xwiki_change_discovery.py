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
        if space.endswith(".*"):
            prefix = space[:-2]
            selected = [
                p
                for p in self._pages
                if str(p["space"]).replace("\\.", ".").startswith(prefix + ".")
            ]
        else:
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
    # space:ADAS pages of 50/50/20, plus the empty nested-space query.
    assert len(server.requests) == 4
    assert [r["start"][0] for r in server.requests[:3]] == ["0", "50", "100"]
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
    # Requests: pages [0:5], [5:10], [10:15] -> stopped on the third,
    # plus one empty nested-space query.
    assert len(server.requests) == 4


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
    assert queried_spaces == {
        "space:Zulu",
        "space:Zulu.*",
        "space:ADAS",
        "space:ADAS.*",
    }


async def test_gate_nested_spaces_are_discovered(monkeypatch) -> None:
    """A mapped space covers its subtree: space:X plus space:X.*."""
    import urllib.request

    base = _now()
    pages = [
        _page("odoogarageeu.WebHome", "odoogarageeu", base),
        _page(
            "odoogarageeu.Architecture.WebHome",
            "odoogarageeu.Architecture",
            base - timedelta(minutes=1),
        ),
        _page(
            "odoogarageeu.Details.WebHome",
            "odoogarageeu.Details",
            base - timedelta(minutes=2),
        ),
    ]
    server = _FakeSolrServer(pages)
    monkeypatch.setattr(urllib.request, "urlopen", server)

    result = await _transport().list_changed_pages(["odoogarageeu"], since=None)
    assert [p["id"] for p in result] == [
        "odoogarageeu.WebHome",
        "odoogarageeu.Architecture.WebHome",
        "odoogarageeu.Details.WebHome",
    ]
    assert [p["space"] for p in result] == [
        "odoogarageeu",
        "odoogarageeu.Architecture",
        "odoogarageeu.Details",
    ]


async def test_gate_adapter_requires_spaces(monkeypatch) -> None:
    adapter = XWikiDocumentationAdapter(transport=_FakeTransport())
    assert await adapter.list_changed_documents(_now(), spaces=None) == []
    refs = await adapter.list_changed_documents(_now(), spaces=["ADAS"])
    assert [ref.external_id for ref in refs] == ["ADAS.Page"]
    assert refs[0].provider == "xwiki"
    assert refs[0].external_type == "page"


def test_transport_splits_dotted_references() -> None:
    transport = XWikiHTTPTransport("http://xwiki", user="u", password="p")

    # Single-space page: Space.Page
    assert transport._space("odoogarage.WebHome") == "odoogarage"
    assert transport._name("odoogarage.WebHome") == "WebHome"

    # Nested space page: the space is everything before the last segment.
    assert transport._space("odoogarage.Requirements.WebHome") == "odoogarage.Requirements"
    assert transport._name("odoogarage.Requirements.WebHome") == "WebHome"
    assert transport._space("odoogarage.Requirements.Vehicle") == "odoogarage.Requirements"
    assert transport._name("odoogarage.Requirements.Vehicle") == "Vehicle"

    # Slash form with and without wiki prefix.
    assert transport._space("xwiki/Main/WebHome") == "Main"
    assert transport._name("xwiki/Main/WebHome") == "WebHome"
    assert transport._space("hierarchy-test.Child/WebHome") == "hierarchy-test.Child"
    assert transport._name("hierarchy-test.Child/WebHome") == "WebHome"

    # Bare references fall back to Main.
    assert transport._space("WebHome") == "Main"
    assert transport._name("WebHome") == "WebHome"


def test_transport_builds_nested_space_url_paths() -> None:
    transport = XWikiHTTPTransport("http://xwiki", user="u", password="p")
    assert transport._space_url_path("odoogarage") == "spaces/odoogarage"
    assert (
        transport._space_url_path("odoogarageeu.Architecture")
        == "spaces/odoogarageeu/spaces/Architecture"
    )
    assert transport._space_url_path("a.b.c") == "spaces/a/spaces/b/spaces/c"


async def test_query_results_unescape_solr_references(monkeypatch) -> None:
    """Solr escapes dots in pageFullName/space; refs must be unescaped."""
    base = _now()
    server = _FakeSolrServer(
        [
            {
                "pageFullName": "odoogarage\\.Requirements\\.WebHome",
                "space": "odoogarage\\.Requirements",
                "title": "Requirements",
                "version": "1.1",
                "modified": int(base.timestamp() * 1000),
            },
            _page("odoogarage.WebHome", "odoogarage", base),
        ]
    )
    monkeypatch.setattr(urllib.request, "urlopen", server)
    result = await _transport().list_changed_pages(["odoogarage"], since=None)
    assert [p["id"] for p in result] == [
        "odoogarage.WebHome",
        "odoogarage.Requirements.WebHome",
    ]
    assert result[1]["space"] == "odoogarage.Requirements"


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
