from contextlib import contextmanager

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


cfg = get_settings()
if cfg.database_url.startswith("sqlite"):
    from sqlalchemy.engine import make_url

    database = make_url(cfg.database_url).database
    if database and database != ":memory:":
        from pathlib import Path

        Path(database).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(
    cfg.database_url,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False, "timeout": 30} if cfg.database_url.startswith("sqlite") else {},
)
if cfg.database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_setup(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")


Session = sessionmaker(engine, expire_on_commit=False)


@contextmanager
def transaction():
    """Serialize reservations/settings/schedule changes on SQLite and Postgres."""
    from .models import SystemState

    with Session() as db:
        if engine.dialect.name == "sqlite":
            db.execute(text("BEGIN IMMEDIATE"))
        else:
            db.execute(select(SystemState).where(SystemState.id == 1).with_for_update())
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


def initialize():
    from .models import SystemState, User
    from .security import hash_password, verify_password

    if cfg.app_env != "production":
        Base.metadata.create_all(engine)
    with Session.begin() as db:
        if not db.get(SystemState, 1):
            db.add(
                SystemState(
                    id=1,
                    autopilot=cfg.autopilot,
                    stop_all_posting=cfg.stop_all_posting,
                    timezone=cfg.timezone,
                    posting_times=cfg.posting_times.split(","),
                    daily_limit=cfg.max_posts_per_platform_per_day,
                    min_interval=cfg.min_post_interval_minutes,
                )
            )
        # A configured ADMIN_PASSWORD is the password. Without one (the desktop app), the owner
        # creates it on the first-run screen and it's never overwritten here.
        if "admin_password" not in cfg.model_fields_set:
            return
        if not db.get(User, "owner"):
            db.add(User(id="owner", name="Studio owner", password_hash=hash_password(cfg.admin_password)))
        elif not verify_password(cfg.admin_password, db.get(User, "owner").password_hash):
            db.get(User, "owner").password_hash = hash_password(cfg.admin_password)
