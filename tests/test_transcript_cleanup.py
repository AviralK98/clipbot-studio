"""Provider placeholder tokens must never reach published copy or dedup fingerprints."""

from clipbot.ai import clean_transcript, prefer_provider_title

OPUS_TRANSCRIPT = (
    "Am I Chris Benoit Yes How did you get that Oh that's great __silence "
    "Because you guys said one small blemish __missing on his record"
)


def test_clean_transcript_removes_provider_markers():
    cleaned = clean_transcript(OPUS_TRANSCRIPT)
    assert "__silence" not in cleaned
    assert "__missing" not in cleaned
    assert "__" not in cleaned
    # Spoken words and their order survive, with no double spaces left behind.
    assert cleaned.startswith("Am I Chris Benoit Yes")
    assert cleaned.endswith("one small blemish on his record")
    assert "  " not in cleaned


def test_clean_transcript_leaves_ordinary_text_untouched():
    text = "Do you think my favorite day of the week would be Friday? No."
    assert clean_transcript(text) == text
    assert clean_transcript("") == ""
    assert clean_transcript(None) == ""


def test_provider_title_replaces_transcript_excerpt_on_every_platform():
    metadata = {
        "youtube": {"title": "Am I Chris Benoit Yes How", "description": "d", "hashtags": []},
        "tiktok": {"title": "Am I Chris Benoit Yes How", "caption": "c", "hashtags": []},
        "instagram": {"title": "Am I Chris Benoit Yes How", "caption": "c", "hashtags": []},
        "hooks": [],
    }
    updated = prefer_provider_title(metadata, "Chris Benoit: The Tragic Wrestler's Dark Legacy")

    for platform in ("youtube", "tiktok", "instagram"):
        assert updated[platform]["title"] == "Chris Benoit: The Tragic Wrestler's Dark Legacy"
    # Everything else is preserved, and the original dict is not mutated.
    assert updated["youtube"]["description"] == "d"
    assert updated["tiktok"]["caption"] == "c"
    assert updated["hooks"] == []
    assert metadata["youtube"]["title"] == "Am I Chris Benoit Yes How"


def test_provider_title_is_truncated_and_optional():
    metadata = {"youtube": {"title": "old", "description": "d", "hashtags": []}}
    assert prefer_provider_title(metadata, "x" * 130)["youtube"]["title"] == "x" * 100
    assert prefer_provider_title(metadata, "") == metadata
