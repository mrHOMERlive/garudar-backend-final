"""Add customer_reports and transaction_reports tables

Revision ID: 45a1a398984c
Revises: add_nda_fields_001
Create Date: 2026-02-21 20:26:46.880789

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '45a1a398984c'
down_revision: Union[str, None] = 'add_nda_fields_001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'customer_reports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('customer_type', sa.String(length=50), nullable=True),
        sa.Column('registration_number', sa.String(length=100), nullable=True),
        sa.Column('tax_number', sa.String(length=100), nullable=True),
        sa.Column('legal_tax_number_type', sa.String(length=50), nullable=True),
        sa.Column('legal_tax_number', sa.String(length=100), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('address', sa.Text(), nullable=True),
        sa.Column('indonesian_citizenship', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('director_name', sa.String(length=255), nullable=True),
        sa.Column('pep_indicator', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('code_type', sa.String(length=50), nullable=True),
        sa.Column('business_area', sa.String(length=255), nullable=True),
        sa.Column('created_date', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_customer_reports_created_date', 'customer_reports', ['created_date'], unique=False)
    
    op.create_table(
        'transaction_reports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('transaction_id', sa.String(length=100), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('sender_name', sa.String(length=255), nullable=True),
        sa.Column('sender_address', sa.Text(), nullable=True),
        sa.Column('sender_bank_bic', sa.String(length=20), nullable=True),
        sa.Column('sender_bank_name', sa.String(length=255), nullable=True),
        sa.Column('account_holder_name', sa.String(length=255), nullable=True),
        sa.Column('account_number', sa.String(length=100), nullable=True),
        sa.Column('transaction_type', sa.String(length=50), nullable=True),
        sa.Column('transaction_purpose', sa.Text(), nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('amount', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('recipient_name', sa.String(length=255), nullable=True),
        sa.Column('recipient_address', sa.Text(), nullable=True),
        sa.Column('transfer_fee', sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column('beneficiary_type', sa.String(length=50), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),
        sa.Column('dttot_check', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('dpppspm_check', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_date', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', sa.String(length=255), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transaction_id')
    )
    op.create_index('idx_transaction_reports_date', 'transaction_reports', ['date'], unique=False)
    op.create_index('idx_transaction_reports_transaction_id', 'transaction_reports', ['transaction_id'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_transaction_reports_transaction_id', table_name='transaction_reports')
    op.drop_index('idx_transaction_reports_date', table_name='transaction_reports')
    op.drop_table('transaction_reports')
    
    op.drop_index('idx_customer_reports_created_date', table_name='customer_reports')
    op.drop_table('customer_reports')
