# Vizard integration

Official documentation checked 14 September 2026:
- [Submit](https://docs.vizard.ai/reference/submit)
- [Response codes](https://docs.vizard.ai/docs/response)
- [Retrieve output](https://docs.vizard.ai/docs/retrieve-video-clips)
- [Rate limits](https://docs.vizard.ai/docs/rate-limit)

The adapter uses POST https://elb-api.vizard.ai/hvizard-server-front/open-api/v1/project/create with the VIZARDAI_API_KEY header. It selects lang=auto, preferLength=[2], ratioOfClip=1 and disables generated headlines to avoid rewriting facts. videoType maps YouTube, Drive, Dropbox or remote files. Remote files require ext. VIZARD_MODEL supports documented clip_v1/clip_v2 values; v2 reserves 1.25 times source-minute credits.

Creation code 2000 means accepted, not finished. GET /project/query/{projectId} returns processing code 1000 or completion 2000. videoMsDuration is converted to seconds. Missing timestamps remain unknown. Native viralScore is stored unchanged; it never substitutes for ClipBot's weighted rubric. Download URLs expire after seven days, so the worker archives media before evaluating it.

Submission is limited to three per minute and twenty per hour under the published standard limits. SQL reservations enforce these windows. HTTP 429 and application code 4003 defer work. Insufficient credits and invalid credentials hold jobs. Timeouts or server errors after POST may represent successful creation: reconciliation requires attaching the existing project ID rather than issuing another charge. Exactly-once external creation cannot be guaranteed without provider-side idempotency.
