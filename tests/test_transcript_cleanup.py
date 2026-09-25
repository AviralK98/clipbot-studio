"""Provider placeholder tokens must never reach published copy or dedup fingerprints,
and local review's transcript-derived title/caption must be replaced by the engine's
own clip title on every platform (2026-09-21: a TikTok post went out with a raw
transcript excerpt as its visible caption, because only `title` was being replaced)."""

from clipbot.ai import clean_transcript, prefer_provider_copy

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


def test_provider_copy_replaces_title_and_caption_on_every_platform():
    metadata = {
        "youtube": {"title": "Am I Chris Benoit Yes How", "description": "d", "hashtags": []},
        "tiktok": {"title": "Am I Chris Benoit Yes How", "caption": "raw transcript quote", "hashtags": []},
        "instagram": {"title": "Am I Chris Benoit Yes How", "caption": "raw transcript quote", "hashtags": []},
        "hooks": [],
    }
    updated = prefer_provider_copy(metadata, "Chris Benoit: The Tragic Wrestler's Dark Legacy")

    for platform in ("youtube", "tiktok", "instagram"):
        assert updated[platform]["title"] == "Chris Benoit: The Tragic Wrestler's Dark Legacy"
        # TikTok/Instagram show `caption` as their primary visible text, so it must be
        # replaced too, not just `title` (which is what actually shipped the bug).
        assert updated[platform]["caption"] == "Chris Benoit: The Tragic Wrestler's Dark Legacy"
    # Everything else (description, hashtags) is preserved, and the input is not mutated.
    assert updated["youtube"]["description"] == "d"
    assert updated["hooks"] == []
    assert metadata["tiktok"]["caption"] == "raw transcript quote"


def test_provider_copy_is_truncated_per_field_and_optional():
    metadata = {"tiktok": {"title": "old", "caption": "old", "hashtags": []}}
    updated = prefer_provider_copy(metadata, "x" * 3000)
    assert updated["tiktok"]["title"] == "x" * 100  # YouTube/TikTok title limit
    assert updated["tiktok"]["caption"] == "x" * 2200  # TikTok caption limit
    assert prefer_provider_copy(metadata, "") == metadata  # no title -> no-op
