# chatbot/views.py
import json
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt

VERIFY_TOKEN = "toktok_secret"  # tu définis ton token secret ici

@csrf_exempt
def whatsapp_webhook(request):
    if request.method == "GET":
        # Vérification initiale Meta
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            return HttpResponse(challenge, status=200)
        return HttpResponse("Verification failed", status=403)

    if request.method == "POST":
        body = json.loads(request.body.decode("utf-8"))
        # Récupération du message entrant
        try:
            entry = body["entry"][0]
            changes = entry["changes"][0]["value"]
            messages = changes.get("messages")
            if messages:
                msg = messages[0]
                from_number = msg["from"]
                text = msg["text"]["body"] if msg.get("type") == "text" else None

                # TODO: appeler ton agent IA ou logique TokTok
                print(f"Message reçu de {from_number}: {text}")

        except Exception as e:
            print("Erreur webhook:", e)

        return JsonResponse({"status": "ok"}, status=200)
