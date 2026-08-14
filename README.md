<p align="center">
  <img src="assets/ham-logo.png" alt="HAM — Herdr Agent Messenger mascot logo" width="360">
</p>

# HAM — Herdr Agent Messenger

HAM is an agent-labeling and multi-agent messaging plugin for Herdr. It assigns
an unused `color-animal` name to every unnamed agent, then uses those names to
route prompts to one or more agents from a keyboard-first popup or an AI skill.
Manually named agents are left unchanged.

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

### Migrate from 0.7.x

Version 0.8.0 changes the plugin ID from `herdr.agent-labels` to
`herdr.agent-messenger`. The GitHub repository and install source remain
`zerodice0/herdr-agent-labels`.

For an existing GitHub installation, disable the legacy ID, install the new
version, verify it, and then remove the legacy registration:

```bash
herdr plugin disable herdr.agent-labels
herdr plugin install zerodice0/herdr-agent-labels --yes
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
herdr plugin uninstall herdr.agent-labels
```

For a local development link, update the checkout and reload Herdr. Local links
are path-backed, so Herdr rereads the 0.8.0 manifest and adopts the new ID without
an unlink/relink cycle:

```bash
git pull --ff-only
herdr config check
herdr server reload-config
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

HAM reads the legacy `ssh-hosts` allowlist when the new config path does not yet
contain one, and it falls back to legacy cache and request-state directories when
their new counterparts are absent. The old environment variables remain
compatibility fallbacks, but new configuration should use the
`HERDR_AGENT_MESSENGER_*` names documented below. Use the `HAM Skill` screen to
update any previously copied project or system skill before removing the legacy
plugin. The 0.8.0 launcher checks the new plugin ID first and then the legacy ID,
while an unchanged 0.7.x copy knows only the legacy ID.

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

## HAM agent skill

HAM (Herdr Agent Messenger) lets Codex or Claude route requests without opening
the popup. Address each current recipient as `host/label`:

- `local/yellow-falcon` targets this Herdr server.
- `macbook-pro/purple-koala` targets the concrete `macbook-pro` alias from the
  user's SSH config.

Use the exact Agent Labels value. HAM resolves the label again before every
operation so it does not silently reuse a stale pane occupant. Only the literal
host `local` selects the current server; every other host is treated as SSH.

The packaged skill keeps the canonical name `herdr-agent-messenger` for
compatibility. `HAM` is its shorter user-facing name.

### Install HAM with the plugin

The plugin bundles `.agents/skills/herdr-agent-messenger/SKILL.md` for Codex and
`.claude/skills/herdr-agent-messenger/SKILL.md` for Claude Code. A checkout is
discovered at project scope. To use HAM from every workspace, open `HAM Skill`
from Herdr's command palette and install the Codex or Claude target at `System`
scope. `Project` affects only the active Herdr workspace.

The same installer opens with `Ctrl+G` from Agent Messenger. Press `?` for the
HAM invocation and prompt guide. Each target carries a compact badge: `✓`
current, `↑` update available, `○` not installed, or `!` conflicting files. The
installer refuses to overwrite an unrelated skill directory with the same name.
Codex normally detects skill changes automatically and Claude Code live-reloads
skills when its watched directory already exists. If HAM does not appear, start
a new agent session.

You can also open the installer from any directory:

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

From the plugin checkout or installed plugin root, print the packaged skill path:

```bash
python3 agent_messenger.py skill-path
```

### Invoke HAM

Codex CLI and the IDE extension use `$` mentions. Type `$ham`, then select
**HAM — Herdr Agent Messenger** from the skill picker. `$ham` is a convenient
search term; the selected skill's canonical name remains
`herdr-agent-messenger`.

Claude Code supports the same skill and can choose it automatically from a
matching natural-language request. Its explicit syntax uses the exact skill
name, so invoke `/herdr-agent-messenger`; `$ham` is not a Claude Code command.

Give the host-qualified target, the task, and what to do with the response:

```text
$ham Ask local/yellow-falcon what language label dxp-ui uses. Wait for the
reply, then align this work and its defaults with that answer.
```

For Claude Code, the equivalent explicit request is:

```text
/herdr-agent-messenger Ask local/yellow-falcon what language label dxp-ui uses.
Wait for the reply, then align this work and its defaults with that answer.
```

Do not write only `yellow-falcon`: another agent host may use the same label,
and an AI client may mistake the bare label for one of its own subagent names.

### Use HAM without the plugin

HAM can run with Herdr without installing or enabling the HAM plugin,
but the current standalone setup is source-backed: the skill wrapper loads its
router modules from a persistent checkout of this repository. Copying only the
skill directory, including via a generic skill installer, is not yet a
self-contained installation.

Clone the source once, then link its Codex and Claude entries into the personal
skill locations. These commands expect the destination links not to exist:

```bash
git clone https://github.com/zerodice0/herdr-agent-labels.git \
  "$HOME/.local/share/ham"
mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
ln -s "$HOME/.local/share/ham/.agents/skills/herdr-agent-messenger" \
  "$HOME/.agents/skills/herdr-agent-messenger"
ln -s "$HOME/.local/share/ham/.claude/skills/herdr-agent-messenger" \
  "$HOME/.claude/skills/herdr-agent-messenger"
```

Update this installation with:

```bash
git -C "$HOME/.local/share/ham" pull --ff-only
```

Plugin-free HAM keeps label-based request, wait, read, and batch routing, but it
does not provide the popup, command-palette installer, automatic `color-animal`
assignment, or the agent-detected event hook. Give each recipient a unique name
yourself before using HAM:

```bash
herdr api snapshot
herdr agent rename <pane-id> yellow-falcon
```

Herdr must be installed and running on the local machine and on every selected
SSH host. Remote hosts must be concrete aliases in `~/.ssh/config`. If the new
skill directories were created after Codex or Claude Code started, restart that
agent session so the directories are discovered.

The bundled helper supports listing and a unified request lifecycle that resolves
the recipient, submits a prompt, safely observes a fresh turn, and returns bounded
new output. Its persisted request ID can be queried later to advance a timed-out
nonterminal observation. Submission failures,
working or settled submissions, and unknown outcomes are kept distinct, so a
timeout is not automatically reported as delivery failure. Lower-level send and
read commands remain available for diagnostics. Use `request-status --request-id`
to advance a saved nonterminal request. The helper also supports compact agent
lists, a single-recipient `status`
lookup, sending with an optional settled-state wait, and bounded incremental
output reads. `list` returns only `address`, `status`, and `workspace` by default;
use `--verbose` (or the compatibility alias `--legacy`) for the complete agent
record. `read --max-bytes` caps UTF-8 output without splitting a character, and
its returned cursor can be supplied to the next `read --cursor` call. Cursors
use snapshot hashes and terminal-tail overlap; if a terminal screen was rewritten
or the overlap is no longer safe, the helper returns a bounded current snapshot
with `cursor_status` set to `expired`. It also supports bounded batch sends of
already-tailored route/message JSON. Batch dispatch preserves input order and
reports each target as
`succeeded`, `submitted`, `failed`, `timeout`, or `cancelled`; it does not perform
semantic decomposition. Waiting batches use the same correlated request lifecycle
per target and return request IDs plus bounded responses. `submitted` means prompt
acceptance was confirmed but settlement was not; a submission timeout whose
acceptance cannot be confirmed remains `timeout`. The helper uses the same SSH
host allowlist location, forwarding protections, host-key policy, and
current-agent verification as the plugin, including in source-backed mode.

The skill is optional for the popup workflow. Coordinator delegation embeds the
installed plugin's executable router path and an opaque route token for every
selected worker in the coordinator request. V2 tokens contain the host, an
occupant fingerprint, and hashed continuity fields rather than raw session IDs or
working directories. Before sending or reading, the router discovers the recorded
local or SSH host again and resolves the exact occupant first. A stale v2 route is
refreshed only for a unique registered label with matching pane, workspace, and
agent kind. Unlabeled and display-only labels additionally require sessionless,
revision, terminal, target, and working-directory continuity; ambiguous or changed
occupants remain `route_expired`. V1 tokens remain readable for exact matches.
`status`, `send`, `read`, and `request` return `route_refreshed` and a current
`route`; callers should
use the returned token for later operations. This also makes unlabeled agents
selected in the GUI addressable without requiring the coordinator to discover
Herdr CLI syntax or install the skill first.

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
`HERDR_AGENT_MESSENGER_SSH_HOSTS_FILE` to use a different allowlist path. The
legacy `HERDR_AGENT_LABELS_SSH_HOSTS_FILE` name remains supported. Herdr
provides the default path through `HERDR_PLUGIN_CONFIG_DIR`; it normally resolves
to `~/.config/herdr/plugins/config/herdr.agent-messenger/ssh-hosts`. When that
file is absent, HAM also checks the former `herdr.agent-labels` config directory.

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

Set `HERDR_AGENT_MESSENGER_SSH_CONFIG` to use a different SSH config file. The
legacy `HERDR_AGENT_LABELS_SSH_CONFIG` name remains supported.
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

## Safe SSH Rollout

`rollout_plugin.py` is a standalone operator helper for installing, migrating,
or updating this plugin on explicitly selected remote Herdr hosts. It accepts
only full 40-character commit SHAs and only concrete SSH aliases authorized by
the same SSH config and optional `ssh-hosts` allowlist used by Agent Messenger.
It never discovers or adds rollout targets on its own.

Preview the exact commands without opening an SSH connection:

```bash
python3 rollout_plugin.py \
  --host macbook-pro \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --dry-run \
  --format json
```

After reviewing the plan, `--confirm` explicitly authorizes the selected hosts'
plugin install/update and server reload:

```bash
python3 rollout_plugin.py \
  --host macbook-pro \
  --host desktop \
  --ref 0123456789abcdef0123456789abcdef01234567 \
  --confirm \
  --format json
```

The default `smoke` profile checks the enabled state, exact GitHub source and
resolved commit, manifest version, `herdr config check`, server config reload,
and the three core plugin actions. Add `--profile full` to also compare SHA-256
hashes for every file tracked by the target commit and run the complete unittest
suite. Herdr currently enables a plugin as part of `plugin install`, with no staged
install option. The helper therefore disables the new install immediately, checks
hashes and runs tests, and only then re-enables it and reloads the server. This
minimizes—but cannot eliminate—the brief interval between install and disable.
Full tests disable bytecode writes.

Before changing a host, the helper records either the current
`herdr.agent-messenger` installation or the legacy `herdr.agent-labels`
installation, including its exact GitHub commit and enabled state. A validated
rollout disables and removes the legacy ID only after the new ID is working. Any
install, migration, or post-install validation failure triggers a best-effort
rollback to the recorded identity and state; if the plugin was previously absent,
the failed installation is removed. Rollback success or failure is included in
that host's result.

The rollout helper updates the Herdr plugin registration, not separately copied
Codex or Claude skill directories. After migrating a host that has a project- or
system-installed 0.7.x skill, open its `HAM Skill` action and update that copy.

Each host is reported independently, and a failure on one host does not stop
later selected hosts. Exit status is `0` only when every selected host passes,
`1` for host-level rollout or validation failures, and `2` for missing approval
or invalid preflight input. The helper reuses the plugin's non-interactive,
forwarding-disabled SSH transport and does not set or replace SSH host-key trust
options.

## Test

```bash
python3 -m unittest -v
```
