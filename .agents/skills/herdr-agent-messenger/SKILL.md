---
name: herdr-agent-messenger
description: Routes prompts to current Herdr agents by SSH host and Agent Labels name, waits for responses, reads terminal output, and coordinates tailored multi-agent work. Use when the user asks Codex or Claude to message, delegate to, check, or collect results from labeled Herdr agents such as local/white-bison or macbook-pro/purple-koala.
---

# Herdr Agent Messenger

Use the bundled CLI instead of reconstructing SSH commands. It validates the current sender, restricts remote hosts to concrete aliases in the configured SSH config, resolves the label again immediately before each operation, and reuses the plugin's hardened SSH transport.

Agent Messenger's GUI may send the coordinator a self-contained orchestration request containing an absolute bundled CLI path and opaque `--route` tokens. Follow those commands directly. They work without this skill being installed, support unlabeled GUI selections, and revalidate the exact pane occupant before every operation. Do not replace them with guessed `herdr` commands or try to decode or modify the tokens.

The executable is `scripts/herdr_agent_messenger.py` relative to this file. Invoke it with an absolute path when the working directory differs from the skill directory.

## Address agents

Treat `(host, label)` as the identity supplied by the user:

- Use `local` for the current Herdr server.
- Use a concrete SSH `Host` alias for a remote Herdr server.
- Treat only the literal `local` as local transport. A hostname that happens to
  match the current machine still means SSH, preventing transport ambiguity.
- Use the exact Agent Labels value, such as `white-bison`; do not substitute a pane ID.
- Do not assume a label identifies the same agent after a restart. Every command resolves the current occupant again.

List current candidates before dispatching:

```bash
python3 scripts/herdr_agent_messenger.py list --host local
python3 scripts/herdr_agent_messenger.py list --host macbook-pro
```

If the requested host or label is missing or ambiguous, report that and do not guess.
Use each list result's `address` field for subsequent operations.
The default list payload is compact. Use `list --verbose` only when a complete
agent record is required; `list --legacy` is its compatibility alias.

Check one already-selected recipient without listing its host:

```bash
python3 scripts/herdr_agent_messenger.py status --route ROUTE_TOKEN
```

## Send one request

Run from the coordinator's active Herdr pane so `HERDR_PANE_ID` identifies the sender:

```bash
python3 scripts/herdr_agent_messenger.py send \
  --host macbook-pro \
  --label purple-koala \
  --message 'Inspect the current task and report blockers.' \
  --wait \
  --timeout 120000
```

`send` waits by default. Use `--no-wait` only when the user does not need a result in the current turn. If the recipient was already `working`, Herdr's wait may match completion of its previous active turn; always read and verify the requested response instead of treating that wait as proof. If waiting times out, the prompt may already have been delivered; inspect the agent before retrying to avoid duplicate work.

Read recent output after the agent settles:

```bash
python3 scripts/herdr_agent_messenger.py read \
  --host macbook-pro \
  --label purple-koala \
  --lines 160 \
  --max-bytes 65536
```

The response contains `truncated`, `cursor_status`, and an opaque `cursor`.
Pass that cursor to the next read to suppress unchanged output and return only a
safe delta:

```bash
python3 scripts/herdr_agent_messenger.py read \
  --host macbook-pro \
  --label purple-koala \
  --lines 160 \
  --max-bytes 65536 \
  --cursor PREVIOUS_CURSOR
```

Do not infer progress from terminal line numbers. Herdr output can be a rewritten
screen rather than an append-only log. When `cursor_status` is `expired`, treat
the returned output as a fresh bounded snapshot; `delta` will be false. When
`truncated` is true, report that older bytes were omitted.

## Coordinate multiple agents

1. List each requested host and verify every label.
2. Decompose the request into specific, non-overlapping assignments.
3. Send only the context each worker needs. Do not copy the complete original request to every worker unless the user explicitly requests direct broadcast.
4. Dispatch independent assignments concurrently when safe.
5. Wait for every requested worker or a clear terminal failure.
6. Read each response, verify it against the relevant workspace, and follow up on missing or inconsistent work.
7. Synthesize the results for the user, identifying unavailable hosts, timed-out agents, unverified claims, and remaining risks.

Do not modify SSH trust settings, bypass host-key verification, or send through an alias that is absent from the configured SSH config.
