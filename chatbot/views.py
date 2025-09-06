import json, logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .utils import (
    send_whatsapp_message,
    send_whatsapp_buttons,
    send_whatsapp_location_request
)
from .conversation_flow import handle_message, get_session

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
        body = json.loads(request.body.decode("utf-8"))
        try:
            entry = body["entry"][0]
            changes = entry["changes"][0]["value"]
            messages = changes.get("messages")

            if messages:
                msg = messages[0]
                from_number = msg["from"]
                session = get_session(from_number)

                msg_type = msg.get("type")
                text = ""

                # 🟢 Gestion texte
                if msg_type == "text":
                    if session["step"] == "LOGIN_WAIT_PWD":
                        logger.info(f"[WHATSAPP] Mot de passe reçu de {mask_sensitive(from_number)} (masqué)")
                        text = msg["text"]["body"]  # passe quand même au flow
                    else:
                        text = msg["text"]["body"]
                        logger.info(f"[WHATSAPP] Message reçu de {mask_sensitive(from_number)}: {text}")

                # 🟢 Gestion bouton
                elif msg_type == "interactive":
                    interactive_type = msg["interactive"]["type"]
                    if interactive_type == "button_reply":
                        button_id = msg["interactive"]["button_reply"]["id"]
                        button_title = msg["interactive"]["button_reply"]["title"]
                        logger.info(f"[WHATSAPP] Bouton cliqué par {mask_sensitive(from_number)}: {button_title} ({button_id})")
                        text = button_title  # on renvoie le titre dans le flow

                # 🟢 Gestion localisation
                elif msg_type == "location":
                    lat = msg["location"]["latitude"]
                    lng = msg["location"]["longitude"]
                    if session["step"] == "COURIER_DEPART":
                        session["new_request"]["depart"] = f"{lat},{lng}"
                        session["step"] = "COURIER_DEST"
                        logger.info(f"[WHATSAPP] Localisation reçue de {mask_sensitive(from_number)}: {lat},{lng}")
                        send_whatsapp_message(
                            from_number,
                            "✅ Localisation enregistrée.\n📍 Maintenant, quelle est l'adresse de destination ?"
                        )
                        return JsonResponse({"status": "ok"}, status=200)

                # 🔄 Passer au moteur conversationnel
                bot_output = handle_message(from_number, text)
                response_text = bot_output.get("response", "❌ Erreur interne.")
                buttons = bot_output.get("buttons")

                # Cas spécial localisation demandée
                if session["step"] == "COURIER_DEPART":
                    send_whatsapp_location_request(from_number)
                    return JsonResponse({"status": "ok"}, status=200)

                # Envoi normal
                if buttons:
                    send_whatsapp_buttons(from_number, response_text, buttons)
                else:
                    send_whatsapp_message(from_number, response_text)

        except Exception as e:
            logger.error(f"Erreur webhook: {str(e)}")

        return JsonResponse({"status": "ok"}, status=200)
