import json, logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .utils import (
    send_whatsapp_message,
    send_whatsapp_buttons,
    send_whatsapp_location_request,
    send_whatsapp_media_url
)
from conversation_flow import handle_message, get_session
from router import handle_incoming           # ⇦ point d'entrée unique (login commun + flows)
from auth_core import get_session, normalize # ⇦ sessions partagées + helper

logger = logging.getLogger(__name__)
VERIFY_TOKEN = "toktok_secret"

# Masquage des infos sensibles (ex: numéros)
def mask_sensitive(value: str, visible: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]


@csrf_exempt
def whatsapp_webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return HttpResponse(challenge, status=200)
        return HttpResponse("Verification failed", status=403)

    if request.method == "POST":
        try:
            body = json.loads(request.body.decode("utf-8"))
            entry = body["entry"][0]
            changes = entry["changes"][0]["value"]
            messages = changes.get("messages")

            if not messages:
                return JsonResponse({"status": "no_messages"}, status=200)

            msg = messages[0]
            from_number = msg["from"]                # ex: "24206...."
            session = get_session(from_number)       # ☑️ session partagée (auth_core)

            # --- Normalisation input WhatsApp ---
            msg_type = msg.get("type")
            text = ""
            lat = lng = None
            media_url = None

            if msg_type == "text":
                text = msg["text"]["body"]
                logger.info(f"[WA] Text from {from_number}: {text}")

            elif msg_type == "interactive":
                itype = msg["interactive"]["type"]
                if itype == "button_reply":
                    # on passe le titre bouton au flow (ex: "Connexion", "Missions dispo", etc.)
                    text = msg["interactive"]["button_reply"]["title"]
                    logger.info(f"[WA] Button from {from_number}: {text}")
                elif itype == "list_reply":
                    text = msg["interactive"]["list_reply"]["title"]
                    logger.info(f"[WA] List from {from_number}: {text}")

            elif msg_type == "location":
                lat = msg["location"]["latitude"]
                lng = msg["location"]["longitude"]
                # on peut mettre un mot-clé pour garder un historique lisible
                text = "📍 localisation envoyée"
                logger.info(f"[WA] Location from {from_number}: {lat},{lng}")

            elif msg_type in {"image","audio","video","document","sticker"}:
                # selon ton provider WA, la structure peut changer ; ici un exemple image
                if "image" in msg:
                    media_url = msg["image"].get("link") or msg["image"].get("url")
                elif "document" in msg:
                    media_url = msg["document"].get("link") or msg["document"].get("url")
                text = msg.get(msg_type, {}).get("caption") or f"[{msg_type}]"
                logger.info(f"[WA] Media from {from_number}: type={msg_type} url={media_url}")

            # --- Passe au moteur (router -> auth commune -> flow par rôle) ---
            bot_output = handle_incoming(
                phone=from_number,
                text=text or "",
                lat=lat, lng=lng,
                media_url=media_url
            )
            response_text = bot_output.get("response", "❌ Erreur interne.")
            buttons = bot_output.get("buttons")  # liste de str (max 3 gérées)

            # --- Cas spé: si un flow attend une localisation, tu peux relancer une demande WA native
            # Exemple: si ton flow client utilise session["step"] == "COURIER_DEPART"
            if session.get("step") == "COURIER_DEPART":
                send_whatsapp_location_request(from_number)
                return JsonResponse({"status": "ok"}, status=200)

            # --- Envoi WA ---
            if media_url:  # si ton flow/IA veut renvoyer un média (selon ton implémentation)
                send_whatsapp_media_url(from_number, media_url, caption=response_text)
            elif buttons:
                send_whatsapp_buttons(from_number, response_text, buttons)
            else:
                send_whatsapp_message(from_number, response_text)

            return JsonResponse({"status": "ok"}, status=200)

        except Exception as e:
            logger.exception(f"[WA] Webhook error: {e}")
            return JsonResponse({"status": "error"}, status=200)