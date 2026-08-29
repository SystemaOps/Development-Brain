"""Domain unit tests for Project, Repository, and Actor."""

from __future__ import annotations

from brain.domain.actors import Actor, ActorType
from brain.domain.external_reference import ExternalReference
from brain.domain.projects import Project, ProjectStatus
from brain.domain.repositories import Repository


def test_project_has_internal_identity() -> None:
    project = Project(name="auth")
    assert project.id is not None
    assert project.status == ProjectStatus.PLANNED
    assert project.repositories == []
    assert project.external_refs == []


def test_project_can_exist_without_external_provider() -> None:
    project = Project(name="auth")
    assert project.external_refs == []


def test_project_with_external_references() -> None:
    project = Project(
        name="auth",
        external_refs=[ExternalReference(provider="openproject", external_id="42")],
    )
    assert project.external_refs[0].external_id == "42"


def test_repository_links_to_project() -> None:
    project = Project(name="auth")
    repository = Repository(
        project_id=project.id,
        name="auth-service",
        clone_url="git@example.com:auth/auth-service.git",
    )
    assert repository.project_id == project.id
    assert repository.default_branch == "main"
    assert repository.current_revision is None


def test_repository_revision_can_be_recorded() -> None:
    project = Project(name="auth")
    repository = Repository(
        project_id=project.id,
        name="auth-service",
        clone_url="https://example.com/auth.git",
        current_revision="9c31e72",
    )
    assert repository.current_revision == "9c31e72"


def test_actor_types() -> None:
    human = Actor(actor_type=ActorType.HUMAN, display_name="dev")
    agent = Actor(actor_type=ActorType.AGENT, display_name="pi", capabilities=["coding"])
    assert human.actor_type == ActorType.HUMAN
    assert agent.capabilities == ["coding"]


def test_models_serialize_to_json() -> None:
    project = Project(name="auth")
    repository = Repository(project_id=project.id, name="auth", clone_url="x")
    actor = Actor(actor_type=ActorType.AGENT, display_name="pi")
    assert Project.model_validate_json(project.model_dump_json()) == project
    assert Repository.model_validate_json(repository.model_dump_json()) == repository
    assert Actor.model_validate_json(actor.model_dump_json()) == actor
