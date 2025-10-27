# chatbot/template_messages.py
"""
Messages Template WhatsApp pour notifications proactives
Permet d'envoyer des messages hors de la fenêtre de 24h

Documentation WhatsApp Template Messages:
https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates
"""

import os
import logging
import requests
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"


def send_template_message(
    to: str,
    template_name: str,
    language_code: str = "fr",
    components: Optional[List[Dict]] = None
) -> Dict[str, Any]:
    """
    Envoie un message template WhatsApp approuvé
    
    Args:
        to: Numéro du destinataire (sans +)
        template_name: Nom du template approuvé par Meta
        language_code: Code langue (fr, en, etc.)
        components: Composants du template (header, body, buttons variables)
    
    Returns:
        Response JSON de WhatsApp API
    
    Example:
        # Template simple sans variables
        send_template_message(
            "21651832756",
            "hello_world",
            "fr"
        )
        
        # Template avec variables
        send_template_message(
            "21651832756",
            "order_confirmation",
            "fr",
            components=[
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "Jean"},
                        {"type": "text", "text": "CMD-123"}
                    ]
                }
            ]
        )
    """
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": language_code
            }
        }
    }
    
    if components:
        payload["template"]["components"] = components
    
    try:
        response = requests.post(WHATSAPP_URL, headers=headers, json=payload)
        logger.info(f"[TEMPLATE] Sent {template_name} to {to}: {response.status_code}")
        print(f"Réponse API template: {response.text}")
        return response.json()
    except Exception as e:
        logger.exception(f"[TEMPLATE] Error sending template: {e}")
        return {"error": str(e)}


# === TEMPLATES PRÉDÉFINIS (À créer dans Meta Business Manager) ===

def send_mission_reminder(client_phone: str, mission_ref: str, driver_name: str) -> Dict:
    """
    Rappel de mission en cours
    
    Template à créer dans Meta:
    Nom: mission_reminder
    Catégorie: UTILITY
    Langue: Français
    
    Body:
    Bonjour {{1}}, votre livraison {{2}} est en cours avec le livreur {{3}}.
    Suivez votre colis en temps réel sur TokTok Delivery.
    
    Buttons:
    1. [URL] Suivre ma livraison
    """
    return send_template_message(
        client_phone,
        "mission_reminder",
        "fr",
        components=[{
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Client"},  # {{1}}
                {"type": "text", "text": mission_ref},  # {{2}}
                {"type": "text", "text": driver_name}  # {{3}}
            ]
        }]
    )


def send_delivery_delayed(client_phone: str, mission_ref: str, new_eta: str) -> Dict:
    """
    Notification de retard de livraison
    
    Template à créer dans Meta:
    Nom: delivery_delayed
    Catégorie: UTILITY
    Langue: Français
    
    Body:
    Votre livraison {{1}} est retardée. Nouvelle heure d'arrivée estimée: {{2}}.
    Nous nous excusons pour le désagrément.
    
    Buttons:
    1. [QUICK_REPLY] Contacter le support
    """
    return send_template_message(
        client_phone,
        "delivery_delayed",
        "fr",
        components=[{
            "type": "body",
            "parameters": [
                {"type": "text", "text": mission_ref},
                {"type": "text", "text": new_eta}
            ]
        }]
    )


def send_payment_reminder(client_phone: str, order_ref: str, amount: str) -> Dict:
    """
    Rappel de paiement
    
    Template à créer dans Meta:
    Nom: payment_reminder
    Catégorie: UTILITY
    Langue: Français
    
    Body:
    Rappel: Le paiement de {{1}} FCFA pour la commande {{2}} est en attente.
    Merci de finaliser votre paiement.
    
    Buttons:
    1. [URL] Payer maintenant
    2. [QUICK_REPLY] Besoin d'aide
    """
    return send_template_message(
        client_phone,
        "payment_reminder",
        "fr",
        components=[{
            "type": "body",
            "parameters": [
                {"type": "text", "text": amount},
                {"type": "text", "text": order_ref}
            ]
        }]
    )


def send_feedback_request(client_phone: str, driver_name: str) -> Dict:
    """
    Demande d'avis après livraison
    
    Template à créer dans Meta:
    Nom: feedback_request
    Catégorie: UTILITY
    Langue: Français
    
    Body:
    Votre livraison avec {{1}} est terminée! 
    Aidez-nous à améliorer notre service en nous donnant votre avis.
    
    Buttons:
    1. [QUICK_REPLY] ⭐⭐⭐⭐⭐ Excellent
    2. [QUICK_REPLY] ⭐⭐⭐⭐ Bien
    3. [QUICK_REPLY] ⭐⭐⭐ Moyen
    """
    return send_template_message(
        client_phone,
        "feedback_request",
        "fr",
        components=[{
            "type": "body",
            "parameters": [
                {"type": "text", "text": driver_name}
            ]
        }]
    )


def send_promotional_offer(client_phone: str, offer_code: str, discount: str) -> Dict:
    """
    Offre promotionnelle
    
    Template à créer dans Meta:
    Nom: promotional_offer
    Catégorie: MARKETING
    Langue: Français
    
    Header:
    [IMAGE] URL de l'image promotionnelle
    
    Body:
    🎉 Offre spéciale! Bénéficiez de {{1}} de réduction avec le code {{2}}.
    Valable jusqu'à la fin du mois.
    
    Buttons:
    1. [URL] Commander maintenant
    2. [QUICK_REPLY] Plus d'infos
    """
    return send_template_message(
        client_phone,
        "promotional_offer",
        "fr",
        components=[{
            "type": "body",
            "parameters": [
                {"type": "text", "text": discount},
                {"type": "text", "text": offer_code}
            ]
        }]
    )


# === GUIDE DE CRÉATION DE TEMPLATES ===

TEMPLATE_CREATION_GUIDE = """
╔════════════════════════════════════════════════════════════════╗
║  GUIDE: Créer des Templates WhatsApp dans Meta Business Manager  ║
╚════════════════════════════════════════════════════════════════╝

1. ACCÉDER À META BUSINESS MANAGER
   • Aller sur https://business.facebook.com
   • Sélectionner votre compte WhatsApp Business
   • Aller dans "Message Templates"

2. CRÉER UN NOUVEAU TEMPLATE
   • Cliquer sur "Create Template"
   • Choisir un nom (snake_case, ex: mission_reminder)
   • Sélectionner la catégorie:
     - UTILITY: Notifications transactionnelles
     - MARKETING: Offres commerciales
     - AUTHENTICATION: OTP et codes

3. STRUCTURE D'UN TEMPLATE

   HEADER (Optionnel):
   • Text: Titre court
   • Image/Video: Média statique
   • Document: PDF ou fichier

   BODY (Requis):
   • Message principal
   • Variables: {{1}}, {{2}}, {{3}}...
   • Max 1024 caractères
   • Formatage: *bold*, _italic_

   FOOTER (Optionnel):
   • Petit texte en bas
   • Pas de variables
   • Ex: "TokTok Delivery - À votre service"

   BUTTONS (Optionnel):
   • QUICK_REPLY: Réponse rapide (max 3)
   • CALL: Appel téléphonique (max 1)
   • URL: Lien web (max 2)

4. EXEMPLES DE TEMPLATES UTILES

   📦 MISSION_ACCEPTED
   -------------------
   Catégorie: UTILITY
   Body: Bonne nouvelle! Le livreur {{1}} a accepté votre mission {{2}}.
         Suivez votre livraison en temps réel.
   Button: [URL] Suivre ma livraison

   🎉 ORDER_CONFIRMED
   ------------------
   Catégorie: UTILITY
   Body: Votre commande {{1}} a été confirmée par {{2}}.
         Montant: {{3}} FCFA. Préparation en cours.
   Button: [QUICK_REPLY] Voir détails

   📍 DRIVER_NEARBY
   ----------------
   Catégorie: UTILITY
   Body: Votre livreur {{1}} arrive dans {{2}} minutes!
         Préparez-vous à recevoir votre colis.
   Buttons: 
     [CALL] Appeler le livreur
     [QUICK_REPLY] J'ai un problème

   ⭐ FEEDBACK_REQUEST
   -------------------
   Catégorie: UTILITY
   Body: Votre livraison est terminée! Comment évaluez-vous {{1}}?
   Buttons:
     [QUICK_REPLY] ⭐⭐⭐⭐⭐ Excellent
     [QUICK_REPLY] ⭐⭐⭐⭐ Bien
     [QUICK_REPLY] ⭐⭐⭐ Moyen

   🎁 PROMOTIONAL_OFFER
   --------------------
   Catégorie: MARKETING
   Header: [IMAGE] Promo banner
   Body: 🎉 Offre spéciale! {{1}} de réduction avec le code {{2}}.
         Valable jusqu'au {{3}}.
   Button: [URL] Commander maintenant

5. PROCESSUS D'APPROBATION
   • Soumettre le template pour révision
   • Délai: 24-48h généralement
   • Status: Pending → Approved/Rejected
   • Si rejeté: Modifier et resoumettre

6. BONNES PRATIQUES
   ✅ Utiliser un langage clair et professionnel
   ✅ Éviter les fautes d'orthographe
   ✅ Tester avec des vraies données
   ✅ Respecter les règles WhatsApp (pas de spam)
   ✅ Limiter les variables (max 5 par template)
   
   ❌ Pas de contenu promotionnel dans UTILITY
   ❌ Pas de langage agressif ou trompeur
   ❌ Pas de demande d'informations sensibles
   ❌ Pas de liens raccourcis ou suspects

7. INTÉGRATION DANS LE CODE
   
   from chatbot.template_messages import send_template_message
   
   # Envoyer un template
   send_template_message(
       "21651832756",
       "mission_accepted",
       "fr",
       components=[{
           "type": "body",
           "parameters": [
               {"type": "text", "text": "Jean Malonga"},
               {"type": "text", "text": "COUR-123"}
           ]
       }]
   )

8. LIMITATIONS
   • Templates: Illimités
   • Messages/mois: Selon tier WhatsApp Business
   • Variables par body: Max 10
   • Boutons: Max 3 (ou 2 URL + 1 CALL)
   • Caractères body: Max 1024
   • Caractères header: Max 60

9. COÛTS (Approximatif)
   • Templates UTILITY: ~0.005 USD/message
   • Templates MARKETING: ~0.01-0.015 USD/message
   • Varie selon le pays destinataire

10. SUPPORT & RESSOURCES
    • Doc officielle: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-message-templates
    • Support Meta Business: https://business.facebook.com/help
    • Limites et pricing: https://developers.facebook.com/docs/whatsapp/pricing
"""

# Pour afficher le guide:
# print(TEMPLATE_CREATION_GUIDE)

