import os, requests
from typing import Optional, List
import mimetypes




ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"



def send_whatsapp_message(to, text):
    """Envoi d’un simple message texte WhatsApp"""
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API text:", res.text)
    return res.json()


def send_whatsapp_buttons(to, body_text, buttons):
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

    # Mapping automatique texte → id
    id_map = {
        "Confirmer": "btn_confirmer",
        "Annuler": "btn_annuler",
        "Cash": "btn_cash",
        "Mobile Money": "btn_mobile",
        "Virement": "btn_virement",
        "Nouvelle demande": "btn_1",
        "Suivre ma livraison": "btn_2",
        "Marketplace": "btn_3",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": id_map.get(b, b.lower()), "title": b}}
                    for b in buttons[:3]
                ]
            }
        }
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API boutons:", res.text)
    return res.json()

def send_whatsapp_location_request(to: str, message: str = "📍 Merci de partager votre localisation."):
    """Demande officielle de localisation (WhatsApp Cloud API)"""
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "location_request_message",
            "body": {
                "text": message
            },
            "action": {
                "name": "send_location"
            }
        }
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API location_request:", res.text)
    return res.json()

def send_whatsapp_media_url(to: str, media_url: str, kind: str = "image", caption: Optional[str] = None, filename: Optional[str] = None):
    """
    Envoie un média via une URL publique.
    kind ∈ {"image","video","document","audio"}.
    - image/video/document : supporte 'caption'
    - document : optionnel 'filename'
    """
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    kind = (kind or "image").lower().strip()
    if kind not in {"image", "video", "document", "audio"}:
        kind = "image"

    content = {"link": media_url}
    if caption and kind in {"image", "video", "document"}:
        content["caption"] = caption
    if filename and kind == "document":
        content["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": kind,
        kind: content
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API media_url:", res.text)
    return res.json()


def upload_media(file_path: str, mime: Optional[str] = None) -> dict:
    """
    Upload d’un fichier binaire vers WhatsApp pour obtenir un media_id réutilisable.
    Retourne le JSON de l’API (contient 'id' si OK).
    """
    if not PHONE_NUMBER_ID:
        raise RuntimeError("WHATSAPP_PHONE_NUMBER_ID non défini")

    upload_url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/media"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
    mime = mime or (mimetypes.guess_type(file_path)[0] or "application/octet-stream")

    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, mime),
            "messaging_product": (None, "whatsapp"),
        }
        res = requests.post(upload_url, headers=headers, files=files)
    print("Réponse API upload_media:", res.text)
    return res.json()  # ex: {"id":"MEDIA_ID"}


def send_whatsapp_media_id(to: str, media_id: str, kind: str = "image", caption: Optional[str] = None, filename: Optional[str] = None):
    """
    Envoie un média déjà uploadé (via son media_id).
    kind ∈ {"image","video","document","audio"}.
    - image/video/document : supporte 'caption'
    - document : optionnel 'filename'
    """
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    kind = (kind or "image").lower().strip()
    if kind not in {"image", "video", "document", "audio"}:
        kind = "image"

    content = {"id": media_id}
    if caption and kind in {"image", "video", "document"}:
        content["caption"] = caption
    if filename and kind == "document":
        content["filename"] = filename

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": kind,
        kind: content
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API media_id:", res.text)
    return res.json()

def send_whatsapp_list(to: str, body_text: str, rows: List[dict], title: str = "Options"):
    """
    Envoi d’un menu (list message) WhatsApp Cloud API.
    rows = [{"id": "accept_123", "title": "Accepter #123", "description": "Départ → Destination"}, ...]
    """
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {
                "button": "Choisir",
                "sections": [{
                    "title": title,
                    "rows": rows
                }]
            }
        }
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API list:", res.text)
    return res.json()

def dispatch_whatsapp_message(to: str, resp: dict):
    """
    Envoie la réponse générée par le bot via la bonne fonction WhatsApp.
    - Texte simple
    - Boutons
    - Demande de localisation
    - Listes (si resp['list'] existe)
    """
    text = resp.get("response", "")

    # Cas localisation
    if resp.get("location_request"):
        return send_whatsapp_location_request(to)

    # Cas boutons
    if "buttons" in resp:
        return send_whatsapp_buttons(to, text, resp["buttons"])

    # Cas liste (optionnel si tu ajoutes un flag 'list')
    if resp.get("list"):
        rows = resp["list"].get("rows", [])
        title = resp["list"].get("title", "Options")
        return send_whatsapp_list(to, text, rows, title=title)

    # Fallback texte
    return send_whatsapp_message(to, text)
