"""Picking clips in the library queues them in pick order; unpicking takes them out and closes the gap."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from clipbot.db import Session, transaction
from clipbot.jobs import drain
from clipbot.models import Clip, PublishedPost, ScheduledPost, SocialAccount, SystemState, now
from sqlalchemy import select
from test_pipeline import finish_demo


async def studio_with_clips(client):
    video_id = await finish_demo(client)
    with transaction() as db:
        state = db.get(SystemState, 1)
        state.timezone, state.posting_times, state.min_interval = (
            "Europe/London",
            ["09:00", "14:00", "19:00"],
            180,
        )
        clips = [
            c.id
            for c in db.scalars(
                select(Clip).where(Clip.source_video_id == video_id, Clip.status == "approved")
            )
        ]
        account = db.scalar(select(SocialAccount).where(SocialAccount.platform == "youtube")).id
    return clips, account


def queue_order(account):
    with Session() as db:
        posts = db.scalars(
            select(ScheduledPost)
            .where(ScheduledPost.account_id == account, ScheduledPost.status == "scheduled")
            .order_by(ScheduledPost.scheduled_at)
        )
        return [(p.clip_id, p.scheduled_at) for p in posts]


async def test_picked_clips_queue_in_pick_order_and_unpicking_closes_the_gap(client):
    (a, b, c, d), account = await studio_with_clips(client)

    body = client.post("/api/queue/batch", json={"clip_ids": [c, a, b], "account_id": account}).json()
    assert [q["id"] for q in body["queued"]] == [c, a, b] and body["skipped"] == []
    first = queue_order(account)
    assert [clip for clip, _ in first] == [c, a, b]

    # A later pick goes after everything already queued.
    client.post("/api/queue/batch", json={"clip_ids": [d], "account_id": account})
    assert [clip for clip, _ in queue_order(account)] == [c, a, b, d]

    # Picking a queued clip again doesn't queue it twice.
    again = client.post("/api/queue/batch", json={"clip_ids": [a], "account_id": account}).json()
    assert again["queued"] == [] and "Already queued" in again["skipped"][0]["reason"]

    # Unpicking the 2nd clip moves the later ones up into the freed slots, in the same order.
    with Session() as db:
        post = db.scalar(select(ScheduledPost).where(ScheduledPost.clip_id == a))
    unpicked = client.post(f"/api/queue/{post.id}/cancel?compact=true", json={})
    assert unpicked.status_code == 200, unpicked.json()
    after = queue_order(account)
    assert [clip for clip, _ in after] == [c, b, d]
    assert [when for _, when in after] == [when for _, when in first]
    with Session() as db:
        assert db.get(Clip, a).status == "approved"

    # Picking it again puts it at the end of the queue.
    repicked = client.post("/api/queue/batch", json={"clip_ids": [a], "account_id": account}).json()
    assert [q["id"] for q in repicked["queued"]] == [a]
    assert [clip for clip, _ in queue_order(account)] == [c, b, d, a]


async def test_a_cancelled_slot_can_be_used_again(client):
    (a, b, *_), account = await studio_with_clips(client)
    post = client.post("/api/queue", json={"clip_id": a, "account_id": account}).json()
    assert client.post(f"/api/queue/{post['id']}/cancel", json={}).status_code == 200
    again = client.post("/api/queue", json={"clip_id": b, "account_id": account})
    assert again.status_code == 200, again.json()
    assert again.json()["scheduled_at"] == post["scheduled_at"]


async def test_picking_a_clip_waiting_for_review_approves_it(client):
    (a, b, *_), account = await studio_with_clips(client)
    with transaction() as db:
        waiting, flagged = db.get(Clip, a), db.get(Clip, b)
        waiting.status = flagged.status = "reserve"
        waiting.manually_approved = flagged.manually_approved = False
        flagged.policy_flags = ["violence"]

    body = client.post("/api/queue/batch", json={"clip_ids": [a, b], "account_id": account}).json()
    assert [q["id"] for q in body["queued"]] == [a]
    assert "content flags" in body["skipped"][0]["reason"]
    with Session() as db:
        assert db.get(Clip, a).manually_approved is True
        assert (db.get(Clip, b).status, db.get(Clip, b).manually_approved) == ("reserve", False)


async def test_too_close_custom_time_says_what_it_clashes_with(client):
    (a, b, *_), account = await studio_with_clips(client)
    day = (now() + timedelta(days=2)).date()
    first = datetime(day.year, day.month, day.day, 11, 0, tzinfo=UTC)
    assert (
        client.post(
            "/api/queue", json={"clip_id": a, "account_id": account, "scheduled_at": first.isoformat()}
        ).status_code
        == 200
    )

    clash = client.post(
        "/api/queue",
        json={
            "clip_id": b,
            "account_id": account,
            "scheduled_at": (first + timedelta(minutes=6)).isoformat(),
        },
    )
    assert clash.status_code == 409
    detail = clash.json()["detail"]
    with Session() as db:
        title = db.get(Clip, a).title
    assert f"need 3 h between them, and “{title}” goes out at" in detail
    earliest = (first + timedelta(hours=3)).astimezone(ZoneInfo("Europe/London")).strftime("%a %d %b %H:%M")
    assert detail.endswith(f"The earliest free time is {earliest} (change the spacing in Settings).")


async def test_upload_now_posts_picked_clips_straight_away_in_pick_order(client):
    (a, b, c, *_), account = await studio_with_clips(client)
    with transaction() as db:
        db.get(Clip, c).status = "reserve"  # waiting for review; picking it approves it

    body = client.post(
        "/api/queue/batch", json={"clip_ids": [c, a, b], "account_id": account, "now": True}
    ).json()
    assert [q["id"] for q in body["queued"]] == [c, a, b] and body["skipped"] == []
    # Minutes apart at most: upload-now skips the posting times and the 3-hour spacing.
    times = [when for _, when in queue_order(account)]
    assert times[-1] - times[0] < timedelta(minutes=1)

    await drain()
    with Session() as db:
        published = db.scalars(
            select(PublishedPost)
            .where(PublishedPost.clip_id.in_([a, b, c]))
            .order_by(PublishedPost.published_at)
        )
        assert [p.clip_id for p in published] == [c, a, b]


async def test_upload_now_respects_the_daily_limit_and_the_pause(client):
    (a, b, *_), account = await studio_with_clips(client)
    with transaction() as db:
        db.get(SocialAccount, account).daily_limit = 1
    body = client.post(
        "/api/queue/batch", json={"clip_ids": [a, b], "account_id": account, "now": True}
    ).json()
    assert [q["id"] for q in body["queued"]] == [a]
    assert "posting limit" in body["skipped"][0]["reason"]
    with Session() as db:
        assert db.get(Clip, b).status == "approved"

    with transaction() as db:
        db.get(SystemState, 1).stop_all_posting = True
    paused = client.post("/api/queue/batch", json={"clip_ids": [b], "account_id": account, "now": True})
    assert paused.status_code == 409 and "stopped" in paused.json()["detail"]
