---
name: list_files
description: List files in a directory
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
      default: "."
      description: Directory path
    pattern:
      type: string
      default: "*"
      description: Glob pattern
---