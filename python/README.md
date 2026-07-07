# codag

Python SDK for the Codag hosted API.

```python
from codag import Codag

client = Codag(api_key="cdk_...")
result = client.compact(["ERROR api db pool timeout active=20 waiting=30"])
print(result.text)
```

See the repository root README for the full multi-language SDK documentation.
