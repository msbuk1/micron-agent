---
name: write_knowledge
description: Save a markdown document to the knowledge folder (context/knowledge/). Use this for reference material, guides, or notes the user wants stored long-term. The prompt builder loads these automatically.
write: true
module: micron.tools.builtin
parameters:
  type: object
  properties:
    title:
      type: string
      description: Document title (used to generate the filename)
    content:
      type: string
      description: Markdown content of the knowledge document
    tags:
      type: string
      description: Optional comma-separated tags for organization
  required:
    - title
    - content