# Popup UI reference

[한국어](ko/ui-reference.md) · English · [README](../README.md)

## Open the messenger

Run **Send Prompt to Agents** from a pane containing an agent. The focused agent
becomes the fixed sender. If no agent is running in the focused pane, HAM shows
an error notification instead of opening the popup.

Local agents appear immediately, sorted by Herdr workspace label. Unicode labels
are preserved and worktree-backed workspaces use a `WT:` prefix. Remote agents
are grouped under their SSH host alias.

## Recipient rows

Interaction and lifecycle indicators are separate:

- `›` keyboard cursor
- `[x]` selected recipient
- `●` working
- `○` idle
- `✓` done
- `!` blocked
- `~` stale

Color is only a redundant cue, so state remains readable in monochrome. Each row
prioritizes the Agent Labels name, workspace, Herdr pane ID, and lifecycle state.
The full session ID remains searchable without taking the main row width.

Long groups keep the host heading visible while scrolling. The recipient heading
shows the visible range when needed. Unavailable remote hosts are summarized;
open the details view to see each alias and its latest error.

## Message editor and layout

The popup grows up to 120 columns by 32 rows and shrinks to fit compact
terminals. Discovered recipients receive most of the available space while at
least four soft-wrapped message rows remain visible when possible. Long messages
follow the text cursor and display a viewport scrollbar.

Shortcut hints wrap instead of clipping on narrow terminals. The popup inherits
Herdr's terminal palette. Lifecycle colors remain reserved for working, done,
blocked, and warning states.

The UI follows `LC_ALL`, `LC_MESSAGES`, or `LANG` and supports English, Japanese,
and Korean. Unsupported locales fall back to English.

## Keyboard controls

- `Up` / `Down`: move through choices, recipients, or message lines
- `Enter`: confirm the highlighted discovery choice
- `D` / `L`: choose remote discovery or local-only
- `C` / `D`: choose coordinator delegation or direct delivery
- `Space`: toggle a recipient
- `Ctrl+A`: select all filtered recipients
- `Ctrl+D`: clear the selection
- `Tab`: switch between recipients and the message editor
- `Ctrl+O`: reopen the delivery mode screen
- `Ctrl+R`: refresh local and authorized remote agents
- `Ctrl+U`: show unavailable remote hosts and their latest errors
- `Ctrl+G`: open the HAM skill installer and guide
- `Ctrl+S`: send the prompt
- `Esc`: go back, cancel pending discovery or sends, then close the popup
