---
name: search_skill_library
description: Search existing skills by keyword. Use before creating a new skill to check if one already exists.
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    query:
      type: string
      description: Keywords to search for in skill names and descriptions
    text:
      type: string
      description: Alias for query
---