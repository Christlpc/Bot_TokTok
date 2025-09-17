# chatbot/views.py
import json, logging, time
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import requests

from .utils import (
    send_whatsapp_message,
    send_whatsapp_buttons,
    send_whatsapp_location_request,
    send_whatsapp_media_url,
    send_whatsapp_list, ACCESS_TOKEN,
)
from .router import handle_incoming        # ⇦ point d'entrée unique
from .auth_core import get_session         # ⇦ sessions partagées

logger = logging.getLogger(__name__)
VERIFY_TOKEN = "toktok_secret"
RECENT_WAMIDS = {}
WAMID_TTL_SEC = 60


# Masque numéros sensibles
def mask_sensitive(value: str, visible: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]


# Anti-doublons webhook
def _seen_wamid(wamid: str) -> bool:
    now = time.time()
    for k, exp in list(RECENT_WAMIDS.items()):
        if exp < now:
            RECENT_WAMIDS.pop(k, None)
    if not wamid:
        return False
    if wamid in RECENT_WAMIDS:
        return True
    RECENT_WAMIDS[wamid] = now + WAMID_TTL_SEC
    return False


@csrf_exempt
@csrf_exempt
def whatsapp_webhook(request):
    if request.method == "GET":
        ...
    if request.method == "POST":
        body = json.loads(request.body.decode("utf-8"))
        try:
            entry = body["entry"][0]
            changes = entry["changes"][0]["value"]
            messages = changes.get("messages")

            if messages:
                msg = messages[0]
                wamid = msg.get("id") or msg.get("wamid")
                if _seen_wamid(wamid):
                    return JsonResponse({"status": "ok"}, status=200)

                from_number = msg["from"]
                session = get_session(from_number)

                msg_type = msg.get("type")
                text, lat, lng, media_url = "", None, None, None

                if msg_type == "text":
                    text = msg["text"]["body"]

                elif msg_type == "interactive":
                    inter = msg["interactive"]
                    itype = inter.get("type")
                    if itype == "button_reply":
                        text = inter["button_reply"]["title"]
                    elif itype == "list_reply":
                        row = inter["list_reply"]
                        row_id = row.get("id", "")
                        if row_id.startswith("accept_"):
                            text = f"Accepter {row_id.split('_',1)[1]}"
                        elif row_id.startswith("details_"):
                            text = f"Détails {row_id.split('_',1)[1]}"
                        else:
                            text = row.get("title") or "Menu"

                elif msg_type == "image":
                    media = msg.get("image", {})
                    media_id = media.get("id")
                    if media_id:
                        r = requests.get(
                            f"https://graph.facebook.com/v19.0/{media_id}",
                            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"}
                        )
                        if r.status_code == 200:
                            media_url = r.json().get("url")

                elif msg_type == "location":
                    lat = msg["location"]["latitude"]
                    lng = msg["location"]["longitude"]
                    if session.get("step") == "SIGNUP_MARCHAND_GPS":
                        session.setdefault("signup", {}).setdefault("data", {})["coordonnees_gps"] = f"{lat},{lng}"
                        session["step"] = "SIGNUP_MARCHAND_RCCM"
                    elif session.get("step") == "COURIER_DEPART":
                        nr = session.setdefault("new_request", {})
                        nr["depart"] = f"{lat},{lng}"
                        nr["coordonnees_gps"] = f"{lat},{lng}"
                        session["step"] = "COURIER_DEST"

                # Passage unique au moteur
                bot_output = handle_incoming(
                    from_number,
                    text,
                    lat=lat, lng=lng,
                    media_url=media_url,
                    wa_message_id=wamid,
                    wa_timestamp=msg.get("timestamp"),
                    wa_type=msg_type,
                )

                # Réponses
                if "list" in bot_output:
                    send_whatsapp_list(...)
                elif bot_output.get("buttons"):
                    send_whatsapp_buttons(...)
                elif bot_output.get("ask_location"):
                    msg_txt = bot_output["ask_location"] if isinstance(bot_output["ask_location"], str) else None
                    send_whatsapp_location_request(from_number, msg_txt or "📍 Merci de partager votre localisation.")
                else:
                    send_whatsapp_message(from_number, bot_output.get("response", "❌ Erreur interne."))

        except Exception as e:
            logger.exception(f"[WA_WEBHOOK] Exception: {e}")

        return JsonResponse({"status": "ok"}, status=200)
