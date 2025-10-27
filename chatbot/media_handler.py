# chatbot/media_handler.py
"""
Gestionnaire de médias pour enrichir l'expérience utilisateur.
Documentation: https://developers.facebook.com/docs/whatsapp/conversation-types
"""
import os
import logging
from .utils import send_whatsapp_media_url

logger = logging.getLogger(__name__)


def send_product_with_image(to: str, product: dict) -> dict:
    """
    Envoie un produit avec son image et description formatée.
    
    Args:
        to: Numéro WhatsApp du destinataire
        product: Dict contenant {nom, prix, description, photo_url}
    
    Returns:
        Response de l'API WhatsApp
    """
    nom = product.get("nom", "Produit")
    prix = product.get("prix", 0)
    description = product.get("description", "")
    photo_url = product.get("photo_url")
    
    # Caption formatée professionnellement
    caption = (
        f"*{nom}*\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 *{prix:,} FCFA*\n\n"
    )
    
    if description:
        caption += f"_{description}_\n\n"
    
    caption += "🛒 _Tapez le numéro pour commander_"
    
    # Si pas d'image, envoyer juste le texte
    if not photo_url:
        from .utils import send_whatsapp_message
        return send_whatsapp_message(to, caption)
    
    # Envoyer l'image avec caption
    try:
        return send_whatsapp_media_url(
            to=to,
            media_url=photo_url,
            kind="image",
            caption=caption
        )
    except Exception as e:
        logger.error(f"[MEDIA] Failed to send product image: {e}")
        # Fallback sur texte
        from .utils import send_whatsapp_message
        return send_whatsapp_message(to, caption)


def send_delivery_map(to: str, mission_ref: str, pickup_coords: str, 
                      delivery_coords: str) -> dict:
    """
    Envoie une carte avec l'itinéraire de livraison.
    
    Utilise l'API WhatsApp Location Message pour partager:
    - Point de départ (pickup)
    - Point d'arrivée (delivery)
    """
    # TODO: Implémenter envoi de location WhatsApp
    # https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages#location-object
    pass


def send_receipt_pdf(to: str, mission_ref: str, receipt_data: dict) -> dict:
    """
    Génère et envoie un reçu PDF professionnel.
    
    Args:
        to: Numéro WhatsApp
        mission_ref: Référence de la mission
        receipt_data: Données du reçu (items, total, etc.)
    
    Returns:
        Response API WhatsApp
    """
    # TODO: Générer PDF avec reportlab ou weasyprint
    # Puis uploader et envoyer via send_whatsapp_media_url
    pass


def send_driver_contact_card(to: str, driver_name: str, driver_phone: str) -> dict:
    """
    Envoie une carte de contact du livreur.
    
    Documentation: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/messages#contacts-object
    """
    from .utils import ACCESS_TOKEN, PHONE_NUMBER_ID, WHATSAPP_URL
    import requests
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "contacts",
        "contacts": [{
            "name": {
                "formatted_name": driver_name,
                "first_name": driver_name.split()[0] if driver_name else "Livreur"
            },
            "phones": [{
                "phone": driver_phone,
                "type": "CELL",
                "wa_id": driver_phone
            }]
        }]
    }
    
    try:
        res = requests.post(WHATSAPP_URL, headers=headers, json=payload)
        logger.info(f"[MEDIA] Contact card sent: {res.status_code}")
        return res.json()
    except Exception as e:
        logger.error(f"[MEDIA] Failed to send contact card: {e}")
        return {}

