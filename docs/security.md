# Security

## JWT And RBAC

The API uses bearer JWTs. Users have one of three roles:

- `owner`: can manage meetings they own.
- `reviewer`: can review meetings explicitly shared through `meeting_permissions`.
- `admin`: can view operations, prompt registry details, system audit events, and system-wide pipeline status.

The first registered user and demo account can default to `admin` for local bootstrapping. Production should create admins through controlled provisioning and set `FIRST_USER_ADMIN=false` after setup.

## Object-Level Authorization

Meeting, transcript, action item, export, AI run, and audit access is checked against the authenticated user and the target resource. Cross-user meeting and AI-run access returns a not-found style response and records `permission.denied`.

## Secrets Policy

Secrets are read from environment variables. Do not commit real `.env` values, OpenAI keys, JWT secrets, database passwords, or provider credentials. Production should use a secret manager and separate staging and production configuration.

## Logging Redaction

Structured logs and audit metadata are sanitized. Sensitive field names such as `authorization`, `password`, `secret`, `token`, `key`, `transcript`, `content`, and `source` are redacted before logging.

Audit records store hashed IP and user-agent values, not raw network identifiers.

## Kafka And Worker Payloads

Kafka is an internal backend integration. Browsers receive progress through backend SSE and never connect directly to Kafka.

Pipeline events must carry IDs, status, hashes, filenames, and metadata only. They must not include raw transcript text, JWTs, provider secrets, full prompts, or upload file bytes. The worker reads sensitive transcript content from the database or staged upload path after normal backend authorization and governance checks.

## Rate Limits And Upload Limits

The API applies:

- request body limit via `MAX_UPLOAD_BYTES`
- transcript character limit via `MAX_TRANSCRIPT_CHARS`
- in-memory per-path rate limit via `RATE_LIMIT_PER_MINUTE`
- optional per-user daily AI spend limit via `USER_DAILY_AI_COST_LIMIT`

Production should replace the in-memory limiter with a shared Redis or gateway-backed limiter.

## Dependency Scanning

CI runs:

```bash
bandit -q -r backend
pip-audit
python -m evals.run --json
```

Frontend builds run with `npm run build`.

## Error Handling

API errors return concise messages and avoid leaking transcripts, raw prompts, JWTs, secrets, provider payloads, or stack traces.
