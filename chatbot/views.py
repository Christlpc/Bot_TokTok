# chatbot/views.py
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .utils import send_whatsapp_message

VERIFY_TOKEN = "toktok_secret"

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
                text = msg["text"]["body"] if msg.get("type") == "text" else None

                print(f"Message reçu de {from_number}: {text}")

                # Répondre automatiquement
                send_whatsapp_message(from_number, "Bonjour 👋, bienvenue chez TokTok Delivery !")

        except Exception as e:
            print("Erreur webhook:", e)

        return JsonResponse({"status": "ok"}, status=200)
