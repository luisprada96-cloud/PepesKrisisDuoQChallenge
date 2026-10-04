"""Discord live alerts driven by the existing Twitch polling job."""
import json
import re
import urllib.error
import urllib.request


def webhook_url(value):
    """Accept only a private incoming Discord webhook, never arbitrary hosts."""
    value = str(value or "").strip()
    if re.fullmatch(r"https://discord\.com/api/(?:v\d+/)?webhooks/\d+/[A-Za-z0-9_.-]+", value):
        return value
    return ""


def plain_text(value, limit):
    text = " ".join(str(value or "").split())[:limit]
    return re.sub(r"([\\`*_~|<>])", r"\\\1", text)


def message(alert):
    name = plain_text(alert.get("name") or alert["channel"], 100)
    team = plain_text(alert.get("teamName"), 100)
    title = plain_text(alert.get("title"), 300)
    lines = [f"🔴 **{name} está en directo**", f"👥 Equipo: **{team}**"]
    if title:
        lines.append(f"🎮 {title}")
    lines.append(f"https://www.twitch.tv/{alert['channel']}")
    return {"content": "\n".join(lines), "allowed_mentions": {"parse": []}}


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(url, alert):
    return send_payload(url, message(alert))


def send_payload(url, payload):
    """Return only safe diagnostics; the webhook URL contains a secret token."""
    # SUPPRESS_EMBEDS keeps links clickable without generating Twitch previews.
    payload = {**payload, "flags": 4}
    request = urllib.request.Request(
        url + "?wait=true", data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "PepesKrisis-LiveAlerts/1.0"}, method="POST")
    try:
        with urllib.request.build_opener(NoRedirects()).open(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not isinstance(result, dict) or not result.get("id"):
            return {"success": False, "error": "Discord no confirmó el mensaje.", "retryAfter": 300}
        return {"success": True, "messageId": str(result["id"])}
    except urllib.error.HTTPError as error:
        retry_after = 300
        if error.code == 429:
            try:
                retry_after = max(1, min(86400, float(json.loads(error.read()).get("retry_after", 300))))
            except (ValueError, TypeError, AttributeError):
                pass
        return {"success": False, "error": f"Discord respondió HTTP {error.code}.", "retryAfter": retry_after}
    except Exception:
        return {"success": False, "error": "No se pudo confirmar el envío a Discord.", "retryAfter": 300}


def prepare(db, live, owners):
    """Keep one durable notification per channel and latest stream ID."""
    ledger = db.setdefault("discordLiveNotifications", {})
    changed = False
    for channel, owner in owners.items():
        stream = live.get(channel) or {}
        stream_id = str(stream.get("id") or "")
        if not stream_id or ledger.get(channel, {}).get("streamId") == stream_id:
            continue
        ledger[channel] = {"channel": channel, "streamId": stream_id, "status": "pending",
                           "teamId": owner["teamId"], "playerKey": owner["playerKey"],
                           "name": owner["name"], "teamName": owner["teamName"],
                           "title": str(stream.get("title") or "")[:300]}
        changed = True
    # Removed channels must not retain team-related notification records.
    for channel in list(ledger):
        if channel not in owners:
            del ledger[channel]
            changed = True
    return changed


def pending(db, live, owners):
    return [dict(alert) for channel, alert in db.get("discordLiveNotifications", {}).items()
            if channel in owners and str((live.get(channel) or {}).get("id") or "") == alert.get("streamId")
            and alert.get("status") == "pending"
            and (alert.get("teamId"), alert.get("playerKey")) == (owners[channel]["teamId"], owners[channel]["playerKey"])]
