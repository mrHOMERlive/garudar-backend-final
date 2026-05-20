"""Service Agreement: dedicated tables + clients.service_agreement_status + migrate badges

Revision ID: ed6b73328198
Revises: 2ca13599e880
Create Date: 2026-05-18

Создаёт `service_agreement_requests` и `service_agreement_status_history` по
зеркальной схеме `nda_requests` / `nda_status_history`. Добавляет колонку
`clients.service_agreement_status` (зеркало `clients.nda_status`).

Data migration: переносит существующие `client_request_badges` с
`badge_type='service_agreement'` в новые таблицы, чтобы dedicated SA-flow
работал с историческими записями.

Маппинг badge.status → SA.status:
    not_required   → not_started   (или пропуск)
    pending        → draft
    need_signing   → generated
    submitted      → submitted
    completed      → accepted
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ed6b73328198"
down_revision: Union[str, None] = "2ca13599e880"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Таблица service_agreement_requests
    # ------------------------------------------------------------------
    op.create_table(
        "service_agreement_requests",
        sa.Column("sa_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(255), sa.ForeignKey("clients.client_id"), nullable=False),
        sa.Column("template_code", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), nullable=True, server_default="not_started"),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("company_name", sa.String(500), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("signatory_name", sa.String(500), nullable=True),
        sa.Column("signatory_title", sa.String(255), nullable=True),
        sa.Column("registration_number", sa.String(100), nullable=True),
        sa.Column("tax_id", sa.String(100), nullable=True),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("term", sa.String(100), nullable=True),
        sa.Column("generated_file_key", sa.String(500), nullable=True),
        sa.Column("generated_file_url", sa.Text(), nullable=True),
        sa.Column("generated_file_name", sa.String(255), nullable=True),
        sa.Column("generated_file_size", sa.BigInteger(), nullable=True),
        sa.Column("signed_file_key", sa.String(500), nullable=True),
        sa.Column("signed_file_url", sa.Text(), nullable=True),
        sa.Column("signed_file_name", sa.String(255), nullable=True),
        sa.Column("signed_file_size", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_sa_request_client", "service_agreement_requests", ["client_id"])
    op.create_index("idx_sa_request_status", "service_agreement_requests", ["status"])

    # ------------------------------------------------------------------
    # 2. Таблица service_agreement_status_history
    # ------------------------------------------------------------------
    op.create_table(
        "service_agreement_status_history",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "sa_id",
            sa.BigInteger(),
            sa.ForeignKey("service_agreement_requests.sa_id"),
            nullable=False,
        ),
        sa.Column("old_status", sa.String(50), nullable=True),
        sa.Column("new_status", sa.String(50), nullable=True),
        sa.Column("changed_by", sa.String(36), sa.ForeignKey("users.user_id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
    )
    op.create_index("idx_sa_history_sa", "service_agreement_status_history", ["sa_id"])
    op.create_index("idx_sa_history_date", "service_agreement_status_history", ["changed_at"])

    # ------------------------------------------------------------------
    # 3. Колонка clients.service_agreement_status
    # ------------------------------------------------------------------
    op.add_column(
        "clients",
        sa.Column(
            "service_agreement_status",
            sa.String(50),
            nullable=True,
            server_default="not_started",
        ),
    )

    # ------------------------------------------------------------------
    # 4. Data migration: badges → service_agreement_requests
    # Только активные / непустые badge переносим. is_active=true ИЛИ
    # submitted_document_url IS NOT NULL — заведомо «настоящие» записи.
    # ------------------------------------------------------------------
    op.execute(
        """
        INSERT INTO service_agreement_requests (
            client_id,
            status,
            generated_file_url,
            signed_file_url,
            created_at,
            updated_at,
            submitted_at
        )
        SELECT
            b.client_id,
            CASE
                WHEN b.status = 'completed'    THEN 'accepted'
                WHEN b.status = 'submitted'    THEN 'submitted'
                WHEN b.status = 'need_signing' THEN 'generated'
                WHEN b.status = 'pending'      THEN 'draft'
                ELSE 'not_started'
            END AS status,
            b.document_url           AS generated_file_url,
            b.submitted_document_url AS signed_file_url,
            b.created_at,
            b.updated_at,
            CASE
                WHEN b.status IN ('submitted', 'completed') THEN b.updated_at
                ELSE NULL
            END AS submitted_at
        FROM client_request_badges b
        WHERE b.badge_type = 'service_agreement'
          AND (b.is_active = true OR b.submitted_document_url IS NOT NULL)
        ;
        """
    )

    # Зеркалим SA-статус в clients.service_agreement_status.
    op.execute(
        """
        UPDATE clients c
        SET service_agreement_status = sub.status
        FROM (
            SELECT DISTINCT ON (sar.client_id)
                sar.client_id,
                sar.status
            FROM service_agreement_requests sar
            ORDER BY sar.client_id, sar.sa_id DESC
        ) sub
        WHERE c.client_id = sub.client_id
        ;
        """
    )


def downgrade() -> None:
    op.drop_column("clients", "service_agreement_status")
    op.drop_index("idx_sa_history_date", table_name="service_agreement_status_history")
    op.drop_index("idx_sa_history_sa", table_name="service_agreement_status_history")
    op.drop_table("service_agreement_status_history")
    op.drop_index("idx_sa_request_status", table_name="service_agreement_requests")
    op.drop_index("idx_sa_request_client", table_name="service_agreement_requests")
    op.drop_table("service_agreement_requests")
