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

# --- Helpers UI ---
def _fmt_fcfa(n: int | str | None) -> str:
    try:
        i = int(str(n or 0))
        # séparateur fin (espace insécable)
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n or 0)

def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-C] {method} {path} -> {r.status_code}")
    return r

# --- Création mission ---
def courier_create(session: Dict[str, Any]) -> Dict[str, Any]:
    d = session.setdefault("new_request", {})
    try:
        # Vérification minimum avant envoi
        if not d.get("destination") and not d.get("coordonnees_livraison"):
            session["step"] = "COURIER_DEST"
            return build_response("📍 Indiquez l’adresse de destination ou partagez la position du point de livraison.")

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
            "🎉 *Demande enregistrée !*\n"
            f"🔖 Référence : {ref}\n"
            "🚴 Un·e livreur·se prendra la course très bientôt. "
            "Vous recevrez une notification dès son affectation."
        )
        # On nettoie le brouillon pour la prochaine demande
        session.pop("new_request", None)
        return build_response(msg, MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[COURIER create error] {e}")
        return build_response(
            "😓 Impossible de créer la demande pour le moment.\n"
            "Réessayez dans un instant ou revenez au menu.",
            MAIN_MENU_BTNS
        )

# --- Flow principal ---
def flow_coursier_handle(session: Dict[str, Any], text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    step = session.get("step")
    t = normalize(text).lower() if text else ""

    # Raccourcis menu
    if t in {"menu", "accueil", "0"}:
        session["step"] = "MENU"
        session.pop("new_request", None)
        return build_response("🏠 Menu principal — que souhaitez-vous faire ?", MAIN_MENU_BTNS)

    # Début du flow
    if step in {None, "MENU", "AUTHENTICATED"} and t in {"nouvelle demande", "1"}:
        session["step"] = "COURIER_DEPART"
        resp = build_response(
            "📍 Top départ ! Où récupérer le colis ?\n"
            "• Envoyez *l’adresse* (ex. `10 Avenue de la Paix, BZV`)\n"
            "• ou *partagez votre position*."
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
                "✅ Position de départ enregistrée.\n"
                "🎯 Où livrer le colis ? Adresse ou partage de position."
            )

        if step == "COURIER_DEST":
            nr = session.setdefault("new_request", {})
            nr["destination"] = "Position partagée"
            nr["coordonnees_livraison"] = f"{lat},{lng}"
            session["step"] = "DEST_NOM"
            return build_response("✅ Destination enregistrée.\n👤 Quel est le *nom du destinataire* ?")

    # Étapes classiques
    if step == "COURIER_DEPART":
        session.setdefault("new_request", {})["depart"] = text
        session["step"] = "COURIER_DEST"
        return build_response("🎯 Et l’*adresse de destination* ? (ou partagez la position)")

    if step == "COURIER_DEST":
        session["new_request"]["destination"] = text
        session["step"] = "DEST_NOM"
        return build_response("👤 Quel est le *nom du destinataire* ?")

    if step == "DEST_NOM":
        session["new_request"]["destinataire_nom"] = text
        session["step"] = "DEST_TEL"
        return build_response("📞 Son *numéro de téléphone* ? (ex. `06 555 00 00`)")

    if step == "DEST_TEL":
        # on normalise léger pour l’affichage ultérieur (mais on n’impose pas de format)
        tel = re.sub(r"\s+", " ", text).strip()
        session["new_request"]["destinataire_tel"] = tel
        session["step"] = "COURIER_VALUE"
        return build_response("💰 Quelle est la *valeur estimée* du colis (en FCFA) ?\nEx. `15000`")

    if step == "COURIER_VALUE":
        digits = re.sub(r"[^0-9]", "", text or "")
        amt = int(digits) if digits else None
        if not amt:
            return build_response("⚠️ Montant invalide. Saisissez un nombre (ex. `15000`).")
        session["new_request"]["value_fcfa"] = amt
        session["step"] = "COURIER_DESC"
        return build_response("📦 Décrivez brièvement le colis (ex. *Dossier A4 scellé*, *Paquet 2 kg*).")

    if step == "COURIER_DESC":
        session["new_request"]["description"] = text
        session["step"] = "COURIER_CONFIRM"
        d = session["new_request"]
        dest_aff = "Position partagée" if d.get("coordonnees_livraison") else d.get("destination")
        recap = (
            "📝 *Récapitulatif*\n"
            f"• Départ : {d.get('depart')}\n"
            f"• Destination : {dest_aff}\n"
            f"• Destinataire : {d.get('destinataire_nom')} ({d.get('destinataire_tel')})\n"
            f"• Valeur : {_fmt_fcfa(d.get('value_fcfa'))} FCFA\n"
            f"• Description : {d.get('description')}\n\n"
            "Tout est bon ?"
        )
        return build_response(recap, ["Confirmer", "Modifier", "Annuler"])

    if step == "COURIER_CONFIRM":
        if t in {"confirmer", "oui", "ok"}:
            # message de transition doux
            return build_response("✨ Je finalise votre demande…") | courier_create(session)
        if t in {"annuler", "non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("✅ Demande annulée. Que souhaitez-vous faire ?", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"] = "COURIER_EDIT"
            return build_response(
                "✏️ Que voulez-vous modifier ?",
                ["Départ", "Destination", "Destinataire", "Valeur", "Description"]
            )

    # Si l’utilisateur demande une modification précise (micro-raccourcis)
    if step == "COURIER_EDIT":
        choice = t
        if "départ" in choice:
            session["step"] = "COURIER_DEPART"
            return build_response("✏️ Modif *Départ* — envoyez la nouvelle adresse, ou partagez votre position.")
        if "destination" in choice:
            session["step"] = "COURIER_DEST"
            return build_response("✏️ Modif *Destination* — envoyez la nouvelle adresse, ou partagez la position.")
        if "destinataire" in choice:
            session["step"] = "DEST_NOM"
            return build_response("✏️ Modif *Destinataire* — quel est le *nom* ?")
        if "valeur" in choice:
            session["step"] = "COURIER_VALUE"
            return build_response("✏️ Modif *Valeur* — montant en FCFA (ex. `15000`).")
        if "description" in choice:
            session["step"] = "COURIER_DESC"
            return build_response("✏️ Modif *Description* — décrivez le colis en une phrase.")
        # si choix non reconnu
        return build_response(
            "Je n’ai pas compris. Que voulez-vous modifier ?",
            ["Départ", "Destination", "Destinataire", "Valeur", "Description"]
        )

    # fallback IA (petite garde-fou UX)
    if text:
        return ai_fallback(text, session.get("phone"))
    return build_response("🤖 J’ai besoin d’une information pour continuer. Dites *Nouvelle demande* ou *Menu*.", MAIN_MENU_BTNS)

# --- Entrée principale ---
def handle_message(phone: str, text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_coursier_handle(session, text, lat=lat, lng=lng)
