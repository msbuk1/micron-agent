---
name: web_search
description: Search the web for current information
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: Search query
    max_results:
      type: integer
      default: 5
---

# Implementation in micron/tools/builtin.py
def web_search(query: str, max_results: int = 5) -> list[dict]:
    ...