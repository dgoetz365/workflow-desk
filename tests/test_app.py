"""Behavior and HTTP integration tests; no dependencies and no browser required."""

import concurrent.futures
import http.client
import json
import queue
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from app import Problem, Server, Store


def command(operation, payload, key=None):
    return {"command_id": key or str(uuid.uuid4()), "operation": operation, "payload": payload}


def decision(request_id, version=1, note=""):
    return {"request_id": request_id, "expected_version": version, "note": note}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "desk.sqlite3"
        self.store = Store(self.path)
        self.store.seed()

    def create(self, **overrides):
        payload = {"item_id": 1, "person": "Rowan Lane", "purpose": "Build a display", "quantity": 1}
        payload.update(overrides)
        return self.store.command(command("create", payload))["request"]

    def assert_problem(self, code, function, *args):
        with self.assertRaises(Problem) as result:
            function(*args)
        self.assertEqual(code, result.exception.code)

    def test_pending_does_not_hold_stock_and_seed_is_non_destructive(self):
        self.assertEqual(3, self.store.state()["items"][0]["available"])
        self.create(quantity=3)
        self.assertEqual(3, self.store.state()["items"][0]["available"])
        self.assertFalse(self.store.seed())
        self.assertEqual(5, len(self.store.state()["requests"]))

    def test_approve_return_restores_exact_capacity_and_retains_history(self):
        approved = self.store.command(command("approve", decision(1)))["request"]
        self.assertEqual(("approved", 2), (approved["status"], approved["version"]))
        self.assertEqual(1, self.store.state()["items"][0]["available"])
        returned = self.store.command(command("return", decision(1, 2, "Both units received")))["request"]
        self.assertEqual(("returned", 3), (returned["status"], returned["version"]))
        state = self.store.state()
        self.assertEqual(3, state["items"][0]["available"])
        self.assertEqual(["returned", "approved", "requested"], [event["action"] for event in state["events"] if event["request_id"] == 1])
        self.assertEqual("Both units received", state["events"][0]["note"])

    def test_decline_requires_reason_and_does_not_change_stock(self):
        self.assert_problem("invalid_input", self.store.command, command("decline", decision(1)))
        result = self.store.command(command("decline", decision(1, note="Project postponed")))
        self.assertEqual("declined", result["request"]["status"])
        self.assertEqual(3, self.store.state()["items"][0]["available"])

    def test_capacity_failure_has_no_partial_changes(self):
        self.store.command(command("approve", decision(1)))
        before = self.store.state()
        self.assert_problem("capacity", self.store.command, command("approve", decision(2)))
        after = self.store.state()
        for key in ("items", "requests", "events"):
            self.assertEqual(before[key], after[key])

    def test_stale_version_precedes_transition_and_never_rewrites_history(self):
        self.store.command(command("approve", decision(1)))
        self.assert_problem("stale_version", self.store.command, command("decline", decision(1, note="Old tab")))
        self.assert_problem("stale_version", self.store.command, command("return", decision(1)))
        request = next(row for row in self.store.state()["requests"] if row["id"] == 1)
        self.assertEqual(("approved", 2), (request["status"], request["version"]))

    def test_invalid_transition_rejected(self):
        self.assert_problem("invalid_transition", self.store.command, command("return", decision(1)))
        self.assert_problem("invalid_transition", self.store.command, command("approve", decision(4, 3)))

    def test_exact_repeat_returns_original_result_even_after_later_change(self):
        original = command("approve", decision(1))
        result = self.store.command(original)
        self.store.command(command("return", decision(1, 2)))
        repeated = self.store.command(original)
        self.assertTrue(repeated["replayed"])
        self.assertEqual(result["request"], repeated["request"])
        self.assertEqual(3, len([event for event in self.store.state()["events"] if event["request_id"] == 1]))

    def test_command_id_cannot_be_reused_with_different_payload(self):
        original = command("approve", decision(1))
        self.store.command(original)
        self.assert_problem("key_reused", self.store.command, command("approve", decision(2), original["command_id"]))

    def test_simultaneous_approvals_never_overbook(self):
        barrier = threading.Barrier(2)
        def approve(request_id):
            barrier.wait(timeout=5)
            try:
                self.store.command(command("approve", decision(request_id)))
                return "approved"
            except Problem as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(approve, [1, 2]))
        self.assertCountEqual(["approved", "capacity"], outcomes)
        self.assertEqual(1, self.store.state()["items"][0]["available"])

    def test_simultaneous_identical_commands_save_once(self):
        original = command("create", {"person": "Robin Vale", "item_id": 2, "purpose": "Animation", "quantity": 1})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: self.store.command(original), range(6)))
        self.assertEqual(1, len({result["request"]["id"] for result in results}))
        self.assertEqual(1, sum(not result["replayed"] for result in results))
        self.assertEqual(5, len(self.store.state()["requests"]))

    def test_event_failure_rolls_back_new_request_and_command_receipt(self):
        before = self.store.state()
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'injected event failure'); END")
        pending = command("create", {"person": "Robin Vale", "item_id": 2, "purpose": "Animation", "quantity": 1})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.command(pending)
        with self.store.connection() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM commands").fetchone()[0])
            db.execute("DROP TRIGGER fail_event")
        after = self.store.state()
        self.assertEqual(before["requests"], after["requests"])
        self.assertEqual(before["events"], after["events"])
        self.assertFalse(self.store.command(pending)["replayed"])

    def test_event_failure_rolls_back_approval_and_capacity(self):
        before = self.store.state()
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'injected event failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.command(command("approve", decision(1)))
        after = self.store.state()
        for key in ("items", "requests", "events"):
            self.assertEqual(before[key], after[key])

    def test_restart_preserves_decision_and_idempotency_receipt(self):
        original = command("approve", decision(1))
        result = self.store.command(original)
        reopened = Store(self.path)
        self.assertEqual(1, reopened.state()["items"][0]["available"])
        replay = reopened.command(original)
        self.assertTrue(replay["replayed"])
        self.assertEqual(result["request"], replay["request"])

    def test_input_validation_and_sql_text_remains_data(self):
        for quantity in (0, -1, 1.5, True, "2", 4):
            with self.assertRaises(Problem):
                self.create(quantity=quantity)
        for person in ("", "  ", "x" * 81, None, "null\x00byte"):
            with self.assertRaises(Problem):
                self.create(person=person)
        name = "<img src=x onerror=alert(1)>'); DROP TABLE items;--"
        request = self.create(person=name)
        self.assertEqual(name, request["person"])
        self.assertEqual(5, len(self.store.state()["items"]))
        with self.assertRaises(Problem):
            self.create(item_id=999)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "http.sqlite3"
        self.store = Store(self.path)
        self.store.seed()
        self.start_server()
        self.addCleanup(self.cleanup)

    def start_server(self):
        self.server = Server(("127.0.0.1", 0), self.store)
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def cleanup(self):
        self.stop_server()
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def post(self, body, headers=None):
        status, response_headers, raw = self.request("POST", "/api/commands", json.dumps(body),
            {"Content-Type": "application/json", "Origin": self.origin, **(headers or {})})
        return status, response_headers, json.loads(raw)

    def test_static_assets_and_security_headers(self):
        for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"), ("/styles.css", "text/css")):
            status, headers, body = self.request("GET", path)
            self.assertEqual(200, status)
            self.assertIn(mime, headers["Content-Type"])
            self.assertEqual("nosniff", headers["X-Content-Type-Options"])
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            self.assertTrue(body)

    def test_http_create_approve_replay_return(self):
        status, _, data = self.post(command("create", {"person": "Rowan Lane", "item_id": 4, "purpose": "Sew a bag", "quantity": 2}))
        self.assertEqual(200, status)
        request_id = data["request"]["id"]
        original = command("approve", decision(request_id))
        self.assertEqual(200, self.post(original)[0])
        self.assertTrue(self.post(original)[2]["replayed"])
        stale = self.post(command("decline", decision(request_id, note="Old tab")))
        self.assertEqual((409, "stale_version"), (stale[0], stale[2]["error"]["code"]))
        self.assertEqual(200, self.post(command("return", decision(request_id, 2)))[0])
        _, _, raw = self.request("GET", "/api/state")
        self.assertEqual(2, json.loads(raw)["items"][3]["available"])

    def test_concurrent_http_reservations_have_one_winner(self):
        barrier = threading.Barrier(2)
        def approve(request_id):
            barrier.wait(timeout=5)
            return self.post(command("approve", decision(request_id)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(approve, [1, 2]))
        self.assertCountEqual([200, 409], [result[0] for result in outcomes])
        conflict = next(result for result in outcomes if result[0] == 409)
        self.assertEqual("capacity", conflict[2]["error"]["code"])
        self.assertEqual(1, self.store.state()["items"][0]["available"])

    def test_cross_origin_and_rebinding_hosts_are_rejected(self):
        original = command("approve", decision(1))
        for origin in ("https://example.invalid", "null", "http://localhost:9999", self.origin + "/"):
            with self.subTest(origin=origin):
                self.assertEqual(403, self.post(original, {"Origin": origin})[0])
        self.assertEqual(403, self.post(original, {"Sec-Fetch-Site": "cross-site"})[0])
        self.assertEqual(403, self.post(original, {"Host": "example.invalid"})[0])
        self.assertEqual(403, self.request("GET", "/api/state", headers={"Host": "example.invalid"})[0])
        self.assertEqual(405, self.request("OPTIONS", "/api/commands")[0])
        self.assertEqual(3, self.store.state()["items"][0]["available"])

    def test_cli_client_without_origin_can_write_json(self):
        status, _, _ = self.request("POST", "/api/commands", json.dumps(command("approve", decision(1))), {"Content-Type": "application/json"})
        self.assertEqual(200, status)

    def test_traversal_and_private_file_paths_are_never_served(self):
        for path in ("/../app.py", "/%2e%2e/app.py", "/static/../app.py", "/app.py", "/.local/workflow.sqlite3", "/README.md", "/docs/decisions.md", "/.impeccable/surfaces/workspace.md"):
            with self.subTest(path=path):
                self.assertEqual(404, self.request("GET", path)[0])

    def test_malformed_and_oversized_requests_are_rejected(self):
        for raw in ("not-json", "null", "[]", '{"command_id":"invalid-key","operation":"approve","payload":{"request_id":NaN}}',
                    '{"command_id":"duplicate-key","operation":"approve","operation":"decline","payload":{}}'):
            with self.subTest(raw=raw):
                self.assertEqual(400, self.request("POST", "/api/commands", raw, {"Content-Type": "application/json"})[0])
        self.assertEqual(415, self.request("POST", "/api/commands", "{}", {"Content-Type": "text/plain"})[0])
        self.assertEqual(413, self.request("POST", "/api/commands", "x" * 32769, {"Content-Type": "application/json"})[0])

    def test_invalid_unicode_rejected_and_valid_unicode_preserved(self):
        before = self.store.state()
        for name in ("Name\ud800", "\udfff"):
            status, _, response = self.post(command("create", {"person": name, "item_id": 4, "purpose": "Project", "quantity": 1}))
            self.assertEqual(400, status)
            self.assertEqual("invalid_input", response["error"]["code"])
        status, _, response = self.post(command("decline", decision(1, note="Note\ud800")))
        self.assertEqual(400, status)
        self.assertEqual(before["requests"], self.store.state()["requests"])
        status, _, response = self.post(command("create", {"person": "Renée Sol", "item_id": 4, "purpose": "Textile study", "quantity": 1}))
        self.assertEqual(200, status)
        self.assertEqual("Renée Sol", response["request"]["person"])

    def test_http_database_failure_rolls_back_and_same_command_can_retry(self):
        original = command("approve", decision(1))
        with self.store.connection() as db:
            db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'injected event failure'); END")
        self.assertEqual(500, self.post(original)[0])
        self.assertEqual(3, self.store.state()["items"][0]["available"])
        with self.store.connection() as db:
            db.execute("DROP TRIGGER fail_event")
        self.assertEqual(200, self.post(original)[0])
        self.assertEqual(1, self.store.state()["items"][0]["available"])

    def test_http_restart_keeps_changes_and_repeat_receipt(self):
        original = command("approve", decision(1))
        self.assertEqual(200, self.post(original)[0])
        self.stop_server()
        self.store = Store(self.path)
        self.start_server()
        self.assertTrue(self.post(original)[2]["replayed"])
        self.assertEqual(1, self.store.state()["items"][0]["available"])


class CLITests(unittest.TestCase):
    def test_seed_and_run_print_usable_url_and_persist_state(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "cli.sqlite3")
            seed = subprocess.run([sys.executable, str(root / "app.py"), "seed", "--db", database],
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(0, seed.returncode, seed.stderr)
            self.assertIn("Fictional demo data added", seed.stdout)
            process = subprocess.Popen([sys.executable, str(root / "app.py"), "run", "--db", database, "--port", "0"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                lines = queue.Queue()
                reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
                reader.start()
                startup = lines.get(timeout=10)
                match = re.search(r"http://127\.0\.0\.1:(\d+)", startup)
                self.assertIsNotNone(match, startup)
                connection = http.client.HTTPConnection("127.0.0.1", int(match.group(1)), timeout=5)
                try:
                    connection.request("GET", "/api/state")
                    response = connection.getresponse()
                    self.assertEqual(200, response.status)
                    self.assertEqual(5, len(json.loads(response.read())["items"]))
                finally:
                    connection.close()
            finally:
                process.terminate()
                process.wait(timeout=5)
                process.stdout.close()
                process.stderr.close()


if __name__ == "__main__":
    unittest.main()
