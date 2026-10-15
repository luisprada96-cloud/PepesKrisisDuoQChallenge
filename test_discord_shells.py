"""Unit tests for duo-specific Discord Blue Shell notifications."""
import copy
import io
import json
import os
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import discord_shells
import discord_live
import server
import test_shell_penalties as fixtures


TEST_WEBHOOK_URL_1 = "https://discord.com/api/webhooks/111111111111111111/test_token_duo_1"
TEST_WEBHOOK_URL_2 = "https://discord.com/api/webhooks/222222222222222222/test_token_duo_2"
TEST_ROLE_ID_1 = "111222333444555666"
TEST_ROLE_ID_2 = "999888777666555444"


class DiscordShellsUnitTests(unittest.TestCase):
    def test_webhook_url_validation(self):
        self.assertEqual(discord_shells.webhook_url(TEST_WEBHOOK_URL_1), TEST_WEBHOOK_URL_1)
        self.assertEqual(discord_shells.webhook_url("https://discord.com/api/v10/webhooks/987654/valid_token"), "https://discord.com/api/v10/webhooks/987654/valid_token")
        # Reject non-Discord domains or malformed URLs
        self.assertEqual(discord_shells.webhook_url(""), "")
        self.assertEqual(discord_shells.webhook_url(None), "")
        self.assertEqual(discord_shells.webhook_url("http://discord.com/api/webhooks/123/token"), "")
        self.assertEqual(discord_shells.webhook_url("https://evil.com/api/webhooks/123/token"), "")
        self.assertEqual(discord_shells.webhook_url("https://discord.com/other/path"), "")

    def test_message_shell_received_escaping_and_content(self):
        # Case 1: Without role ID -> @TeamName
        msg = discord_shells.message_shell_received("Equipo *Atacante* <1>", "Equipo _Destino_")
        self.assertIn("ALERTA DE CAPARAZÓN AZUL", msg["content"])
        self.assertIn("Equipo \\*Atacante\\* \\<1\\>", msg["content"])
        self.assertIn("Equipo \\_Destino\\_", msg["content"])
        self.assertIn("@Equipo _Destino_", msg["content"])
        self.assertIn("https://duoqchallenge.luisjourney.xyz/player.html", msg["content"])
        self.assertEqual(msg["allowed_mentions"], {"parse": ["roles", "users", "everyone"]})

        # Case 2: With role ID -> <@&ID>
        msg_role = discord_shells.message_shell_received("Equipo Atacante", "Equipo Destino", TEST_ROLE_ID_2)
        self.assertIn(f"<@&{TEST_ROLE_ID_2}>", msg_role["content"])

    def test_message_shell_spun_content(self):
        penalty = {"icon": "🐢", "name": "Flash Invertido", "desc": "Juega con el flash en la D", "scope": "both"}
        msg = discord_shells.message_shell_spun("Equipo Destino", "Equipo Atacante", penalty)
        self.assertIn("Ruleta de Castigo girada", msg["content"])
        self.assertIn("Flash Invertido", msg["content"])
        self.assertIn("Ambos integrantes", msg["content"])

    def test_message_returned_and_bounced(self):
        ret_msg = discord_shells.message_shell_returned_to_target("Defensores", "Atacantes")
        self.assertIn("CAPARAZÓN DEVUELTO", ret_msg["content"])
        self.assertIn("Defensores", ret_msg["content"])

        bounced_msg = discord_shells.message_shell_bounced_back("Defensores", "Atacantes", TEST_ROLE_ID_1)
        self.assertIn("EL CAPARAZÓN OS HA SIDO DEVUELTO", bounced_msg["content"])
        self.assertIn("Atacantes", bounced_msg["content"])
        self.assertIn(f"<@&{TEST_ROLE_ID_1}>", bounced_msg["content"])
        self.assertIn("https://duoqchallenge.luisjourney.xyz/player.html", bounced_msg["content"])

    def test_message_test(self):
        msg = discord_shells.message_test("Mi Equipo", TEST_ROLE_ID_1)
        self.assertIn("Prueba de conexión", msg["content"])
        self.assertIn("Mi Equipo", msg["content"])
        self.assertIn(f"<@&{TEST_ROLE_ID_1}>", msg["content"])

    def test_send_sync_rejects_invalid_url(self):
        res = discord_shells.send_sync("https://invalid-host.com/hook", {"content": "test"})
        self.assertFalse(res["success"])
        self.assertIn("no válida", res["error"])

    @patch.object(discord_live, "send_payload", return_value={"success": True, "messageId": "123"})
    def test_send_sync_valid(self, mock_send):
        res = discord_shells.send_sync(TEST_WEBHOOK_URL_1, {"content": "test"})
        self.assertTrue(res["success"])
        self.assertEqual(res["messageId"], "123")
        mock_send.assert_called_once()

    @patch("threading.Thread")
    def test_send_async_dispatches_daemon_thread(self, mock_thread_cls):
        mock_thread = MagicMock()
        mock_thread_cls.return_value = mock_thread

        res = discord_shells.send_async(TEST_WEBHOOK_URL_1, {"content": "test"})
        self.assertTrue(res)
        mock_thread_cls.assert_called_once()
        self.assertTrue(mock_thread_cls.call_args.kwargs.get("daemon"))
        mock_thread.start.assert_called_once()

    def test_send_async_invalid_url_returns_false(self):
        res = discord_shells.send_async("invalid", {"content": "test"})
        self.assertFalse(res)


class DiscordShellsServerIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(server, "DB_FILE", str(Path(self.temp.name) / "db.json"))
        self.remote_patch = patch.object(server, "remote_backend", None)
        self.send_patch = patch.object(discord_live, "send_payload", return_value={"success": True, "messageId": "mock"})
        self.db_patch.start()
        self.remote_patch.start()
        self.send_patch.start()
        self.addCleanup(self.send_patch.stop)
        self.addCleanup(self.db_patch.stop)
        self.addCleanup(self.remote_patch.stop)
        self.addCleanup(self.temp.cleanup)

        self.db_data = {
            "config": {
                "adminPinHash": server.hash_secret("1234"),
                "penaltyWeights": server.default_penalty_weights()
            },
            "duos": [
                {
                    "id": "team-attacker",
                    "teamName": "Attacking Duo",
                    "blueShells": 3,
                    "passwordHash": server.hash_secret("1234"),
                    "discordWebhook": TEST_WEBHOOK_URL_1,
                    "discordRoleId": TEST_ROLE_ID_1,
                    "player1": {"name": "P1", "tag": "EUW", "mainRole": "TOP"},
                    "player2": {"name": "P2", "tag": "EUW", "mainRole": "JUNGLE"},
                    "history": []
                },
                {
                    "id": "team-target",
                    "teamName": "Defending Duo",
                    "blueShells": 1,
                    "passwordHash": server.hash_secret("1234"),
                    "discordWebhook": TEST_WEBHOOK_URL_2,
                    "discordRoleId": TEST_ROLE_ID_2,
                    "player1": {"name": "P3", "tag": "EUW", "mainRole": "MIDDLE"},
                    "player2": {"name": "P4", "tag": "EUW", "mainRole": "BOTTOM"},
                    "history": []
                }
            ],
            "shellAttacks": [],
            "events": []
        }
        server.save_db(copy.deepcopy(self.db_data))

    def _post(self, path, payload):
        class FakeRequest:
            def makefile(self, *args, **kwargs):
                body = json.dumps(payload).encode("utf-8")
                raw = f"POST {path} HTTP/1.1\r\nContent-Length: {len(body)}\r\nContent-Type: application/json\r\n\r\n".encode("utf-8") + body
                return io.BytesIO(raw)

        # Use server handler logic directly
        handler = server.CustomHandler.__new__(server.CustomHandler)
        handler.headers = {"Content-Length": str(len(json.dumps(payload))), "Content-Type": "application/json"}
        handler.rfile = io.BytesIO(json.dumps(payload).encode("utf-8"))
        handler.wfile = io.BytesIO()
        handler.path = path
        
        sent_data = {}
        sent_status = [200]
        def fake_send_json(data, status=200):
            sent_data.clear()
            sent_data.update(data if isinstance(data, dict) else {"_list": data})
            sent_status[0] = status
        handler._send_json = fake_send_json

        # Dispatch do_POST
        handler.do_POST()
        return sent_status[0], sent_data

    def test_admin_save_and_clear_discord_webhook(self):
        # Update webhook and role ID via admin
        new_url = "https://discord.com/api/webhooks/999999/new_valid_token"
        new_role = "555666777888999000"
        status, res = self._post("/api/duos", {
            "authPin": "1234",
            "duo": {
                "id": "team-target",
                "discordWebhook": new_url,
                "discordRoleId": new_role
            }
        })
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        db = server.load_db()
        target_duo = next(d for d in db["duos"] if d["id"] == "team-target")
        self.assertEqual(target_duo["discordWebhook"], new_url)
        self.assertEqual(target_duo["discordRoleId"], new_role)

        # Reject invalid webhook
        status, res = self._post("/api/duos", {
            "authPin": "1234",
            "duo": {
                "id": "team-target",
                "discordWebhook": "https://evil.com/hook"
            }
        })
        self.assertEqual(status, 400)
        self.assertFalse(res["success"])

        # Clear webhook and role
        status, res = self._post("/api/duos", {
            "authPin": "1234",
            "duo": {
                "id": "team-target",
                "discordWebhook": "",
                "discordRoleId": ""
            }
        })
        self.assertEqual(status, 200)
        db = server.load_db()
        target_duo = next(d for d in db["duos"] if d["id"] == "team-target")
        self.assertEqual(target_duo["discordWebhook"], "")
        self.assertEqual(target_duo["discordRoleId"], "")

    def test_role_names_rejected_without_changing_team_settings(self):
        before = server.load_db()
        for invalid in ("Marx&Mises", "@everyone", "<@&1560279740261343352>", "123", "１" * 18):
            with self.subTest(role=invalid):
                status, result = self._post("/api/duos", {
                    "authPin": "1234", "duo": {"id": "team-target", "discordRoleId": invalid}
                })
                self.assertEqual(status, 400)
                self.assertFalse(result["success"])
                self.assertEqual(server.load_db(), before)

        new_team = copy.deepcopy(before["duos"][0])
        new_team.update(id="new-team", discordRoleId="Marx&Mises")
        status, _ = self._post("/api/duos", {"authPin": "1234", "duo": new_team})
        self.assertEqual(status, 400)
        self.assertEqual(server.load_db(), before)

    def test_admin_saves_numeric_role_id_and_can_clear_it(self):
        for role in ("1560279740261343352", ""):
            status, result = self._post("/api/duos", {
                "authPin": "1234", "duo": {"id": "team-target", "discordRoleId": role}
            })
            self.assertEqual(status, 200)
            self.assertTrue(result["success"])
            saved = next(d for d in server.load_db()["duos"] if d["id"] == "team-target")
            self.assertEqual(saved["discordRoleId"], role)
            self.assertEqual(saved["discordWebhook"], TEST_WEBHOOK_URL_2)
            self.assertEqual(saved["blueShells"], 1)

    def test_legacy_role_name_does_not_block_unrelated_admin_edits(self):
        db = server.load_db()
        db["duos"][1]["discordRoleId"] = "Old role name"
        server.save_db(db)
        status, result = self._post("/api/duos", {
            "authPin": "1234", "duo": {"id": "team-target", "teamName": "Updated name"}
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["success"])
        saved = next(d for d in server.load_db()["duos"] if d["id"] == "team-target")
        self.assertEqual(saved["discordRoleId"], "Old role name")

    @patch.object(discord_shells, "notify_shell_received_async")
    def test_launch_shell_triggers_discord_alert(self, mock_notify):
        token = server.create_player_session("team-attacker")
        status, res = self._post("/api/player/launch-shell", {
            "sessionToken": token,
            "targetId": "team-target"
        })
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        mock_notify.assert_called_once_with(
            TEST_WEBHOOK_URL_2, "Attacking Duo", "Defending Duo", TEST_ROLE_ID_2
        )

    @patch.object(discord_shells, "notify_shell_received_async")
    @patch.object(discord_shells, "notify_shell_spun_async")
    def test_spin_shell_triggers_discord_alert(self, mock_notify_spun, mock_notify_recv):
        token_attacker = server.create_player_session("team-attacker")
        _, launch_res = self._post("/api/player/launch-shell", {
            "sessionToken": token_attacker,
            "targetId": "team-target"
        })
        attack_id = launch_res["attack"]["id"]

        token_target = server.create_player_session("team-target")
        with patch.object(server, "weighted_penalty", return_value={"baseId": "swap_flash", "name": "Flash en la D", "icon": "⚡", "scope": "both", "desc": "Jugar con flash invertido"}):
            status, spin_res = self._post("/api/player/spin-shell", {
                "sessionToken": token_target,
                "attackId": attack_id
            })
            self.assertEqual(status, 200)
            self.assertTrue(spin_res["success"])
            mock_notify_spun.assert_called_once()
            self.assertEqual(mock_notify_spun.call_args.args[0], TEST_WEBHOOK_URL_2)
            self.assertEqual(mock_notify_spun.call_args.args[1], "Defending Duo")
            self.assertEqual(mock_notify_spun.call_args.args[2], "Attacking Duo")

    @patch.object(discord_shells, "notify_shell_received_async")
    @patch.object(discord_shells, "notify_shell_returned_async")
    @patch.object(discord_shells, "notify_shell_bounced_back_async")
    def test_spin_shell_bounce_back_triggers_both_discord_alerts(self, mock_bounce, mock_returned, mock_recv):
        token_attacker = server.create_player_session("team-attacker")
        _, launch_res = self._post("/api/player/launch-shell", {
            "sessionToken": token_attacker,
            "targetId": "team-target"
        })
        attack_id = launch_res["attack"]["id"]

        token_target = server.create_player_session("team-target")
        with patch.object(server, "weighted_penalty", return_value={"baseId": "return_shell", "name": "Devolver Caparazón", "icon": "↩️", "scope": "both", "desc": "Rebota"}):
            status, spin_res = self._post("/api/player/spin-shell", {
                "sessionToken": token_target,
                "attackId": attack_id
            })
            self.assertEqual(status, 200)
            self.assertTrue(spin_res["success"])
            mock_returned.assert_called_once_with(TEST_WEBHOOK_URL_2, "Defending Duo", "Attacking Duo")
            mock_bounce.assert_called_once_with(TEST_WEBHOOK_URL_1, "Defending Duo", "Attacking Duo", TEST_ROLE_ID_1)

    def test_privacy_webhook_url_not_leaked_publicly(self):
        # 1. Public summaries must NOT have discordWebhook or discordRoleId
        summaries = server.public_duo_summaries()
        for duo in summaries:
            self.assertNotIn("discordWebhook", duo)
            self.assertNotIn("discordRoleId", duo)

        # 2. Player state must NOT include discordWebhook or discordRoleId
        db = server.load_db()
        duo1 = next(d for d in db["duos"] if d["id"] == "team-attacker")
        state1 = server.player_state(db, duo1)
        self.assertNotIn("discordWebhook", state1)
        self.assertNotIn("discordRoleId", state1)

        # 3. Admin includes discordWebhook and discordRoleId
        status, admin_res = self._post("/api/admin/login", {"pin": "1234"})
        self.assertEqual(status, 200)
        duos = admin_res.get("duos", [])
        self.assertTrue(any(d.get("discordWebhook") == TEST_WEBHOOK_URL_1 for d in duos))
        self.assertTrue(any(d.get("discordRoleId") == TEST_ROLE_ID_1 for d in duos))


class DiscordTestConcurrencyTests(unittest.TestCase):
    tearDown = fixtures.ShellEndpointTests.tearDown
    post = fixtures.ShellEndpointTests.post

    def setUp(self):
        patcher = patch.object(server, 'remote_backend', None)
        patcher.start()
        self.addCleanup(patcher.stop)
        fixtures.ShellEndpointTests.setUp(self)
        db = server.load_db()
        db['duos'][0]['discordWebhook'] = TEST_WEBHOOK_URL_1
        db['duos'][0]['discordRoleId'] = TEST_ROLE_ID_1
        server.save_db(db)
        self.token = self.post('/api/player/login', {'teamId':'a','password':'a-pass'})['sessionToken']

    def test_slow_admin_discord_test_does_not_block_reads_or_mutations(self):
        started, release = threading.Event(), threading.Event()
        def slow_discord(url, body):
            started.set()
            if not release.wait(5):
                raise TimeoutError('Test did not release mocked Discord response.')
            return {'success':True,'messageId':'fake-message'}
        before = copy.deepcopy(server.load_db())
        with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL':TEST_WEBHOOK_URL_1}), \
             patch.object(discord_live, 'send_payload', side_effect=slow_discord) as send, \
             ThreadPoolExecutor(max_workers=2) as pool:
            waiting = pool.submit(self.post, '/api/discord/test', {'authPin':'9999'})
            try:
                self.assertTrue(started.wait(2), 'Discord send was not reached')
                # Both requests need db_lock; they must finish while Discord is still waiting.
                read = pool.submit(self.post, '/api/player/state', {'sessionToken':self.token})
                self.assertTrue(read.result(timeout=1)['success'])
                changed_url = TEST_WEBHOOK_URL_2 if before['duos'][0]['discordWebhook']==TEST_WEBHOOK_URL_1 else TEST_WEBHOOK_URL_1
                update = pool.submit(self.post, '/api/duos',
                                     {'authPin':'9999','duo':{'id':'a','discordWebhook':changed_url,'discordRoleId':TEST_ROLE_ID_1}})
                self.assertTrue(update.result(timeout=1)['success'])
                self.assertFalse(waiting.done(), 'Mocked send should still be waiting')
            finally:
                release.set()
            self.assertTrue(waiting.result(timeout=2)['success'])
            send.assert_called_once()
        after = server.load_db()
        self.assertEqual(after['duos'][0]['discordWebhook'], changed_url, 'Sending a test must not overwrite concurrent changes')
        self.assertEqual(after['duos'][0]['discordRoleId'], TEST_ROLE_ID_1)

    def test_invalid_admin_pin_and_missing_env_never_send(self):
        with patch.object(discord_live, 'send_payload') as send:
            self.post('/api/discord/test', {'authPin':'wrong'}, expected=401)
            with patch.dict(os.environ, {'DISCORD_LIVE_WEBHOOK_URL':''}):
                self.post('/api/discord/test', {'authPin':'9999'}, expected=400)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
