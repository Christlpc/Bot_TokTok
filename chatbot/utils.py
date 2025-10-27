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

def send_whatsapp_contact(to: str, contact_name: str, contact_phone: str, message: Optional[str] = None):
    """
    Envoie une carte de contact WhatsApp
    
    Args:
        to: Numéro du destinataire
        contact_name: Nom du contact
        contact_phone: Numéro du contact (format international: +XXX...)
        message: Message optionnel avant la carte
    """
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    
    # Nettoyer le numéro de téléphone
    phone_clean = contact_phone.replace(" ", "").replace("+", "").replace("-", "")
    if not phone_clean.startswith("+"):
        phone_clean = f"+{phone_clean}"
    
    # Format du contact WhatsApp
    contact_payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "contacts",
        "contacts": [{
            "name": {
                "formatted_name": contact_name,
                "first_name": contact_name.split()[0] if contact_name else "Livreur"
            },
            "phones": [{
                "phone": phone_clean,
                "type": "CELL",
                "wa_id": phone_clean.replace("+", "")
            }]
        }]
    }
    
    # Envoyer le message d'abord si fourni
    if message:
        send_whatsapp_message(to, message)
    
    # Envoyer la carte de contact
    res = requests.post(WHATSAPP_URL, headers=headers, json=contact_payload)
    print("Réponse API contact:", res.text)
    return res.json()

def send_whatsapp_list(to: str, body_text: str, rows: List[dict], title: str = "Options", button: str = "Choisir"):
    """
    Envoi d'un menu (list message) WhatsApp Cloud API.
    rows = [{"id": "accept_123", "title": "Accepter #123", "description": "Départ → Destination"}, ...]
    button = Texte du bouton (par défaut "Choisir", max 20 chars)
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
                "button": button[:20],  # Max 20 caractères
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
    """
    text = resp.get("response", "")

    # Cas localisation
    if resp.get("ask_location"):
        return send_whatsapp_location_request(to)

    # ✅ Cas LISTE WhatsApp (NOUVEAU!)
    if resp.get("whatsapp_list"):
        list_config = resp["whatsapp_list"]
        rows = list_config.get("rows", [])
        title = list_config.get("title", "Options")
        return send_whatsapp_list(to, text, rows, title=title)

    # Cas boutons (limité à 3)
    if "buttons" in resp and resp["buttons"]:
        return send_whatsapp_buttons(to, text, resp["buttons"])

    # Fallback texte
    return send_whatsapp_message(to, text)