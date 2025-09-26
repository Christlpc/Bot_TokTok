# chatbot/conversation_flow_coursier.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # réutilise la fonction IA

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-C] {method} {path} -> {r.status_code}")
    return r

# ------------------------------------------------------
# Création de mission coursier
# ------------------------------------------------------
def courier_create(session: Dict[str, Any]) -> Dict[str, Any]:
    d = session.setdefault("new_request", {})
    try:
        if not d.get("destination") and not d.get("coordonnees_livraison"):
            session["step"] = "COURIER_DEST"
            return build_response(
                "⚠️ Destination manquante.\n"
                "📍 Merci d’indiquer une *adresse de livraison* ou de partager la localisation."
            )

        payload = {
            "entreprise_demandeur": (session.get("user") or {}).get("display_name") or "Client TokTok",
            "contact_entreprise": session.get("phone"),
            "adresse_recuperation": d.get("depart") or "",
            "coordonnees_recuperation": d.get("coordonnees_gps", ""),
            "adresse_livraison": d.get("destination") or "Position partagée",
            "coordonnees_livraison": d.get("coordonnees_livraison", ""),
            "nom_client_final": d.get("destinataire_nom") or "",
            "telephone_client_final": d.get("destinataire_tel") or "",
            "description_produit": d.get("description") or "",
            "valeur_produit": str(d.get("value_fcfa") or 0),
            "type_paiement": d.get("payment_method", "entreprise_paie"),
        }

        r = api_request(session, "POST", "/api/v1/coursier/missions/", json=payload)
        r.raise_for_status()
        mission = r.json()
        session["step"] = "MENU"

        ref = mission.get("numero_mission") or f"M-{mission.get('id','')}"
        msg = (
            "🎉 *Demande confirmée !*\n\n"
            f"🔖 Référence : *{ref}*\n"
            "🚴 Un livreur sera assigné très prochainement.\n\n"
            "Merci pour votre confiance 🙏"
        )
        return build_response(msg, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[COURIER create error] {e}")
        return build_response(
            "❌ Oups… une erreur est survenue lors de l’enregistrement de votre demande.\n"
            "👉 Veuillez réessayer dans un instant.",
            MAIN_MENU_BTNS
        )

# ------------------------------------------------------
# Gestion du flow coursier
# ------------------------------------------------------
def flow_coursier_handle(session: Dict[str, Any], text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    step = session.get("step")
    t = normalize(text).lower() if text else ""

    # Démarrage
    if step in {None, "MENU", "AUTHENTICATED"} and t in {"nouvelle demande", "1"}:
        session["step"] = "COURIER_DEPART"
        resp = build_response(
            "🚀 *Nouvelle demande de livraison*\n\n"
            "📍 Indiquez votre *adresse de départ* ou partagez directement votre localisation."
        )
        resp["ask_location"] = True
        return resp

    # Localisation partagée
    if lat is not None and lng is not None:
        if step == "COURIER_DEPART":
            nr = session.setdefault("new_request", {})
            nr["depart"] = "Position actuelle"
            nr["coordonnees_gps"] = f"{lat},{lng}"
            session["step"] = "COURIER_DEST"
            return build_response(
                "✅ Localisation de départ enregistrée.\n\n"
                "📍 Quelle est l’*adresse de destination* ?"
            )

        if step == "COURIER_DEST":
            nr = session.setdefault("new_request", {})
            nr["destination"] = "Position partagée"
            nr["coordonnees_livraison"] = f"{lat},{lng}"
            session["step"] = "DEST_NOM"
            return build_response(
                "✅ Destination enregistrée.\n\n"
                "👤 Quel est le *nom du destinataire* ?"
            )

    # Étapes classiques
    if step == "COURIER_DEPART":
        session.setdefault("new_request", {})["depart"] = text
        session["step"] = "COURIER_DEST"
        return build_response("📍 Merci. Indiquez maintenant l’*adresse de destination*.")

    if step == "COURIER_DEST":
        session["new_request"]["destination"] = text
        session["step"] = "DEST_NOM"
        return build_response("👤 Quel est le *nom du destinataire* ?")

    if step == "DEST_NOM":
        session["new_request"]["destinataire_nom"] = text
        session["step"] = "DEST_TEL"
        return build_response("📞 Merci. Entrez le *numéro de téléphone du destinataire*.")

    if step == "DEST_TEL":
        session["new_request"]["destinataire_tel"] = text
        session["step"] = "COURIER_VALUE"
        return build_response(
            "💰 Indiquez la *valeur du colis* (en FCFA).\n"
            "Exemple : *15000*"
        )

    if step == "COURIER_VALUE":
        digits = re.sub(r"[^0-9]", "", text)
        amt = int(digits) if digits else None
        if not amt:
            return build_response(
                "⚠️ Montant invalide.\n👉 Entrez un nombre uniquement (ex: *15000*)."
            )
        session["new_request"]["value_fcfa"] = amt
        session["step"] = "COURIER_DESC"
        return build_response("📦 Merci. Décrivez brièvement le contenu du colis.")

    if step == "COURIER_DESC":
        session["new_request"]["description"] = text
        session["step"] = "COURIER_CONFIRM"
        d = session["new_request"]
        dest_aff = "Position partagée" if d.get("coordonnees_livraison") else d.get("destination")
        recap = (
            "📝 *Récapitulatif de votre demande*\n\n"
            f"🚏 Départ : {d.get('depart')}\n"
            f"📍 Destination : {dest_aff}\n"
            f"👤 Destinataire : {d.get('destinataire_nom')} ({d.get('destinataire_tel')})\n"
            f"💰 Valeur : {d.get('value_fcfa')} FCFA\n"
            f"📦 Colis : {d.get('description')}\n\n"
            "👉 Confirmez-vous cette demande ?"
        )
        return build_response(recap, ["✅ Confirmer", "❌ Annuler", "✏️ Modifier"])

    if step == "COURIER_CONFIRM":
        if t in {"confirmer", "oui"}:
            return courier_create(session)
        if t in {"annuler", "non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("❌ Demande annulée.\nRetour au menu principal.", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"] = "COURIER_EDIT"
            return build_response(
                "✏️ Que souhaitez-vous modifier ?",
                ["Départ", "Destination", "Valeur", "Description", "Destinataire"]
            )

    # fallback IA
    return ai_fallback(text, session.get("phone"))

# ------------------------------------------------------
# Router
# ------------------------------------------------------
def handle_message(phone: str, text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_coursier_handle(session, text, lat=lat, lng=lng)
