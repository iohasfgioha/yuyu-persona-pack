import contextlib
import copy
import importlib.util
import io
import hashlib
import shutil
import urllib.error
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("manage_under_test", ROOT / "tools/manage.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
MANIFEST = m.read_json(ROOT / "settings/pack.json")
ORIGIN = "test:FriendMessage:123456"


def fixture_config():
    return {
        "agent_runner": {"runner_type": "local", "config": {"persona": {"persona_id": "default"}, "model": {"provider_id": "existing-model"}}},
        "platform_settings": {"segmented_reply": {"enable": False, "only_llm_result": True,
            "split_mode": "regex", "regex": ".+", "interval_method": "random", "interval": "1.5,3.5",
            "log_base": 2.6, "words_count_threshold": 150, "content_cleanup_rule": ""}, "id_whitelist": [ORIGIN]},
        "provider_settings": {"streaming_response": True}, "provider_tts_settings": {"enable": True, "provider_id": "original-voice"},
        "t2i": True, "plugin_set": ["existing-plugin"],
        "provider": [{"api_key": "FAKE_SECRET_NOT_FOR_DISK", "url": "https://example.invalid"}],
        "platform": [{"id": "test", "token": "FAKE_QQ_TOKEN"}],
    }


class FakeApi:
    base = "http://127.0.0.1:6185"

    def __init__(self):
        self.configs = {"default": fixture_config()}
        self.names = {"default": "Default"}
        self.mapping = {"test::": "default", "other::": "default"}
        self.personas = {}
        self.rules = {}
        self.writes = []
        self.calls = []
        self.fail_after = None
        self.seen = [ORIGIN]
        self.plugins = []

    def call(self, method, endpoint, body=None):
        parsed = urlsplit(endpoint)
        path, query = unquote(parsed.path), parse_qs(parsed.query)
        self.calls.append((method, path))
        if method == "GET":
            if path == "/sessions/active-umos":
                return {"umos": self.seen}
            if path == "/plugins":
                return copy.deepcopy(self.plugins)
            if path == "/personas":
                return copy.deepcopy(list(self.personas.values()))
            if path.startswith("/personas/"):
                raise m.ApiError(method, path, 400)  # actual upstream missing-persona response
            if path == "/stats/version":
                return {"version": "4.29.3"}
            if path == "/config-profiles":
                return {"info_list": [{"id": k, "name": self.names[k]} for k in self.configs]}
            if path.startswith("/config-profiles/"):
                return {"config": copy.deepcopy(self.configs[path.split("/")[-1]])}
            if path == "/config-routes":
                return {"routing": copy.deepcopy(self.mapping)}
            if path == "/sessions/rules":
                rows = [{"umo": origin, "rules": {m.RULE_KEY: copy.deepcopy(value)}} for origin, value in self.rules.items()
                        if query.get("search", [""])[0] in origin]
                page, size = int(query.get("page", [1])[0]), int(query.get("page_size", [100])[0])
                return {"rules": rows[(page-1)*size:page*size], "total": len(rows)}
            raise AssertionError((method, path))
        self.writes.append((method, path, copy.deepcopy(body)))
        result = {}
        if path == "/plugins/enabled" and method == "PATCH":
            next(p for p in self.plugins if p["name"] == body["plugin_id"])["activated"] = body["enabled"]
        elif path == "/personas" and method == "POST":
            if body["persona_id"] in self.personas:
                raise m.PackError("duplicate persona")
            self.personas[body["persona_id"]] = {**body, "system_prompt": body["system_prompt"].strip()}
        elif path == "/config-profiles" and method == "POST":
            key = "abconf_" + str(len(self.configs))
            self.configs[key] = copy.deepcopy(body["config"])
            self.names[key] = body["name"]
            result = {"conf_id": key}
        elif path == "/config-routes" and method == "PUT":
            self.mapping = copy.deepcopy(body["routing"])
        elif path == "/sessions/rules" and method == "POST":
            self.rules[body["umo"]] = copy.deepcopy(body["rule_value"])
        elif path == "/sessions/rules/delete" and method == "POST":
            assert body["rule_key"] == m.RULE_KEY
            self.rules.pop(body["umo"], None)
        else:
            raise AssertionError((method, path))
        if self.fail_after == path:
            self.fail_after = None
            raise m.PackError("simulated timeout after server write")
        return result


class ManageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = Path(self.temp.name) / ".local"
        self.local_patch = patch.object(m, "LOCAL", self.local)
        self.local_patch.start()
        self.api = FakeApi()

    def tearDown(self):
        self.local_patch.stop()
        self.temp.cleanup()

    def install(self, **kwargs):
        # File integrity is tested independently; operation tests don't require rebuilt hashes after each code edit.
        with patch.object(m, "verify_files", return_value={"checked_files": 28, "warnings": []}):
            return m.install(self.api, MANIFEST, ORIGIN, **kwargs)

    def state(self):
        return m.read_json(m.state_path(self.api.base, ORIGIN))

    def test_install_normalizes_persona_and_does_not_get_missing_persona(self):
        result = self.install()
        self.assertTrue(result["ok"])
        self.assertEqual(result["verification_scope"], "configuration")
        self.assertFalse(any(path.startswith("/personas/") for _, path in self.api.calls))
        self.assertEqual(self.api.personas[MANIFEST["persona_id"]]["system_prompt"], self.state()["prompt"])

    def test_existing_equivalent_prompt_with_outer_whitespace_is_reused(self):
        prompt = (ROOT / MANIFEST["persona_file"]).read_text(encoding="utf-8")
        self.api.personas[MANIFEST["persona_id"]] = {"persona_id": MANIFEST["persona_id"], "system_prompt": "\n" + prompt + "\n"}
        self.install()
        self.assertFalse(any(p == "/personas" for _, p, _ in self.api.writes))

    def test_existing_different_persona_stops_without_writes(self):
        self.api.personas[MANIFEST["persona_id"]] = {"persona_id": MANIFEST["persona_id"], "system_prompt": "user customization"}
        with self.assertRaises(m.PackError):
            self.install()
        self.assertEqual(self.api.writes, [])

    def test_plan_and_cancel_do_not_write_backend_or_state(self):
        self.assertEqual(self.install(dry_run=True)["status"], "planned")
        self.assertEqual(self.install(confirm=lambda _: False)["status"], "cancelled")
        self.assertEqual(self.api.writes, [])
        self.assertFalse(m.state_path(self.api.base, ORIGIN).exists())

    def test_original_connections_and_profile_untouched_no_credentials_saved(self):
        before = copy.deepcopy(self.api.configs["default"])
        self.install()
        self.assertEqual(self.api.configs["default"], before)
        target = self.api.configs[self.state()["profile_id"]]
        for key in ("provider", "platform", "plugin_set"):
            self.assertEqual(target[key], before[key])
        saved = m.state_path(self.api.base, ORIGIN).read_text(encoding="utf-8")
        self.assertNotIn("FAKE_SECRET", saved)
        self.assertNotIn("FAKE_QQ_TOKEN", saved)
        self.assertNotIn("provider\":", saved)

    def test_exact_route_precedes_existing_wildcard(self):
        self.install()
        self.assertEqual(list(self.api.mapping)[0], ORIGIN)
        self.assertEqual(m.matching_profile(self.api.mapping, ORIGIN), self.state()["profile_id"])
        self.assertEqual(m.matching_profile(self.api.mapping, "test:FriendMessage:999"), "default")

    def test_session_override_sets_persona_without_modifying_history(self):
        self.api.rules[ORIGIN] = {"persona_id": "old-role", "llm_enabled": True, "custom_name": "keep"}
        self.install()
        self.assertEqual(self.api.rules[ORIGIN]["persona_id"], MANIFEST["persona_id"])
        self.assertEqual(self.api.rules[ORIGIN]["custom_name"], "keep")
        self.assertFalse(any("conversation" in p for _, p in self.api.calls))

    def test_repeat_install_is_read_only(self):
        self.install()
        count = len(self.api.writes)
        self.assertEqual(self.install()["status"], "already_installed")
        self.assertEqual(len(self.api.writes), count)

    def test_manual_change_rejected_on_repeat(self):
        self.install()
        self.api.rules[ORIGIN]["persona_id"] = "custom"
        count = len(self.api.writes)
        with self.assertRaises(m.PackError):
            self.install()
        self.assertEqual(len(self.api.writes), count)

    def test_restore_and_reinstall(self):
        before = copy.deepcopy(self.api.mapping)
        self.install()
        m.restore(self.api, self.state())
        self.assertEqual(list(self.api.mapping.items()), list(before.items()))
        self.assertNotIn(ORIGIN, self.api.rules)
        self.assertEqual(self.state()["status"], "restored")
        self.assertEqual(m.restore(self.api, self.state())["status"], "already_restored")
        self.assertTrue(self.install()["ok"])

    def test_restore_preserves_later_unrelated_changes(self):
        self.api.rules[ORIGIN] = {"persona_id": "old", "custom_name": "before", "tts_enabled": True}
        self.install()
        self.api.rules[ORIGIN]["custom_name"] = "changed later"
        self.api.mapping["new::*"] = "default"
        m.restore(self.api, self.state())
        self.assertEqual(self.api.rules[ORIGIN], {"persona_id": "old", "custom_name": "changed later", "tts_enabled": True})
        self.assertIn("new::*", self.api.mapping)

    def test_restore_conflict_does_not_partially_revert_other_fields(self):
        self.install()
        self.api.rules[ORIGIN]["persona_id"] = "changed"
        before = copy.deepcopy(self.api.mapping)
        count = len(self.api.writes)
        with self.assertRaises(m.PackError):
            m.restore(self.api, self.state())
        self.assertEqual(self.api.mapping, before)
        self.assertEqual(len(self.api.writes), count)

    def test_restore_detects_changed_target_route(self):
        self.install()
        self.api.mapping[ORIGIN] = "other-profile"
        before = copy.deepcopy(self.api.rules)
        with self.assertRaises(m.PackError):
            m.restore(self.api, self.state())
        self.assertEqual(self.api.rules, before)

    def test_original_exact_route_order_is_restored(self):
        self.api.configs["old"] = fixture_config()
        self.api.names["old"] = "old"
        self.api.mapping = {"other::": "default", ORIGIN: "old", "test::": "default"}
        before = list(self.api.mapping.items())
        self.install()
        m.restore(self.api, self.state())
        self.assertEqual(list(self.api.mapping.items()), before)

    def test_timeouts_after_each_mutation_remain_recoverable(self):
        for endpoint in ("/personas", "/config-profiles", "/config-routes", "/sessions/rules"):
            with self.subTest(endpoint=endpoint), tempfile.TemporaryDirectory() as td, patch.object(m, "LOCAL", Path(td)):
                self.api = FakeApi()
                self.api.fail_after = endpoint
                with self.assertRaises(m.PackError):
                    self.install()
                self.assertEqual(self.state()["status"], "installing")
                m.restore(self.api, self.state())
                self.assertNotIn(ORIGIN, self.api.mapping)
                self.assertNotIn(ORIGIN, self.api.rules)
                self.assertEqual(self.state()["status"], "restored")

    def test_new_version_does_not_silently_upgrade(self):
        self.install()
        state = self.state()
        state["version"] = "older"
        m.save_json(m.state_path(self.api.base, ORIGIN), state)
        with self.assertRaises(m.PackError):
            self.install()

    def test_changed_same_version_manifest_does_not_silently_reuse_old_install(self):
        self.install()
        changed = copy.deepcopy(MANIFEST)
        changed["rhythm"]["log_base"] = 4.0
        with patch.object(m, "verify_files", return_value={"checked_files": 28, "warnings": []}), self.assertRaises(m.PackError):
            m.install(self.api, changed, ORIGIN)

    def test_changes_after_preview_stop_before_write(self):
        def changed(_):
            self.api.configs["default"]["t2i"] = False
            return True
        with self.assertRaises(m.PackError):
            self.install(confirm=changed)
        self.assertEqual(self.api.writes, [])

    def test_wrong_field_type_and_external_runner_stop(self):
        for path, value in (("agent_runner.runner_type", "dify"), ("t2i", "false")):
            with self.subTest(path=path):
                self.api = FakeApi()
                m.path_set(self.api.configs["default"], path, value)
                with self.assertRaises(m.PackError):
                    self.install()
                self.assertEqual(self.api.writes, [])

    def test_disabled_session_stops(self):
        self.api.rules[ORIGIN] = {"llm_enabled": False}
        with self.assertRaises(m.PackError):
            self.install()
        self.assertEqual(self.api.writes, [])

    def test_origin_does_not_expand_scope(self):
        for bad in ("123456", "test:FriendMessage:*", "test::123", "test:FriendMessage:a b"):
            with self.assertRaises(m.PackError):
                m.validate_origin(bad)

    def test_only_loopback_urls_and_no_redirect_paths(self):
        self.assertEqual(m.normalize_url("localhost:6185"), "http://localhost:6185")
        for bad in ("https://example.com", "http://127.0.0.1/foo", "http://user:pass@localhost", "http://localhost?token=x"):
            with self.assertRaises(m.PackError):
                m.normalize_url(bad)

    def test_answers_reject_plaintext_password(self):
        path = Path(self.temp.name) / "answers.json"
        path.write_text(json.dumps({"password": "do-not-share"}))
        args = type("Args", (), {"answers": str(path)})()
        with self.assertRaises(m.PackError):
            m.read_options(args)

    def test_answer_file_relative_secret_path(self):
        path = Path(self.temp.name) / "answers.json"
        path.write_text(json.dumps({"password_file": "password.secret.txt", "origin": ORIGIN}))
        secret_path = path.parent / "password.secret.txt"
        secret_path.write_text("password with spaces \n")
        options = m.read_options(type("Args", (), {"answers": str(path)})())
        self.assertEqual(m.secret(options, "password"), "password with spaces ")

    def test_state_mismatch_stops(self):
        self.install()
        state = self.state()
        state["base"] = "http://localhost:6185"
        with self.assertRaises(m.PackError):
            m.restore(self.api, state)

    def test_lock_stops_concurrent_writes(self):
        with m.mutation_lock():
            with self.assertRaises(m.PackError):
                with m.mutation_lock():
                    pass
        self.assertFalse((self.local / "operation.lock").exists())


    def test_install_and_repeat_keep_actual_preview(self):
        result = self.install()
        self.assertEqual(result["preview"]["origin"], ORIGIN)
        self.assertEqual(result["preview"]["changes"], self.state()["changes"])
        self.assertEqual(self.install()["preview"], result["preview"])
        self.assertNotIn("FAKE_SECRET", json.dumps(result))

    def test_unseen_umo_plan_is_read_only_install_requires_opt_in(self):
        self.api.seen = []
        result = self.install(dry_run=True)
        self.assertFalse(result["plan"]["umo_seen"])
        with self.assertRaises(m.PackError):
            self.install()
        self.assertEqual(self.api.writes, [])
        self.assertFalse(m.state_path(self.api.base, ORIGIN).exists())
        self.assertTrue(self.install(allow_unseen=True)["ok"])

    def test_malformed_seen_response_never_writes(self):
        self.api.seen = "not-a-list"
        with self.assertRaises(m.PackError):
            self.install(allow_unseen=True)
        self.assertEqual(self.api.writes, [])

    def test_cli_plan_remains_available_under_mutation_lock(self):
        output = io.StringIO()
        with m.mutation_lock(), patch.object(m, "Api", return_value=self.api), patch.dict(os.environ, {"YUYU_TEST_TOKEN": "test"}), contextlib.redirect_stdout(output):
            code = m.main(["plan", "--base-url", self.api.base, "--origin", ORIGIN, "--token-env", "YUYU_TEST_TOKEN", "--non-interactive", "--json"])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())["status"], "planned")
        self.assertEqual(self.api.writes, [])

    def test_missing_backend_url_does_not_guess_port_or_connect(self):
        output = io.StringIO()
        with patch.object(m, "Api") as api, contextlib.redirect_stdout(output):
            code = m.main(["inspect", "--non-interactive"])
        self.assertEqual(code, 1)
        self.assertIn("base_url", json.loads(output.getvalue())["error"])
        api.assert_not_called()

    def test_api_error_redacts_umo_and_query(self):
        error = m.ApiError("GET", "/sessions/" + ORIGIN + "?secret=hidden", 403)
        self.assertNotIn(ORIGIN, str(error))
        self.assertNotIn("123456", str(error))
        self.assertNotIn("hidden", str(error))
        self.assertIn("sessions", str(error))

    def test_connection_error_explains_launcher_and_write_ambiguity(self):
        api = m.Api(self.api.base)
        for method, path, ambiguous in [("GET", "/stats/version", False), ("POST", "/auth/login", False), ("PUT", "/config-routes", True)]:
            with self.subTest(path=path), patch.object(api.opener, "open", side_effect=urllib.error.URLError("offline")):
                with self.assertRaises(m.PackError) as error:
                    api.call(method, path)
                self.assertIn("Launcher", str(error.exception))
                self.assertEqual("写入结果可能不明确" in str(error.exception), ambiguous)

    def package_copy(self):
        folder = Path(self.temp.name) / "pack"
        folder.mkdir(exist_ok=True)
        for rel in m.CORE_FILES | {"README.md", "persona/鱼鱼.md", "docs/note.md"}:
            target = folder / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            source = ROOT / rel
            target.write_bytes(source.read_bytes() if source.exists() else b"notes")
        sums = {str(p.relative_to(folder)).replace(os.sep, "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in folder.rglob("*") if p.is_file() and p.name != "SHA256SUMS.json"}
        (folder / "SHA256SUMS.json").write_text(json.dumps(sums), encoding="utf-8")
        return folder

    def test_document_edits_and_missing_chinese_alias_do_not_block_install(self):
        folder = self.package_copy()
        (folder / "README.md").write_text("my notes", encoding="utf-8")
        (folder / "persona/鱼鱼.md").unlink()
        (folder / "docs/note.md").unlink()
        with patch.object(m, "ROOT", folder):
            result = m.install(self.api, MANIFEST, ORIGIN)
            self.assertTrue(result["ok"])
            self.assertEqual(len(result["warnings"]), 3)
            self.assertEqual(len(m.restore(self.api, self.state())["warnings"]), 3)

    def test_every_core_file_is_mandatory_and_unchanged(self):
        folder = self.package_copy()
        with patch.object(m, "ROOT", folder):
            for rel in m.CORE_FILES:
                with self.subTest(path=rel):
                    path = folder / rel
                    original = path.read_bytes()
                    path.write_bytes(original + b"modified")
                    with self.assertRaises(m.PackError):
                        m.verify_files()
                    path.unlink()
                    with self.assertRaises(m.PackError):
                        m.verify_files()
                    path.write_bytes(original)

    def test_manifest_missing_core_and_outside_path_are_rejected(self):
        folder = self.package_copy()
        sums_path = folder / "SHA256SUMS.json"
        original = json.loads(sums_path.read_text())
        for sums in [{k: v for k, v in original.items() if k != "tools/run.ps1"}, {**original, "../outside": "0"*64}]:
            sums_path.write_text(json.dumps(sums))
            with patch.object(m, "ROOT", folder), self.assertRaises(m.PackError):
                m.verify_files()

    def test_restore_checks_integrity_before_any_backend_access(self):
        self.install()
        calls = len(self.api.calls)
        with patch.object(m, "verify_files", side_effect=m.PackError("modified")), self.assertRaises(m.PackError):
            m.restore(self.api, self.state())
        self.assertEqual(len(self.api.calls), calls)

    def test_legacy_inventory_retains_everything_and_redacts_other_umos(self):
        self.api.plugins = [{"name": m.LEGACY_PLUGIN, "activated": True}]
        self.api.personas[m.LEGACY_PERSONA] = {"persona_id": m.LEGACY_PERSONA}
        self.api.configs["default"]["agent_runner"]["config"]["persona"]["persona_id"] = m.LEGACY_PERSONA
        self.api.rules[ORIGIN] = {"persona_id": m.LEGACY_PERSONA}
        result = m.cleanup_legacy(self.api)
        self.assertTrue(result["plugin"]["enabled"])
        self.assertEqual(result["profiles"][0]["route_count"], 2)
        self.assertEqual(result["session_rule_count"], 1)
        self.assertNotIn(ORIGIN, json.dumps(result))
        self.assertEqual(self.api.writes, [])

    def test_legacy_disable_needs_selection_and_confirmation(self):
        self.api.plugins = [{"name": m.LEGACY_PLUGIN, "activated": True}]
        m.cleanup_legacy(self.api, confirm=lambda _: True)
        self.assertEqual(m.cleanup_legacy(self.api, disable_plugin=True)["status"], "cancelled")
        self.assertEqual(self.api.writes, [])
        original = copy.deepcopy(self.api.configs)
        result = m.cleanup_legacy(self.api, disable_plugin=True, confirm=lambda _: True)
        self.assertEqual(result["status"], "legacy_plugin_disabled")
        self.assertFalse(result["plugin"]["enabled"])
        self.assertEqual(self.api.configs, original)
        self.assertEqual(len(self.api.writes), 1)
        self.assertEqual(m.read_json(next((self.local / "legacy").glob("*.json")))["status"], "disabled")

    def test_legacy_disable_network_failure_preserves_recovery_record(self):
        self.api.plugins = [{"name": m.LEGACY_PLUGIN, "activated": True}]
        self.api.fail_after = "/plugins/enabled"
        with self.assertRaises(m.PackError):
            m.cleanup_legacy(self.api, disable_plugin=True, confirm=lambda _: True)
        self.assertEqual(m.read_json(next((self.local / "legacy").glob("*.json")))["status"], "disabling")
        self.assertFalse(m.cleanup_legacy(self.api)["plugin"]["enabled"])
        self.assertEqual(len(self.api.writes), 1)

    def test_http_transport_full_cycle(self):
        backend = self.api
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_api(self):
                path = self.path.removeprefix("/api/v1")
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0")))) if self.headers.get("Content-Length") else None
                if path == "/auth/login":
                    data = {"token": "FAKE_TEST_TOKEN"}
                else:
                    if self.headers.get("Authorization") != "Bearer FAKE_TEST_TOKEN":
                        self.send_error(401)
                        return
                    data = backend.call(self.command, path, body)
                payload = json.dumps({"status": "ok", "data": data}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            do_GET = do_POST = do_PUT = handle_api
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = m.Api(f"http://127.0.0.1:{server.server_port}")
            api.login("tester", "fake-password")
            with patch.object(m, "verify_files", return_value={"checked_files": 28, "warnings": []}):
                result = m.install(api, MANIFEST, ORIGIN)
                self.assertTrue(result["ok"])
                self.assertEqual(m.install(api, MANIFEST, ORIGIN)["status"], "already_installed")
            state = m.read_json(m.state_path(api.base, ORIGIN))
            self.assertEqual(m.restore(api, state)["status"], "restored")
            answers = Path(self.temp.name) / "answers.json"
            credential = Path(self.temp.name) / "password.secret.txt"
            credential.write_text("fake-password", encoding="utf-8")
            answers.write_text(json.dumps({"base_url": api.base, "username": "tester", "password_file": credential.name, "origin": ORIGIN}), encoding="utf-8")
            for action in ("inspect", "plan", "install", "verify", "restore"):
                output = io.StringIO()
                with patch.object(m, "verify_files", return_value={"checked_files": 28, "warnings": []}), contextlib.redirect_stdout(output):
                    code = m.main([action, "--answers", str(answers), "--yes", "--json"])
                self.assertEqual(code, 0, output.getvalue())
                self.assertIsInstance(json.loads(output.getvalue()), dict)
                self.assertNotIn("fake-password", output.getvalue())
                self.assertNotIn("FAKE_TEST_TOKEN", output.getvalue())
                self.assertNotIn("FAKE_SECRET_NOT_FOR_DISK", output.getvalue())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
