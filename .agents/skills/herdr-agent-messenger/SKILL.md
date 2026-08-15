---
name: herdr-agent-messenger
description: HAM (Herdr Agent Messenger) routes prompts to current Herdr agents by SSH host and Agent Labels name, waits for responses, reads terminal output, and coordinates tailored multi-agent work. Use when the user mentions HAM or asks Codex or Claude to message, delegate to, check, or collect results from labeled Herdr agents such as local/white-bison or macbook-pro/purple-koala.
---

# HAM — Herdr Agent Messenger

Use the bundled CLI instead of reconstructing SSH commands. It validates the current sender, restricts remote hosts to concrete aliases in the configured SSH config, resolves the label again immediately before each operation, and reuses the plugin's hardened SSH transport.

Agent Messenger's GUI may send the coordinator a self-contained orchestration request containing an absolute bundled CLI path and opaque `--route` tokens. Follow those commands directly. They work without this skill being installed, support unlabeled GUI selections, and resolve the exact pane occupant before every operation. A stale v2 route is refreshed only when conservative continuity checks identify one safe current occupant. If a result has `route_refreshed: true`, use its returned `route` for subsequent reads or follow-ups. Do not replace these tokens with guessed `herdr` commands or try to decode or modify them.

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
If local discovery returns `host_unavailable` with a sandbox or socket permission
error, rerun the same bundled CLI command with the required local-socket access.
Do not report the agent as missing unless discovery itself succeeded.

Check one already-selected recipient without listing its host:

```bash
python3 scripts/herdr_agent_messenger.py status --route ROUTE_TOKEN
```

## Send one request

Run from the coordinator's active Herdr pane so `HERDR_PANE_ID` identifies the sender:

```bash
python3 scripts/herdr_agent_messenger.py request \
  --host macbook-pro \
  --label purple-koala \
  --message 'Inspect the current task and report blockers.' \
  --timeout 120000
```

`request` resolves the recipient, submits without Herdr's ambiguous `--wait`,
observes a fresh working-to-settled cycle, and returns only bounded output added
after its baseline. Inspect `state`, `response.truncated`, and
`response.correlated` before using the result. The reported states are
`submission_failed`, `submitted_working`, `submitted_settled`, and
`submitted_unknown`. A timeout after prompt submission is not proof of delivery
failure, so do not retry `submitted_working` or `submitted_unknown` requests
without checking their stored state and the recipient first.

When the recipient was already working, the first settlement belongs to the old
turn and is used only as a boundary. The request is settled only after another
working-to-settled cycle is observed. This is intentionally conservative.

Every result contains a `request_id`. Re-read and advance a nonterminal request's
latest atomic state with:

```bash
python3 scripts/herdr_agent_messenger.py request-status \
  --request-id REQUEST_ID
```

The lower-level `send` and `read` commands remain available for compatibility.
Read recent output manually only when investigating an unknown result:

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
4. Encode the already-tailored assignments as route/message JSON and let the
   bundled CLI dispatch them with bounded concurrency. The CLI does not interpret,
   split, or rewrite messages:

```bash
python3 scripts/herdr_agent_messenger.py batch \
  --requests-json '[{"route":"ROUTE_TOKEN","message":"Tailored instruction."}]' \
  --wait \
  --timeout 120000 \
  --max-workers 4
```

   Use `--requests-json -` to read the same JSON array from stdin. Batch results
   remain in input order and report each target as `succeeded`, `submitted`,
   `failed`, `timeout`, or `cancelled`. A `submitted` result means delivery was
   accepted but this invocation did not verify the matching request's completion.
   With `--wait`, every delivered result includes its lifecycle `request_id` and
   bounded response; advance a submitted item with `request-status` instead of
   resending it. `submitted` requires confirmed prompt acceptance; an unconfirmed
   submission timeout remains `timeout`. Existing work is treated as a boundary
   before the requested turn.
5. Wait for every requested worker or a clear terminal failure.
6. Read each response, verify it against the relevant workspace, and follow up on missing or inconsistent work.
7. Synthesize the results for the user, identifying unavailable hosts, timed-out agents, unverified claims, and remaining risks.

Do not modify SSH trust settings, bypass host-key verification, or send through an alias that is absent from the configured SSH config.
