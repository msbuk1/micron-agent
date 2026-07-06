---
name: search_knowledge
description: Search knowledge documents by keyword. Finds relevant sections from the knowledge vault.
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: Keywords to search for in knowledge documents
    text:
      type: string
      description: Alias for query (search text)
  required:
    - query
---