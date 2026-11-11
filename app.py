"""Workflow Desk: a loopback-only, standard-library equipment lending demo."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / ".local" / "workflow.sqlite3"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8")}
KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{8,100}\Z")


class Problem(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def integer(value, label: str, minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= 1000000:
        raise Problem(400, "invalid_input", f"{label} must be a whole number from {minimum} to 1000000.")
    return value


def text_field(value, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise Problem(400, "invalid_input", f"{label} must contain 1 to {maximum} characters.")
    value = value.strip()
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise Problem(400, "invalid_input", f"{label} contains an unsupported control character.")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise Problem(400, "invalid_input", f"{label} contains an invalid Unicode character. Replace it and try again.")
    return value


def unique_object(pairs):
    """Reject ambiguous JSON objects instead of accepting the last duplicate key."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    category TEXT NOT NULL,
                    total INTEGER NOT NULL CHECK(total > 0)
                );
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES items(id),
                    person TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','declined','returned')),
                    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id INTEGER NOT NULL REFERENCES requests(id),
                    action TEXT NOT NULL,
                    note TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    happened_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS commands (
                    command_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    response TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS request_capacity ON requests(item_id, status);
                CREATE INDEX IF NOT EXISTS event_request ON events(request_id, id);
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def transaction(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def seed(self) -> bool:
        """Seed once; never overwrite or reset an existing inventory."""
        with self.transaction() as db:
            if db.execute("SELECT COUNT(*) FROM items").fetchone()[0]:
                return False
            db.executemany("INSERT INTO items(id,name,category,total) VALUES(?,?,?,?)", [
                (1, "Cordless drill", "Woodworking", 3),
                (2, "Camera kit", "Media", 2),
                (3, "Bar clamp", "Woodworking", 8),
                (4, "Sewing machine", "Textiles", 2),
                (5, "Soldering station", "Electronics", 4),
            ])
            examples = [(1, "Mira Chen", "Build a small book stand", 2, "pending"),
                        (1, "Theo Park", "Assemble a planter box", 2, "pending"),
                        (2, "Ada Vale", "Record a stop-motion short", 1, "approved"),
                        (3, "Jules Reed", "Glue a picture frame", 4, "returned")]
            for item_id, person, purpose, quantity, final in examples:
                timestamp = now()
                cursor = db.execute("""INSERT INTO requests
                    (item_id,person,purpose,quantity,status,version,created_at,updated_at)
                    VALUES(?,?,?,?,'pending',1,?,?)""",
                    (item_id, person, purpose, quantity, timestamp, timestamp))
                request_id = cursor.lastrowid
                self.event(db, request_id, "requested", "Synthetic demo request.", 1)
                if final != "pending":
                    db.execute("UPDATE requests SET status='approved',version=2 WHERE id=?", (request_id,))
                    self.event(db, request_id, "approved", "Synthetic demo approval.", 2)
                if final == "returned":
                    db.execute("UPDATE requests SET status='returned',version=3 WHERE id=?", (request_id,))
                    self.event(db, request_id, "returned", "Synthetic demo return.", 3)
        return True

    @staticmethod
    def event(db, request_id: int, action: str, note: str, version: int):
        db.execute("INSERT INTO events(request_id,action,note,version,happened_at) VALUES(?,?,?,?,?)",
                   (request_id, action, note, version, now()))

    @staticmethod
    def request(db, request_id: int) -> dict:
        row = db.execute("""SELECT r.*, i.name AS item_name FROM requests r
                            JOIN items i ON i.id=r.item_id WHERE r.id=?""", (request_id,)).fetchone()
        if row is None:
            raise Problem(404, "not_found", "This request no longer exists. Refresh the workspace.")
        return dict(row)

    def state(self) -> dict:
        with self.connection() as db:
            # One read transaction keeps availability, requests and events on one snapshot.
            db.execute("BEGIN")
            try:
                items = [dict(row) for row in db.execute("""
                    SELECT i.*, COALESCE(SUM(CASE WHEN r.status='approved' THEN r.quantity ELSE 0 END),0) AS held
                    FROM items i LEFT JOIN requests r ON r.item_id=i.id GROUP BY i.id ORDER BY i.id
                """)]
                for item in items:
                    item["available"] = item["total"] - item["held"]
                requests = [dict(row) for row in db.execute("""SELECT r.*,i.name AS item_name
                    FROM requests r JOIN items i ON i.id=r.item_id ORDER BY r.id DESC""")]
                events = [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id DESC")]
                return {"items": items, "requests": requests, "events": events, "read_at": now()}
            finally:
                db.rollback()

    def command(self, body: dict) -> dict:
        if not isinstance(body, dict) or set(body) != {"command_id", "operation", "payload"}:
            raise Problem(400, "invalid_input", "Send command_id, operation, and payload.")
        key, operation, payload = body["command_id"], body["operation"], body["payload"]
        if not isinstance(key, str) or not KEY_PATTERN.fullmatch(key):
            raise Problem(400, "invalid_input", "Command ID must be 8 to 100 letters, digits, underscores, or hyphens.")
        if operation not in ("create", "approve", "decline", "return") or not isinstance(payload, dict):
            raise Problem(400, "invalid_input", "Choose create, approve, decline, or return with a payload object.")
        fingerprint = hashlib.sha256(json.dumps([operation, payload], sort_keys=True, ensure_ascii=True,
                                                separators=(",", ":")).encode()).hexdigest()
        with self.transaction() as db:
            prior = db.execute("SELECT * FROM commands WHERE command_id=?", (key,)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise Problem(409, "key_reused", "This command ID belongs to a different action. Start a new action.")
                result = json.loads(prior["response"])
                result["replayed"] = True
                return result
            if operation == "create":
                request_id = self.create_request(db, payload)
            else:
                request_id = self.transition(db, operation, payload)
            result = {"request": self.request(db, request_id), "replayed": False}
            db.execute("INSERT INTO commands(command_id,fingerprint,response,created_at) VALUES(?,?,?,?)",
                       (key, fingerprint, json.dumps(result), now()))
            return result

    def create_request(self, db, payload: dict) -> int:
        if set(payload) != {"item_id", "person", "purpose", "quantity"}:
            raise Problem(400, "invalid_input", "A request needs item_id, person, purpose, and quantity.")
        item_id = integer(payload["item_id"], "Item ID")
        quantity = integer(payload["quantity"], "Quantity")
        person = text_field(payload["person"], "Borrower name", 80)
        purpose = text_field(payload["purpose"], "Purpose", 240)
        item = db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        if not item:
            raise Problem(404, "not_found", "Choose an item in the current inventory.")
        if quantity > item["total"]:
            raise Problem(400, "invalid_input", f"This workshop owns {item['total']} units. Reduce the quantity.")
        timestamp = now()
        request_id = db.execute("""INSERT INTO requests
            (item_id,person,purpose,quantity,status,version,created_at,updated_at)
            VALUES(?,?,?,?,'pending',1,?,?)""", (item_id, person, purpose, quantity, timestamp, timestamp)).lastrowid
        self.event(db, request_id, "requested", "Request entered in the local workspace.", 1)
        return request_id

    def transition(self, db, operation: str, payload: dict) -> int:
        if set(payload) != {"request_id", "expected_version", "note"}:
            raise Problem(400, "invalid_input", "A decision needs request_id, expected_version, and note.")
        request_id = integer(payload["request_id"], "Request ID")
        expected = integer(payload["expected_version"], "Expected version")
        note = payload["note"]
        if not isinstance(note, str) or len(note.strip()) > 240:
            raise Problem(400, "invalid_input", "Decision note must be text of up to 240 characters.")
        note = text_field(note, "Decision note", 240) if note.strip() else ""
        if operation == "decline" and not note:
            raise Problem(400, "invalid_input", "Add a short reason before declining this request.")
        request = self.request(db, request_id)
        if request["version"] != expected:
            raise Problem(409, "stale_version", "This request changed in another tab. Refresh, review its history, then decide again.")
        target, required = {"approve": ("approved", "pending"), "decline": ("declined", "pending"),
                            "return": ("returned", "approved")}[operation]
        if request["status"] != required:
            raise Problem(409, "invalid_transition", f"A {request['status']} request cannot be {target}. Refresh to see available actions.")
        if operation == "approve":
            total = db.execute("SELECT total FROM items WHERE id=?", (request["item_id"],)).fetchone()[0]
            held = db.execute("SELECT COALESCE(SUM(quantity),0) FROM requests WHERE item_id=? AND status='approved'",
                              (request["item_id"],)).fetchone()[0]
            available = total - held
            if request["quantity"] > available:
                raise Problem(409, "capacity", f"Only {available} of {total} units are available. Leave this request pending until equipment returns, or decline it with a reason.")
        version = expected + 1
        db.execute("UPDATE requests SET status=?,version=?,updated_at=? WHERE id=? AND version=?",
                   (target, version, now(), request_id, expected))
        defaults = {"approve": "Equipment reserved.", "return": "All equipment received; availability restored."}
        self.event(db, request_id, target, note or defaults.get(operation, ""), version)
        return request_id


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, store: Store):
        self.store = store
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = "WorkflowDesk"

    def log_message(self, format, *args):
        # Avoid logging names, payloads, arbitrary request paths, or terminal controls.
        pass

    def reply(self, status: int, data: bytes, content_type="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        if self.command != "HEAD":
            self.wfile.write(data)

    def json_reply(self, status, body):
        self.reply(status, json.dumps(body, ensure_ascii=True).encode())

    def problem(self, error: Problem):
        # A Windows socket closed with unread incoming bytes can reset before the
        # client receives the error. Drain only small, unambiguous request bodies.
        if self.command == "POST" and not getattr(self, "body_read", False):
            lengths = self.headers.get_all("Content-Length", [])
            if (len(lengths) == 1 and len(lengths[0]) <= 6 and lengths[0].isascii() and lengths[0].isdigit()
                    and int(lengths[0]) <= 65536 and not self.headers.get("Transfer-Encoding")):
                self.connection.settimeout(2)
                try:
                    self.rfile.read(int(lengths[0]))
                except (TimeoutError, OSError):
                    pass
                self.body_read = True
        self.json_reply(error.status, {"error": {"code": error.code, "message": error.message}})

    def check_host(self):
        port = self.server.server_address[1]
        if self.headers.get_all("Host", []) not in ([f"127.0.0.1:{port}"], [f"localhost:{port}"]):
            raise Problem(403, "host", "Use the loopback URL printed by the server.")

    def do_GET(self):
        try:
            self.check_host()
            path = urlsplit(self.path).path
            if path == "/api/state":
                self.json_reply(200, self.server.store.state())
            elif path in STATIC:
                filename, content_type = STATIC[path]
                self.reply(200, (ROOT / "static" / filename).read_bytes(), content_type)
            else:
                raise Problem(404, "not_found", "This route does not exist.")
        except Problem as error:
            self.problem(error)
        except (sqlite3.Error, OSError):
            self.problem(Problem(503, "unavailable", "The local database or application file is unavailable. Check the server, then retry."))
        except ValueError:
            self.problem(Problem(400, "invalid_path", "Use a valid application route."))

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        try:
            self.check_host()
            if self.path != "/api/commands":
                raise Problem(404, "not_found", "This route does not exist.")
            origin = self.headers.get("Origin")
            if origin is not None and origin != f"http://{self.headers['Host']}":
                raise Problem(403, "origin", "Cross-origin writes are not allowed.")
            if len(self.headers.get_all("Origin", [])) > 1 or self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
                raise Problem(403, "origin", "Use this application's own page to submit changes.")
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise Problem(415, "content_type", "Commands require application/json.")
            if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
                raise Problem(400, "body_length", "Send one Content-Length header and no Transfer-Encoding.")
            length = self.headers.get("Content-Length", "")
            if len(length) > 10 or not length.isascii() or not length.isdigit() or not 1 <= int(length) <= 32768:
                raise Problem(413, "body_length", "Command body must contain 1 to 32768 bytes.")
            self.connection.settimeout(5)
            self.body_read = True
            raw = self.rfile.read(int(length))
            if len(raw) != int(length):
                raise Problem(400, "body_length", "The complete command was not received. Retry the same command.")
            try:
                body = json.loads(raw, object_pairs_hook=unique_object,
                                  parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
            except (ValueError, UnicodeError, RecursionError):
                raise Problem(400, "invalid_json", "Send a valid JSON command.") from None
            self.json_reply(200, self.server.store.command(body))
        except Problem as error:
            self.problem(error)
        except sqlite3.OperationalError:
            self.problem(Problem(503, "database_busy", "The database is busy or unavailable. Retry the same command in a moment."))
        except sqlite3.Error:
            self.problem(Problem(500, "database_error", "The change could not be saved and was rolled back. Check the server, then retry."))
        except (TimeoutError, ConnectionError):
            self.close_connection = True

    def do_OPTIONS(self):
        self.problem(Problem(405, "method", "Only same-origin GET and POST requests are supported."))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seed = sub.add_parser("seed", help="Add fictional demo data to an empty database")
    seed.add_argument("--db", type=Path, default=DEFAULT_DB)
    run = sub.add_parser("run", help="Run the loopback-only local application")
    run.add_argument("--db", type=Path, default=DEFAULT_DB)
    run.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    if args.command == "run" and not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        store = Store(args.db)
        if args.command == "seed":
            print("Fictional demo data added." if store.seed() else "Inventory already exists; no data changed.")
            return 0
        with Server(("127.0.0.1", args.port), store) as server:
            print(f"Workflow Desk is running at http://127.0.0.1:{server.server_address[1]}", flush=True)
            print("Local demonstration only. Press Ctrl+C to stop.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nStopped. Your changes remain in the local database.")
        return 0
    except (OSError, sqlite3.Error) as error:
        print(f"Could not start Workflow Desk: {error}. Check the database location or choose another port.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
