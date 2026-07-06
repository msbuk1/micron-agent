---
name: web_search
description: Search the web for current information, documentation, or news
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: "Search query — use keywords, not a question. Good: 'python pandas drop duplicates keep last'. Bad: 'how do i drop duplicate rows in pandas but keep the final one please'"
    max_results:
      type: integer
      description: Number of results to return (default 5)
  required:
    - query
---