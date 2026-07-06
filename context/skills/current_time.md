---
name: current_time
description: Get current date and time
write: false
module: micron.tools.builtin
parameters:
  type: object
  properties:
    timezone:
      type: string
      default: "UTC"
      description: Timezone (UTC or local)
---