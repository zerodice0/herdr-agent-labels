---
name: herdr-agent-messenger
description: HAM (Herdr Agent Messenger) messages current Herdr agents and starts new labeled agent sessions by SSH host and Agent Labels name, waits for responses, reads terminal output, and coordinates tailored multi-agent work. Use when the user mentions HAM or asks Codex, Claude, or omp to start, open, message, delegate to, check, or collect results from labeled Herdr agents such as local/white-bison or macbook-pro/purple-koala.
---

# HAM — Herdr Agent Messenger

## Choose the operation

- **Message an existing agent:** `list` → copy its exact `address` → `request --address HOST/LABEL`.
- **Start/open a new agent and message it:** `spawn` → copy its returned `address` → `request --address HOST/LABEL`. Do not substitute raw `herdr agent start <name>`: that bypasses HAM label selection and metadata reporting. Create agents only when asked; a missing existing label is an error, not permission to create or guess one.
- **Coordinate multiple agents:** verify recipients, decompose into non-overlapping assignments, then `batch` tailored address/message or route/message items. Wait, inspect every result, and synthesize.

Use the bundled CLI, not reconstructed SSH commands. It verifies the sender, restricts SSH hosts to configured concrete aliases, and resolves the current recipient before every operation. Run messaging commands from the coordinator's active Herdr agent pane (`HERDR_PANE_ID`).

## Exact commands

The executable is `scripts/herdr_agent_messenger.py` **relative to this skill directory**. Run these examples from that directory; otherwise use its absolute path. Replace uppercase example values with returned identifiers, not guessed labels.

```bash
python3 scripts/herdr_agent_messenger.py list --host local
python3 scripts/herdr_agent_messenger.py list --host macbook-pro
python3 scripts/herdr_agent_messenger.py status --address macbook-pro/purple-koala
python3 scripts/herdr_agent_messenger.py request \
  --address macbook-pro/purple-koala \
  --message 'Inspect the current task and report blockers.' \
  --timeout 120000 --output-lines 120 --output-chars 12000
python3 scripts/herdr_agent_messenger.py request-status --request-id REQUEST_ID
```

When asked to create a session (the directory must exist on the selected host):

```bash
python3 scripts/herdr_agent_messenger.py spawn \
  --kind omp --cwd /path/to/project --placement tab
# Copy address from that JSON result into the next command.
python3 scripts/herdr_agent_messenger.py request \
  --address RETURNED_HOST/RETURNED_LABEL --message 'Review the project and report blockers.'
# Optional agent-specific arguments go after --, never among HAM flags:
python3 scripts/herdr_agent_messenger.py spawn \
  --kind codex --cwd /path/to/project --placement workspace -- --model MODEL
```

For GUI selections, use the supplied absolute CLI path and opaque `--route` tokens directly. Tokens support unlabeled selections too. Never decode, alter, or replace them with guessed `herdr` commands. Use `route` returned by `status`, `spawn`, or request payloads for later GUI-style routing. A v2 route refreshes only when conservative continuity checks identify one safe occupant; if `route_refreshed: true`, retain the new token.

Manual delivery/output inspection:

```bash
python3 scripts/herdr_agent_messenger.py send \
  --address macbook-pro/purple-koala --message 'Report your current task.' --no-wait
python3 scripts/herdr_agent_messenger.py read \
  --address macbook-pro/purple-koala --lines 160 --max-bytes 65536
python3 scripts/herdr_agent_messenger.py read \
  --address macbook-pro/purple-koala --cursor PREVIOUS_CURSOR
```

Batch dispatch (JSON is already tailored; HAM does not split or rewrite it):

```bash
python3 scripts/herdr_agent_messenger.py batch \
  --requests-json '[{"address":"local/white-bison","message":"Inspect API behavior."},{"route":"ROUTE_TOKEN","message":"Review the UI."}]' \
  --wait --timeout 120000 --max-workers 4
```

## Command and flag reference

All eight subcommands accept `-h` / `--help` (print usage and exit 0). Optional flags are unset unless a default is specified. Numeric values are integers.

### Recipient selectors

`status`, `send`, `read`, and `request` require **exactly one** of:

| Flag | Meaning / default |
| --- | --- |
| `--address HOST/LABEL` | Exact `address` from `list` or `spawn`; carries its own host. |
| `--label LABEL` | Exact current Agent Labels name, combined with `--host`. |
| `--route TOKEN` | Opaque verified GUI/CLI route; carries its own host. |
| `--host HOST` | Default `local`; otherwise a concrete configured SSH alias. With `--address`, an explicit non-default host must agree or `conflicting_address` results. For routes, use the token's host rather than overriding it. |

Only literal `local` means local transport. Even a hostname matching this machine means SSH. Labels can repeat across hosts; never use an unqualified label as a global identity or substitute a pane ID. Missing/ambiguous hosts or labels must be reported, not guessed. A label does not guarantee the same occupant after restart.

### Commands

| Command | Flags, defaults, units, ranges |
| --- | --- |
| `list` | `--host HOST` (default `local`); `--verbose` (default off, full agent records); `--legacy` (alias of `--verbose`). Default payload is compact and includes each agent's `address`, `status`, and `workspace`. |
| `status` | Recipient selectors above; `--verbose` (default off, full agent record). Checks one recipient without listing its host. |
| `send` | Recipient selectors; required `--message TEXT` (nonblank); `--wait` / `--no-wait` (mutually exclusive, default `--wait`); `--timeout MS` (default 120000, >0, no HAM upper bound). Uses Herdr's lower-level completion signal, not safe lifecycle correlation. |
| `batch` | Required `--requests-json JSON` (`-` reads stdin); `--wait` / `--no-wait` (mutually exclusive, default `--wait`); `--timeout MS` (per-request, default 120000, >0, no HAM upper bound); `--max-workers N` (default 4, range 1–8). Wait mode uses request lifecycles with 120 response lines / 12000 characters; no-wait mode stops after acceptance. |
| `read` | Recipient selectors; `--lines N` (default 120, >0 recent lines); `--max-bytes N` (default 65536, >0 UTF-8 bytes); `--cursor TOKEN` / `--watermark TOKEN` (aliases, prior read cursor). No HAM upper bound on positive limits. |
| `request` | Recipient selectors; required `--message TEXT` (nonblank); `--timeout MS` (default 120000, >0 observation deadline); `--output-lines N` (default 120, >0); `--output-chars N` (default 12000, >0 characters). No HAM upper bound on positive limits. Submits once without Herdr's ambiguous `--wait`, observes a fresh turn, and captures bounded output. |
| `request-status` | Required `--request-id ID` (32 lowercase hexadecimal characters, returned by a lifecycle). Reads/advances saved nonterminal state with one current observation; does not resend or start another full wait. |
| `spawn` | Required `--kind KIND`; all flags and forwarded arguments below. Creates a labeled interactive session, not a prompt. |

### Spawn flags

| Flag | Meaning / default / range |
| --- | --- |
| `--kind KIND` | Required Herdr-supported agent-kind token (e.g. `omp`, `codex`, `claude`); nonblank, no whitespace. |
| `--host HOST` | Default `local`; remote must be a concrete configured SSH alias with Herdr running. |
| `--cwd PATH` | Local default: current working directory. Required for SSH; path is on the selected host. |
| `--placement split\|tab\|workspace` | Default `split`; create a pane, a tab, or a workspace without focusing it. |
| `--from-pane PANE` | Source pane on selected host. Split default locally: `HERDR_PANE_ID`; required for a remote split. For tabs, may identify the source workspace. |
| `--direction right\|down` | Split direction, default `right`; relevant only to split placement. |
| `--workspace WS` | Workspace for a new tab. If omitted, infer from `--from-pane` or local `HERDR_PANE_ID` when available; otherwise use Herdr's default. Not used for splits/workspaces. |
| `--workspace-label TEXT` | Label for a new tab/workspace. Default: explicit `--label`, otherwise the generated agent label (applied after startup). Not used for splits. |
| `--label LABEL` | Default: a free HAM `color-animal` label. Explicit label must be nonblank and contain no `/`; a name collision fails rather than silently choosing another explicit name. |
| `--timeout MS` | Interactive readiness timeout, default 90000 ms, inclusive range 1–300000. Not a reply deadline. |
| `-- AGENT_ARGS...` | Optional arguments forwarded to the interactive agent; no default arguments. Put all HAM flags before `--`. |

Spawn success returns `address`, `label`, `marker`, `color`, `host`, `pane_id`, `workspace_id`, optional `tab_id`, `kind`, `cwd`, `route`, compact `agent`, `label_metadata_reported`, `placement_label_reported`, and `created` (`pane`, `tab`, or `workspace`). Metadata flags report reporting/renaming success, not reply completion. A custom label outside HAM's palette has empty marker/color and no palette metadata. Inspect cleanup details on startup failure before creating another session.

## Result contracts

### Exit codes

| Code | Meaning | Action |
| --- | --- | --- |
| `0` | `request`/`request-status`: `submitted_settled`; batch: every item `succeeded`; other commands: successful payload (or help). | Inspect payload and response quality; exit 0 is not proof that a worker's claims are correct. `send --no-wait` does not mean settled. |
| `1` | JSON error envelope, lifecycle `submission_failed`, or batch containing any `failed`, `cancelled`, or `timeout` item. | Inspect per-item status and error; retry only known-undelivered work after fixing the cause. Exit 1 alone does not prove non-delivery. |
| `2` | Argument-parser usage error (stderr, not the JSON envelope contract). | Correct command syntax before retrying. |
| `3` | Request is `submitted_working`/`submitted_unknown`; or batch has `submitted` items and no failures. | **Never resend.** Use each lifecycle `request_id` with `request-status`; for no-wait batch items without IDs, inspect the recipient with `status`/`read`. Respect `terminal: true` occupant-change cases. |

### Lifecycle states and response fields

| `state` | Meaning / next step |
| --- | --- |
| `submission_failed` | Resolution failed or submission was rejected/cancelled before delivery; terminal. Inspect `error_code` before retrying. |
| `submitted_working` | Submitted/possibly submitted and recipient observed working; requested completion not proven. Advance with `request-status`, not another request. |
| `submitted_settled` | Fresh requested working→settled cycle observed; terminal. Review bounded response. |
| `submitted_unknown` | Submitted/possibly submitted but matching requested turn cannot yet be confirmed. Advance saved state; never blindly resend. May be terminal when `error_code: recipient_changed`. |

Lifecycle payloads contain `request_id`, `state`, `phase`, `terminal`, `submitted` (true/false/null for accepted/rejected/unknown), human-readable `error`, and machine-readable `error_code` (null when no lifecycle error). **Preflight error envelopes** are `{"error":{"code":"...","message":"..."}}` and have no `request_id`. Not every CLI result has one.

- `response.output`: bounded terminal text added after the baseline when safely recoverable, not a structured assistant-message API.
- `response.truncated`: output was bounded/omitted, a baseline/read was unreliable, or safe delta recovery was lost. Do not claim the full reply was captured.
- `response.correlated`: a fresh requested working→settled cycle was observed and baseline/read were reliable. False means the text is not proven to be this request's completed answer.
- `response.anchored` (optional, true when used): baseline overlap was unavailable, so capture started at the last matching `Message from HOST/LABEL:` prompt-header line. It removes preceding startup/history text; it does **not** prove settlement or uniquely correlate concurrent messages from the same sender. Check `correlated` and `truncated` independently.

If the recipient was already working, its first settlement is only the old-turn boundary. HAM requires another working→settled cycle. `request-status` cannot reconstruct cycles missed between observations. An occupant change stops capture, preserves the original route, and sets terminal `submitted_unknown` / `recipient_changed`; do not collect replacement-agent output.

### Batch results

Input is a nonempty JSON array, or `{"requests":[...]}`. Each item needs exactly one of `address` / `route` and a nonblank string `message`. Duplicate resolved targets (including an address and a route naming the same agent) fail as `duplicate_route`. Results stay in input order; invalid items do not prevent independent valid items from dispatching.

| Per-item `status` | Meaning |
| --- | --- |
| `succeeded` | Requested lifecycle settled (wait mode). |
| `submitted` | Acceptance confirmed, but completion not verified (including all successful no-wait submissions). Never resend. |
| `failed` | Validation, resolution, or submission failure; inspect `error`/`detail`. |
| `timeout` | Acceptance could not be confirmed, or dispatch timed out. Possibly delivered; inspect before retrying. |
| `cancelled` | Dispatch/submission cancelled; inspect delivery evidence before retrying. |

Aggregate `status` is `succeeded` when every item is **delivered** (`succeeded` or `submitted`), `partial` when only some are delivered, and `failed` when none are delivered. Aggregate `succeeded` does **not** mean settled; inspect every item and the exit code. Wait-mode lifecycle items include `request_id` and bounded `response` when available; preflight failures and no-wait items may not. Batch `error` is the per-item error/detail channel, not the lifecycle `error_code` field; use `request-status` for the full lifecycle contract, including optional anchoring.

### Error code catalog and retry policy

Codes occur as envelope `error.code`, lifecycle `error_code`, or batch item `error` as applicable. A batch lifecycle failure can carry human-readable failure text in `error`; consult its `request_id` for machine-readable lifecycle details.

| Group / codes | Meaning and safe recovery |
| --- | --- |
| Input: `invalid_address`, `conflicting_address`, `missing_address`, `invalid_label`, `empty_message`, `invalid_message`, `invalid_timeout`, `invalid_lines`, `invalid_max_bytes`, `invalid_output_lines`, `invalid_output_chars`, `invalid_cursor`, `invalid_request_id` | Fix input, then retry the rejected operation. Never fabricate an address, route, cursor, or request ID. |
| Batch input: `invalid_batch_json`, `invalid_batch`, `empty_batch`, `invalid_request`, `invalid_workers`, `duplicate_route` | Correct JSON/schema/worker range, or remove duplicate targets. `invalid_request` includes providing address and route together or neither. Retry only rejected items, not already delivered peers. |
| Target: `agent_not_found`, `agent_ambiguous`, `invalid_route`, `route_expired`, `route_ambiguous`, `resolve_failed`, `recipient_is_sender` | Relist/reselect the intended recipient or fix self-routing. Do not guess or create a missing agent unless asked. On a post-submission refresh error, preserve the original request and retry `request-status`, not delivery. |
| Connectivity: `host_not_configured`, `host_unavailable`, `read_failed` | Configure a concrete authorized SSH alias or restore Herdr/connectivity/trust. Local sandbox/socket permission failures require local-socket access; discovery failure is not evidence that an agent is missing. Retry discovery/status/read; retry delivery only when known not submitted, never resend because a `read` failed. |
| Sender: `sender_unavailable`, `sender_probe_failed` | Run from the current Herdr agent pane. Probe failure happens before submission; if details show sandbox/socket denial, obtain local Herdr socket access and retry that exact undelivered request. In batches retry only those failed items, never delivered/submitted/unknown/timed-out peers. |
| Submission: `prompt_failed` | Prompt rejected; fix the reported cause before retrying known-undelivered work. |
| Uncertain/wait: `prompt_acceptance_unknown`, `prompt_timeout`, `wait_timed_out`, `timeout` | Delivery/completion is uncertain or waiting expired. Never blindly resend; advance saved lifecycle state or inspect recipient status/output if no request ID exists. |
| Cancellation: `prompt_cancelled`, `cancelled` | Cancellation before submission is retryable after fixing the cause; cancellation after submission only cancels waiting, not recipient work. Use `submitted` and saved state to decide; never assume non-delivery. |
| Occupant: `recipient_changed` | Original occupant no longer matches; terminal unknown result, no replacement output. Report uncertainty and reselect only for explicitly new work. |
| State: `request_not_found`, `request_state_invalid`, `request_state_unavailable` | Verify the request ID, original coordinator host/state location, permissions, and stored state. Storage failure may occur after submission; do not resend until delivery is checked. |
| Spawn input: `cwd_required`, `sender_pane_unavailable`, `label_unavailable` | Supply remote cwd/source pane or an available valid label, then retry startup. |
| Spawn execution: `placement_failed`, `agent_start_failed` | Inspect Herdr failure and cleanup result. Check for an already-created session/resource before retrying; unsuccessful cleanup may leave one behind. |
| Installation/internal: `cli_not_found`, `internal_error`, `dispatch_failed`, `invalid_sender_result`, `invalid_command` | Restore the source-backed CLI installation or investigate the reported failure. Do not assume an unexpected error means nothing was sent; inspect recipient/state before retrying delivery. `invalid_command` is a defensive fallback; unknown CLI commands normally exit 2. |

## Output and coordination safety

`read` returns `truncated`, `cursor_status`, opaque `cursor`, and `delta`. Pass the cursor to the next read. Do not infer progress from line numbers: terminal screens can be rewritten. `cursor_status: expired` returns a fresh bounded snapshot (`delta: false`), not a safe append-only delta. Report omitted output when truncated.

Replies are scraped from the agent's TUI. Narrow panes hard-wrap lines; prefer `spawn --placement tab` or `--placement workspace` for long replies. Anchoring does not undo hard wrapping.

For multi-agent work: (1) list each requested host and verify every label; (2) assign non-overlapping work; (3) send only worker-specific context unless the user explicitly requests direct broadcast; (4) batch dispatch; (5) wait for each requested worker or clear terminal failure; (6) review responses against the workspace and follow up on inconsistencies; (7) synthesize unavailable hosts, uncertainty, unverified claims, and risks. HAM does not perform semantic decomposition or verification itself.

Never modify SSH trust settings, bypass host-key verification, or send through an alias absent from configured SSH config.

## Client onboarding

Install with **HAM Skill** in Herdr's command palette (or `Ctrl+G` in Agent Messenger). Installer targets are `codex`, `claude`, `omp`, or `all`. From the plugin/checkout root: `python3 agent_skill_installer.py install all` installs all user-scope targets.

- Codex: type `$ham` and select **HAM — Herdr Agent Messenger**.
- Claude Code: use `/herdr-agent-messenger` or a matching natural-language request.
- omp: ask naturally to use HAM, or read `skill://herdr-agent-messenger`. Install to `~/.omp/agent/skills/herdr-agent-messenger` (user scope) or `<project>/.omp/skills/herdr-agent-messenger` (project scope).

For installation details and expanded usage, see `docs/skill-guide.md` in the plugin/source checkout.
