from types import SimpleNamespace

import pytest
from clipbot.ai import DemoLLMProvider, Rubric, classify, validated_metadata
from clipbot.analytics import normalize
from clipbot.dedup import cosine, duplicate_reason, overlap
from clipbot.integrations.clipping import DEMO_TRANSCRIPTS
from pydantic import ValidationError


async def test_weighted_score_is_computed_not_trusted():
    result, _ = await DemoLLMProvider().evaluate(DEMO_TRANSCRIPTS[0][1])
    result.scores = Rubric(hook=100, standalone=80, curiosity=60, payoff=40, shareability=20, information=0)
    score, tier, _ = classify(result, {"priority": 90, "approved": 82, "reserve": 75}, [])
    assert score == 63
    assert tier == "rejected"


async def test_missing_context_rejected_even_with_high_scores():
    result, _ = await DemoLLMProvider().evaluate(DEMO_TRANSCRIPTS[0][1])
    result.requires_context = True
    assert classify(result, {"priority": 90, "approved": 82, "reserve": 75}, [])[1] == "rejected"


async def test_sensitive_content_requires_review():
    result, _ = await DemoLLMProvider().evaluate(DEMO_TRANSCRIPTS[0][1])
    result.policy_flags = ["personal_information"]
    _, tier, flags = classify(
        result, {"priority": 90, "approved": 82, "reserve": 75}, ["personal_information"]
    )
    assert tier == "reserve"
    assert "personal_information" in flags


async def test_hook_evidence_must_exist_in_transcript():
    result, _ = await DemoLLMProvider().evaluate(DEMO_TRANSCRIPTS[0][1])
    result.hooks[0].evidence_quote = "Invented quotation"
    assert validated_metadata(result, DEMO_TRANSCRIPTS[0][1])["hooks"] == []


def test_invalid_score_rejected():
    with pytest.raises(ValidationError):
        Rubric(hook=101, standalone=80, curiosity=60, payoff=40, shareability=20, information=0)


def test_disjoint_timestamp_ranges_not_bounding_boxes():
    assert overlap([[0, 10], [90, 100]], [[40, 60]]) == 0
    assert overlap([[201, 242]], [[205, 247]]) > 0.8


def test_semantic_duplicate_and_missing_embeddings():
    a = SimpleNamespace(id="a", transcript="different words", ranges=[], source_video_id="a")
    b = SimpleNamespace(id="b", transcript="another phrase", ranges=[], source_video_id="b")
    embeddings = {
        "a": SimpleNamespace(model="test", vector=[1, 0]),
        "b": SimpleNamespace(model="test", vector=[1, 0]),
    }
    assert duplicate_reason(a, b, embeddings) == "Semantic similarity above threshold"
    assert duplicate_reason(a, b, {}) is None
    assert cosine([], []) == 0


def test_missing_metrics_remain_unknown_and_rates_normalize():
    result = normalize({"views": 1000, "shares": 10, "comments": 5}, 2)
    assert result["views_per_hour"] == 500
    assert result["shares_per_1000"] == 10
    assert result["followers_per_1000"] is None
    assert result["engagement_rate"] is None
    assert normalize({"views": 0}, 0)["shares_per_1000"] is None
