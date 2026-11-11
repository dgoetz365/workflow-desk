# Workflow Desk interface

## Purpose and surface

One operational workspace: current equipment, a searchable request queue, a selected request, its decisions, and history. Information needed to approve is adjacent to the action. The public recreation registration reference supplies a plum identity band, precise rows, and compact labels; normal web controls remain normal web controls.

## Tokens

| Token | Value | Use |
| --- | --- | --- |
| Ground | `#f6f5f9` | Page background |
| Surface | `#ffffff` | Queue, form, inventory |
| Detail ground | `#fbfafe` | Request review area |
| Ink | `#252130` | Primary text |
| Muted | `#655f70` | Secondary text |
| Line | `#dedbe6` | Structural separators |
| Shell | `#352344` | Identity band |
| Accent | `#60418c` | Primary action and available-unit ruler |
| Accent dark | `#473067` | Hover and selected text |
| Selection | `#f0eaf8` | Selected request row |
| Success | `#236144` | Return action |
| Error | `#99342f` | Failed action and decline controls |
| Focus | `#b57c05` | Three-pixel keyboard focus ring |
| Radius | `7px` | Principal controls and section boundaries |

Use the platform sans-serif stack. Base body text is 14px with 1.5 line height; the page heading is 27px, section headings 16px, and row metadata 12px. Quantities use tabular numerals. Long entered text wraps; purpose and notes preserve line breaks. No fonts or imagery are fetched.

## Structure and behavior

- A compact 68px header identifies the app and its fictional local context.
- Inventory uses five columns on desktop, three below 800px, and two below 520px. Each item shows free and out quantities plus a proportional segmented ruler.
- The main workspace has a flexible queue and a detail pane of at least 340px at its standard desktop size. Below 800px they stack, and selecting a request brings the detail heading into view.
- The new-request form is an inline section above the queue, with labeled native fields and an explicit close action.
- Requests are real table rows. The borrower name is a button with a descriptive accessible name and pressed state. The selected row has a pale accent fill.
- Status chips always include words: Pending, Approved / out, Declined, Returned. Color is supplementary.
- A live status region explains success, rejection, and connectivity errors. Unconfirmed mutations expose a retry button linked to the original command.

## Motion, accessibility, and validation

Only short background/border changes and a loading placeholder pulse are animated. Reduced motion removes both. Focus rings, skip navigation, semantic labels, a table caption, and time elements are implemented. Contrast and layout choices were inspected in source; no browser-rendered or assistive-technology validation is claimed. Runtime backend and HTTP validation is documented in the README.
