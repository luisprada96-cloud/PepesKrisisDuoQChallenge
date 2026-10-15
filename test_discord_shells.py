"""Unit tests for duo-specific Discord Blue Shell notifications."""
import copy
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import discord_shells
import discord_live
import server


TEST_WEBHOOK_URL_1 = "https://discord.com/api/webhooks/111111111111111111/test_token_duo_1"
TEST_WEBHOOK_URL_2 = "https://discord.com/api/webhooks/222222222222222222/test_token_duo_2"


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
        msg = discord_shells.message_shell_received("Equipo *Atacante* <1>", "Equipo _Destino_")
        self.assertIn("ALERTA DE CAPARAZÓN AZUL", msg["content"])
        self.assertIn("Equipo \\*Atacante\\* \\<1\\>", msg["content"])
        self.assertIn("Equipo \\_Destino\\_", msg["content"])
        self.assertEqual(msg["allowed_mentions"], {"parse": []})

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

        bounced_msg = discord_shells.message_shell_bounced_back("Defensores", "Atacantes")
        self.assertIn("EL CAPARAZÓN OS HA SIDO DEVUELTO", bounced_msg["content"])
        self.assertIn("Atacantes", bounced_msg["content"])

    def test_message_test(self):
        msg = discord_shells.message_test("Mi Equipo")
        self.assertIn("Prueba de conexión", msg["content"])
        self.assertIn("Mi Equipo", msg["content"])

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

    def test_player_save_and_clear_discord_webhook(self):
        token = server.create_player_session("team-target")

        # Update webhook with valid url
        new_url = "https://discord.com/api/webhooks/999999/new_valid_token"
        status, res = self._post("/api/player/discord-webhook", {"sessionToken": token, "webhookUrl": new_url})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["discordWebhook"], new_url)
        db = server.load_db()
        target_duo = next(d for d in db["duos"] if d["id"] == "team-target")
        self.assertEqual(target_duo["discordWebhook"], new_url)

        # Reject invalid webhook
        status, res = self._post("/api/player/discord-webhook", {"sessionToken": token, "webhookUrl": "https://evil.com/hook"})
        self.assertEqual(status, 400)
        self.assertFalse(res["success"])

        # Clear webhook by sending empty string
        status, res = self._post("/api/player/discord-webhook", {"sessionToken": token, "webhookUrl": ""})
        self.assertEqual(status, 200)
        self.assertEqual(res["discordWebhook"], "")
        db = server.load_db()
        target_duo = next(d for d in db["duos"] if d["id"] == "team-target")
        self.assertEqual(target_duo["discordWebhook"], "")

    @patch.object(discord_shells, "send_sync", return_value={"success": True, "messageId": "999"})
    def test_player_test_discord_webhook(self, mock_send):
        token = server.create_player_session("team-target")
        status, res = self._post("/api/player/discord-webhook/test", {"sessionToken": token})
        self.assertEqual(status, 200)
        self.assertTrue(res["success"])
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.args[0], TEST_WEBHOOK_URL_2)

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
            TEST_WEBHOOK_URL_2, "Attacking Duo", "Defending Duo"
        )

    @patch.object(discord_shells, "notify_shell_spun_async")
    def test_spin_shell_triggers_discord_alert(self, mock_notify):
        token_attacker = server.create_player_session("team-attacker")
        _, launch_res = self._post("/api/player/launch-shell", {
            "sessionToken": token_attacker,
            "targetId": "team-target"
        })
        attack_id = launch_res["attack"]["id"]

        token_target = server.create_player_session("team-target")
        # Mock weighted_penalty to return a regular penalty
        with patch.object(server, "weighted_penalty", return_value={"baseId": "swap_flash", "name": "Flash en la D", "icon": "⚡", "scope": "both", "desc": "Jugar con flash invertido"}):
            status, spin_res = self._post("/api/player/spin-shell", {
                "sessionToken": token_target,
                "attackId": attack_id
            })
            self.assertEqual(status, 200)
            self.assertTrue(spin_res["success"])
            mock_notify.assert_called_once()
            self.assertEqual(mock_notify.call_args.args[0], TEST_WEBHOOK_URL_2)
            self.assertEqual(mock_notify.call_args.args[1], "Defending Duo")
            self.assertEqual(mock_notify.call_args.args[2], "Attacking Duo")

    @patch.object(discord_shells, "notify_shell_returned_async")
    @patch.object(discord_shells, "notify_shell_bounced_back_async")
    def test_spin_shell_bounce_back_triggers_both_discord_alerts(self, mock_bounce, mock_returned):
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
            mock_bounce.assert_called_once_with(TEST_WEBHOOK_URL_1, "Defending Duo", "Attacking Duo")

    def test_privacy_webhook_url_not_leaked_publicly(self):
        # 1. Public summaries must NOT have discordWebhook
        summaries = server.public_duo_summaries()
        for duo in summaries:
            self.assertNotIn("discordWebhook", duo)

        # 2. Player state includes discordWebhook ONLY for authenticated duo
        db = server.load_db()
        duo1 = next(d for d in db["duos"] if d["id"] == "team-attacker")
        state1 = server.player_state(db, duo1)
        self.assertEqual(state1.get("discordWebhook"), TEST_WEBHOOK_URL_1)

        # 3. Admin includes discordWebhook
        status, admin_res = self._post("/api/admin/login", {"pin": "1234"})
        self.assertEqual(status, 200)
        duos = admin_res.get("duos", [])
        self.assertTrue(any(d.get("discordWebhook") == TEST_WEBHOOK_URL_1 for d in duos))


if __name__ == "__main__":
    unittest.main()
