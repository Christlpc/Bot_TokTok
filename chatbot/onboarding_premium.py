# chatbot/onboarding_premium.py
"""
Expérience d'onboarding premium avec intelligence contextuelle.
"""
from typing import Dict, Any
from .auth_core import build_response


def welcome_first_time(user_name: str = "utilisateur") -> Dict[str, Any]:
    """Premier contact - Expérience découverte"""
    return build_response(
        f"👋 *Bienvenue sur TokTok, {user_name} !*\n\n"
        "🚚 *Votre service de livraison express à Brazzaville*\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Ce que nous faisons pour vous :*\n"
        "📦 Livraison de colis en ville\n"
        "🛍️ Commande & livraison de produits\n"
        "⚡ Suivi en temps réel\n\n"
        "✨ _Commençons ! Que souhaitez-vous faire ?_",
        ["📦 Envoyer un colis", "🛍️ Commander", "ℹ️ En savoir plus"]
    )


def welcome_returning(user_name: str, last_mission_ref: str = None,
                     pending_missions: int = 0) -> Dict[str, Any]:
    """Retour utilisateur - Contexte personnalisé"""
    
    greeting = f"👋 *Ravi de vous revoir, {user_name} !*\n\n"
    
    # Contexte personnalisé
    if pending_missions > 0:
        greeting += (
            f"📦 *Vous avez {pending_missions} livraison(s) en cours*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        buttons = [
            "🔍 Voir mes livraisons",
            "📦 Nouvelle demande",
            "🛍️ Marketplace"
        ]
    elif last_mission_ref:
        greeting += (
            f"✅ _Dernière mission :_ `{last_mission_ref}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        buttons = [
            "📦 Nouvelle demande",
            "🔍 Voir l'historique",
            "🛍️ Marketplace"
        ]
    else:
        greeting += "💡 _Que puis-je faire pour vous ?_\n\n"
        buttons = [
            "📦 Envoyer un colis",
            "🛍️ Commander",
            "🔍 Historique"
        ]
    
    return build_response(greeting, buttons)


def driver_dashboard(driver_name: str, available_missions: int,
                     completed_today: int, earnings_today: int) -> Dict[str, Any]:
    """Tableau de bord livreur - Stats en temps réel"""
    return build_response(
        f"🚴 *Tableau de bord - {driver_name}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📊 AUJOURD'HUI*\n"
        f"✅ Livraisons : *{completed_today}*\n"
        f"💰 Gains : *{earnings_today:,} FCFA*\n\n"
        "*📍 MISSIONS DISPONIBLES*\n"
        f"🔔 _{available_missions} mission(s) près de vous_\n\n"
        "💡 _Que souhaitez-vous faire ?_",
        ["🔍 Voir les missions", "📊 Mon historique", "⚙️ Paramètres"]
    )


def merchant_dashboard(merchant_name: str, pending_orders: int,
                       today_revenue: int, products_count: int) -> Dict[str, Any]:
    """Tableau de bord marchand - Vue business"""
    return build_response(
        f"🏪 *{merchant_name}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        "*📊 VUE D'ENSEMBLE*\n"
        f"🛒 Commandes en attente : *{pending_orders}*\n"
        f"💰 CA du jour : *{today_revenue:,} FCFA*\n"
        f"📦 Produits actifs : *{products_count}*\n\n"
        "💡 _Gestion de votre boutique_",
        ["🛒 Commandes", "📦 Produits", "📊 Statistiques"]
    )


def progress_indicator(current_step: int, total_steps: int, step_name: str) -> str:
    """
    Indicateur de progression visuel.
    
    Exemple: [▓▓▓▓▓▓░░░░] 60% - Validation
    """
    progress = current_step / total_steps
    filled = int(progress * 10)
    empty = 10 - filled
    bar = "▓" * filled + "░" * empty
    percentage = int(progress * 100)
    
    return f"[{bar}] {percentage}% · _{step_name}_\n\n"


def confirmation_with_visual(title: str, items: list, total: int = None,
                            action_buttons: list = None) -> str:
    """
    Récapitulatif visuel professionnel avec séparateurs.
    
    Args:
        title: Titre du récapitulatif
        items: Liste de tuples (label, value, emoji)
        total: Montant total optionnel
        action_buttons: Boutons d'action
    """
    msg = f"*{title}*\n"
    msg += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    for label, value, emoji in items:
        msg += f"{emoji} *{label}*\n"
        if isinstance(value, list):
            for item in value:
                msg += f"  • {item}\n"
        else:
            msg += f"_{value}_\n\n"
    
    if total is not None:
        msg += "━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"*💰 TOTAL : {total:,} FCFA*\n\n"
    
    msg += "✅ _Tout est correct ?_"
    
    return msg

