import os
import requests

ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

WHATSAPP_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_message(to, text):
    """Envoie un message texte simple."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
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
    """Envoie un message interactif avec boutons."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
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
                    {"type": "reply", "reply": {"id": f"btn_{i}", "title": b}}
                    for i, b in enumerate(buttons, 1)
                ]
            }
        }
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API boutons:", res.text)
    return res.json()


def send_whatsapp_location_request(to):
    """Invite l’utilisateur à partager sa localisation."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "📍 Merci de partager la localisation de départ du colis"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "share_location", "title": "Partager ma localisation"}},
                    {"type": "reply", "reply": {"id": "manual_address", "title": "Entrer une adresse manuellement"}},
                ]
            }
        }
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API location btn:", res.text)
    return res.json()
