# Implementation decisions

## Approval is the reservation boundary

A pending request expresses demand without holding equipment. Approving a request reserves the entire quantity. Returning it releases the entire quantity. This makes capacity explainable using one invariant:

`available = item.total - sum(quantity of approved requests for that item)`

There is no independently maintained availability counter to drift out of sync. The interface shows both current free units and the expected remainder before approval. Requests can exceed currently free stock, but never the total owned quantity. A request can wait pending until equipment returns.

## Serialize writers, detect stale reviewers

Every command begins with `BEGIN IMMEDIATE`. SQLite obtains the writer reservation before reading availability or the current request version, so competing writers do not approve from the same stale capacity snapshot. The busy timeout provides a bounded wait; the HTTP layer returns a retryable error if the database remains unavailable.

Database serialization and reviewer freshness solve different problems. Each request also has a monotonically increasing version. The browser sends the version it displayed. A conflict reloads the latest workspace while preserving the decision note. The reviewer must assess the latest state and choose again.

Reads use one transaction for inventory, requests, and events. A response therefore represents a coherent SQLite snapshot even if another command commits concurrently.

## Commands have durable receipts

The browser generates a random UUID for each new action. SQLite stores the key, a SHA-256 fingerprint of the operation and payload, and the original response. Identical retries return that response and set `replayed: true`. A different payload under the same key is a conflict.

The receipt is inserted in the same transaction as the state change and history event. There is no interval where the reservation is committed without its receipt. The event table is deliberately local history, not an authenticated security audit log.

Only successful commands have receipts. A rejected capacity decision can be tried after stock is returned. A stale request still needs a current expected version and a new command. Server failures roll back and may be retried using the same key. The page keeps an uncertain command in memory and blocks new actions until it can resolve that command. Reloading the page loses that in-memory recovery context, so the README explicitly advises keeping it open.

## Small stack, explicit boundaries

Python's HTTP server and SQLite minimize setup and make the transaction logic readable. The threaded server is useful for demonstrating competing commands. It is not a production serving stack. Only loopback binding is exposed through the CLI, and the Host header must match loopback plus the actual port.

The server accepts JSON writes, rejects cross-origin browser requests and preflight, and permits local CLI clients without an Origin header. These browser boundaries are not authentication. A local program can act as the operator. A hardcoded static route allowlist prevents traversal and prevents accidental exposure of the database or source files.

No HTML is constructed from input strings. The page uses DOM creation, `textContent`, and form values. A content security policy disallows inline scripts, plugins, foreign resources, framing, and foreign form submissions. SQL uses bound parameters.

## Task-focused interface

The queue and details stay visible together on wider screens; narrow screens stack them. Selecting a row moves focus to the detail heading. Inventory quantities are text first; the small segmented ruler reinforces available versus allocated units. Search and status filters change the queue; the selected request can remain visible in the detail pane when filtered out so an in-progress review is not discarded.

A request form expands in the page instead of interrupting the review with a modal. Errors name a recovery path. Decisions and their history share a panel. Synthetic-data and local-only labels remain visible. The UI intentionally avoids charts and totals that do not help decide a request.

## Verification and deliberate omissions

Tests exercise concurrent writers and repeated commands at both the store and HTTP boundaries, not just pure functions. Injected SQLite triggers force event writes to fail, proving that request changes and receipts roll back. Separate tests reopen the database and restart the HTTP server before retrying a saved command.

No browser tooling was used. Frontend verification is limited to syntax and static inspection; responsive rendering and assistive-technology behavior still require manual evaluation. Dates, identities, notifications, inventory maintenance, deletion, distributed deployment, backups, and migrations are outside this demonstration's scope. A real service would need a fresh threat model, authenticated authorization, an appropriate server stack, operational controls, and product requirements for those features.
