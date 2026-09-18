# Security model

Single-owner authentication uses salted scrypt password hashing and signed HttpOnly SameSite=Lax sessions with a twelve-hour lifetime. Session signatures include a credential fingerprint, so password rotation invalidates old sessions. Production enforces strong configuration, HTTPS and no demo mode. Browser mutations validate Origin; optional X-API-Key authenticates trusted event ingress. A process-local login throttle is implemented; use edge throttling before multiple API replicas.

Next.js proxies requests without exposing provider credentials. Inputs use Pydantic validation. Private dashboard routes and media require authentication. Storage paths must resolve beneath the root. Video URLs reject credentials, private/link-local IPs, non-web schemes and unexpected ports; redirects are revalidated. Feed redirects are refused and XML entity expansion is blocked. Feed and media sizes are bounded. Network-level egress filtering is necessary against DNS rebinding.

Authorization records are mandatory and checked again before publication. Demo media cannot reach live accounts. Policy flags require manual acknowledgment. The LLM treats transcripts as untrusted source text and returns a strict schema. Transcript review is not audiovisual moderation or an external fact check. Generated hook evidence quotes must occur in the transcript.

Opus callbacks validate raw-body HMAC, project identity, timestamp freshness and persistent salt replay records. Paid mutations persist intent and ambiguous results require reconciliation. Jobs are leased and guarded by SQL uniqueness/transactions.

.env, databases, media, virtual environments and build output are excluded from Git and Docker contexts. Provider secrets stay in environment variables. Logs contain request/job/entity identifiers and sanitized errors. Upload URLs remain private journal state. Apply filesystem permissions and encryption/backup policies suitable for deployment.
