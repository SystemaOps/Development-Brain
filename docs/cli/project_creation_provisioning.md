# Project Creation and Provisioning Commands

This document defines the proposed project-creation workflows for the Brain.

The Brain owns the **canonical Project**. External systems such as OpenProject, GitLab, and XWiki remain separate systems and are linked to the canonical project through `ExternalReference` records.

## Goals

Support two main project-creation scenarios:

1. Create a completely new project across the Brain and all configured external systems.
2. Create only the canonical Brain project and connect or provision external systems later.

## Command 1 — Create a Complete Connected Project

```bash
brainctl project create <name>
```

### Purpose

Create a new project everywhere:

- Brain
- Work management system
- Source-control system
- Requirements / documentation system

Example:

```bash
brainctl project create "ADAS Platform"
```

### Expected Flow

```text
brainctl project create
        |
        v
Create canonical Brain Project
        |
        +--> Create OpenProject project
        |
        +--> Create GitLab project / repository
        |
        +--> Create XWiki project space
        |
        v
Create ExternalReference mappings
        |
        v
Project READY
```

Example mapping:

```text
Canonical Project
id = brain-uuid-123
name = ADAS Platform

ExternalReference
├── openproject/project/41
├── gitlab/project/812
└── xwiki/space/ADASPlatform
```

The canonical Brain project remains the primary project identity.

## Required Port Extensions

### Work Management

```python
class WorkManagementPort:
    async def create_project(...):
        ...
```

Example:

```text
OpenProjectAdapter
    -> POST /api/v3/projects
```

### Source Control

```python
class SourceControlPort:
    async def create_project(...):
        ...
```

Example:

```text
GitLabAdapter
    -> POST /projects
```

### Requirements / Documentation

```python
class RequirementsPort:
    async def create_project(...):
        ...
```

For XWiki, this may mean creating a project/root space and its initial documentation structure.

## Command 2 — Create Canonical Brain Project Only

```bash
brainctl project create-canonical <name>
```

Example:

```bash
brainctl project create-canonical "ADAS Platform"
```

### Purpose

Create only the canonical project in the Brain database.

It must not create anything in:

- OpenProject
- GitLab
- XWiki

### Flow

```text
brainctl project create-canonical
        |
        v
Create Project model
        |
        v
INSERT INTO projects
        |
        v
Commit Brain DB transaction
```

Example result:

```text
created 2c07... ADAS Platform
status: PLANNED
external systems: none
```

# Connecting External Systems Later

There are two different cases and they should be handled separately.

## Case A — External Projects Already Exist

Use:

```bash
brainctl project bootstrap <brain-project-id>
```

Example:

```bash
brainctl project bootstrap <brain-id> \
    --openproject 42 \
    --gitlab group/adas-platform \
    --xwiki ADASPlatform
```

### Purpose

Connect an existing Brain project to projects that already exist in external systems.

### Flow

```text
Canonical Brain Project
        |
        +--> Link existing OpenProject project
        |
        +--> Link existing GitLab project
        |
        +--> Link existing XWiki project
        |
        v
Create ExternalReferences
        |
        v
Import historical data
        |
        v
Resolve relationships
        |
        v
Build baseline
        |
        v
Enable live synchronization
```

Bootstrap should mean:

> Attach to existing external projects and import their history.

## Case B — External Projects Do Not Exist Yet

Use:

```bash
brainctl project provision <brain-project-id>
```

Example:

```bash
brainctl project provision <brain-id>
```

### Purpose

Create missing external projects for an already-existing canonical Brain project.

### Flow

```text
Existing Brain Project
        |
        +--> Create OpenProject project
        |
        +--> Create GitLab project
        |
        +--> Create XWiki project structure
        |
        v
Create ExternalReferences
        |
        v
Project READY
```

# Recommended CLI

## Create a new project everywhere

```bash
brainctl project create "ADAS Platform"
```

Meaning:

> Create a brand-new project ecosystem.

## Create only the Brain project

```bash
brainctl project create-canonical "ADAS Platform"
```

Meaning:

> Create the canonical Brain project but do not touch external systems.

## Connect existing external projects

```bash
brainctl project bootstrap <brain-id> \
    --openproject 42 \
    --gitlab group/adas-platform \
    --xwiki ADASPlatform
```

Meaning:

> These external projects already exist. Connect them and import their history.

## Create external systems later

```bash
brainctl project provision <brain-id>
```

Meaning:

> The Brain project already exists. Create its missing external counterparts.

# Optional Selective Creation

```bash
brainctl project create "ADAS Platform" \
    --work-management openproject \
    --source-control gitlab \
    --requirements xwiki
```

Selective creation:

```bash
brainctl project create "ADAS Platform" \
    --work-management openproject \
    --source-control gitlab \
    --no-requirements
```

# Application Architecture

The orchestration logic should not live directly inside the CLI command.

```text
CLI / API
    |
    v
ProjectProvisioningService
    |
    +--> ProjectRepository
    +--> WorkManagementPort
    +--> SourceControlPort
    +--> RequirementsPort
    +--> ExternalReferenceRepository
```

Example:

```python
class ProjectProvisioningService:

    async def create_canonical(
        self,
        name: str,
        description: str | None = None,
    ) -> Project:
        ...

    async def create_connected(
        self,
        name: str,
        description: str | None = None,
    ) -> Project:
        ...

    async def bootstrap(
        self,
        project_id: UUID,
        external_projects: ExternalProjects,
    ):
        ...

    async def provision(
        self,
        project_id: UUID,
    ):
        ...
```

This allows the same logic to be reused by:

- CLI
- REST API
- agents
- automation workflows

# Command Semantics

## `create`

```text
"I want a brand-new project ecosystem."
```

Creates:

- Brain project
- work-management project
- source-control project
- requirements/documentation project

## `create-canonical`

```text
"Brain should know about this project,
but external systems should not be touched yet."
```

Creates:

- Brain project only

## `bootstrap`

```text
"These external projects already exist.
Connect them and learn their history."
```

Performs:

- linking
- historical import
- relationship resolution
- baseline creation
- synchronization setup

## `provision`

```text
"The Brain project already exists.
Now create its missing external counterparts."
```

Creates:

- missing external projects
- corresponding `ExternalReference` mappings

# Design Principle

The Brain must continue to own the canonical project identity.

Even when the Brain creates projects in external systems, those external projects remain representations of the canonical project.

```text
Canonical Brain Project
        |
        +--> ExternalReference --> OpenProject Project
        |
        +--> ExternalReference --> GitLab Project
        |
        +--> ExternalReference --> XWiki Project
```

External systems should never become the canonical identity source.

# Summary

```text
NEW PROJECT EVERYWHERE
brainctl project create
```

```text
BRAIN ONLY
brainctl project create-canonical
```

```text
CONNECT EXISTING SYSTEMS
brainctl project bootstrap
```

```text
CREATE EXTERNAL SYSTEMS LATER
brainctl project provision
```

This keeps project creation, linking, historical import, and external-system provisioning clearly separated.
