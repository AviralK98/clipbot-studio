"""Per-video YouTube analysis for the AI insights page: endpoints and the plain-language notes."""

import httpx
import pytest
import respx
from clipbot import video_insights

# The `live` and `published` fixtures live in conftest.py; `published` creates this video.
VIDEO = "EdJ1Ebbaedg"


@pytest.fixture(autouse=True)
def empty_cache():
    video_insights._cache.clear()
    yield
    video_insights._cache.clear()


def watching_at(i):
    """A falling retention curve: a steep early drop, then a slow tail (i = percent through)."""
    return 1.05 - 0.02 * i if i <= 30 else 0.45 - 0.003 * (i - 30)


def analytics_reply(request):
    params = request.url.params
    dims = params.get("dimensions", "")
    tables = {
        "": (
            [
                "views",
                "engagedViews",
                "averageViewDuration",
                "averageViewPercentage",
                "likes",
                "comments",
                "shares",
                "subscribersGained",
            ],
            [[1219, 536, 15, 44.0, 5, 0, 0, 0]],
        ),
        "video": (
            [
                "video",
                "views",
                "engagedViews",
                "averageViewPercentage",
                "averageViewDuration",
                "likes",
                "shares",
                "subscribersGained",
            ],
            [[VIDEO, 1219, 536, 44.0, 15, 5, 0, 0], ["other", 0, 0, 0, 0, 0, 0, 0]],
        ),
        "insightTrafficSourceType": (
            ["insightTrafficSourceType", "views"],
            [["SHORTS", 1180], ["YT_OTHER_PAGE", 36], ["YT_SEARCH", 3]],
        ),
        "day": (
            ["day", "views", "engagedViews"],
            [["2026-09-17", 303, 140], ["2026-09-18", 859, 390], ["2026-09-19", 0, 0], ["2026-09-20", 0, 0]],
        ),
        "country": (["country", "views"], [["US", 153], ["IN", 85]]),
        "elapsedVideoTimeRatio": (
            ["elapsedVideoTimeRatio", "audienceWatchRatio", "relativeRetentionPerformance"],
            [[i / 100, watching_at(i), 0.2] for i in range(1, 101)],
        ),
    }
    names, rows = tables[dims]
    return httpx.Response(200, json={"columnHeaders": [{"name": n} for n in names], "rows": rows})


def mock_youtube(reports=analytics_reply):
    respx.post("https://oauth2.googleapis.com/token").mock(
        return_value=httpx.Response(200, json={"access_token": "contract-test-token"})
    )
    reports_route = respx.get(video_insights.REPORTS_URL).mock(side_effect=reports)
    respx.get(video_insights.VIDEOS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": VIDEO,
                        "snippet": {
                            "title": "Finally Guessing The Character!",
                            "publishedAt": "2026-09-18T03:24:00Z",
                        },
                        "statistics": {"viewCount": "1164", "likeCount": "5", "commentCount": "0"},
                        "contentDetails": {"duration": "PT34S"},
                    }
                ]
            },
        )
    )
    return reports_route


def test_insight_endpoints_require_login():
    from clipbot.api import app
    from fastapi.testclient import TestClient

    with TestClient(app) as anonymous:
        for path in ("/api/insights/videos", "/api/insights/top", f"/api/insights/videos/{VIDEO}"):
            assert anonymous.get(path).status_code == 401


def test_live_youtube_analysis_is_off_in_demo_mode(client):
    response = client.get("/api/insights/top?period=week")
    assert response.status_code == 409
    assert "DEMO_MODE" in response.json()["detail"]


def test_unknown_period_is_rejected(client, live):
    assert client.get("/api/insights/top?period=decade").status_code == 422


@respx.mock
def test_video_breakdown_explains_a_shorts_feed_burst(client, published):
    reports = mock_youtube()
    assert [v["video_id"] for v in client.get("/api/insights/videos").json()["videos"]] == [VIDEO]

    body = client.get(f"/api/insights/videos/{VIDEO}").json()

    # Pacific-time reporting days: the window must start the day before the UTC publish date.
    assert body["range"]["start"] == "2026-09-17"
    assert reports.calls[0].request.url.params["startDate"] == "2026-09-17"
    assert body["video"]["opening"] == "Yes. Am I Apu? Yes! Good job."
    assert body["video"]["duration"] == 34 and body["video"]["removed"] is False
    assert body["live"]["viewCount"] == 1164
    assert body["summary"]["stayed_rate"] == pytest.approx(536 / 1219)
    assert body["traffic"][0]["label"] == "Shorts feed"
    notes = " ".join(body["observations"])
    assert "Shorts feed: YouTube chose to show it" in notes
    assert "within about a day (17 Sep-18 Sep), then it went quiet" in notes
    assert "44% of viewers stayed past the first few seconds" in notes
    assert "Biggest drop-off between" in notes
    assert "worse than most similar Shorts" in notes


@respx.mock
def test_top_videos_skip_zero_view_rows_and_are_cached(client, published):
    reports = mock_youtube()
    first = client.get("/api/insights/top?period=week").json()
    assert [v["video_id"] for v in first["videos"]] == [VIDEO]
    assert first["videos"][0]["published_by_clipbot"] is True
    assert first["videos"][0]["stayed_rate"] == pytest.approx(536 / 1219)

    client.get("/api/insights/top?period=week")
    assert reports.call_count == 1  # served from cache
    client.get("/api/insights/top?period=week&refresh=true")
    assert reports.call_count == 2


def test_unknown_video_is_404(client, published):
    assert client.get("/api/insights/videos/not-ours").status_code == 404


@respx.mock
def test_disabled_analytics_api_gives_a_fixable_message(client, published):
    mock_youtube(
        reports=lambda request: httpx.Response(
            403,
            json={
                "error": {
                    "message": "YouTube Analytics API has not been used in project 1 before or it is disabled.",
                    "errors": [{"reason": "accessNotConfigured"}],
                }
            },
        )
    )
    response = client.get("/api/insights/top?period=month")
    assert response.status_code == 409
    assert "Turn on the YouTube Analytics API" in response.json()["detail"]


def test_search_driven_video_is_described_as_search():
    analysis = {
        "summary": {"views": 36, "stayed_rate": 0.39, "subscribers_gained": 1},
        "typical_views": 2,
        "traffic": [{"source": "YT_SEARCH", "label": "YouTube search", "views": 35, "share": 35 / 36}],
        "daily": [
            {"date": "2026-09-18", "views": 16},
            {"date": "2026-09-19", "views": 15},
            {"date": "2026-09-20", "views": 5},
        ],
        "retention": [],
    }
    notes = video_insights.observations(analysis)
    assert any("YouTube search: people looked for it" in n for n in notes)
    assert not any("went quiet" in n for n in notes)  # 5 of 36 views on the latest day
    assert "Brought in 1 new subscriber." in notes


def test_no_views_yet_explains_the_reporting_delay():
    notes = video_insights.observations(
        {"summary": {"views": 0}, "traffic": [], "daily": [], "retention": []}
    )
    assert notes == ["YouTube hasn't reported views for this video yet; its analytics run 1-2 days behind."]


def compare_row(**overrides):
    row = {
        "video_id": "v",
        "title": "A clip",
        "views": 3,
        "feed_views": 0,
        "search_views": 3,
        "stayed_rate": 0.5,
        "posted_day": "2026-09-21",
        "posted_same_day": 19,
        "upload_number": 10,
        "feed_tested": False,
    }
    row.update(overrides)
    return row


def test_comparison_findings_point_at_feed_distribution_not_content():
    videos = [
        compare_row(
            video_id="hit",
            title="Finally Guessing The Character!",
            views=1164,
            feed_views=1131,
            search_views=10,
            stayed_rate=0.46,
            posted_day="2026-09-18",
            posted_same_day=10,
            upload_number=2,
            feed_tested=True,
        ),
        compare_row(video_id="ww", title="Walter White", views=35, search_views=35, stayed_rate=0.4),
        compare_row(video_id="cb", title="Chris Benoit", views=18, search_views=15, stayed_rate=0.6),
        compare_row(video_id="none", title="Nobody", views=0, search_views=0, stayed_rate=None),
    ]
    notes = video_insights.comparison_findings(videos)
    text = " ".join(notes)
    assert "Only 1 of your 4 videos was shown in the Shorts feed (“Finally Guessing The Character!”)" in text
    assert "96% of all your views" in text  # 1164 of 1217
    assert "Viewers didn't react better to it: 46% stayed past the opening, about the same as" in text
    assert "was the 2nd video you ever posted" in text
    assert "10 on Fri 18 Sep, 19 on Mon 21 Sep" in text
    assert "2 videos got most views from YouTube search, led by “Walter White” (35 of 35)" in text
    assert "isn't enough evidence yet" in text


def test_comparison_findings_when_nothing_reached_the_feed():
    notes = video_insights.comparison_findings([compare_row(views=5, posted_same_day=1)])
    assert notes[0].startswith("None of your 1 videos has been shown in the Shorts feed yet")
    assert video_insights.comparison_findings([compare_row(views=0)]) == [
        "YouTube hasn't reported views for your videos yet; its analytics run 1-2 days behind."
    ]


@respx.mock
def test_compare_endpoint_splits_views_by_source(client, published):
    mock_youtube()
    body = client.get("/api/insights/compare").json()
    [video] = body["videos"]
    assert (video["views"], video["feed_views"], video["search_views"], video["other_views"]) == (
        1219,
        1180,
        3,
        36,
    )
    assert video["feed_tested"] is True
    assert (video["upload_number"], video["posted_same_day"], video["posted_day"]) == (1, 1, "2026-09-18")
    assert body["start"] == "2026-09-17"
    assert body["findings"][0].startswith("Only 1 of your 1 videos was shown in the Shorts feed")
