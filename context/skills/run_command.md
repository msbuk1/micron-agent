---
name: run_command
description: Run a shell command (use with caution)
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    cmd:
      type: string
      description: Command to run
    cwd:
      type: string
      default: "."
      description: Working directory
    timeout:
      type: integer
      default: 30
      description: Timeout in seconds
---