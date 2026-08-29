# Backup and Rebuild Strategy (Task 40.9)

## Canonical vs rebuildable data

The Brain distinguishes data it must never lose from data it can always
regenerate from another source.

| Store        | Role                                 | Canonical | Rebuildable |
| ------------ | ------------------------------------ | :-------: | :---------: |
| Postgres     | state: projects, repos, requirements, work items, executions, verification results, observations, audit, approvals, checkpoints, context capsules, catalog | **yes**   |             |
| Neo4j        | code + knowledge graph               |           | **yes** (from Postgres + re-analysis) |
| Weaviate     | semantic index (embeddings)          |           | **yes** (re-embed from Postgres + source) |
| MinIO        | artifacts, repository snapshots, evidence | **yes** | partial (snapshots re-derivable from source control; artifacts not) |

Rule of thumb: **if it can be recomputed from Postgres + source control, it is
rebuildable.** Artifacts and evidence uploaded by external tools are canonical.

## Postgres

- `pg_dump -Fc brain > brain.dump` (scheduled, offsite).
- Restore: `pg_restore -d brain_new brain.dump`.
- Alembic migrations are forward-only; restore + `alembic upgrade head`.

## Neo4j

- Backup option A (fastest): Neo4j online backup (`neo4j-admin backup`).
- Backup option B (rebuild): delete the graph and re-run the projection:

  ```bash
  brainctl project reconcile --project <id>   # re-projects repository + knowledge graph
  ```

  The graph is rebuilt from repository ingestion and the canonical catalog in
  Postgres.  This is the preferred disaster-recovery path: no Neo4j-specific
  backup to maintain.

## Weaviate

- Never a backup target: re-embedding is cheap and deterministic.
- Rebuild:

  ```bash
  brainctl runtime reconcile               # scheduler re-indexes documents
  brainctl runtime reindex --all          # semantic re-index from Postgres
  ```

  Indexes carry no canonical state; losing Weaviate is a rebuild, not a loss.

## MinIO

- `mc mirror` the bucket to an offsite target (canonical artifacts/evidence).
- Repository snapshots are rebuildable via re-ingestion; uploaded artifacts
  (PDFs, binaries, conversion results) are not.

## Recovery order

1. Restore Postgres (canonical state).
2. Rebuild Neo4j (reconcile) and Weaviate (reindex).
3. Restore MinIO artifacts if the bucket was lost.
4. Start `brain-api`/`brain-worker`/`brain-scheduler`; capability registry
   confirms store availability.