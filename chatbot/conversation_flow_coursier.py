# chatbot/conversation_flow_coursier.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional
from urllib.parse import quote_plus
from datetime import datetime
from openai import OpenAI
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT  = int(os.getenv("TOKTOK_TIMEOUT", "15"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
openai_client  = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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

def courier_create(session: Dict[str, Any]) -> Dict[str, Any]:
    d = session.setdefault("new_request", {})
    try:
        payload = {
            "entreprise_demandeur": (session.get("user") or {}).get("display_name") or "Client TokTok",
            "contact_entreprise": session.get("phone"),
            "adresse_recuperation": d.get("depart"),
            "coordonnees_recuperation": str(d.get("coordonnees_gps", "")),
            "adresse_livraison": d.get("destination"),
            "coordonnees_livraison": "",
            "nom_client_final": d.get("destinataire_nom"),
            "telephone_client_final": d.get("destinataire_tel"),
            "description_produit": d.get("description"),
            "valeur_produit": str(d.get("value_fcfa", 0)),
            "type_paiement": d.get("payment_method", "entreprise_paie"),
        }
        r = api_request(session, "POST", "/api/v1/coursier/missions/", json=payload)
        r.raise_for_status()
        mission = r.json()
        session["step"] = "MENU"

        ref = mission.get("numero_mission") or f"M-{mission.get('id','')}"
        msg = (
            "✅ Votre demande a été enregistrée.\n"
            f"🔖 Référence : {ref}\n"
            "🚴 Un livreur prendra en charge la course très bientôt."
        )
        return build_response(msg, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[COURIER] create error: {e}")
        return build_response("❌ Une erreur est survenue lors de la création de la demande.", MAIN_MENU_BTNS)

def flow_coursier_handle(session: Dict[str, Any], text: str, lat: Optional[float]=None, lng: Optional[float]=None) -> Dict[str, Any]:
    step = session.get("step")
    t = normalize(text).lower() if text else ""

    # localisation pour départ
    if lat is not None and lng is not None and step == "COURIER_DEPART":
        nr = session.setdefault("new_request", {})
        nr["depart"] = "Position actuelle"
        nr["coordonnees_gps"] = f"{lat},{lng}"
        session["step"] = "COURIER_DEST"
        return build_response("✅ Localisation enregistrée.\n📍 Quelle est l’adresse de destination ?")

    if step == "COURIER_DEPART":
        session.setdefault("new_request", {})["depart"] = text
        session["step"] = "COURIER_DEST"
        return build_response("📍 Quelle est l’adresse de destination ?")

    if step == "COURIER_DEST":
        session["new_request"]["destination"] = text
        session["step"] = "DEST_NOM"
        return build_response("👤 Quel est le *nom du destinataire* ?")

    if step == "DEST_NOM":
        session["new_request"]["destinataire_nom"] = text
        session["step"] = "DEST_TEL"
        return build_response("📞 Quel est le *numéro de téléphone du destinataire* ?")

    if step == "DEST_TEL":
        session["new_request"]["destinataire_tel"] = text
        session["step"] = "COURIER_VALUE"
        return build_response("💰 Quelle est la valeur du colis (en FCFA) ?")

    if step == "COURIER_VALUE":
        digits = re.sub(r"[^0-9]", "", text)
        amt = int(digits) if digits else None
        if not amt:
            return build_response("⚠️ Montant invalide. Entrez un nombre (ex: 15000).")
        session["new_request"]["value_fcfa"] = amt
        session["step"] = "COURIER_DESC"
        return build_response("📦 Merci. Décrivez brièvement le colis.")

    if step == "COURIER_DESC":
        session["new_request"]["description"] = text
        session["step"] = "COURIER_CONFIRM"
        d = session["new_request"]
        depart_aff = d.get("depart")
        recap = (
            "📝 Récapitulatif de votre demande :\n"
            f"• Départ : {depart_aff}\n"
            f"• Destination : {d.get('destination')}\n"
            f"• Destinataire : {d.get('destinataire_nom')} ({d.get('destinataire_tel')})\n"
            f"• Valeur : {d.get('value_fcfa')} FCFA\n"
            f"• Description : {d.get('description')}\n\n"
            "👉 Confirmez-vous cette demande ?"
        )
        return build_response(recap, ["Confirmer", "Annuler", "Modifier"])

    if step == "COURIER_CONFIRM":
        if t in {"confirmer", "oui"}:
            return courier_create(session)
        if t in {"annuler", "non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("✅ Demande annulée.", MAIN_MENU_BTNS)

    # si pas match, revenir au fallback
    return ai_fallback(text, session.get("phone"))
