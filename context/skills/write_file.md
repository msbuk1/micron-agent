---
name: write_file
description: Write or append content to a file in the working directory
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
      description: Path to the file (relative to working directory)
    content:
      type: string
      description: The full content to write to the file
    mode:
      type: string
      description: "Write mode: 'w' to overwrite/create, 'a' to append. Default 'w'."
  required:
    - path
    - content
---