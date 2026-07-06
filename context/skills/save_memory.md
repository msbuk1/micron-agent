---
name: save_memory
description: Save something to long-term memory for future reference
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    text:
      type: string
      description: What to remember
    tags:
      type: array
      items:
        type: string
      description: Tags for categorization
    importance:
      type: integer
      default: 3
      description: Importance level (1-5, 5=highest)
---