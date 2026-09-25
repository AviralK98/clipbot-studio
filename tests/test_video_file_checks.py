"""Damaged clip files are caught before they reach YouTube, Gemini or the media folder."""

import httpx
import pytest
import respx
from clipbot import storage
from clipbot.errors import Blocked
from clipbot.storage import LocalStorage, is_video_file

JUNK = bytes([0x24, 0x1A, 0x9C, 0x92, 0x6D, 0x85, 0xCE, 0x6D]) * 64  # seen on 2026-09-22


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"\x00\x00\x00\x20ftypisom" + b"\x00" * 24, True),  # normal MP4
        (b"\x00\x00\x00\x08moov", True),  # MOV/MP4 that starts with the movie box
        (JUNK, False),
        (b"\x00\x00\x00", False),  # too short to hold a box header
        (b"", False),
    ],
)
def test_is_video_file(tmp_path, content, expected):
    path = tmp_path / "clip.mp4"
    path.write_bytes(content)
    assert is_video_file(path) is expected


def test_missing_file_is_not_a_video(tmp_path):
    assert is_video_file(tmp_path / "missing.mp4") is False


@respx.mock
async def test_download_that_is_not_a_video_is_rejected_and_not_kept(monkeypatch):
    monkeypatch.setattr(storage, "public_url", lambda url: url)  # no DNS lookups in tests
    respx.get("https://cdn.example.com/clip.mp4").mock(
        return_value=httpx.Response(200, headers={"content-type": "video/mp4"}, content=JUNK)
    )
    local = LocalStorage()
    with pytest.raises(Blocked, match="not a valid MP4"):
        await local.archive("https://cdn.example.com/clip.mp4", "clips/junk-download.mp4")
    assert not local.path("clips/junk-download.mp4").exists()
    assert not local.path("clips/junk-download.part").exists()
