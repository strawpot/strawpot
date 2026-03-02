---
name: noop
description: No-op memory provider — returns empty context and discards dumps
metadata:
  version: "0.1.0"
  strawpot:
    memory_module: provider.py
---

# Noop Memory Provider

Built-in no-op provider. Returns empty results for `get` and discards
all data on `dump`. Used as the default when no memory provider is configured.
