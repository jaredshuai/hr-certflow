# AI Workflows

Workflow definitions for the shared AI workflow center belong here after they
are exported from Dify.

Rules:

- Store workflow DSL/YAML, prompts, schemas, and review notes in Git.
- Do not store Dify API keys, model-provider keys, credentials, or runtime
  endpoints here.
- Keep one folder per workflow app.
- Changes to a workflow definition should go through normal code review before
  infra imports or publishes it in the shared Dify deployment.

Planned first workflow:

```text
dify/certificate-extraction/
```

The runtime contract is documented in
[`docs/external-services.md`](../docs/external-services.md).

