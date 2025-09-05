# chatbot/utils.py
import requests
import os

# Ton Access Token permanent WhatsApp (EAA...)
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

# Phone Number ID de ton numéro WhatsApp (visible dans Meta Developer Console)
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

WHATSAPP_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"


def send_whatsapp_message(to, text):
    """Envoie un message texte WhatsApp via l'API Cloud."""
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,  # ex: "242061234567"
        "type": "text",
        "text": {"body": text}
    }
    res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
    try:
        res.raise_for_status()
    except Exception as e:
        print("Erreur envoi WhatsApp:", res.text)
    return res.json()
