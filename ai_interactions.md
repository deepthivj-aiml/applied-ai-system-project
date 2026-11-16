# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agent Workflow (SF7)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

<!-- Describe the goal you asked the agent to accomplish -->

**What did the agent do?**

<!-- List the steps the agent took (files edited, commands run, etc.) -->

**What did you have to verify or fix manually?**

<!-- Describe anything the agent got wrong or that required human review -->

---

## Prompt Comparison (SF11)

> Compare two different prompts (or two different models) on the same task.

| | Option A | Option B |
|-|----------|----------|
| **Model / tool used** | | |
| **Prompt** | | |
| **Response summary** | | |
| **What was useful** | | |
| **Problems noticed** | | |
| **Decision** | | |

**Which approach did you use in your final implementation and why?**

<!-- Your conclusion -->

## Agent Trace — 2026-11-16T04:21:07

```json
{
  "started_at": "2026-11-16T04:21:07",
  "steps": [
    {
      "step": "1-intake",
      "status": "lost",
      "species": "dog",
      "place": "Central Park, Fremont"
    },
    {
      "step": "2-vision",
      "mode": "skipped",
      "note": "No photo uploaded."
    },
    {
      "step": "3-verifier",
      "note": "Manual attributes used (demo mode or no photo)."
    },
    {
      "step": "4-retriever",
      "sources": [
        "data/knowledge/breed_profiles.md",
        "data/knowledge/lost_pet_search.md",
        "data/knowledge/coat_colours.md"
      ]
    },
    {
      "step": "5-matcher",
      "matches": [
        {
          "case_id": "LF-002",
          "score": 100
        }
      ]
    },
    {
      "step": "6-notifier",
      "draft_created": true,
      "note": "Draft only. Nothing is sent by the app."
    }
  ],
  "query": {
    "species": "dog",
    "breed": "golden retriever",
    "colour": "golden",
    "size": "large",
    "sex": "male",
    "markings": "white chest patch",
    "date": "2026-11-10",
    "lat": 37.5515,
    "lon": -121.9678,
    "status": "lost",
    "place_label": "Central Park, Fremont"
  }
}
```
