"""Discord webhook notifications for Blue Shell (Caparazón Azul) events per duo team."""
import logging
import threading
import discord_live


logger = logging.getLogger("discord_shells")


def webhook_url(value):
    """Validate and return only private incoming Discord webhooks."""
    return discord_live.webhook_url(value)


def message_shell_received(attacker_name, target_name):
    """Notification sent to the target team's private Discord channel when attacked."""
    attacker_safe = discord_live.plain_text(attacker_name, 100)
    target_safe = discord_live.plain_text(target_name, 100)
    lines = [
        "🐢⚡ **¡ALERTA DE CAPARAZÓN AZUL!**",
        f"¡Atención **{target_safe}**! El equipo **{attacker_safe}** os acaba de lanzar un Caparazón Azul. 💥",
        "",
        "🎲 Tenéis un caparazón pendiente en vuestra bandeja de entrada.",
        "👉 ¡Entrad a girar la ruleta de castigos antes de vuestra próxima partida!",
        "🔗 https://pepes-krisis-duoq-challenge.onrender.com/player.html",
    ]
    return {
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []}
    }


def message_shell_spun(target_name, attacker_name, penalty):
    """Notification sent when the target team spins the wheel and gets a penalty."""
    target_safe = discord_live.plain_text(target_name, 100)
    attacker_safe = discord_live.plain_text(attacker_name, 100)
    icon = penalty.get("icon") or "🎰"
    name = discord_live.plain_text(penalty.get("name") or "Castigo", 100)
    desc = discord_live.plain_text(penalty.get("desc") or "", 300)
    scope = penalty.get("scope", "both")
    scope_text = "Ambos integrantes" if scope == "both" else ("1 integrante" if scope == "single" else scope)

    lines = [
        "🎰 **¡Ruleta de Castigo girada!**",
        f"Equipo: **{target_safe}** (Caparazón de **{attacker_safe}**)",
        "",
        f"Castigo obtenido: {icon} **{name}**",
        f"📝 *{desc}*",
        f"👥 **Afecta a:** {scope_text}",
        "",
        "¡Mucho ánimo con la partida! 🔥",
    ]
    return {
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []}
    }


def message_shell_returned_to_target(target_name, attacker_name):
    """Notification sent to the defending team when they rolled Return Shell."""
    target_safe = discord_live.plain_text(target_name, 100)
    attacker_safe = discord_live.plain_text(attacker_name, 100)
    lines = [
        "↩️🛡️ **¡CAPARAZÓN DEVUELTO CON ÉXITO!**",
        f"¡Enhorabuena **{target_safe}**! Habéis sacado *Devolver Caparazón* en la ruleta.",
        f"El proyectil de **{attacker_safe}** ha rebotado y vuelve directo hacia ellos. ¡Os habéis librado!",
    ]
    return {
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []}
    }


def message_shell_bounced_back(target_name, attacker_name):
    """Notification sent to the original attacker when their shell bounces back at them."""
    target_safe = discord_live.plain_text(target_name, 100)
    attacker_safe = discord_live.plain_text(attacker_name, 100)
    lines = [
        "↩️💥 **¡EL CAPARAZÓN OS HA SIDO DEVUELTO!**",
        f"¡Cuidado **{attacker_safe}**! El equipo **{target_safe}** ha sacado *Devolver Caparazón*.",
        "",
        "🎯 El caparazón ha rebotado contra vosotros y ahora tenéis una ruleta pendiente en vuestro panel.",
        "👉 Entrad a girar la ruleta de castigos antes de vuestra próxima partida:",
        "https://pepes-krisis-duoq-challenge.onrender.com/player.html",
    ]
    return {
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []}
    }


def message_test(team_name):
    """Test notification to verify that the private duo Discord channel is properly linked."""
    team_safe = discord_live.plain_text(team_name, 100)
    lines = [
        "🐢⚡ **Prueba de conexión — Pepes Krisis Duo Q**",
        f"¡Hola **{team_safe}**! La conexión con vuestro canal de Discord funciona correctamente.",
        "A partir de ahora, cuando otro equipo os lance un Caparazón Azul o recibáis un castigo, os llegará un aviso automático por este canal.",
    ]
    return {
        "content": "\n".join(lines),
        "allowed_mentions": {"parse": []}
    }


def send_sync(url, payload):
    """Synchronously send a payload to a Discord webhook."""
    valid_url = webhook_url(url)
    if not valid_url:
        return {"success": False, "error": "URL de webhook no válida."}
    return discord_live.send_payload(valid_url, payload)


def send_async(url, payload):
    """Dispatch a Discord notification in a background thread so web requests never stall."""
    valid_url = webhook_url(url)
    if not valid_url:
        return False

    def worker():
        try:
            res = discord_live.send_payload(valid_url, payload)
            if not res.get("success"):
                logger.warning("Discord webhook failed: %s", res.get("error"))
        except Exception as exc:
            logger.warning("Unexpected error sending Discord webhook: %s", exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return True


def notify_shell_received_async(target_webhook, attacker_name, target_name):
    """Send async alert to target team that they have received a shell."""
    if not target_webhook:
        return False
    return send_async(target_webhook, message_shell_received(attacker_name, target_name))


def notify_shell_spun_async(target_webhook, target_name, attacker_name, penalty):
    """Send async alert to target team with the spun penalty."""
    if not target_webhook:
        return False
    return send_async(target_webhook, message_shell_spun(target_name, attacker_name, penalty))


def notify_shell_returned_async(target_webhook, target_name, attacker_name):
    """Send async alert to defending team confirming the shell was deflected."""
    if not target_webhook:
        return False
    return send_async(target_webhook, message_shell_returned_to_target(target_name, attacker_name))


def notify_shell_bounced_back_async(attacker_webhook, target_name, attacker_name):
    """Send async alert to attacking team warning them their shell bounced back."""
    if not attacker_webhook:
        return False
    return send_async(attacker_webhook, message_shell_bounced_back(target_name, attacker_name))
