# Social APIs and capability boundaries

Official sources checked 14 September 2026. No browser posting automation is used.

## YouTube Shorts

A working resumable upload adapter initializes videos.insert, checkpoints the returned session URL, queries the session before each chunk, uploads bounded 8 MiB chunks, and records completion only when the API returns a video ID. If the final response is lost, querying the same session recovers the ID. An initiation response lost before the session URL was persisted requires reconciliation. Default privacy is private. Vertical format and duration influence Shorts classification; there is no separate Shorts upload endpoint.

Uploads from unaudited API projects created after 28 July 2020 are restricted to private viewing until an audit. OAuth consent and quota requirements depend on the configured project. View current quota in your console rather than assuming historic upload-unit costs. Metrics come from videos.list and optional owner Analytics reports. Reporting delay and missing scopes leave unsupported metrics null.

Sources: [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [resumable protocol](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol), [reports.query](https://developers.google.com/youtube/analytics/reference/reports/query), [OAuth offline access](https://developers.google.com/identity/protocols/oauth2/web-server).

## Instagram Reels

The implemented Facebook Login / Page-token adapter creates a REELS container at /{ig_user_id}/media, polls /{container_id}?fields=status_code,status until FINISHED, then calls /{ig_user_id}/media_publish with creation_id. URLs must be publicly fetchable. The target must be an eligible professional account, linked to a Page for this login path. Use the appropriate instagram_basic, instagram_content_publish and Page discovery/read scopes. App review / advanced access and business verification depend on the app's intended users and permissions; complete Meta's current requirements in the app dashboard. Development app roles are not general public access.

Meta's documentation returned HTTP 429 during this build. Request and response contracts were verified against Meta's official Postman collection. Automatic Instagram insight collection is deliberately blocked pending verification of the app's metric schema and scopes; manually attach exported analytics. Refreshing/rotating Meta credentials is an operator responsibility in this environment-token adapter.

Sources: [Meta's official Instagram collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api), [Meta publishing documentation](https://developers.facebook.com/docs/instagram-platform/content-publishing/).

## TikTok

The requested personal tool conflicts with TikTok's Direct Post intended-use rule, which explicitly excludes private utilities that post only to accounts managed by the developer/team. Direct Post also requires creator-info UI, creator consent, privacy selection, video.publish authorization and an audit for public visibility. ClipBot therefore exposes an explicit PublishingProvider interface that blocks automatic TikTok submission, plus authenticated video downloads and generated TikTok copy for manual posting. This is a real capability limit, not a missing secret or a hidden mock.

Sources: [Direct Post guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines), [Direct Post endpoint](https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post).

## Account scale

The schema supports multiple accounts and the scheduler enforces per-account and per-platform limits. The initial environment-credential adapters allow one live account per platform to prevent misrouting posts to the same credential owner under multiple labels. A token-vault/OAuth account adapter is needed before enabling multiple live accounts per platform.
