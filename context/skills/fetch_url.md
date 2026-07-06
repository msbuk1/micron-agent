---
name: fetch_url
description: Fetch and extract text content from a URL
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    url:
      type: string
      description: URL to fetch
    max_chars:
      type: integer
      default: 8000
      description: Maximum characters to return
---