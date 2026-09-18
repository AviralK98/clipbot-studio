import math
import re
from difflib import SequenceMatcher


def cosine(a: list, b: list) -> float:
    if not a or len(a) != len(b):
        return 0
    denom = math.sqrt(sum(x * x for x in a) * sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / denom if denom else 0


def overlap(a: list, b: list) -> float:
    # Intersection over the shorter selected duration; multi-segment clips remain disjoint.
    if not a or not b:
        return 0
    common = sum(max(0, min(e1, e2) - max(s1, s2)) for s1, e1 in a for s2, e2 in b)
    shortest = min(sum(e - s for s, e in a), sum(e - s for s, e in b))
    return min(1, common / shortest) if shortest > 0 else 0


def duplicate_reason(a, b, embeddings: dict) -> str | None:
    if a.source_video_id == b.source_video_id and overlap(a.ranges, b.ranges) >= 0.7:
        return "Overlapping source timestamps"

    def normalize(s):
        return " ".join(re.findall(r"\w+", s.lower()))

    ta, tb = normalize(a.transcript), normalize(b.transcript)
    if min(len(ta), len(tb)) > 50 and SequenceMatcher(None, ta, tb, autojunk=False).ratio() >= 0.87:
        return "Near-identical transcript"
    ea, eb = embeddings.get(a.id), embeddings.get(b.id)
    if ea and eb and ea.model == eb.model and cosine(ea.vector, eb.vector) >= 0.92:
        if ea.model == "local-lexical-v1":
            # Word counts lose ordering; require matching phrases as corroboration.
            if min(len(ta), len(tb)) > 50 and SequenceMatcher(None, ta, tb, autojunk=False).ratio() >= 0.8:
                return "Similar wording (local transcript comparison)"
            return None
        return "Semantic similarity above threshold"
    return None
