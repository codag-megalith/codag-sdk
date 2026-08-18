# Security

Please report security issues privately instead of opening a public GitHub
issue.

Email: security@codag.ai

Include the affected SDK, version, operating system, reproduction steps, and
any logs or screenshots needed to understand the issue. Do not include secrets
or customer data in the initial report.

## Data Boundary

The SDKs send eligible coding-agent tool results plus the tool call and minimal
task context you provide to the configured Codag API server for transient
reduction. Codag does not retain that content. Required accounting events are
contentless and reject prompt, command, path, filename, task, arguments,
result, and output fields. API keys are sent as bearer tokens over HTTPS by
default.

Use `CODAG_SERVER` or a constructor option to target staging, local
development, or a self-hosted API.
