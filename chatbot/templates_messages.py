# chatbot/templates_messages.py
"""
Templates WhatsApp pour messages professionnels et notifications temps réel.
Documentation: https://developers.facebook.com/docs/whatsapp/conversation-types
"""

def format_mission_created(mission_ref: str, depart: str, dest: str) -> str:
    """Message de confirmation de création de mission - Style Premium"""
    return (
        "🎉 *MISSION CRÉÉE AVEC SUCCÈS*\n\n"
        f"*Référence :* `{mission_ref}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📍 ITINÉRAIRE*\n"
        f"🚏 Départ : _{depart}_\n"
        f"🎯 Arrivée : _{dest}_\n\n"
        "*⏱️ STATUT ACTUEL*\n"
        f"🔍 _Recherche d'un livreur disponible..._\n\n"
        "💡 *Vous recevrez une notification dès qu'un livreur acceptera votre demande.*"
    )


def format_driver_assigned(mission_ref: str, driver_name: str, driver_phone: str, 
                           eta_minutes: int = 15) -> str:
    """Notification d'assignation de livreur avec contact"""
    return (
        "✅ *LIVREUR ASSIGNÉ !*\n\n"
        f"*Mission :* `{mission_ref}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🚴 VOTRE LIVREUR*\n"
        f"👤 *{driver_name}*\n"
        f"📱 `{driver_phone}`\n\n"
        f"*⏱️ TEMPS ESTIMÉ*\n"
        f"🕒 ~{eta_minutes} min pour arriver au point de départ\n\n"
        "💬 _Vous pouvez le contacter directement._"
    )


def format_status_update(mission_ref: str, old_status: str, new_status: str,
                         location: str = None) -> str:
    """Notification de changement de statut avec émojis dynamiques"""
    status_emoji = {
        "en_attente": "⏳",
        "assigned": "✅",
        "en_route": "🚴",
        "arrived_pickup": "📍",
        "picked_up": "📦",
        "arrived_delivery": "🏁",
        "delivered": "✅",
    }
    
    status_labels = {
        "en_attente": "En attente",
        "assigned": "Livreur assigné",
        "en_route": "En route vers le départ",
        "arrived_pickup": "Arrivé au point de départ",
        "picked_up": "Colis récupéré",
        "arrived_delivery": "Arrivé à destination",
        "delivered": "Livré avec succès",
    }
    
    emoji = status_emoji.get(new_status, "📍")
    label = status_labels.get(new_status, new_status)
    
    msg = (
        f"{emoji} *MISE À JOUR DE STATUT*\n\n"
        f"*Mission :* `{mission_ref}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*Statut :* _{label}_\n"
    )
    
    if location:
        msg += f"*Position :* _{location}_\n"
    
    return msg


def format_marketplace_order(order_ref: str, merchant_name: str, product_name: str,
                             price: int, delivery_address: str) -> str:
    """Confirmation de commande marketplace - Format facture"""
    return (
        "🛍️ *COMMANDE CONFIRMÉE*\n\n"
        f"*N° Commande :* `{order_ref}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "*🏪 MARCHAND*\n"
        f"_{merchant_name}_\n\n"
        "*📦 ARTICLE*\n"
        f"• {product_name}\n"
        f"• Prix : *{price:,} FCFA*\n\n"
        "*📍 LIVRAISON*\n"
        f"_{delivery_address}_\n\n"
        "*💳 PAIEMENT*\n"
        f"_À la livraison_\n\n"
        "✨ _Votre commande sera préparée et livrée dans les meilleurs délais._"
    )


def format_receipt(mission_ref: str, items: list, total: int, payment_method: str) -> str:
    """Reçu détaillé post-livraison"""
    items_text = "\n".join([f"• {item['name']}: {item['price']:,} FCFA" for item in items])
    
    return (
        "🧾 *REÇU DE LIVRAISON*\n\n"
        f"*Référence :* `{mission_ref}`\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "*DÉTAILS*\n"
        f"{items_text}\n\n"
        f"*TOTAL :* *{total:,} FCFA*\n"
        f"*Mode de paiement :* _{payment_method}_\n\n"
        "✅ _Merci d'avoir utilisé TokTok !_\n"
        "⭐ _N'hésitez pas à nous noter._"
    )


def format_error_user_friendly(error_type: str, context: str = "") -> str:
    """Messages d'erreur professionnels et rassurants"""
    errors = {
        "network": (
            "🔌 *Connexion temporaire*\n\n"
            "Nous rencontrons un petit souci de connexion.\n\n"
            "🔄 _Réessayez dans quelques instants._"
        ),
        "not_found": (
            f"🔍 *Élément introuvable*\n\n"
            f"_{context or 'Cet élément'} est introuvable._\n\n"
            "💡 _Vérifiez la référence ou contactez-nous._"
        ),
        "invalid_input": (
            "⚠️ *Format incorrect*\n\n"
            f"_{context}_\n\n"
            "💡 _Consultez l'exemple ci-dessus._"
        ),
        "unauthorized": (
            "🔒 *Accès restreint*\n\n"
            "Cette action nécessite des permissions spéciales.\n\n"
            "📞 _Contactez le support si nécessaire._"
        ),
    }
    
    return errors.get(error_type, errors["network"])

