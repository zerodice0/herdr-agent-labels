# Herdr Agent Labels

Assigns an unused `color-animal` name to every unnamed agent detected by Herdr.
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

## Test

```bash
python3 -m unittest -v
```
