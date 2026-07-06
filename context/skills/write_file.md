---
name: write_file
description: Write a file to the workspace
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
      description: Path to the file
    content:
      type: string
      description: Content to write
---