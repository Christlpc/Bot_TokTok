import os, requests

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


def send_whatsapp_location_request(to):
    """Demande officielle de localisation (WhatsApp Cloud API)"""
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "location_request_message",
            "body": {
                "text": "📍 Merci de partager la *localisation de départ* du colis"
            },
            "action": {
                "name": "send_location"
            }
        }
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    print("Réponse API location_request:", res.text)
    return res.json()
