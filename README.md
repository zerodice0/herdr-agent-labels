# Herdr Agent Labels

Assigns an unused `color-animal` name to every unnamed agent detected by Herdr,
then uses those names to route prompts to one or more agents from a keyboard-first
popup. Manually named agents are left unchanged.

The routable agent name stays ASCII, for example `blue-otter`. The sidebar and
pane border display a color marker, for example `🟦 blue-otter`.

No discovery call is required when the name is already visible:

```bash
herdr agent prompt blue-otter "Review the current change"
herdr agent prompt white-owl "Run the focused tests"
```

## Requirements

- Herdr 0.8.0 or newer
- Python 3

## Install

Install and enable the plugin from this public GitHub repository:

```bash
herdr plugin install zerodice0/herdr-agent-labels --yes
```

For local development, link this checkout instead:

```bash
herdr plugin link "$PWD" --enabled
```

Existing unnamed agents can be labeled with the `Assign Agent Label` plugin
action. Agents detected after installation are labeled automatically.

## Agent Messenger

Run the `Send Prompt to Agents` action from a pane that contains an agent. The
focused agent becomes the fixed sender; the action shows an error notification
instead of opening the popup when the focused pane has no running agent.

The popup lists agents from the current Herdr session immediately, sorted by
the workspace label shown by Herdr. Unicode labels are preserved, and
worktree-backed workspaces carry a `WT:` prefix. When concrete
`Host` aliases exist in `~/.ssh/config`, choose remote discovery to query them
asynchronously. Only hosts that return a valid Herdr snapshot response within
five seconds are included. Remote results are cached briefly so reopening the
popup does not contact every host again.

## Agent Skill

The plugin bundles `.agents/skills/herdr-agent-messenger/SKILL.md` as the
canonical skill and a Claude discovery entry at
`.claude/skills/herdr-agent-messenger/SKILL.md`.
It lets an agent route requests without opening the popup by addressing a current
recipient as `host/label`, for example `macbook-pro/purple-koala`. Remote hosts
must be concrete aliases in the user's SSH config, and labels are resolved again
before every operation so a stale pane occupant is not reused.
Only the literal host `local` selects the current Herdr server; every other host
is treated as an SSH alias, even if it matches the local machine's hostname.

In a repository checkout, Codex and Claude discover the skill from their
project-level skill directories. To make it available from every workspace,
open `Agent Skill` from Herdr's command palette and select Codex, Claude, and
either the current project or the whole system. The same interactive screen
opens with `Ctrl+G` from Agent Messenger; press `?` to switch to concise usage
help. Each target carries
a compact badge: `✓` current, `↑` update available, `○` not installed, or `!`
conflicting files. The selected badge is explained at the bottom of the popup.
System-wide installs use the user's agent skill directories; project installs
use the active Herdr workspace. Start a new agent session afterward. The
installer refuses to overwrite an unrelated skill directory with the same name.

For usage help, open `Agent Skill` from Herdr's command palette and press `?`,
press `Ctrl+G` inside Agent Messenger, or invoke the action from any directory:

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-labels
```

From the plugin checkout or installed plugin root, print the packaged skill path
directly:

```bash
python3 agent_messenger.py skill-path
```

Ask Codex or Claude to read that `SKILL.md`, then request work naturally. The
`$herdr-agent-messenger` form is available when the project-level skill has been
discovered; an explicit natural-language request also works after loading the
printed path:

```text
Use $herdr-agent-messenger to ask macbook-pro/purple-koala for a status report.
```

The bundled helper supports listing, individual sends, bounded batch sends of
already-tailored route/message JSON, optional settled-state waits, and reading
recent output. Batch dispatch preserves input order and reports each target as
`succeeded`, `submitted`, `failed`, `timeout`, or `cancelled`; it does not perform
semantic decomposition. The helper reuses the plugin's SSH host allowlist,
forwarding protections, host-key policy, and current-agent verification.

The skill is optional for the popup workflow. Coordinator delegation embeds the
installed plugin's executable router path and an opaque route token for every
selected worker in the coordinator request. The token contains a hash of the
observed pane occupant rather than its session metadata. Before sending or
reading, the router discovers the recorded local or SSH host again and rejects
the route if that occupant has changed. This also makes unlabeled agents selected
in the GUI addressable without requiring the coordinator to discover Herdr CLI
syntax or install the skill first.

After SSH discovery, choose a delivery mode:

- **Delegate through coordinator (default and recommended):** the focused agent
  that opened the popup is the coordinator. The plugin sends that coordinator one
  self-contained orchestration request containing the selected worker list,
  verified route tokens, bundled router commands, and the user's original request.
  It does not send the original request to the selected workers.
  The coordinator performs the semantic task breakdown, creates route/message JSON
  with one tailored instruction per worker, and hands that fixed list to the
  bundled batch command for bounded delivery. It then waits for and verifies the
  responses and synthesizes the result for the user. This route does not depend on
  a globally or project-installed Agent Messenger skill. The Python plugin
  deliberately does not try to interpret or split the work.
- **Send directly (advanced):** preserves the original behavior. The plugin copies
  the same complete message to every selected agent immediately.

These modes have different privacy boundaries. Delegate mode exposes the complete
request only to the coordinator; selected workers receive whatever tailored
context the coordinator decides they need. Direct mode exposes the complete
message to every selected agent, including agents reached through SSH. Agent and
workspace metadata needed to route either mode remains subject to the discovery
cache behavior described below.

Remote discovery uses non-interactive SSH authentication and honors the user's
host-key policy. It disables SSH forwarding, agent forwarding, X11 forwarding,
and local commands for plugin probes. Hosts without an already trusted key when
the configured policy requires one, usable authentication, a reachable SSH
service, or a running Herdr server are skipped. Concrete `Host` aliases from
recursive `Include` files are supported.

The editor shows a compact remote summary instead of listing every SSH alias.
When any host is unavailable, the warning is highlighted; press `Ctrl+U` to open
a scrollable list of the affected aliases and their latest errors.

Recipient rows keep interaction and lifecycle state separate: `›` is the
keyboard cursor, `[x]` means selected, and the final icon plus localized text is
the agent state (`●` working, `○` idle, `✓` done, `!` blocked, `~` stale). Color
is applied only as a redundant state cue, so the meaning remains visible in
monochrome and selected rows retain their actual status. The popup starts at a
height appropriate for the known local recipient count, then gives additional
discovered agents most of the available editor space while preserving a message
area. When the terminal has enough room, the editor always keeps at least four
soft-wrapped message rows visible. Longer messages follow the text cursor and
show a right-side scrollbar with the current viewport position. The recipient
heading shows the visible range when scrolling is required.
When remote agents are present, recipients are grouped under a single host
heading instead of repeating the host on every row. A long group keeps its host
heading visible while scrolling. Each row prioritizes the Agent Labels name,
workspace, Herdr pane ID, and lifecycle state; the full agent session ID remains
searchable without consuming the main list width. The last successful remote
cache contributes to the next popup's initial height estimate.

By default, the plugin probes every concrete alias for backward compatibility.
That is usually broader than necessary when `~/.ssh/config` also contains work,
deployment, or dormant hosts. To restrict discovery, create `ssh-hosts` in the
plugin config directory with one authorized alias per line:

```text
macbook-pro
winmini
```

Only aliases that also exist in the SSH config are used. An empty file selects
local-only discovery, while a missing file retains the all-alias behavior. Set
`HERDR_AGENT_LABELS_SSH_HOSTS_FILE` to use a different allowlist path. Herdr
provides the default path through `HERDR_PLUGIN_CONFIG_DIR`; it normally resolves
to `~/.config/herdr/plugins/config/herdr.agent-labels/ssh-hosts`.

Tailscale does not require a special plugin-specific SSH format. Keep a stable,
human-readable SSH alias and point it to either the device's MagicDNS name or
Tailscale IP, for example:

```sshconfig
Host winmini
  HostName winmini.example-tailnet.ts.net
  User your-remote-user
```

The plugin still probes only explicit SSH aliases; it never treats every device
in the tailnet as authorized automatically. The UI displays only the stable SSH
alias, such as `macbook-pro`, rather than combining it with a Tailscale device
name or destination. This keeps host groups concise and avoids implying a
sender-to-recipient relationship.

Prompts sent remotely include the sender's local hostname and agent label. The
private `0600` discovery cache stores remote agent labels, pane/session metadata,
status, workspace paths, and host aliases under `HERDR_PLUGIN_STATE_DIR`.

Set `HERDR_AGENT_LABELS_SSH_CONFIG` to use a different SSH config file.
The popup uses Herdr's inherited terminal palette, so its accent and status
colors follow the active Herdr theme instead of defining a separate theme.

Keyboard controls:

- `Up` / `Down`: move through choices, recipients, or wrapped message lines
- `Enter`: confirm the highlighted discovery choice
- `D` / `L`: choose remote discovery or local-only directly
- `C` / `D`: choose coordinator delegation or direct delivery on the mode screen
- `Space`: toggle a recipient
- `Ctrl+A`: select all filtered recipients
- `Ctrl+D`: clear the selection
- `Tab`: switch between recipients and the message editor
- `Ctrl+O`: reopen the delivery mode screen
- `Ctrl+R`: refresh local and authorized remote agents
- `Ctrl+U`: show unavailable remote hosts and their latest errors
- `Ctrl+G`: show the bundled Agent Messenger skill guide
- `Ctrl+S`: send the prompt
- `Esc`: go back from delivery mode, cancel discovery or pending sends, then close
  the popup

Shortcut hints wrap onto additional footer rows at word boundaries when the
popup is narrow, so later actions such as refresh, skill guide, and close remain
visible instead of being clipped.

The main messenger grows up to 120 columns by 32 rows on large Herdr viewports,
while retaining margins and shrinking to fit compact devices. Host headings and
healthy remote summaries use the brighter terminal accent color; lifecycle
colors remain reserved for working, done, blocked, and warning states.

The UI follows `LC_ALL`, `LC_MESSAGES`, or `LANG` and supports English, Japanese,
and Korean. Unsupported locales fall back to English.

## Test

```bash
python3 -m unittest -v
```
