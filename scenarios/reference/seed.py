"""Seed the Phase 39 reference scenario (Task 39.3).

Registers the sample project, repository, requirement and work item:

  uv run python -m scenarios.reference.seed --project e2e-demo

The sample repository already contains login-attempt tracking so the Brain
can discover the partial implementation (Task 39.2).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from brain.bootstrap.container import create_brain_container
from brain.bootstrap.settings import (
    BrainSettings,
    DocumentationSettings,
    Neo4jSettings,
    PostgresSettings,
    RedisSettings,
    SourceControlSettings,
    VerificationSettings,
    WeaviateSettings,
    WorkManagementSettings,
)
from brain.domain.repositories import Repository
from brain.domain.requirements import (
    AcceptanceCriterion,
    Constraint,
    ConstraintKind,
    Requirement,
    RequirementSource,
    RequirementSourceType,
    RequirementStatus,
)

SEED_DIR = Path(__file__).parent / "seed_repository"


def _settings() -> BrainSettings:
    return BrainSettings(
        storage_state=PostgresSettings(
            url="postgresql+asyncpg://postgres:postgres@localhost:5432/brain"
        ),
        storage_graph=Neo4jSettings(uri="bolt://localhost:7687"),
        storage_semantic=WeaviateSettings(host="localhost"),
        storage_queue=RedisSettings(url="redis://localhost:6379/0"),
        work_management=WorkManagementSettings(enabled=False),
        documentation=DocumentationSettings(git_enabled=False, xwiki_enabled=False),
        source_control=SourceControlSettings(enabled=False),
        verification=VerificationSettings(require_pass_before_pr=True),
    )


async def seed(project_name: str) -> dict[str, str]:
    container = await create_brain_container(_settings())
    try:
        from brain.domain.projects import Project
        from brain.domain.work_items import WorkItem, WorkItemType

        project = Project(name=project_name)
        await container.repositories.projects.create(project)

        repository = Repository(
            project_id=project.id,
            name="e2e-demo",
            clone_url=str(SEED_DIR.resolve().as_uri()),
            default_branch="main",
        )
        await container.repositories.repositories.create(repository)

        requirement = Requirement(
            project_id=project.id,
            key="REQ-ACCOUNT-LOCK",
            title="Account locking after five failed login attempts",
            description=(
                "After five consecutive failed login attempts the account must be "
                "locked for 15 minutes; further attempts must be rejected even "
                "with correct credentials."
            ),
            status=RequirementStatus.APPROVED,
            acceptance_criteria=[
                AcceptanceCriterion(description="A fifth failed attempt locks the account"),
                AcceptanceCriterion(
                    description="Locked accounts reject login attempts with LockedOut"
                ),
                AcceptanceCriterion(description="Lockout expires after 15 minutes"),
                AcceptanceCriterion(
                    description="Failed attempts before lockout are counted per account"
                ),
            ],
            constraints=[
                Constraint(
                    kind=ConstraintKind.MUST,
                    description="Lockout policy constants live in auth.security.SecurityPolicy",
                )
            ],
            source_refs=[
                RequirementSource(
                    source_type=RequirementSourceType.DOCUMENT,
                )
            ],
        )
        await container.repositories.requirements.create(requirement)

        work_item = WorkItem(
            project_id=project.id,
            type=WorkItemType.FEATURE,
            title="Implement account locking after five failed login attempts",
            description=requirement.description,
            requirement_refs=[requirement.id],
        )
        await container.repositories.work_items.create(work_item)

        return {
            "project_id": str(project.id),
            "repository_id": str(repository.id),
            "requirement_id": str(requirement.id),
            "work_item_id": str(work_item.id),
        }
    finally:
        await container.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the Phase 39 scenario")
    parser.add_argument("--project", default="e2e-demo", help="project name")
    args = parser.parse_args()
    ids = asyncio.run(seed(args.project))
    for name, value in ids.items():
        print(f"{name}={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
