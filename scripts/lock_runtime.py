"""Capture the installed runtime dependency closure, excluding development/artifact tools."""
from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

pending = [("clipbot", set())]
seen, versions = {}, {}
while pending:
    name, extras = pending.pop()
    name = canonicalize_name(name)
    if name in seen and extras <= seen[name]:
        continue
    seen[name] = seen.get(name, set()) | extras
    package = distribution(name)
    if name != "clipbot":
        versions[name] = package.version
    for raw in package.requires or []:
        req = Requirement(raw)
        if req.marker is None or any(req.marker.evaluate({"extra": extra}) for extra in ({""} | extras)):
            pending.append((req.name, set(req.extras)))
Path("requirements.lock").write_text("# Runtime versions validated by the build; regenerate with scripts/lock_runtime.py.\n" + "\n".join(f"{n}=={v}" for n,v in sorted(versions.items())) + "\n", encoding="utf-8")
