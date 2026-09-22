"""add rejected_row_ids to data quality reports

Revision ID: 969bc06cbab4
Revises: accafd4212d1
Create Date: 2026-09-22 08:13:56.221582

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '969bc06cbab4'
down_revision = 'accafd4212d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default nécessaire : des rapports existent déjà en base
    # (runs précédents) et n'ont pas de valeur pour cette nouvelle colonne.
    op.add_column(
        'data_quality_reports',
        sa.Column('rejected_row_ids', sa.JSON(), nullable=False, server_default='[]'),
    )
    op.alter_column('data_quality_reports', 'rejected_row_ids', server_default=None)


def downgrade() -> None:
    op.drop_column('data_quality_reports', 'rejected_row_ids')
