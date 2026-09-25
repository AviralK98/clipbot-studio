"""clip_analyses: saved Gemini watch-through analyses of published Shorts"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c2d61f4a9e7"
down_revision: str | None = "3f8d4073d87a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Development databases create tables on startup (Base.metadata.create_all), so the
    # table may already exist when this migration first runs there.
    if sa.inspect(op.get_bind()).has_table("clip_analyses"):
        return
    op.create_table(
        "clip_analyses",
        sa.Column("video_id", sa.String(length=64), nullable=False),
        sa.Column("clip_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["clip_id"], ["clips.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("video_id"),
    )
    with op.batch_alter_table("clip_analyses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_clip_analyses_clip_id"), ["clip_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_clip_analyses_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("clip_analyses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_clip_analyses_created_at"))
        batch_op.drop_index(batch_op.f("ix_clip_analyses_clip_id"))
    op.drop_table("clip_analyses")
