"""Domain unit tests for ExternalReference mapping behavior."""

from __future__ import annotations

import pytest

from brain.domain.external_reference import ExternalReference


def test_external_reference_round_trip() -> None:
    ref = ExternalReference(provider="jira", external_id="AUTH-42", url="https://jira/AUTH-42")
    assert ref.provider == "jira"
    assert ref.external_id == "AUTH-42"
    assert ref.url == "https://jira/AUTH-42"


@pytest.mark.parametrize(
    ("provider", "external_id"),
    [
        ("openproject", "2148"),
        ("jira", "AUTH-42"),
        ("gitlab", "51"),
        ("github", "42"),
        ("confluence", "18722"),
        ("xwiki", "page-9"),
        ("backstage", "auth-service"),
    ],
)
def test_external_reference_supports_all_providers(provider: str, external_id: str) -> None:
    ref = ExternalReference(provider=provider, external_id=external_id)
    assert ref.provider == provider
    assert ref.external_id == external_id


def test_external_reference_optional_fields_default_to_none() -> None:
    ref = ExternalReference(provider="gitlab", external_id="51")
    assert ref.external_type is None
    assert ref.url is None
    assert ref.namespace is None


def test_external_reference_string_representation() -> None:
    assert str(ExternalReference(provider="jira", external_id="AUTH-42")) == "jira:AUTH-42"


def test_external_references_are_distinct_from_internal_ids() -> None:
    # External references are metadata, not identities; they never replace UUIDs.
    from brain.domain.identity import ProjectId, new_project_id

    project_id: ProjectId = new_project_id()
    ref = ExternalReference(provider="openproject", external_id="2148")
    assert str(project_id) != ref.external_id
    assert isinstance(project_id, object)
