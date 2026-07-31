"""add repository index

Revision ID: 0009_repository_index
Revises: 0008_repository_bindings
Create Date: 2026-07-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_repository_index"
down_revision = "0008_repository_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "repository_symbols",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository_key", sa.String(length=80), nullable=False),
        sa.Column("symbol_key", sa.String(length=500), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=True),
        sa.Column("end_line", sa.Integer(), nullable=True),
        sa.Column("parent_symbol_key", sa.String(length=500), nullable=True),
        sa.Column(
            "symbol_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "repository_key",
            "symbol_key",
            name="uq_repository_symbols_project_symbol",
        ),
    )
    op.create_index(
        "idx_repository_symbols_project_repository",
        "repository_symbols",
        ["project_id", "repository_key", "kind"],
    )
    op.create_index(
        "idx_repository_symbols_name",
        "repository_symbols",
        ["repository_key", "name"],
    )

    op.create_table(
        "repository_relationships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("repository_key", sa.String(length=80), nullable=False),
        sa.Column("source_symbol_key", sa.String(length=500), nullable=False),
        sa.Column("target_symbol_key", sa.String(length=500), nullable=True),
        sa.Column("target_name", sa.Text(), nullable=True),
        sa.Column("relationship_type", sa.String(length=80), nullable=False),
        sa.Column(
            "relationship_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_repository_relationships_project_repository",
        "repository_relationships",
        ["project_id", "repository_key", "relationship_type"],
    )
    op.create_index(
        "idx_repository_relationships_source",
        "repository_relationships",
        ["repository_key", "source_symbol_key"],
    )
    op.create_index(
        "idx_repository_relationships_target",
        "repository_relationships",
        ["repository_key", "target_symbol_key"],
    )


def downgrade() -> None:
    op.drop_index("idx_repository_relationships_target", table_name="repository_relationships")
    op.drop_index("idx_repository_relationships_source", table_name="repository_relationships")
    op.drop_index(
        "idx_repository_relationships_project_repository",
        table_name="repository_relationships",
    )
    op.drop_table("repository_relationships")
    op.drop_index("idx_repository_symbols_name", table_name="repository_symbols")
    op.drop_index(
        "idx_repository_symbols_project_repository",
        table_name="repository_symbols",
    )
    op.drop_table("repository_symbols")
