## Error fix
```python
from repotest.scripts.build_image import build_image
build_image("realcode_image")
```

The error "`StoreError: docker-credential-desktop not installed or not available in PATH`" occurs because Docker is trying to use credential storage (docker-credential-desktop) but can't find it. Here’s how to fix it:

cat ~/.docker/config.json

modify
"credsStore": "desktop"
to "credsStore": ""