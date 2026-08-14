<p align="center">
  <img src="assets/ham-logo.png" alt="HAM — Herdr Agent Messenger mascot logo" width="360">
</p>

# HAM — Herdr Agent Messenger

[한국어](README.ko.md) · English

HAM is an agent-labeling and multi-agent messaging plugin for Herdr. It gives
unnamed agents memorable `color-animal` names and routes prompts to those agents
from a keyboard-first popup, Codex, or Claude Code.

## What HAM provides

- Automatic labels such as `blue-otter` with matching color markers
- Local and SSH agent discovery using concrete aliases from `~/.ssh/config`
- Coordinator delegation and direct multi-recipient delivery
- A bundled `herdr-agent-messenger` skill for Codex and Claude Code
- Safe request, wait, read, batch, and rollout helpers

Manually named agents are left unchanged. Agent addresses are always
host-qualified, for example `local/blue-otter` or
`macbook-pro/purple-koala`.

## Requirements

- Herdr 0.8.0 or newer
- Python 3

## Install

```bash
herdr plugin install zerodice0/herdr-agent-labels --yes
```

The repository name remains `herdr-agent-labels`, while the plugin ID is
`herdr.agent-messenger` and its display name is **HAM**.

For local development:

```bash
herdr plugin link "$PWD" --enabled
```

Upgrading from 0.7.x requires migrating the former `herdr.agent-labels` ID.
Follow the [migration guide](docs/migration.md) before removing the old plugin.

## Use

Open **Send Prompt to Agents** from a Herdr agent pane to select recipients and
choose coordinator delegation or direct delivery.

Codex users can type `$ham` and select **HAM — Herdr Agent Messenger**. Claude
Code users can invoke `/herdr-agent-messenger` or make a matching natural-language
request.

```text
$ham Ask local/yellow-falcon what language label dxp-ui uses. Wait for the
reply, then align this work and its defaults with that answer.
```

Use the exact `host/label` shown by Herdr. A bare label can collide with an agent
on another host or be mistaken for a client's own subagent.

Install or update the bundled skill from **HAM Skill** in Herdr's command
palette, or run:

```bash
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

HAM can also be used with Herdr without enabling the plugin. See the
[skill guide](docs/skill-guide.md#use-ham-without-the-plugin) for the
source-backed standalone setup and its limitations.

## Documentation

| Guide | English | 한국어 |
| --- | --- | --- |
| Skill installation and prompting | [Skill guide](docs/skill-guide.md) | [스킬 가이드](docs/ko/skill-guide.md) |
| Installation and 0.7.x migration | [Migration](docs/migration.md) | [마이그레이션](docs/ko/migration.md) |
| SSH discovery and routing contracts | [SSH and routing](docs/ssh-and-routing.md) | [SSH 및 라우팅](docs/ko/ssh-and-routing.md) |
| Popup behavior and keyboard controls | [UI reference](docs/ui-reference.md) | [UI 참고서](docs/ko/ui-reference.md) |
| Safe remote deployment | [Rollout](docs/rollout.md) | [원격 배포](docs/ko/rollout.md) |

## Test

```bash
python3 -m unittest -v
```
