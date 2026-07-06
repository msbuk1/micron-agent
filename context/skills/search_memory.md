---
name: search_memory
description: Search long-term memories by keyword. Returns ranked results by relevance.
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: The search query to find in memories
    text:
      type: string
      description: Alias for query (search text)
    k:
      type: integer
      description: Number of results to return (default 5)
    tags:
      type: string
      description: Optional comma-separated tag filter (e.g. "dark_mode,preference")
  required:
    - query
---