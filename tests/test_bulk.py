from clipbot.db import transaction
from clipbot.models import Clip, SocialAccount, SystemState
from sqlalchemy import select
from test_pipeline import finish_demo


async def test_bulk_approval_upload_limits_and_idempotency(client):
    video = await finish_demo(client)
    with transaction() as db:
        clips = list(db.scalars(select(Clip).where(Clip.source_video_id == video, Clip.status == "approved")))
        for c in clips:
            c.status = "reserve"
            c.manually_approved = False
        ids = [c.id for c in clips]
        account = db.scalar(select(SocialAccount).where(SocialAccount.platform == "youtube"))
        account.daily_limit = 1
        aid = account.id
        state = db.get(SystemState, 1)
        state.stop_all_posting = False
    preview = client.get("/api/clips/bulk-preview").json()
    assert set(ids) <= set(preview["approve"])
    response = client.post("/api/clips/bulk-approve", json={"clip_ids": ids + ids})
    assert len(response.json()["changed"]) == len(ids)
    response = client.post("/api/clips/bulk-upload", json={"clip_ids": ids, "account_id": aid})
    assert response.status_code == 200, response.text
    assert len(response.json()["changed"]) == 1
    assert len(response.json()["skipped"]) == len(ids) - 1
    assert not client.post("/api/clips/bulk-upload", json={"clip_ids": ids, "account_id": aid}).json()[
        "changed"
    ]
    with transaction() as db:
        db.get(SystemState, 1).stop_all_posting = True
    assert client.post("/api/clips/bulk-upload", json={"clip_ids": ids, "account_id": aid}).status_code >= 400


async def test_bulk_skips_flags_and_wrong_environment(client):
    video = await finish_demo(client)
    with transaction() as db:
        clips = list(db.scalars(select(Clip).where(Clip.source_video_id == video)))
        for c in clips:
            c.status = "reserve"
            c.policy_flags = ["violence"]
        ids = [c.id for c in clips]
    result = client.post("/api/clips/bulk-approve", json={"clip_ids": ids}).json()
    assert not result["changed"]
    assert len(result["skipped"]) == len(ids)
