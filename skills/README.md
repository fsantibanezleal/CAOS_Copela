# Skills

Two agent skills ship with copela. Each is a folder with a `SKILL.md` (frontmatter, then the
procedure), the assets it copies from, and the scripts it runs.

| Skill | Use it to |
|---|---|
| [`author-sdd/`](author-sdd/SKILL.md) | write a software design document before development, with every requirement in EARS form and naming the gate that fails when it is violated; ships the stdlib guard that checks each gate exists |
| [`run-sweep/`](run-sweep/SKILL.md) | run a narrative-to-formal sweep across models with copela, with every refusal made before anything is spent and no call recorded that never reached the model |

## Installing

For Claude Code, copy a skill folder into `~/.claude/skills/` (every project) or into a project's
`.claude/skills/` (that project only):

```bash
cp -r skills/author-sdd ~/.claude/skills/
cp -r skills/run-sweep ~/.claude/skills/
```

The scripts run on their own as well:

```bash
python skills/author-sdd/scripts/check_sdd.py <repo_root>
python skills/run-sweep/scripts/run_sweep.py --study my_study.py --provider ollama --model qwen3:8b \
    --ledger runs.jsonl --repeats 1
```

`skills/author-sdd/scripts/check_sdd.py` is the same file as this repository's `scripts/check_sdd.py`,
and a test keeps it so.
