# Step Records

This directory keeps small chronological records for meaningful project changes.
Each record should explain what changed, what decisions were made, why those
decisions were made, how the step was validated, and what follow-up work remains.

Use one file per small implementation step or commit-sized change:

```text
NNNN-short-description.md
```

Draft plan files may exist while a step is being discussed, but consolidate them
into the step record before moving on. The durable repo history should keep one
canonical `NNNN-*.md` file per step.

Prefer concise records. `docs/architecture.md` should describe the current
architecture once it exists; step records should explain how the project arrived
there.
