"""Phase A golden tests: OpenProject webhook parsing against real payloads.

Fixtures are the 8 real webhook bodies extracted from
``docs/webhook/data.txt`` (tests/fixtures/openproject/*.json).  The parser is
pure: no I/O, no orchestrator imports, only normalized snapshots.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain.application.openproject_parser import (
    OpenProjectWorkItemSnapshot,
    SemanticChange,
    diff_snapshots,
    event_type_for_action,
    id_from_href,
    parse_action,
    parse_attachment,
    parse_project,
    parse_work_item,
)
from brain.domain.events import EventType

FIXTURES = Path(__file__).parent / "fixtures" / "openproject"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_all_real_fixtures_parse_with_action() -> None:
    """Every payload in data.txt carries a real `action` field (doc §1)."""
    for fixture in FIXTURES.glob("*.json"):
        body = json.loads(fixture.read_text(encoding="utf-8"))
        assert parse_action(body), f"{fixture.name}: action missing"
        assert body["action"].startswith(("work_package:", "project:", "attachment:")), (
            f"{fixture.name}: unexpected action {body['action']}"
        )


# ---------------------------------------------------------------------------
# parse_action / event_type_for_action
# ---------------------------------------------------------------------------


def test_parse_action_prefers_action_field() -> None:
    assert parse_action({"action": "work_package:updated"}) == "work_package:updated"


def test_parse_action_falls_back_to_event_type() -> None:
    assert parse_action({"eventType": "work_package:updated"}) == "work_package:updated"
    assert parse_action({"event_type": "work_package:created"}) == "work_package:created"


def test_parse_action_missing_returns_empty() -> None:
    assert parse_action({}) == ""


def test_event_type_for_action() -> None:
    assert event_type_for_action("work_package:created") == EventType.WORK_ITEM_CREATED
    assert event_type_for_action("work_package:updated") == EventType.WORK_ITEM_CHANGED
    assert event_type_for_action("project:created") is None


# ---------------------------------------------------------------------------
# id_from_href (doc §7)
# ---------------------------------------------------------------------------


def test_id_from_href() -> None:
    assert id_from_href("/api/v3/work_packages/20") == 20
    assert id_from_href("/api/v3/projects/7") == 7
    assert id_from_href("/api/v3/work_packages/43/") == 43
    assert id_from_href(None) is None
    assert id_from_href("") is None
    assert id_from_href("not-a-number") is None


# ---------------------------------------------------------------------------
# parse_work_item (doc §2, §16) — wp 43 updated (data.txt line 2)
# ---------------------------------------------------------------------------


def test_parse_work_item_updated_snapshot_fields() -> None:
    snapshot = parse_work_item(_load("line2_work_package_updated.json"))
    assert snapshot is not None
    assert snapshot.external_id == "43"
    assert snapshot.summary == "test"
    assert snapshot.description == "Description"  # description.raw, not html
    assert snapshot.type == "Task"
    assert snapshot.priority == "High"
    assert snapshot.state == "New"
    assert snapshot.closed is False
    assert snapshot.project_id == "8"
    assert snapshot.project_name == "Infrastructure"
    assert snapshot.assignee_id == "6"
    assert snapshot.assignee_name == "brain brain"
    assert snapshot.parent_id is None
    assert snapshot.activities_url == "/api/v3/work_packages/43/activities"
    assert snapshot.created_at == "2026-09-01T12:01:07.843Z"
    assert snapshot.updated_at == "2026-09-18T10:52:09.412Z"


def test_parse_work_item_updated_attachments() -> None:
    snapshot = parse_work_item(_load("line2_work_package_updated.json"))
    assert snapshot is not None
    assert len(snapshot.attachments) == 1
    attachment = snapshot.attachments[0]
    assert attachment["id"] == 3
    assert attachment["file_name"] == "Screenshot_2026-04-27_224250.png"
    assert attachment["content_type"] == "image/png"
    assert attachment["file_size"] == 16026
    assert attachment["download_url"] == "/api/v3/attachments/3/content"


def test_parse_work_item_created_no_assignee() -> None:
    """data.txt line 30: same wp 43 but assignee is absent."""
    snapshot = parse_work_item(_load("line30_work_package_created.json"))
    assert snapshot is not None
    assert snapshot.external_id == "43"
    assert snapshot.assignee_id is None
    assert snapshot.assignee_name is None


def test_parse_work_item_without_work_package_returns_none() -> None:
    assert parse_work_item({}) is None
    assert parse_work_item({"action": "project:created", "project": {}}) is None


def test_parse_work_item_relations_and_empty_attachments() -> None:
    """wp 40 (line 33): no attachments, no relations."""
    snapshot = parse_work_item(_load("line33_work_package_updated.json"))
    assert snapshot is not None
    assert snapshot.external_id == "40"
    assert snapshot.summary == "test4"
    assert snapshot.priority == "Normal"
    assert snapshot.project_id == "3"
    assert snapshot.attachments == []
    assert snapshot.relations == []


# ---------------------------------------------------------------------------
# parse_project (doc §12) — root vs subproject
# ---------------------------------------------------------------------------


def test_parse_project_root() -> None:
    parsed = parse_project(_load("line14_project_created.json"))
    assert parsed["external_id"] == "7"
    assert parsed["name"] == "Test project"
    assert parsed["identifier"] == "test-project"
    assert parsed["parent_id"] is None


def test_parse_project_subproject_parent_from_embedded() -> None:
    parsed = parse_project(_load("line17_project_created.json"))
    assert parsed["external_id"] == "8"
    assert parsed["name"] == "Infrastructure"
    assert parsed["parent_id"] == "4"  # _embedded.parent.id


def test_parse_project_updated() -> None:
    parsed = parse_project(_load("line23_project_updated.json"))
    assert parsed["external_id"] == "4"
    assert parsed["parent_id"] == "3"


def test_parse_project_missing_returns_empty() -> None:
    assert parse_project({}) == {}


# ---------------------------------------------------------------------------
# parse_attachment (doc §10b) — attachment:created (data.txt line 20)
# ---------------------------------------------------------------------------


def test_parse_attachment_links_container_work_item() -> None:
    parsed = parse_attachment(_load("line20_attachment_created.json"))
    assert parsed["external_id"] == "3"
    assert parsed["file_name"] == "Screenshot_2026-04-27_224250.png"
    assert parsed["content_type"] == "image/png"
    assert parsed["file_size"] == 16026
    assert parsed["download_url"] == "/api/v3/attachments/3/content"
    assert parsed["work_item_id"] == "43"  # _embedded.container.id (WorkPackage)


def test_parse_attachment_missing_returns_empty() -> None:
    assert parse_attachment({}) == {}


# ---------------------------------------------------------------------------
# diff_snapshots (doc §14)
# ---------------------------------------------------------------------------


def _snapshot(**overrides: object) -> OpenProjectWorkItemSnapshot:
    base: dict[str, object] = {
        "external_id": "43",
        "summary": "test",
        "description": "Description",
        "priority": "High",
        "state": "New",
        "assignee_id": "6",
        "parent_id": None,
    }
    base.update(overrides)
    return OpenProjectWorkItemSnapshot(**base)  # type: ignore[arg-type]


def test_diff_no_previous_snapshot_emits_nothing() -> None:
    assert diff_snapshots(None, _snapshot()) == []


def test_diff_identical_snapshots_emits_nothing() -> None:
    assert diff_snapshots(_snapshot(), _snapshot()) == []


def test_diff_summary_changed() -> None:
    changes = diff_snapshots(_snapshot(), _snapshot(summary="new title"))
    assert changes == [SemanticChange.SUMMARY_CHANGED]


def test_diff_description_changed() -> None:
    changes = diff_snapshots(_snapshot(), _snapshot(description="new body"))
    assert changes == [SemanticChange.DESCRIPTION_CHANGED]


def test_diff_assignee_changed_none_to_brain() -> None:
    """The assignment trigger case (doc §6): None -> brain."""
    changes = diff_snapshots(
        _snapshot(assignee_id=None), _snapshot(assignee_id="6", assignee_name="brain")
    )
    assert changes == [SemanticChange.ASSIGNEE_CHANGED]


def test_diff_state_changed() -> None:
    changes = diff_snapshots(_snapshot(), _snapshot(state="In Progress"))
    assert changes == [SemanticChange.STATE_CHANGED]


def test_diff_priority_changed() -> None:
    changes = diff_snapshots(_snapshot(), _snapshot(priority="Normal"))
    assert changes == [SemanticChange.PRIORITY_CHANGED]


def test_diff_parent_changed() -> None:
    changes = diff_snapshots(_snapshot(), _snapshot(parent_id=20))
    assert changes == [SemanticChange.PARENT_CHANGED]


def test_diff_multiple_changes_reported() -> None:
    changes = diff_snapshots(
        _snapshot(),
        _snapshot(summary="s", state="Review", priority="Normal"),
    )
    assert set(changes) == {
        SemanticChange.SUMMARY_CHANGED,
        SemanticChange.STATE_CHANGED,
        SemanticChange.PRIORITY_CHANGED,
    }


def test_diff_real_created_vs_updated_payloads() -> None:
    """data.txt lines 30 (created, no assignee) vs 2 (updated, assigned).

    The only field differences must be assignee (+ later updated_at); the
    parser must not over-report.
    """
    created = parse_work_item(_load("line30_work_package_created.json"))
    updated = parse_work_item(_load("line2_work_package_updated.json"))
    assert created is not None and updated is not None
    changes = diff_snapshots(created, updated)
    assert SemanticChange.ASSIGNEE_CHANGED in changes
    # timestamps are not part of the semantic diff
    assert SemanticChange.STATE_CHANGED not in changes
    assert SemanticChange.SUMMARY_CHANGED not in changes


@pytest.mark.parametrize(
    ("field", "new_value", "expected"),
    [
        ("summary", "x", SemanticChange.SUMMARY_CHANGED),
        ("description", "x", SemanticChange.DESCRIPTION_CHANGED),
        ("state", "x", SemanticChange.STATE_CHANGED),
        ("priority", "x", SemanticChange.PRIORITY_CHANGED),
        ("parent_id", 7, SemanticChange.PARENT_CHANGED),
        ("assignee_id", "99", SemanticChange.ASSIGNEE_CHANGED),
    ],
)
def test_diff_each_semantic_event(field: str, new_value: object, expected: SemanticChange) -> None:
    changes = diff_snapshots(_snapshot(), _snapshot(**{field: new_value}))
    assert expected in changes
