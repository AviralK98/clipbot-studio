# PyInstaller build for ClipBot.exe; run through scripts/build_windows.ps1, which builds the
# dashboard (apps/frontend/out) and the icon (build/clipbot.ico) first.
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent

hidden = [m for m in collect_submodules("clipbot") if m != "clipbot.worker"]  # worker.py is the Celery setup
hidden += collect_submodules("uvicorn") + collect_submodules("keyring.backends")
hidden += ["pystray._win32", "sqlalchemy.dialects.sqlite"]

datas = [(str(root / "apps/frontend/out"), "frontend")]
datas += collect_data_files("tzdata")  # Windows has no system time zone database
datas += copy_metadata("keyring")  # keyring finds Windows Credential Manager through package metadata

analysis = Analysis(
    [str(root / "packaging/launch.py")],
    pathex=[str(root / "apps/backend")],
    hiddenimports=hidden,
    datas=datas,
    # The server deployment's pieces (Celery, Redis, PostgreSQL, migrations, tests) aren't used here.
    excludes=["celery", "kombu", "redis", "psycopg", "alembic", "pytest", "respx"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ClipBot",
    icon=str(root / "build/clipbot.ico"),
    console=False,
    upx=False,
)
coll = COLLECT(exe, analysis.binaries, analysis.datas, name="ClipBot", upx=False)
