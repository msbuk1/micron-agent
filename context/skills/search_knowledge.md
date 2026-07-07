---
name: search_knowledge
description: Search knowledge documents and long-term memories by keyword. Returns ranked results by relevance.
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: The search query to find in knowledge documents
    k:
      type: integer
      description: Number of results to return (default 5)
  required:
    - query
---