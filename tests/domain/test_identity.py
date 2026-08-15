"""Domain unit tests for identity types."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from brain.domain.identity import (
    ProjectId,
    WorkItemId,
    new_project_id,
    new_work_item_id,
)


class _Holder(BaseModel):
    project_id: ProjectId = Field(default_factory=new_project_id)
    work_item_id: WorkItemId = Field(default_factory=new_work_item_id)


def test_ids_are_uuids() -> None:
    assert isinstance(new_project_id(), uuid.UUID)
    assert isinstance(new_work_item_id(), uuid.UUID)


def test_ids_are_unique() -> None:
    assert new_project_id() != new_project_id()
    assert new_work_item_id() != new_work_item_id()


def test_ids_serialize_through_pydantic() -> None:
    holder = _Holder()
    dumped = holder.model_dump()
    assert isinstance(dumped["project_id"], uuid.UUID)
    assert isinstance(dumped["work_item_id"], uuid.UUID)

    # Round-trip through JSON keeps valid UUIDs.
    reloaded = _Holder.model_validate_json(holder.model_dump_json())
    assert reloaded.project_id == holder.project_id
    assert reloaded.work_item_id == holder.work_item_id


def test_newtype_distinguishes_kinds() -> None:
    project_id = new_project_id()
    work_item_id = new_work_item_id()
    # Types are distinct at the type level; values are still UUIDs at runtime.
    assert type(project_id) is uuid.UUID
    assert type(work_item_id) is uuid.UUID
