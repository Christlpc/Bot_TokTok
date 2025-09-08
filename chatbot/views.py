import json, logging
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from .utils import (
    send_whatsapp_message,
    send_whatsapp_buttons,
    send_whatsapp_location_request,
    send_whatsapp_media_url,
    send_whatsapp_list
)
from .conversation_flow import handle_message, get_session
from .router import handle_incoming           # ⇦ point d'entrée unique (login commun + flows)
from .auth_core import get_session, normalize # ⇦ sessions partagées + helper

logger = logging.getLogger(__name__)
VERIFY_TOKEN = "toktok_secret"
RECENT_WAMIDS = {}
WAMID_TTL_SEC = 60

# Masquage des infos sensibles (ex: numéros)
def mask_sensitive(value: str, visible: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]

def _seen_wamid(wamid: str) -> bool:
    import time
    now = time.time()
    for k, exp in list(RECENT_WAMIDS.items()):
        if exp < now: RECENT_WAMIDS.pop(k, None)
    if not wamid: return False
    if wamid in RECENT_WAMIDS: return True
    RECENT_WAMIDS[wamid] = now + WAMID_TTL_SEC
    return False

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
                wamid = msg.get("id") or msg.get("wamid")
                if _seen_wamid(wamid):
                    logger.info("[WA] duplicate webhook ignored", extra={"wamid": wamid})
                    return JsonResponse({"status": "ok"}, status=200)

                from_number = msg["from"]
                session = get_session(from_number)

                msg_type = msg.get("type")
                text = ""

                if msg_type == "text":
                    text = msg["text"]["body"]

                elif msg_type == "interactive":
                    inter = msg["interactive"]
                    itype = inter.get("type")
                    # Bouton → on récupère le titre déjà géré par tes flows
                    if itype == "button_reply":
                        text = inter["button_reply"]["title"]
                    # Liste → on convertit row.id en commande textuelle
                    elif itype == "list_reply":
                        row = inter["list_reply"]
                        row_id = row.get("id", "")
                        # id attendus: accept_<id> | details_<id>
                        if row_id.startswith("accept_"):
                            text = f"Accepter {row_id.split('_',1)[1]}"
                        elif row_id.startswith("details_"):
                            text = f"Détails {row_id.split('_',1)[1]}"
                        else:
                            text = row.get("title") or "Menu"

                elif msg_type == "location":
                    # … ton code localisation inchangé …
                    pass

                # ----- passage au moteur -----
                bot_output = handle_message(from_number, text)

                # localisation demandée ?
                if session["step"] == "COURIER_DEPART":
                    send_whatsapp_location_request(from_number)
                    return JsonResponse({"status": "ok"}, status=200)

                # ----- envoi selon la réponse -----
                if "list" in bot_output:
                    # bot_output["list"] = {"rows": [...], "title": "..."} (cf. patch flow)
                    send_whatsapp_list(
                        from_number,
                        bot_output.get("response", ""),
                        bot_output["list"]["rows"],
                        bot_output["list"].get("title","Missions")
                    )
                elif bot_output.get("buttons"):
                    send_whatsapp_buttons(from_number, bot_output["response"], bot_output["buttons"])
                else:
                    send_whatsapp_message(from_number, bot_output.get("response", "❌ Erreur interne."))

        except Exception as e:
            logger.error(f"Erreur webhook: {str(e)}")

        return JsonResponse({"status": "ok"}, status=200)