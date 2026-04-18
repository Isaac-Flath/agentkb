---
title: Consolidation
description: Cross-reference chat history and wiki state to find what needs documenting.
order: 7
---

# Consolidation

Knowledge accumulates in chat history: what was tried, what failed, what was learned. The consolidation command exports recent chat history, prints the relevant local paths, and prints instructions the agent can act on.

## The Flow

```text
  chat history         wiki
  (what was learned)   (what's documented)
       \                /
        \              /
     agentkb consolidate
              |
      consolidation report
              |
   agent or human reads it
              |
     wiki pages get written
```

Consolidation is an **instruction generator**. It does not write pages or call an LLM. It exports recent chat history, prints the relevant local paths, and prints instructions for what the agent should extract.

## Commands

```bash
# Default: recent activity
agentkb consolidate

# Custom time range (natural language)
agentkb consolidate --since "30 days"
agentkb consolidate --since "2 weeks"
agentkb consolidate --since "45 days"
```

## What the Report Shows

### Paths

The report includes:

- wiki root
- `schema.md`
- `index.md`
- wiki pages directory
- readable chat exports directory
- raw JSONL sessions directory
- configured chat-history repo URL, if available

### Instructions

A consolidation prompt telling the agent what to extract:

- mistakes and corrections
- technical traps
- taste and judgment
- people knowledge
- writing and communication
- tools and workflows
- books and influences
- domain knowledge
- mental models

### Sessions to Review

The agent is pointed at the readable exports and raw sessions directories and told what time range to review.

## Workflow

### Manual

```bash
agentkb consolidate --since "30 days"
```

Read the report and decide what needs documenting.

### Agent-Assisted

Tell your agent to act on the report:

```text
Run agentkb consolidate --since "30 days" and follow the instructions.
Read the relevant chat sessions, extract reusable knowledge, and write or update wiki pages.
```

### First-Time Catch-Up

```bash
agentkb consolidate --since "90 days"
```

This is useful when bootstrapping a new wiki from existing chat history.

## Design Decisions

**Why not write pages directly?** The report shows what source material exists. The agent still has to read, judge, and write.

**Why not a separate daily log?** Chat history already captures the real work: prompts, tool calls, debugging loops, corrections, and outcomes.

**Why no LLM inside the library?** agentkb handles indexing, search, sync, and report generation. The agent handles synthesis.
