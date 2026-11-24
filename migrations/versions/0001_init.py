"""initial contract tables

Revision ID: 0001_init
Revises:
Create Date: 2026-11-24

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doc_contract",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("site_id", sa.String(length=64), nullable=True),
        sa.Column("object_key", sa.String(length=512), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("ext", sa.String(length=16), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=True),
        sa.Column("contract_type_hint", sa.String(length=32), nullable=True),
        sa.Column("member_company_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="uploaded"),
        sa.Column("dispatch_state", sa.String(length=32), nullable=False, server_default="dispatch_pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # De-duplication rule of order 1899: at most ONE active row per
    # (org_id, sha256).  The partial predicate makes a soft deleted row stop
    # blocking the re-upload of the same file:
    #   CREATE UNIQUE INDEX uq_doc_contract_org_sha256_active
    #     ON doc_contract (org_id, sha256) WHERE deleted_at IS NULL
    op.create_index(
        "uq_doc_contract_org_sha256_active",
        "doc_contract",
        ["org_id", "sha256"],
        unique=True,
        sqlite_where=sa.text("deleted_at IS NULL"),
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_doc_contract_org_id_id", "doc_contract", ["org_id", "id"]
    )

    op.create_table(
        "doc_contract_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("dispatch_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "doc_recognition_task",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("dispatch_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("payload", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("doc_recognition_task")
    op.drop_table("doc_contract_outbox")
    op.drop_index("ix_doc_contract_org_id_id", table_name="doc_contract")
    op.drop_index("uq_doc_contract_org_sha256_active", table_name="doc_contract")
    op.drop_table("doc_contract")
