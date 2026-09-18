import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import feedparser
import httpx
from defusedxml import ElementTree

from .config import get_settings
from .errors import Blocked
from .integrations.http import request_json
from .security import public_url


@dataclass
class Discovery:
    external_id: str
    title: str
    url: str
    duration: float


def youtube_id(url):
    parts = urlparse(url)
    if parts.hostname in {"youtu.be"}:
        return parts.path.strip("/")
    if parts.hostname in {"www.youtube.com", "youtube.com", "m.youtube.com"}:
        return parse_qs(parts.query).get("v", [None])[0]
    return None


def duration_seconds(value):
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?", value)
    if not match:
        raise Blocked("Source duration could not be verified")
    h, m, s = match.groups()
    return float(h or 0) * 3600 + float(m or 0) * 60 + float(s or 0)


async def youtube_details(ids):
    cfg = get_settings()
    if not cfg.youtube_data_api_key:
        raise Blocked("YouTube discovery and duration verification require YOUTUBE_DATA_API_KEY")
    async with httpx.AsyncClient(timeout=30) as client:
        data = await request_json(
            client,
            "GET",
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,contentDetails", "id": ",".join(ids), "key": cfg.youtube_data_api_key},
        )
    return [
        Discovery(
            v["id"],
            v["snippet"]["title"],
            f"https://www.youtube.com/watch?v={v['id']}",
            duration_seconds(v["contentDetails"]["duration"]),
        )
        for v in data.get("items", [])
    ]


async def discover(source):
    cfg = get_settings()
    if source.kind == "manual":
        return []
    if source.kind in {"google_drive", "dropbox"}:
        raise Blocked(
            "Folder discovery needs an OAuth connector; use an authorized public video URL or local folder"
        )
    if source.kind == "local":
        folder = (cfg.source_directory / source.url).resolve()
        if not folder.is_relative_to(cfg.source_directory.resolve()):
            raise Blocked("Local source must be inside SOURCE_DIRECTORY")
        if not cfg.public_media_base_url:
            raise Blocked("Local source delivery requires a publicly reachable PUBLIC_MEDIA_BASE_URL")
        records = []
        for file in sorted(folder.glob("*.mp4"))[:100]:
            if not file.resolve().is_relative_to(cfg.source_directory.resolve()):
                continue
            process = await asyncio.create_subprocess_exec(
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, _ = await asyncio.wait_for(process.communicate(), 30)
            if process.returncode:
                continue  # partially written files are checked again next sweep
            duration = float(json.loads(output)["format"]["duration"])
            identity = hashlib.sha256((str(file) + str(file.stat().st_mtime_ns)).encode()).hexdigest()
            import shutil

            from .storage import LocalStorage

            key = f"sources/{identity}.mp4"
            dest = LocalStorage().path(key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                await asyncio.to_thread(shutil.copyfile, file, dest)
            records.append(
                Discovery(identity, file.stem, f"{cfg.public_media_base_url.rstrip('/')}/{key}", duration)
            )
        return records
    if source.kind in {"youtube_channel", "youtube_playlist"}:
        if not cfg.youtube_data_api_key:
            raise Blocked("Populate YOUTUBE_DATA_API_KEY for YouTube monitoring")
        async with httpx.AsyncClient(timeout=30) as client:
            playlist = parse_qs(urlparse(source.url).query).get("list", [None])[0]
            if source.kind == "youtube_channel":
                handle = urlparse(source.url).path.strip("/").split("/")[-1]
                parameter = "forHandle" if handle.startswith("@") else "id"
                data = await request_json(
                    client,
                    "GET",
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "contentDetails", parameter: handle, "key": cfg.youtube_data_api_key},
                )
                if not data.get("items"):
                    raise Blocked("YouTube channel not found; use a channel ID or @handle URL")
                playlist = data["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
            if not playlist:
                raise Blocked("YouTube playlist URL needs a list parameter")
            ids, token = [], None
            for _ in range(10):
                params = {
                    "part": "contentDetails",
                    "playlistId": playlist,
                    "maxResults": 50,
                    "key": cfg.youtube_data_api_key,
                }
                if token:
                    params["pageToken"] = token
                data = await request_json(
                    client, "GET", "https://www.googleapis.com/youtube/v3/playlistItems", params=params
                )
                ids.extend(i["contentDetails"]["videoId"] for i in data.get("items", []))
                token = data.get("nextPageToken")
                if not token:
                    break
        result = []
        for start in range(0, len(ids), 50):
            result.extend(await youtube_details(ids[start : start + 50]))
        return result
    if source.kind == "rss":
        await asyncio.to_thread(public_url, source.url)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            async with client.stream("GET", source.url) as response:
                response.raise_for_status()
                parts, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise Blocked("RSS feed exceeds 2 MB")
                    parts.append(chunk)
        raw = b"".join(parts)
        ElementTree.fromstring(raw)  # Reject entity expansion / DTD before feedparser.
        feed = feedparser.parse(raw)
        result = []
        for entry in feed.entries[:100]:
            media = next(
                (e for e in entry.get("enclosures", []) if e.get("type", "").startswith("video/")), None
            )
            if not media or not entry.get("itunes_duration"):
                continue
            units = list(map(float, entry.itunes_duration.split(":")))
            seconds = sum(value * 60**index for index, value in enumerate(reversed(units)))
            url = public_url(media.href, resolve=False)
            result.append(Discovery(entry.get("id", url), entry.get("title", "RSS video"), url, seconds))
        return result
    raise Blocked("Unsupported source monitor")
