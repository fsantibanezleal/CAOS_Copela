# Security policy

## Scope

`copela` calls language-model APIs, writes a run ledger, and solves models. Three areas deserve care.

**Credentials.** API keys are read from the environment (`ANTHROPIC_API_KEY`, `GROQ_API_KEY`) or
passed explicitly. This repository never stores a key, and a provider refuses to construct without
one rather than failing later. Do not commit a key; if one is committed, rotate it, because it
persists in the history.

**Untrusted model output.** A response from a language model is untrusted input. The harness parses
it into a `planteo` document and validates it before anything else touches it. Do not execute
emitted model source from an unvalidated response; `planteo`'s security policy covers that path.

**The ledger.** Records carry prompt and response **digests**, not prompts and responses. If your
cases contain sensitive text, the narrative still reaches the provider, so use the local Ollama lane
for anything that must not leave the machine.

## Reporting a vulnerability

Report privately to fsantibanez@gmail.com rather than opening a public issue. Include the version, a
minimal reproduction, and what you expected instead.

Expect an acknowledgement within a week. Fixes ship as a new patch release with a CHANGELOG entry.

## Supported versions

The latest released version. This project is pre-1.0.
