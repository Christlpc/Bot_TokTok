import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .utils import (
    send_whatsapp_message,
    send_whatsapp_buttons,
    send_whatsapp_location_request
)
from .conversation_flow import handle_message, get_session

VERIFY_TOKEN = "toktok_secret"

# 🔑 Mapping global des boutons
BUTTON_MAP = {
    # Menu principal
    "btn_1": "nouvelle demande",
    "btn_2": "suivre ma livraison",
    "btn_3": "marketplace",

    # Confirmation mission
    "btn_confirmer": "confirmer",
    "btn_annuler": "annuler",

    # Paiement Marketplace
    "btn_cash": "cash",
    "btn_mobile": "mobile money",
    "btn_virement": "virement",
}

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
                msg_type = msg.get("type")
                text = ""

                # 🟢 Gestion texte
                if msg_type == "text":
                    text = msg["text"]["body"]

                # 🟢 Gestion bouton interactif
                elif msg_type == "interactive":
                    interactive_type = msg["interactive"]["type"]
                    if interactive_type == "button_reply":
                        button_id = msg["interactive"]["button_reply"]["id"]
                        text = BUTTON_MAP.get(button_id, button_id)  # traduction ID → texte

                # 🟢 Gestion localisation
                elif msg_type == "location":
                    lat = msg["location"]["latitude"]
                    lng = msg["location"]["longitude"]
                    session = get_session(from_number)
                    if session["step"] == "COURIER_DEPART":
                        session["new_request"]["depart"] = f"{lat},{lng}"
                        session["step"] = "COURIER_DEST"
                        send_whatsapp_message(
                            from_number,
                            "✅ Localisation enregistrée.\n📍 Maintenant, quelle est l'adresse de destination ?"
                        )
                        return JsonResponse({"status": "ok"}, status=200)

                print(f"Message reçu de {from_number}: {text}")

                # 🔄 Passer le texte reçu au moteur conversationnel
                bot_output = handle_message(from_number, text)
                response_text = bot_output.get("response", "❌ Erreur interne.")
                buttons = bot_output.get("buttons")

                # Cas spécial : localisation demandée
                session = get_session(from_number)
                if session["step"] == "COURIER_DEPART":
                    send_whatsapp_location_request(from_number)
                    return JsonResponse({"status": "ok"}, status=200)

                # Envoi réponse
                if buttons:
                    send_whatsapp_buttons(from_number, response_text, buttons)
                else:
                    send_whatsapp_message(from_number, response_text)

        except Exception as e:
            print("Erreur webhook:", e)

        return JsonResponse({"status": "ok"}, status=200)
