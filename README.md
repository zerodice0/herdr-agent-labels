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
open `Install Agent Skill` from Herdr's command palette and select Codex,
Claude, or both. This installs or updates the bundled files under the user's
agent skill directories; start a new agent session afterward. The installer
refuses to overwrite an unrelated skill directory with the same name.

For usage help, open `Agent Skill Guide` from Herdr's command palette, press
`Ctrl+G` inside Agent Messenger, or invoke the guide action from any directory:

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

The bundled helper supports listing, sending with an optional settled-state wait,
and reading recent output. It reuses the plugin's SSH host allowlist, forwarding
protections, host-key policy, and current-agent verification.

After SSH discovery, choose a delivery mode:

- **Delegate through coordinator (default and recommended):** the focused agent
  that opened the popup is the coordinator. The plugin sends that coordinator one
  orchestration request containing the selected worker list and the user's
  original request. It does not send the original request to the selected workers.
  The coordinator performs the semantic task breakdown, sends each worker a
  tailored instruction with Herdr, waits for and verifies their responses, then
  synthesizes the result for the user. The Python plugin deliberately does not try
  to interpret or split the work.
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

Tailscale does not require a special plugin-specific SSH format. Keep a stable,
human-readable SSH alias and point it to either the device's MagicDNS name or
Tailscale IP, for example:

```sshconfig
Host winmini
  HostName winmini.example-tailnet.ts.net
  User your-remote-user
```

The plugin still probes only explicit SSH aliases; it never treats every device
in the tailnet as authorized automatically. When the local `tailscale` CLI can
match an alias destination to a peer, the UI shows both identities, such as
`macbook-pro → MacBook Pro`. Otherwise it shows the SSH alias and configured
destination. This keeps the route stable even if the friendly device name
contains spaces or non-ASCII characters.

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
- `Ctrl+G`: show the bundled Agent Messenger skill guide
- `Ctrl+S`: send the prompt
- `Esc`: go back from delivery mode, cancel discovery or pending sends, then close
  the popup

The UI follows `LC_ALL`, `LC_MESSAGES`, or `LANG` and supports English, Japanese,
and Korean. Unsupported locales fall back to English.

## Test

```bash
python3 -m unittest -v
```
