---
name: create_skill
description: Create a new skill file in the skills folder. Generates YAML frontmatter and skeleton.
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    name:
      type: string
      description: Skill name (will be slugified)
    description:
      type: string
      description: What the skill does (shown to the LLM)
    parameters:
      type: string
      description: "YAML parameter definitions (optional, for tool-based skills)"
    module:
      type: string
      description: "Python module path (optional, for tool-based skills)"
    write:
      type: boolean
      description: "Whether the skill writes files (default false)"
  required:
    - name
    - description
---