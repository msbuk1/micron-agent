---
name: list_files
description: List all files and directories in a specified path
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
      description: Directory path to list (relative to working directory, default ".")
---