import asyncio
import os
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urljoin

import httpx

from .config import get_settings
from .errors import Blocked
from .security import public_url

# MP4/MOV files are a series of boxes; the first box's type sits at bytes 4-8.
VIDEO_BOX_TYPES = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"pnot"}


def is_video_file(path) -> bool:
    """True if the file starts like an MP4/MOV.

    Catches files that were damaged on disk: on 2026-09-22 two clips were overwritten with a
    repeating junk block and uploaded anyway, and YouTube abandoned processing both.
    """
    try:
        with open(path, "rb") as stream:
            head = stream.read(8)
    except OSError:
        return False
    return len(head) == 8 and head[4:8] in VIDEO_BOX_TYPES


class StorageProvider(ABC):
    @abstractmethod
    async def archive(self, url: str, key: str) -> str: ...

    @abstractmethod
    def path(self, key: str) -> Path: ...


class LocalStorage(StorageProvider):
    def __init__(self, root: Path | None = None):
        self.root = (root or get_settings().storage_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key):
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise ValueError("Invalid storage key")
        return target

    async def archive(self, url, key):
        target = self.path(key)
        if target.is_file():
            return key
        target.parent.mkdir(parents=True, exist_ok=True)
        # Egress should additionally block private ranges at infrastructure level (DNS rebinding).
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            for _ in range(5):
                await asyncio.to_thread(public_url, url)
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers["location"])
                        continue
                    response.raise_for_status()
                    mime = response.headers.get("content-type", "").split(";")[0]
                    if mime not in {"video/mp4", "application/octet-stream", "video/quicktime"}:
                        raise Blocked("Clip URL did not return a supported video")
                    size = 0
                    part = target.with_suffix(".part")
                    try:
                        with part.open("wb") as stream:
                            async for chunk in response.aiter_bytes(1024 * 128):
                                size += len(chunk)
                                if size > get_settings().max_download_bytes:
                                    raise Blocked("Clip exceeds configured storage download limit")
                                stream.write(chunk)
                        if size == 0:
                            raise Blocked("Downloaded clip is empty")
                        if not is_video_file(part):
                            raise Blocked("Downloaded clip is not a valid MP4 video file")
                        os.replace(part, target)
                    finally:
                        part.unlink(missing_ok=True)
                    return key
        raise Blocked("Too many media redirects")
