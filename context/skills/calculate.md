---
name: calculate
description: Safely evaluate a mathematical expression
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    expression:
      type: string
      description: Mathematical expression (e.g., "2 + 2", "sqrt(16) * 3")
---