"""Add missing fields for report export

Revision ID: add_report_export_fields
Revises: 45a1a398984c
Create Date: 2026-02-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'add_report_export_fields'
down_revision: Union[str, None] = '45a1a398984c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # CustomerReport — new fields
    op.add_column('customer_reports', sa.Column('birth_place_date', sa.String(length=255), nullable=True))
    op.add_column('customer_reports', sa.Column('occupation', sa.String(length=255), nullable=True))
    op.add_column('customer_reports', sa.Column('gender', sa.String(length=10), nullable=True))
    op.add_column('customer_reports', sa.Column('phone_number', sa.String(length=50), nullable=True))
    op.add_column('customer_reports', sa.Column('recipient_name', sa.String(length=255), nullable=True))
    op.add_column('customer_reports', sa.Column('recipient_address', sa.Text(), nullable=True))

    # TransactionReport — new fields
    op.add_column('transaction_reports', sa.Column('customer_report_id', sa.Integer(), nullable=True))
    op.add_column('transaction_reports', sa.Column('fund_source', sa.String(length=255), nullable=True))
    op.add_column('transaction_reports', sa.Column('transaction_method', sa.String(length=100), nullable=True))
    op.create_foreign_key(
        'fk_transaction_reports_customer_report_id',
        'transaction_reports', 'customer_reports',
        ['customer_report_id'], ['id']
    )


def downgrade() -> None:
    op.drop_constraint('fk_transaction_reports_customer_report_id', 'transaction_reports', type_='foreignkey')
    op.drop_column('transaction_reports', 'transaction_method')
    op.drop_column('transaction_reports', 'fund_source')
    op.drop_column('transaction_reports', 'customer_report_id')

    op.drop_column('customer_reports', 'recipient_address')
    op.drop_column('customer_reports', 'recipient_name')
    op.drop_column('customer_reports', 'phone_number')
    op.drop_column('customer_reports', 'gender')
    op.drop_column('customer_reports', 'occupation')
    op.drop_column('customer_reports', 'birth_place_date')
