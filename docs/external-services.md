# External Service Contracts

This document records the runtime contracts for services that sit outside the
FastAPI/PostgreSQL business core.

## Object Storage

Use Alibaba Cloud OSS as the first production S3-compatible object storage
target. Certificate originals and AI raw-response snapshots are durable data and
must live in OSS, not in pod-local storage.

Recommended storage layout:

| Environment | `S3_BUCKET` | `UPLOAD_PREFIX` |
| --- | --- | --- |
| local | `jxccs-shared-infra-oss-cn-hangzhou` | `hr-certflow/local/certificates` |
| dev | `jxccs-shared-infra-oss-cn-hangzhou` | `hr-certflow/dev/certificates` |
| release | `jxccs-shared-infra-oss-cn-hangzhou` | `hr-certflow/release/certificates` |

The OSS bucket is shared infrastructure. Project and environment isolation
happens through object key prefixes:

```text
oss://jxccs-shared-infra-oss-cn-hangzhou/hr-certflow/dev/certificates/
oss://jxccs-shared-infra-oss-cn-hangzhou/hr-certflow/release/certificates/
```

Runtime variables:

```text
S3_ENDPOINT_URL
S3_REGION
S3_BUCKET
S3_FORCE_PATH_STYLE=false
AWS_REQUEST_CHECKSUM_CALCULATION=when_required
AWS_RESPONSE_CHECKSUM_VALIDATION=when_required
UPLOAD_PREFIX
S3_ACCESS_KEY_ID
S3_SECRET_ACCESS_KEY
```

Rules:

- Keep OSS buckets private.
- `S3_ENDPOINT_URL` must be reachable from the backend, the user's browser, and
  the shared AI workflow platform because presigned URLs include the signed host.
- Use short-lived presigned PUT URLs for browser uploads.
- Use short-lived presigned GET URLs when the AI workflow platform needs to
  fetch a certificate file.
- Do not make certificate objects public-read for Dify, Coze, or any other AI
  provider.
- Give HR CertFlow its own RAM user and limit it to the required
  `jxccs-shared-infra-oss-cn-hangzhou/hr-certflow/*` prefixes. If stricter
  separation is required, dev and release can use separate RAM users scoped to
  their own prefixes.
- Do not reuse a personal note-taking bucket for HR certificate data.

Alibaba Cloud OSS Infrequent Access is acceptable for certificate originals
because files are normally uploaded once, recognized once, and rarely read after
review. Treat OSS as the durable cold tier.

Pod-local or node-local storage is only a cache:

- It may hold rendered thumbnails, file previews, or temporary downloaded
  originals.
- It must have TTL cleanup.
- It must be safe to delete at any time.
- A cache miss must be recoverable from OSS.
- It must never be the source of business truth.

The application should not deploy a local S3 service in shared-k3s just to cache
certificate files. If a cache is needed later, prefer an application-managed
cache directory or a small cache service with explicit TTL and size limits.

## AI Workflow Center

Use Dify as the shared AI workflow platform for the MVP and near-term platform
standard.

Rationale:

- Dify has a workflow-first product model that matches certificate extraction.
- It can be self-hosted and exposed as an internal shared platform.
- Workflow apps can be called through HTTP APIs from FastAPI.
- Workflow definitions can be exported and kept in Git as DSL/YAML, which makes
  them practical for developer agents to review and modify.
- Each software project can be separated by workspace, project account, app, and
  API key.

The platform target is:

```text
One internal Dify deployment
    -> project/workspace separation
    -> one workflow app per AI business flow
    -> API keys injected through runtime secrets
    -> workflow DSL exported into Git for review
```

For HR CertFlow, the first workflow is:

```text
certificate-extraction
```

Input contract:

```json
{
  "file_url": "short-lived presigned GET URL for the certificate file",
  "document_id": "certificate_document id"
}
```

Expected output contract:

```json
{
  "holder_name": "string | null",
  "certificate_name": "string | null",
  "certificate_no": "string | null",
  "issuing_authority": "string | null",
  "issue_date": "YYYY-MM-DD | null",
  "valid_from": "YYYY-MM-DD | null",
  "valid_to": "YYYY-MM-DD | null",
  "review_date": "YYYY-MM-DD | null",
  "raw_text": "string",
  "suspicious_points": ["string"],
  "model_name": "string"
}
```

Runtime variables:

```text
DIFY_BASE_URL
DIFY_API_KEY
DIFY_WORKFLOW_ID
```

Rules:

- Dify only produces structured candidates.
- FastAPI still owns employee matching, duplicate detection, state transitions,
  HR review, reminders, and audit logs.
- AI output must not create or update formal certificate records until HR review
  approves it.
- Store the raw Dify response snapshot in OSS for audit and debugging.
- Do not commit Dify API keys or workflow runtime credentials.

## Coze Position

Coze or self-hosted Coze Studio can be considered later as an additional AI
provider, but it is not the default workflow center for this project.

Reasons:

- The current application already implements the Dify workflow API contract.
- Dify's DSL/Git workflow is a better fit for developer-agent modification.
- A shared internal workflow center needs stable source-controlled workflow
  promotion more than it needs another chat-agent surface.

If Coze is introduced later, add an explicit provider abstraction instead of
rewriting business code around Coze:

```text
AI_EXTRACTION_PROVIDER=dify|coze
```

Provider-specific variables should stay in runtime secrets and config maps, not
in code or workflows.
