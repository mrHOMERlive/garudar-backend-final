"""Add surrogate id to payeer_accounts, allow account_no update

Revision ID: 560fa9ca2a32
Revises: 154e02408bc0
Create Date: 2026-02-07 08:23:21.117022

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '560fa9ca2a32'
down_revision: Union[str, None] = '154e02408bc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop FK constraints that reference payeer_accounts.account_no
    op.drop_constraint('mandiri_fx_fifo_account_no_fkey', 'mandiri_fx_fifo', type_='foreignkey')
    op.drop_constraint('mandiri_statement_account_no_fkey', 'mandiri_statement', type_='foreignkey')

    # 2. Drop existing PK on account_no
    op.drop_constraint('payeer_accounts_pkey', 'payeer_accounts', type_='primary')

    # 3. Create sequence and add id column as nullable first
    op.execute("CREATE SEQUENCE payeer_accounts_id_seq AS BIGINT")
    op.add_column('payeer_accounts', sa.Column('id', sa.BigInteger(), nullable=True))

    # 4. Populate id for existing rows
    op.execute("UPDATE payeer_accounts SET id = nextval('payeer_accounts_id_seq')")

    # 5. Make id NOT NULL and set default
    op.alter_column('payeer_accounts', 'id', nullable=False,
                     server_default=sa.text("nextval('payeer_accounts_id_seq')"))
    op.execute("ALTER SEQUENCE payeer_accounts_id_seq OWNED BY payeer_accounts.id")

    # 6. Add PK on id
    op.create_primary_key('payeer_accounts_pkey', 'payeer_accounts', ['id'])

    # 7. Add UNIQUE constraint on account_no
    op.create_unique_constraint('uq_payeer_accounts_account_no', 'payeer_accounts', ['account_no'])

    # 8. Recreate FK constraints with ON UPDATE CASCADE
    op.create_foreign_key(
        'mandiri_statement_account_no_fkey', 'mandiri_statement', 'payeer_accounts',
        ['account_no'], ['account_no'], onupdate='CASCADE'
    )
    op.create_foreign_key(
        'mandiri_fx_fifo_account_no_fkey', 'mandiri_fx_fifo', 'payeer_accounts',
        ['account_no'], ['account_no'], onupdate='CASCADE'
    )


def downgrade() -> None:
    # 1. Drop FK constraints
    op.drop_constraint('mandiri_fx_fifo_account_no_fkey', 'mandiri_fx_fifo', type_='foreignkey')
    op.drop_constraint('mandiri_statement_account_no_fkey', 'mandiri_statement', type_='foreignkey')

    # 2. Drop unique constraint and PK on id
    op.drop_constraint('uq_payeer_accounts_account_no', 'payeer_accounts', type_='unique')
    op.drop_constraint('payeer_accounts_pkey', 'payeer_accounts', type_='primary')

    # 3. Drop id column and sequence
    op.drop_column('payeer_accounts', 'id')
    op.execute("DROP SEQUENCE IF EXISTS payeer_accounts_id_seq")

    # 4. Restore PK on account_no
    op.create_primary_key('payeer_accounts_pkey', 'payeer_accounts', ['account_no'])

    # 5. Restore original FK constraints (without CASCADE)
    op.create_foreign_key(
        'mandiri_statement_account_no_fkey', 'mandiri_statement', 'payeer_accounts',
        ['account_no'], ['account_no']
    )
    op.create_foreign_key(
        'mandiri_fx_fifo_account_no_fkey', 'mandiri_fx_fifo', 'payeer_accounts',
        ['account_no'], ['account_no']
    )
