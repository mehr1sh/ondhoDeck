"""provider credential workspace id

Anthropic API keys that are not scoped to a workspace must send the anthropic-workspace-id header.
Stores that (non-secret) workspace ID alongside the encrypted key.

Revision ID: a1c7e3f9b2d4
Revises: f2b8c4d1e6a9
Create Date: 2026-10-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c7e3f9b2d4"
down_revision: Union[str, None] = "f2b8c4d1e6a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("provider_credentials", sa.Column("workspace_id", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("provider_credentials", "workspace_id")
