# Codag Python SDK

Python client for Codag's coding-agent cost API.

```bash
pip install codag
export CODAG_API_KEY="<paste your cdk_ key>"
```

```python
from codag import ActionEnvelope, Codag, ToolCall

client = Codag()
result = client.reduce_action(ActionEnvelope(
    id="action-1",
    kind="search",
    tool=ToolCall(name="grep", arguments={"pattern": "TODO"}),
    result=large_search_output,
    retrieval_handle="local-action-1",
))
print(result.content)
print(client.usage_summary().estimated_saved_microusd)
```

`AsyncCodag` provides matching async methods. SDK authentication is API-key
only; local harness attachment and encrypted retrieval are handled by
`codag setup` in the CLI.
