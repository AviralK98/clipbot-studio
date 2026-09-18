# AI scoring, deduplication and feedback

## Free local review (default)

`LLM_PROVIDER=local` needs no OpenAI or Anthropic key and makes no AI API calls. It ranks transcripts using simple length/punctuation heuristics, extracts titles and captions directly from the transcript, and compares timestamps and repeated wording for duplicates. These scores are sorting aids, not AI judgments. It does not assess meaning, claims, safety, or video/audio quality. All local results wait in Reserve for your manual approval, even with autopilot enabled. AI usage cost is zero; Vizard/OpusClip processing still consumes their credits. Sample/demo records remain separate simulated fixtures.

Paid review is preserved for later: set `LLM_PROVIDER=openai` plus `OPENAI_API_KEY` and `LLM_MODEL`; or set `LLM_PROVIDER=anthropic` plus `ANTHROPIC_API_KEY` and `LLM_MODEL` (this option still needs OpenAI for embeddings). Restart API and worker after changing providers. Existing reviewed clips retain their original evaluation; changing modes applies to new evaluations.


The provider abstraction supports OpenAI structured Responses output and Anthropic structured Messages output. Pydantic validates all fields. Scores are bounded 0–100. ClipBot computes the overall score itself: hook .30, standalone .20, curiosity .15, payoff .15, shareability .10, information .10. Provider-native scores are retained separately. Thresholds default to priority 90, approved 82, reserve 75; lower scores are rejected.

Prior-context dependence or an incomplete ending forces rejection. Configured sensitive-content flags, unsupported claims and transcript errors require manual review. Missing transcripts are rejected. Transcripts are treated as untrusted data, never system instructions. The judge reviews text; it does not claim audiovisual moderation. A production operator must validate media quality and visual-content suitability for their source category before unattended operation.

Metadata differs per platform. Optional hooks carry exact evidence quotes; hooks with quotes absent from the transcript are discarded. The system does not rewrite the video or claim that a text suggestion has been rendered. Evidence quotation reduces fabrication but does not mathematically prove every generated hook; review high-impact claims.

Duplicate rules: >=70% overlap of the shorter selected timeline, >=87% normalized transcript sequence similarity, or >=.92 cosine similarity using matching embedding models. Disjoint timestamp ranges are preserved. Missing/ambiguous timing is never fabricated. Sort the current source's candidates by weighted score, keep the strongest eligible version, and reject lower-ranked duplicates. Previously selected/scheduled/published content is protected from duplicate republishing. Current implementation performs SQL-backed pairwise comparisons; large libraries should add indexed vector search before scaling to millions of comparisons.

Analytics checkpoints are 1, 6, 24, 72 and 168 hours. Learning uses real API 24-hour snapshots actually collected 23–27 hours after publication, with at least five samples per group. Demo and manual metrics do not drive adaptation. Weights are bounded .5–1.5; provider routing retains at least 20% exploration. Topics and duration preferences inform future submissions. Provider/category routing, source, platform, hook and posting-time evidence are recorded. Posting-time and fine-grained duration/hook rewrites remain advisory until statistically stronger deployment validation.

Official sources: [OpenAI structured output](https://developers.openai.com/api/docs/guides/structured-outputs), [Anthropic structured output](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
