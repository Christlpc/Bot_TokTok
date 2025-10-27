import json, logging, time
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
import requests

from .utils import (
    send_whatsapp_message,
    send_whatsapp_buttons,
    send_whatsapp_location_request,
    send_whatsapp_media_url,
    send_whatsapp_list,
    ACCESS_TOKEN,
)
from .router import handle_incoming        # ⇦ point d'entrée unique
from .auth_core import get_session         # ⇦ sessions partagées
from .analytics import analytics           # ⇦ tracking métriques

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

            if not messages:
                return JsonResponse({"status": "ok"}, status=200)

            msg = messages[0]
            wamid = msg.get("id") or msg.get("wamid")
            if _seen_wamid(wamid):
                logger.info("[WA] duplicate webhook ignored", extra={"wamid": wamid})
                return JsonResponse({"status": "ok"}, status=200)

            from_number = msg["from"]
            session = get_session(from_number)

            msg_type = msg.get("type")
            text = ""
            media_url = None

            # Texte simple
            if msg_type == "text":
                text = msg["text"]["body"]

            # Boutons & Listes
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
                        # FIX: Utiliser l'ID numérique au lieu du title pour éviter les problèmes avec les noms tronqués
                        # Si l'ID est numérique, c'est un indice de liste (catégorie, marchand, produit)
                        text = row_id if row_id else (row.get("title") or "Menu")

            # Image
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
                text = ""  # pas de texte associé

            # Localisation
            elif msg_type == "location":
                lat = msg["location"]["latitude"]
                lng = msg["location"]["longitude"]
                
                logger.info(f"[WA] Localisation reçue de {from_number}: latitude={lat}, longitude={lng}")
                
                # Stocker dans session pour usage ultérieur si nécessaire
                location_str = f"{lat},{lng}"
                session.setdefault("last_location", {})["coords"] = location_str
                session["last_location"]["latitude"] = lat
                session["last_location"]["longitude"] = lng
                
                # Pour l'inscription entreprise GPS : traitement spécial
                if session.get("step") == "SIGNUP_MARCHAND_GPS":
                    signup_data = session.setdefault("signup", {}).setdefault("data", {})
                    signup_data["coordonnees_gps"] = location_str
                    signup_data["latitude"] = lat
                    signup_data["longitude"] = lng
                    text = "LOCATION_SHARED"
                else:
                    # Pour tous les autres cas, laisser le flow gérer
                    # On passe juste un texte indicatif
                    text = "LOCATION_SHARED"

            # Passage au moteur
            bot_output = handle_incoming(
                from_number,
                text,
                lat=msg.get("location", {}).get("latitude") if msg_type == "location" else None,
                lng=msg.get("location", {}).get("longitude") if msg_type == "location" else None,
                media_url=media_url if media_url else None,
                wa_message_id=wamid,
                wa_timestamp=msg.get("timestamp"),
                wa_type=msg_type,
            )

            # Localisation demandée explicitement
            if session.get("step") == "COURIER_DEPART":
                send_whatsapp_location_request(from_number)
                return JsonResponse({"status": "ok"}, status=200)

            # Réponse selon type (priorité : media > ask_location > list > buttons > text)
            
            # 1. Media (image, video, document)
            if bot_output.get("media"):
                media_cfg = bot_output["media"]
                media_type = media_cfg.get("type", "image")
                media_url = media_cfg.get("url")
                media_caption = media_cfg.get("caption", bot_output.get("response", ""))
                
                if media_url:
                    from .utils import send_whatsapp_media_url
                    send_whatsapp_media_url(from_number, media_url, kind=media_type, caption=media_caption)
                    
                    # Si des boutons sont présents, les envoyer après l'image
                    if bot_output.get("buttons"):
                        send_whatsapp_buttons(from_number, bot_output.get("response", ""), bot_output["buttons"])
                else:
                    # Fallback si pas d'URL
                    if bot_output.get("buttons"):
                        send_whatsapp_buttons(from_number, bot_output.get("response", ""), bot_output["buttons"])
                    else:
                        send_whatsapp_message(from_number, bot_output.get("response", ""))
            
            # 2. Location request
            elif bot_output.get("ask_location"):
                msg_txt = bot_output.get("response") or "📍 Merci de partager votre localisation."
                send_whatsapp_location_request(from_number, msg_txt)
            
            # 3. List
            elif "list" in bot_output:
                send_whatsapp_list(
                    from_number,
                    bot_output.get("response", ""),
                    bot_output["list"]["rows"],
                    bot_output["list"].get("title", "Missions"),
                    bot_output["list"].get("button", "Choisir")
                )
            
            # 4. Buttons
            elif bot_output.get("buttons"):
                send_whatsapp_buttons(from_number, bot_output.get("response", ""), bot_output["buttons"])
            
            # 5. Text simple
            else:
                send_whatsapp_message(from_number, bot_output.get("response", "❌ Erreur interne."))

        except Exception as e:
            logger.exception(f"[WA_WEBHOOK] Exception: {e}")
            # Track l'erreur
            analytics.track_error(
                error_type="webhook_exception",
                error_msg=str(e),
                phone=from_number if 'from_number' in locals() else None
            )

        return JsonResponse({"status": "ok"}, status=200)
