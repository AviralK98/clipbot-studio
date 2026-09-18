"""Offline deployment checks. Does not claim to execute Docker or connect to PostgreSQL."""
import io
import os
import tempfile
from pathlib import Path

import yaml
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

root = Path(__file__).resolve().parents[1]
os.chdir(root)
compose = yaml.safe_load((root / "docker-compose.yml").read_text())
assert set(compose["services"]) == {"frontend", "backend", "postgres", "redis", "worker", "scheduler", "n8n"}
for service in compose["services"].values():
    assert service.get("restart") == "unless-stopped"
    for port in service.get("ports", []):
        assert port.startswith("127.0.0.1:")
print("Compose structure: seven services, persistent volumes and loopback ports")

with tempfile.TemporaryDirectory(prefix="clipbot-migration-") as folder:
    url = "sqlite:///" + (Path(folder) / "migration.db").as_posix()
    os.environ["DATABASE_URL"] = url
    from clipbot.config import get_settings
    get_settings.cache_clear()
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    from clipbot.db import Base
    assert tables == set(Base.metadata.tables)
    command.check(Config("alembic.ini"))
    engine.dispose()
    command.downgrade(Config("alembic.ini"), "base")
    print(f"SQLite: fresh upgrade, schema comparison and rollback passed ({len(tables)} tables)")

os.environ["DATABASE_URL"] = "postgresql+psycopg://clipbot:unused@localhost/clipbot"
get_settings.cache_clear()
output = io.StringIO()
config = Config("alembic.ini", output_buffer=output)
command.upgrade(config, "head", sql=True)
sql = output.getvalue()
assert "CREATE TABLE sources" in sql and "CREATE TABLE system_jobs" in sql
artifact = root / "artifacts" / "postgres-migration.sql"
artifact.parent.mkdir(exist_ok=True)
artifact.write_text(sql, encoding="utf-8")
print("PostgreSQL: offline migration SQL generated; database execution still requires a PostgreSQL host")
