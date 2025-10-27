# chatbot/notifications.py
"""
Système de notifications enrichies pour TokTok Delivery
Envoie des notifications formatées aux clients lors des changements de statut
"""

import logging
from typing import Dict, Any, Optional
from .utils import send_whatsapp_message, send_whatsapp_contact

logger = logging.getLogger(__name__)


def _fmt_fcfa(n: int | str | None) -> str:
    """Formate un montant en FCFA avec séparateurs"""
    try:
        i = int(str(n or 0))
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n or 0)


def notify_mission_accepted(client_phone: str, mission_data: Dict[str, Any]) -> bool:
    """
    Notifie le client qu'un livreur a accepté sa mission
    
    Args:
        client_phone: Numéro du client
        mission_data: Données de la mission (doit contenir livreur info)
    
    Returns:
        bool: True si envoyé avec succès
    """
    try:
        mission_ref = mission_data.get("numero_mission", "—")
        livreur_nom = mission_data.get("livreur_nom", "Un livreur")
        livreur_tel = mission_data.get("livreur_telephone", "")
        depart = mission_data.get("adresse_recuperation", "—")
        destination = mission_data.get("adresse_livraison", "—")
        
        message = (
            "✅ *MISSION ACCEPTÉE !*\n\n"
            f"*Référence :* `{mission_ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚴 *Livreur :* {livreur_nom}\n"
        )
        
        if livreur_tel:
            message += f"📞 *Tél :* `{livreur_tel}`\n"
        
        message += (
            "\n*📍 ITINÉRAIRE*\n"
            f"🚏 Départ : _{depart}_\n"
            f"🎯 Arrivée : _{destination}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ *Statut :* _En route vers le point de départ_\n\n"
            "💡 _Vous serez notifié à chaque étape de la livraison._"
        )
        
        send_whatsapp_message(client_phone, message)
        
        # Envoyer automatiquement la carte de contact du livreur
        if livreur_tel:
            try:
                contact_message = f"📇 *Contact de votre livreur*\n\n_Enregistrez ce contact pour communiquer facilement._"
                send_whatsapp_contact(
                    client_phone,
                    livreur_nom,
                    livreur_tel,
                    contact_message
                )
                logger.info(f"[NOTIF] Driver contact card sent to {client_phone}")
            except Exception as e:
                logger.warning(f"[NOTIF] Could not send driver contact: {e}")
        
        logger.info(f"[NOTIF] Mission accepted notification sent to {client_phone}")
        return True
        
    except Exception as e:
        logger.exception(f"[NOTIF] Error sending mission_accepted: {e}")
        return False


def notify_pickup_arrived(client_phone: str, mission_data: Dict[str, Any]) -> bool:
    """
    Notifie le client que le livreur est arrivé au point de départ
    
    Args:
        client_phone: Numéro du client
        mission_data: Données de la mission
    
    Returns:
        bool: True si envoyé avec succès
    """
    try:
        mission_ref = mission_data.get("numero_mission", "—")
        livreur_nom = mission_data.get("livreur_nom", "Le livreur")
        depart = mission_data.get("adresse_recuperation", "—")
        
        message = (
            "📍 *LIVREUR ARRIVÉ !*\n\n"
            f"*Référence :* `{mission_ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚴 *{livreur_nom}* est arrivé au point de départ :\n"
            f"📍 _{depart}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ *Statut :* _Récupération du colis en cours_\n\n"
            "💡 _Le colis sera bientôt en route vers sa destination._"
        )
        
        send_whatsapp_message(client_phone, message)
        logger.info(f"[NOTIF] Pickup arrived notification sent to {client_phone}")
        return True
        
    except Exception as e:
        logger.exception(f"[NOTIF] Error sending pickup_arrived: {e}")
        return False


def notify_in_transit(client_phone: str, mission_data: Dict[str, Any]) -> bool:
    """
    Notifie le client que le colis est en transit
    
    Args:
        client_phone: Numéro du client
        mission_data: Données de la mission
    
    Returns:
        bool: True si envoyé avec succès
    """
    try:
        mission_ref = mission_data.get("numero_mission", "—")
        livreur_nom = mission_data.get("livreur_nom", "Le livreur")
        destination = mission_data.get("adresse_livraison", "—")
        destinataire_nom = mission_data.get("nom_client_final", "")
        
        message = (
            "🚚 *COLIS EN TRANSIT !*\n\n"
            f"*Référence :* `{mission_ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚴 *{livreur_nom}* a récupéré le colis.\n\n"
            "*🎯 Destination :*\n"
            f"📍 _{destination}_\n"
        )
        
        if destinataire_nom:
            message += f"👤 Destinataire : *{destinataire_nom}*\n"
        
        message += (
            "\n━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ *Statut :* _En route vers la destination_\n\n"
            "💡 _Vous recevrez une notification dès l'arrivée._"
        )
        
        send_whatsapp_message(client_phone, message)
        logger.info(f"[NOTIF] In transit notification sent to {client_phone}")
        return True
        
    except Exception as e:
        logger.exception(f"[NOTIF] Error sending in_transit: {e}")
        return False


def notify_delivered(client_phone: str, mission_data: Dict[str, Any]) -> bool:
    """
    Notifie le client que la livraison est terminée
    
    Args:
        client_phone: Numéro du client
        mission_data: Données de la mission
    
    Returns:
        bool: True si envoyé avec succès
    """
    try:
        mission_ref = mission_data.get("numero_mission", "—")
        livreur_nom = mission_data.get("livreur_nom", "Le livreur")
        destination = mission_data.get("adresse_livraison", "—")
        valeur = mission_data.get("valeur_produit", 0)
        
        message = (
            "🎉 *LIVRAISON TERMINÉE !*\n\n"
            f"*Référence :* `{mission_ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "✅ Votre colis a été livré avec succès !\n\n"
            "*📍 LIVRAISON*\n"
            f"📍 _{destination}_\n"
            f"🚴 Livreur : {livreur_nom}\n\n"
        )
        
        if valeur:
            message += f"💰 Valeur : {_fmt_fcfa(valeur)} FCFA\n\n"
        
        message += (
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⭐ *Merci d'avoir utilisé TokTok Delivery !*\n\n"
            "💡 _N'hésitez pas à refaire appel à nous pour vos prochaines livraisons._"
        )
        
        send_whatsapp_message(client_phone, message)
        logger.info(f"[NOTIF] Delivered notification sent to {client_phone}")
        return True
        
    except Exception as e:
        logger.exception(f"[NOTIF] Error sending delivered: {e}")
        return False


def notify_order_confirmed(client_phone: str, order_data: Dict[str, Any]) -> bool:
    """
    Notifie le client que sa commande marketplace a été confirmée par le marchand
    
    Args:
        client_phone: Numéro du client
        order_data: Données de la commande
    
    Returns:
        bool: True si envoyé avec succès
    """
    try:
        order_ref = order_data.get("numero_commande", "—")
        merchant_name = order_data.get("entreprise_nom", "Le marchand")
        product_name = order_data.get("produit_nom", "—")
        quantity = order_data.get("quantite", 1)
        total = order_data.get("total", 0)
        
        message = (
            "✅ *COMMANDE CONFIRMÉE !*\n\n"
            f"*Référence :* `{order_ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏪 *{merchant_name}* a confirmé votre commande.\n\n"
            "*📦 PRODUIT*\n"
            f"_{product_name}_\n"
            f"• Quantité : *{quantity}*\n"
            f"• Total : *{_fmt_fcfa(total)} FCFA*\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ *Statut :* _Préparation en cours_\n\n"
            "💡 _Vous serez notifié quand la commande sera prête._"
        )
        
        send_whatsapp_message(client_phone, message)
        logger.info(f"[NOTIF] Order confirmed notification sent to {client_phone}")
        return True
        
    except Exception as e:
        logger.exception(f"[NOTIF] Error sending order_confirmed: {e}")
        return False


def notify_order_ready(client_phone: str, order_data: Dict[str, Any]) -> bool:
    """
    Notifie le client que sa commande est prête
    
    Args:
        client_phone: Numéro du client
        order_data: Données de la commande
    
    Returns:
        bool: True si envoyé avec succès
    """
    try:
        order_ref = order_data.get("numero_commande", "—")
        merchant_name = order_data.get("entreprise_nom", "Le marchand")
        pickup_address = order_data.get("adresse_retrait", "—")
        
        message = (
            "📦 *COMMANDE PRÊTE !*\n\n"
            f"*Référence :* `{order_ref}`\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏪 *{merchant_name}*\n"
            "Votre commande est prête !\n\n"
            "*📍 RETRAIT*\n"
            f"📍 _{pickup_address}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏱️ *Statut :* _En attente de livraison_\n\n"
            "💡 _Un livreur va bientôt prendre en charge votre commande._"
        )
        
        send_whatsapp_message(client_phone, message)
        logger.info(f"[NOTIF] Order ready notification sent to {client_phone}")
        return True
        
    except Exception as e:
        logger.exception(f"[NOTIF] Error sending order_ready: {e}")
        return False

