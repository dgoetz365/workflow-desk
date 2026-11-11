# Workflow Desk

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Python 3.12 standard library, SQLite, and static HTML/CSS/JavaScript, as specified in the project brief. No frontend dependencies or external assets.

## Users

Brief-backed assumption: a fictional community workshop coordinator reviews equipment requests on a laptop and checks availability on a phone.

## Product Purpose

Make a small equipment lending workflow understandable and reliable: request quantities, approve or decline, record returns, and see a durable history.

## Operating Context

A single-user local portfolio demonstration with synthetic items and people. One browser can submit requests and review them. Multiple tabs and concurrent HTTP requests can demonstrate conflict handling. There is no production identity model.

## Capabilities and Constraints

Inventory availability is consumed by approval and restored by return. Pending requests do not hold stock. Each request has one equipment item and quantity. No dates, partial returns, or inventory editing in this scoped demonstration. SQLite transactions prevent over-allocation. Expected versions prevent stale decisions. Idempotency keys prevent duplicate commands. Writes require a same-origin browser request or a CLI client with no Origin header. Only loopback binding is supported.

## Evidence on Hand

All implementation and demonstration data are newly written and fictional. No customer evidence, historical metrics, identity integrations, external datasets, or imagery are available or claimed.

## Product Principles

- Availability must mean what the application can actually approve.
- Show why a decision failed and how to recover without losing the request.
- Keep review details and the audit trail close to the queue.
- Make every visible control functional.

## Accessibility & Inclusion

Semantic forms, visible labels, keyboard operation, visible focus, status announcements, readable contrast, and responsive structure. Accessibility is implemented in source; no assistive-technology certification is claimed.
