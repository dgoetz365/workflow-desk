[Project overview](../README.md)

This guide contains the full walkthrough, implementation details, and limitations. Run commands from the repository root.

# Workflow Desk

A small, working equipment lending app for a fictional community workshop. Review a request beside its history, approve it only when enough equipment is available, and record a return to release that stock.

This is newly written illustrative software, not employer source code. All included people, requests, and workshop inventory are synthetic. There are no external services, frontend packages, tracking scripts, or network-fetched assets.

## Run locally

Requires Python 3.12 or newer, with its standard `sqlite3` module. No package installation is needed. From this repository:

```sh
python app.py seed
python app.py run
```

Open **[http://127.0.0.1:8765](http://127.0.0.1:8765)**. The server prints its URL. It binds only to `127.0.0.1`. Stop with Ctrl+C; SQLite keeps saved changes in `.local/workflow.sqlite3`. Running `seed` again leaves existing inventory and requests untouched.

If the port is occupied, use `python app.py run --port 8766`. For a separate fresh demonstration, seed and run with the same alternate path: `python app.py seed --db .local/fresh.sqlite3`, then `python app.py run --db .local/fresh.sqlite3`. This preserves the original database.

## Try the workflow

Start with a newly seeded database:

1. Select **Mira Chen** in the queue. Her request needs two cordless drills; three are free. Select **Approve request**. Availability becomes one, and an approval appears in the history.
2. Select **Theo Park**, who also requested two drills. Select **Approve request**. The app explains that only one is available. Theo stays pending; no partial reservation or approval event is written.
3. Select **Mira Chen**, optionally enter a return note, and select **Mark all returned**. All three drills are available again.
4. Select **Theo Park** and approve his request. The same capacity check now succeeds.
5. Use **New request** to submit a fictional borrower, equipment, quantity, and purpose. Select it, enter a reason, and choose **Decline**. The history retains the reason without consuming stock.
6. Filter by **Approved / out**, search for a borrower or item, then use **Refresh** to read the current database. Stop and restart the server: your changes remain.

To demonstrate a stale decision, open the same pending request in two tabs. Approve it in one, then try to decline it in the other without refreshing. The second tab receives a conflict, reloads current data, and retains its note for review. It cannot overwrite the saved decision.

If a command loses its server response, the page keeps the original command and exposes **Retry same command**. A saved command is returned without another reservation or history event. Keep the page open while retrying; the browser's unsent form and recovery command are held in memory. Successful command receipts are persisted in SQLite, including across server restarts.

## What the code demonstrates

- **Transactional capacity:** an approval reads active allocations and changes the request inside one SQLite `BEGIN IMMEDIATE` transaction. Two threads cannot both consume the last units.
- **Explicit transitions:** pending → approved → returned, or pending → declined. Return applies to the complete quantity. Pending requests are not reservations.
- **Optimistic concurrency:** each decision carries the request version the reviewer saw. A mismatched version produces HTTP 409 and changes nothing.
- **Idempotent commands:** each command has a unique key and a fingerprint of its contents. An exact retry returns the original result; reusing its key for different content is rejected.
- **Atomic history:** request changes, history events, and the successful command receipt commit together. A failing write rolls everything back.
- **Local browser boundaries:** strict Host and Origin checks, JSON-only writes, a fixed static-file allowlist, parameterized SQL, and a restrictive content security policy. User-entered text is rendered through `textContent` or form values.

The UI uses semantic forms and tables, visible focus, live status messages, text labels alongside status colors, and a responsive queue/detail layout. No browser automation or rendered visual verification was performed for this version; the validation below is backend/HTTP testing plus static frontend checks.

## Tests

```sh
python -m unittest discover -s tests -v
```

The 25 tests use isolated temporary databases and ephemeral loopback ports. They cover concurrent approvals, concurrent exact retries, invalid input, stale versions, illegal transitions, persistence after reopening the database and restarting the HTTP server, rollback after an injected database failure, cross-origin requests, content types, and unsafe file paths. The full suite passed on Python 3.12.14. Optional frontend syntax check: `node --check static/app.js` (Node is not required to run the app).

## Scope and limitations

This is a **single-user, local demonstration**, not a deployed service or a production authorization system. The same operator can enter requests and make decisions. Names identify fictional borrowers, not authenticated accounts. There is no login, role separation, TLS, access review, tamper-proof audit log, backup service, migration framework, inventory editing, date-based booking, partial return, cancellation, or email delivery. Database access can change the history. Local programs can call the JSON API without an Origin header. Do not expose the server through a proxy or public network, and do not enter sensitive or real operational data.

The entire dataset is returned to the local page and command receipts are retained indefinitely, appropriate for a small demo rather than large-scale use. Availability changes when a full request is approved or returned. The page refreshes on explicit refresh and command outcomes; it does not stream changes from other tabs. An exact retry may return an earlier result after a later decision; the page then fetches the current state.

## Project map

| File | Responsibility |
| --- | --- |
| `app.py` | SQLite store, state transitions, HTTP server, and CLI |
| `static/index.html` | Semantic application shell and request form |
| `static/styles.css` | Responsive workspace and visual states |
| `static/app.js` | Queue/detail interactions and safe command recovery |
| `tests/test_app.py` | Behavioral and HTTP integration tests |
| `docs/decisions.md` | Design choices and tradeoffs |
| `PRODUCT.md`, `DESIGN.md` | Product scope and interface conventions |

MIT licensed. See [LICENSE](../LICENSE).
