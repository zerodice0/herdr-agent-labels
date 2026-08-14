# HAM agent skill

[한국어](ko/skill-guide.md) · English · [README](../README.md)

HAM lets Codex and Claude Code route prompts to current Herdr agents without
opening the popup. The packaged skill's canonical name is
`herdr-agent-messenger`; **HAM** is its shorter user-facing name.

## Install with the plugin

The plugin bundles these entries:

- `.agents/skills/herdr-agent-messenger` for Codex
- `.claude/skills/herdr-agent-messenger` for Claude Code

A repository checkout is discovered at project scope. To make HAM available in
every workspace, open **HAM Skill** from Herdr's command palette and install the
Codex or Claude target at **System** scope. **Project** affects only the active
Herdr workspace.

The same installer opens with `Ctrl+G` from Agent Messenger. Press `?` for the
invocation guide. Target badges mean:

- `✓` current
- `↑` update available
- `○` not installed
- `!` conflicting files

The installer does not overwrite an unrelated skill directory with the same
name. If a newly installed skill does not appear, start a new agent session.

You can also open the installer from a shell:

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

From a checkout or installed plugin root, print the packaged skill path with:

```bash
python3 agent_messenger.py skill-path
```

## Invoke HAM

Codex CLI and the IDE extension use `$` mentions. Type `$ham`, then select
**HAM — Herdr Agent Messenger** from the skill picker. `$ham` is a search term;
the canonical skill name remains `herdr-agent-messenger`.

Claude Code may choose the skill from a matching natural-language request. Its
explicit syntax is `/herdr-agent-messenger`; `$ham` is not a Claude command.

Always include the exact host-qualified Agent Labels value:

```text
$ham Ask local/yellow-falcon to review the current change. Wait for the reply
and summarize any required follow-up.
```

Only the literal host `local` selects the current Herdr server. Every other host
must be a concrete SSH alias. Do not use a bare label: labels can repeat across
hosts and AI clients can mistake them for their own subagent names.

## Request lifecycle

The bundled helper supports `list`, `status`, `send`, `batch`, `read`, `request`,
and `request-status`. Prefer `request` for normal work: it resolves the current
recipient, submits once, observes a fresh turn, and returns bounded output.

A timed-out but nonterminal request is not automatically a delivery failure.
Keep its request ID and continue with:

```bash
python3 herdr_agent_messenger.py request-status --request-id <request-id>
```

Do not resend while the saved request remains nonterminal. Batch results preserve
input order and report `succeeded`, `submitted`, `failed`, `timeout`, or
`cancelled`. `submitted` confirms prompt acceptance without settlement;
`timeout` means acceptance could not be confirmed.

`list` returns compact `address`, `status`, and `workspace` fields by default.
Use `--verbose` for the complete record. `read` accepts `--max-bytes` and a
returned `--cursor`; an unsafe or rewritten terminal cursor expires and returns
a bounded current snapshot instead of guessing.

## Use HAM without the plugin

HAM can run with Herdr without installing or enabling the plugin. The standalone
setup is source-backed: keep a persistent checkout because the skill wrapper
loads router modules from it. Copying only the skill directory is not yet a
self-contained installation.

```bash
git clone https://github.com/zerodice0/herdr-agent-labels.git \
  "$HOME/.local/share/ham"
mkdir -p "$HOME/.agents/skills" "$HOME/.claude/skills"
ln -s "$HOME/.local/share/ham/.agents/skills/herdr-agent-messenger" \
  "$HOME/.agents/skills/herdr-agent-messenger"
ln -s "$HOME/.local/share/ham/.claude/skills/herdr-agent-messenger" \
  "$HOME/.claude/skills/herdr-agent-messenger"
```

Update it with:

```bash
git -C "$HOME/.local/share/ham" pull --ff-only
```

Plugin-free HAM keeps label-based request, wait, read, and batch routing. It does
not provide the popup, command-palette installer, automatic labels, or the
agent-detected hook. Assign unique names yourself:

```bash
herdr api snapshot
herdr agent rename <pane-id> yellow-falcon
```

Herdr must be installed and running locally and on every selected SSH host.
Remote hosts must be concrete aliases in `~/.ssh/config`.
