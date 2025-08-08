from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.test import Client
from django.conf import settings
import json
import requests

from .conversation_flow import handle_message

# Config WhatsApp (remplis bien tes variables dans .env et settings.py)
"""WHATSAPP_API_URL = f"https://graph.facebook.com/v17.0/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
HEADERS = {
    "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
    "Content-Type": "application/json"
}"""

@csrf_exempt
def whatsapp_webhook(request):
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    try:
        data = json.loads(request.body)
        phone = data.get("from")
        message_type = data.get("type", "")
        message = data.get("message", "")
        if message_type == "interactive":
            message = data.get("interactive", {}).get("button_reply", {}).get("id", "")
        if not phone or not message:
            return JsonResponse({"error": "Numéro ou message manquant"}, status=400)

        result = handle_message(phone, message)

        # Envoie sur WhatsApp (pour usage réel, facultatif en simulation)
        if isinstance(result, dict) and result.get("buttons"):
            send_interactive_buttons(phone, result["response"], result["buttons"])
        else:
            text = result if isinstance(result, str) else result.get("response", "Message reçu.")
            send_text_message(phone, text)

        # ➡️ On retourne AUSSI la vraie réponse du flow (utilisé par le simulateur)
        return JsonResponse({"status": "Message envoyé ✅", "flow_response": result})

    except Exception as e:
        print(f"❌ Erreur dans whatsapp_webhook: {e}")
        return JsonResponse({"error": str(e)}, status=500)

def send_text_message(to: str, text: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    """try:
        requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    except requests.RequestException as e:
        print(f"❌ Erreur lors de l'envoi du message texte : {e}")"""

def send_interactive_buttons(to: str, question: str, buttons: list):
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": question},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": f"btn_{i}",
                            "title": btn
                        }
                    } for i, btn in enumerate(buttons)
                ]
            }
        }
    }
    """try:
        requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    except requests.RequestException as e:
        print(f"❌ Erreur lors de l'envoi des boutons : {e}")"""

def simulate_chat_flow(request):
    from django.test import Client
    import json

    client = Client()
    test_user = "242000111222"
    messages = [
        "Bonjour",
        "Je veux envoyer un colis",
        "Christ",
        "Brazzaville",
        "Pointe-Noire",
        "Oui",
        "Combien ça coûte ?"
    ]
    results = []
    for message in messages:
        response = client.post(
            "/chatbot/webhook/",
            data=json.dumps({"from": test_user, "message": message}),
            content_type="application/json"
        )
        # ➡️ On récupère la vraie réponse du flow :
        flow_response = json.loads(response.content).get("flow_response")
        results.append({
            "sent": message,
            "response": flow_response
        })
    return JsonResponse({"flow": results}, json_dumps_params={'ensure_ascii': False})
