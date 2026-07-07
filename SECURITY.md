# Security

Please report security issues privately instead of opening a public GitHub
issue.

Email: security@codag.ai

Include the affected SDK, version, operating system, reproduction steps, and
any logs or screenshots needed to understand the issue. Do not include secrets
or customer data in the initial report.

## Data Boundary

The SDKs send the log lines you pass to the configured Codag API server. API
keys are sent as bearer tokens over HTTPS by default.

Use `CODAG_SERVER` or a constructor option to target staging, local
development, or a self-hosted API.
