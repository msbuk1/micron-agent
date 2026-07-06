# Self-Assembling Skill Architecture

## Overview

micron can create, search, and manage its own skills at runtime. Instead of hard-coding every tool, the agent is given **meta-tools** — the ability to write, validate, and save reusable skill definitions to a permanent library.

This is inspired by research projects like **Voyager** (LLM agent that wrote its own Minecraft control code) and **CREATOR** (self-assembling tool frameworks).

---

## How It Works

### The Skill Lifecycle

```
[User Request] → [search_skill_library] → [create_skill] → [/reload]
                       |                        |
                  (found? use it)        (YAML validated, core protected)
                                               |
                                         [Skill Ready]
```

### 1. Discovery: `search_skill_library`

Before creating anything, the agent searches its existing skills:

```
> Create a skill to parse JSON logs

Agent calls: search_skill_library(query="parse JSON logs")
Result: "No skills match 'parse JSON logs'."
```

If a match exists, the agent reuses it instead of creating a duplicate.

### 2. Creation: `create_skill`

The agent creates a new skill with YAML frontmatter:

```
Agent calls: create_skill(
    name="parse_json_logs",
    description="Parse JSON log files and extract error rates",
    parameters="""
  type: object
  properties:
    path:
      type: string
      description: Path to log file
  required:
    - path
"""
)
```

This generates `context/skills/parse_json_logs.md`:

```markdown
---
name: parse_json_logs
description: Parse JSON log files and extract error rates
write: false
parameters:
  type: object
  properties:
    path:
      type: string
      description: Path to log file
  required:
    - path
---

# parse_json_logs

Parse JSON log files and extract error rates

This is a prompt-based skill. Add instructions below.

## Instructions

Add your skill instructions here.
```

### 3. Activation: `/reload`

The user runs `/reload` to load the new skill into the agent's tool registry.

---

## Guardrails

### Read-Only Core (15 skills)

The agent cannot overwrite core meta-tools:

```python
CORE_SKILLS = {
    "web_search", "fetch_url", "read_file", "write_file", "list_files",
    "run_command", "calculate", "python_eval", "current_time",
    "save_memory", "search_memory", "write_knowledge", "search_knowledge",
    "create_skill", "search_skill_library"
}
```

Attempt to overwrite:
```
Agent calls: create_skill(name="web_search", description="Overwrite core")
Result: "Error: 'web_search' is a core skill and cannot be overwritten."
```

### YAML Linter

Parameters are validated before saving:

```
Agent calls: create_skill(name="bad", description="test", parameters="not: valid: yaml: [")
Result: "Error: Invalid YAML in parameters: mapping values are not allowed here..."
```

### Duplicate Prevention

```
Agent calls: create_skill(name="existing_skill", description="duplicate")
Result: "Error: Skill 'existing_skill' already exists. Use write_file to modify it."
```

---

## Architecture

### Tool Stack

| Tool | Role | Description |
|------|------|-------------|
| `search_skill_library` | Discovery | Find existing skills by keyword |
| `create_skill` | Creation | Generate skill file with YAML frontmatter |
| `write_file` | Modification | Edit skill content (instructions, code) |
| `run_command` | Testing | Run tests to verify skill works |
| `/reload` | Activation | Load new skills into agent |

### The Self-Extension Loop

```
[New Task] → [search_skill_library] → [Match found?]
                                            |
                                    Yes → [Use existing skill]
                                    No  → [create_skill]
                                            |
                                    [write_file: add instructions/code]
                                            |
                                    [run_command: test it]
                                            |
                                    [User: /reload]
                                            |
                                    [Skill active]
```

### Prompt Integration

The agent's system prompt includes:

```
14. `create_skill` — Create a new skill file. Always run `search_skill_library` first.
15. `search_skill_library` — Search existing skills. Use BEFORE creating to avoid duplicates.
```

---

## Example Session

```
> I need a skill to convert CSV files to JSON

[Using: search_skill_library]
[search_skill_library done]
No skills match 'convert CSV JSON'.

[Using: create_skill]
[create_skill done]
Created skill: context/skills/csv_to_json.md
Run /reload to activate it.

> Now add instructions for how to use it

[Using: read_file]
[read_file done]
(context/skills/csv_to_json.md content shown)

[Using: write_file]
[write_file done]
Success: Wrote 450 characters to context/skills/csv_to_json.md

> /reload
Skills reloaded (15 → 16).

> Convert the file at data/sales.csv to JSON

[Using: csv_to_json]
[csv_to_json done]
{"records": [...], "count": 150}
```

---

## Future: Test Harness (Phase 4)

The full self-assembling loop would add automated testing:

```
[create_skill] → [write_file: add Python code]
                        |
                [run_command: pytest test_skill.py]
                        |
                (pass) → [Save to library]
                (fail) → [read_file: error] → [write_file: fix] → retry
```

This requires:
1. Agent writes Python code to the skill file
2. Agent writes a test script
3. Agent runs `pytest` via `run_command`
4. On failure, agent reads the traceback and fixes the code
5. On success, skill is saved permanently

**Status:** Not yet implemented — requires the agent to reliably write and test Python code, which depends on model capability (Gemma4/Qwen3.5 can do this).
