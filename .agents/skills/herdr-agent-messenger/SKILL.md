---
name: herdr-agent-messenger
description: Use HAM (Herdr Agent Messenger) to start/open new labeled Herdr agent sessions, message or delegate to existing agents, check progress, and collect replies. Trigger on HAM, new Herdr session requests, or host/label addresses such as local/white-bison and macbook-pro/purple-koala; supports Codex, Claude, and omp.
---

# HAM — Herdr Agent Messenger

## Choose the operation

- **Existing agent:** `list` on its host → copy the exact `address` → `request --address HOST/LABEL`.
- **New session, only when asked:** `spawn` → copy the returned `address` → `request --address HOST/LABEL`. Do not substitute raw `herdr agent start`: that bypasses HAM labels and metadata. A missing existing label is an error, not permission to create or guess one.
- **Several agents:** list each host, verify recipients, split work into non-overlapping assignments, then `batch` tailored address/message items. Inspect every result and synthesize; HAM does not split or verify the work for you.
- **Follow-up:** keep each `request_id`; run `request-status --request-id ID --wait 120000` until settled or a clear terminal failure. A wait returning without a change is not permission to resend.

Use the bundled CLI, not reconstructed SSH commands. Run messaging from the coordinator's active Herdr agent pane (`HERDR_PANE_ID`). Only literal `local` is local; other hosts must be concrete configured SSH aliases. Labels are host-scoped, can change occupants, and must not be guessed or replaced with pane IDs.

## Exact commands

The executable is `scripts/herdr_agent_messenger.py` **relative to this skill directory**. Run examples from that directory, or use the absolute script path. Replace uppercase placeholders with returned identifiers.

```bash
python3 scripts/herdr_agent_messenger.py list --host local
python3 scripts/herdr_agent_messenger.py list --host macbook-pro
python3 scripts/herdr_agent_messenger.py status --address macbook-pro/purple-koala
python3 scripts/herdr_agent_messenger.py request \
  --address macbook-pro/purple-koala \
  --message 'Inspect the current task and report blockers.' --timeout 120000
python3 scripts/herdr_agent_messenger.py request-status \
  --request-id REQUEST_ID --wait 120000
```

When asked to create a session (the directory must exist on the selected host):

```bash
python3 scripts/herdr_agent_messenger.py spawn \
  --kind omp --cwd /path/to/project --placement tab
python3 scripts/herdr_agent_messenger.py request \
  --address RETURNED_HOST/RETURNED_LABEL --message 'Review the project and report blockers.'
# Optional agent-specific arguments go after --, never among HAM flags.
python3 scripts/herdr_agent_messenger.py spawn \
  --kind codex --cwd /path/to/project --placement workspace -- --model MODEL
```

Batch dispatch accepts a nonempty JSON array (or `{"requests":[...]}`). Each item needs exactly one `address` or opaque `route`, plus a nonblank `message`. Results stay in input order; inspect valid peers even if another item fails.

```bash
python3 scripts/herdr_agent_messenger.py batch \
  --requests-json '[{"address":"local/white-bison","message":"Inspect API behavior."},{"address":"macbook-pro/purple-koala","message":"Review the UI."}]' \
  --wait --timeout 120000 --max-workers 4
```

For manual output inspection (not proof that a request completed):

```bash
python3 scripts/herdr_agent_messenger.py read \
  --address macbook-pro/purple-koala --lines 160 --max-bytes 65536
python3 scripts/herdr_agent_messenger.py read \
  --address macbook-pro/purple-koala --cursor PREVIOUS_CURSOR
```

For GUI-selected recipients, pass the supplied opaque `--route` unchanged instead of `--address`. Never decode or alter it. Prefer `request` over lower-level `send` for correlated completion.

## Focus-held delivery: do not resend

If the recipient pane is focused, HAM holds CLI `request`, `send`, and `batch` delivery to avoid combining a prompt with text the user is typing. This applies to local and remote panes.
Self-send fails immediately with `recipient_is_sender`, even if the sender pane is focused; it is never held.

- `deferred` / phase `deferred_recipient_focused`: not submitted yet; HAM owns delivery and submits when focus leaves before the defer deadline.
- `awaiting_decision` / phase `awaiting_decision`: the defer deadline passed while focused. HAM notifies the user; **HAM: Held Messages** lets them Push or Cancel. There is no automatic push after timeout.
- Both are nonterminal with `submitted: false`. **Do not resend, bypass HAM, or ask the user to unfocus.** Observe the original request with `request-status --request-id ID --wait 120000`.
- The default defer deadline is 180000 ms; `--defer-timeout MS` on `request`, `send`, or `batch` changes it. It is separate from the command's `--timeout` wait budget. A focused `send` returns immediately with a `request_id`, even with `--wait`.
- Cancel becomes terminal `submission_failed` with `error_code: delivery_cancelled`. A missing/replaced recipient can also fail before delivery. Inspect the saved result; do not automatically recreate a session or retry cancelled work.
- After deferred delivery or Push, the worker watches until terminal or 30 minutes after submission. Read the saved result with `request-status`; after that limit, it can still advance observation.

## Compact results and exit codes

Default JSON is compact; use `--verbose` only when diagnostics or full fields are needed.

- `list`: `host`, `agents` with `address`, `status`, `workspace`.
- `status`: `address`, `status`, plus `stale: true` only if stale.
- `spawn`: `address`, `marker`, `created`, `pane_id`, `workspace_id`, optional `tab_id`; metadata-reporting flags appear only when false. Startup is not a reply.
- Requests: `request_id`, `state`, `terminal`, `submitted`, `phase`, `address`; optional `error_code`, `error`, `defer` (`reason`, `deadline`), `changed`, `response` (`text`, `truncated`, `correlated`, optional `anchored: true`). Empty responses may be omitted before settlement.
- `request-status`: unchanged output is only `request_id`, `state`, `terminal`, `submitted`, `changed: false`; otherwise full compact fields and `changed: true`. `--wait MS` stops on a state, phase or `error_code` change, a terminal state, or the deadline, not response-text growth; it never resends.
- `read`: `address`, cleaned `output`, `delta`, `truncated`, opaque `cursor` for the next read.
- Immediate `send`: `sent`, `address`, `waited`, optional nonempty `warnings`. A held send returns the request fields instead.
- Batch items: `address`, `status`, optional `request_id`, `state`, `error_code`, `error`, `response` (`text`, `truncated`). `submitted` and `deferred` are not completed replies.

| Exit | Meaning and action |
| --- | --- |
| `0` | Settled/successful operation; inspect payload and verify worker claims. A successful no-wait send is not proof of completion. |
| `1` | Error envelope, `submission_failed`, or batch failure/cancellation/timeout. Inspect delivery evidence; retry only known-undelivered work after fixing its cause. Exit 1 alone does not prove non-delivery. |
| `3` | **HAM still owns the work: do not resend.** Includes `submitted_working`, `submitted_unknown`, `deferred`, `awaiting_decision`, and batch `submitted`/`deferred` items without failures. Keep observing by ID; without an ID use `status`/`read`. Respect terminal occupant-change results. |

Argument usage errors exit `2`; fix the syntax. Preflight errors have `{"error":{"code":"...","message":"..."}}` and may have no `request_id`.

## Verify before reporting

`submitted_settled` means HAM observed a fresh requested working→settled cycle, not that the answer is correct. `submitted_working` and `submitted_unknown` require follow-up, never blind resend. `submitted_unknown` may be terminal after `recipient_changed`; do not collect the replacement agent's output.

Replies are terminal text, not a structured message API. `correlated: false` is not a proven completed answer. `response.truncated` is true only when reply text itself was cut by output bounds or a failed read, not merely when older history was omitted or baseline overlap was lost. `anchored: true` removes preceding history but does not prove correlation. An expired read cursor can yield a fresh snapshot (`delta: false`), not an append-only delta. Narrow panes hard-wrap; prefer tab/workspace sessions for long replies.

Review responses against actual files/results, follow up on inconsistencies, and report unavailable hosts, uncertainty, unverified claims, and risks. Never resend just because waiting, reading, or storage failed. Never modify SSH trust settings or bypass host-key verification.

Read `reference.md` in this directory only for flags, error codes, verbose fields, or installation details not covered here.
