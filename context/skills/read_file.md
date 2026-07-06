---
name: read_file
description: Read the contents of a file from the working directory
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    path:
      type: string
      description: Path to the file (relative to working directory)
    start_line:
      type: integer
      description: Starting line number (1-indexed). Use for large files to read specific sections.
    end_line:
      type: integer
      description: Ending line number (1-indexed, inclusive). Use with start_line for a range.
---