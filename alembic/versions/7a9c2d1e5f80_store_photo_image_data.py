"""store photo image data

Revision ID: 7a9c2d1e5f80
Revises: 1f2a7b9c3d4e
Create Date: 2026-07-11 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7a9c2d1e5f80"
down_revision: Union[str, None] = "1f2a7b9c3d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("photos", sa.Column("content_type", sa.String(length=100), nullable=True))
    op.add_column("photos", sa.Column("image_data", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("photos", "image_data")
    op.drop_column("photos", "content_type")
