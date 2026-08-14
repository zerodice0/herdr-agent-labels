# Installation and migration

[한국어](ko/migration.md) · English · [README](../README.md)

## New installation

Install and enable HAM from the public GitHub repository:

```bash
herdr plugin install zerodice0/herdr-agent-labels --yes
```

For local development, link a checkout instead:

```bash
herdr plugin link "$PWD" --enabled
```

Existing unnamed agents can be labeled with **Assign Agent Label**. Agents
detected after installation are labeled automatically.

## Migrate from 0.7.x

HAM 0.8.0 changes the plugin ID from `herdr.agent-labels` to
`herdr.agent-messenger`. The repository and install source remain
`zerodice0/herdr-agent-labels`.

For an existing GitHub installation, disable the legacy ID, install the new
version, verify it, and only then remove the legacy registration:

```bash
herdr plugin disable herdr.agent-labels
herdr plugin install zerodice0/herdr-agent-labels --yes
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
herdr plugin uninstall herdr.agent-labels
```

For a local development link, update the checkout and reload Herdr. Local links
are path-backed, so Herdr rereads the 0.8.0 manifest and adopts the new ID
without an unlink/relink cycle:

```bash
git pull --ff-only
herdr config check
herdr server reload-config
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action invoke agent-skill-guide --plugin herdr.agent-messenger
```

## Compatibility behavior

During migration, HAM preserves these fallbacks:

- The legacy `ssh-hosts` allowlist is read when the new config path has no file.
- Legacy discovery cache and request-state directories are used when new state
  does not exist.
- Old `HERDR_AGENT_LABELS_*` variables remain fallbacks; new configuration
  should use `HERDR_AGENT_MESSENGER_*`.
- The 0.8.0 skill wrapper checks `herdr.agent-messenger` first and then the
  legacy plugin ID.

Open **HAM Skill** and update any copied project or system skills before
removing the legacy plugin. An unchanged 0.7.x skill only knows the old ID.

## Verify the final state

```bash
herdr config check
herdr server reload-config
herdr plugin list --plugin herdr.agent-messenger --json
herdr plugin action list --plugin herdr.agent-messenger
```

The final action list should contain `agent-skill-guide`, `label-current`, and
`message-agents`, with only `herdr.agent-messenger` enabled.
