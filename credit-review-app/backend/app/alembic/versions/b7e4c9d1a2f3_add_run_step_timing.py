"""add run step timing columns

Revision ID: b7e4c9d1a2f3
Revises: 607b61c473bc
Create Date: 2026-11-12

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes

# revision identifiers, used by Alembic.
revision = 'b7e4c9d1a2f3'
down_revision = '607b61c473bc'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('run_steps', sa.Column('started_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))
    op.add_column('run_steps', sa.Column('finished_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True))


def downgrade():
    op.drop_column('run_steps', 'finished_at')
    op.drop_column('run_steps', 'started_at')
