---
name: python_eval
description: Execute Python code and return the result
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    code:
      type: string
      description: Python code to execute
---