# chatbot/conversation_flow_marketplace.py
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
    logger.debug(f"[API-M] {method} {path} -> {r.status_code}")
    return r

def marketplace_create_as_coursier(session: Dict[str, Any]) -> Dict[str, Any]:
    # on réutilise courier_create logic (si tu veux)
    from .conversation_flow_coursier import courier_create
    return courier_create(session)

def flow_marketplace_handle(session: Dict[str, Any], text: str, lat: Optional[float]=None, lng: Optional[float]=None) -> Dict[str, Any]:
    step = session.get("step")
    t = normalize(text).lower() if text else ""

    # marketplace initial : choisir catégorie
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})
        if t not in categories:
            return build_response("⚠️ Catégorie invalide. Choisissez un numéro :", list(categories.keys()))
        selected = categories[t]
        session["market_category"] = selected
        session["step"] = "MARKET_MERCHANT"
        r = api_request(session, "GET", f"/api/v1/marketplace/merchants/?categorie={selected['id']}")
        data = r.json() if r.status_code == 200 else []
        merchants = data.get("results", []) if isinstance(data, dict) else data
        if not merchants:
            return build_response(f"❌ Aucun marchand dans la catégorie *{selected.get('nom')}*.", MAIN_MENU_BTNS)
        merchants = merchants[:5]
        session["market_merchants"] = {str(i+1): m for i,m in enumerate(merchants)}
        lignes = [f"{i+1}. {m.get('nom','—')}" for i,m in enumerate(merchants)]
        return build_response(f"🏬 Marchands disponibles :\n" + "\n".join(lignes),
                              list(session["market_merchants"].keys()))

    # choisir marchand
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})
        if t not in merchants:
            return build_response("⚠️ Choisissez un numéro valide de marchand.", list(merchants.keys()))
        merchant = merchants[t]
        session["market_merchant"] = merchant
        session["step"] = "MARKET_PRODUCTS"
        r = api_request(session, "GET", f"/api/v1/marketplace/produits/?merchant_id={merchant['id']}")
        data = r.json() if r.status_code == 200 else []
        produits = data.get("results", []) if isinstance(data, dict) else data
        if not produits:
            return build_response(f"❌ Aucun produit chez *{merchant.get('nom')}*.", MAIN_MENU_BTNS)
        produits = produits[:5]
        session["market_products"] = {str(i+1): p for i,p in enumerate(produits)}
        lignes = []
        for i,p in enumerate(produits, start=1):
            nom = p.get("nom","—")
            prix = p.get("prix","0")
            ligne = f"{i}. {nom} — {prix} FCFA"
            if p.get("photo_url"):
                ligne += f"\n🖼️ {p['photo_url']}"
            lignes.append(ligne)
        return build_response("📦 Produits :\n" + "\n".join(lignes),
                              list(session["market_products"].keys()))

    # choisir produit
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})
        if t not in produits:
            return build_response("⚠️ Choisissez un numéro valide de produit.", list(produits.keys()))
        produit = produits[t]
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = produit.get("description","")
        session["new_request"]["value_fcfa"] = produit.get("prix",0)
        session["step"] = "MARKETPLACE_LOCATION"
        resp = build_response("📍 Indiquez votre adresse de départ ou partagez votre localisation.")
        resp["ask_location"] = True
        return resp

    # localisation
    if step == "MARKETPLACE_LOCATION":
        if lat is not None and lng is not None:
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text:
            session["new_request"]["depart"] = text
        else:
            return build_response("❌ Veuillez fournir votre localisation.", MAIN_MENU_BTNS)
        session["step"] = "DEST_NOM"
        return build_response("👤 Quel est le *nom du destinataire* ?")

    # nom destinataire
    if step == "DEST_NOM":
        session["new_request"]["destinataire_nom"] = text
        session["step"] = "DEST_TEL"
        return build_response("📞 Quel est le *numéro de téléphone du destinataire* ?")

    # téléphone destinataire
    if step == "DEST_TEL":
        session["new_request"]["destinataire_tel"] = text
        session["step"] = "MARKET_PAY"
        return build_response("💳 Choisissez un mode de paiement :", ["Espèces", "Mobile Money", "Virement"])

    # paiement
    if step == "MARKET_PAY":
        mapping = {"espèces":"cash","mobile money":"mobile_money","virement":"virement"}
        if t not in mapping:
            return build_response("Merci de choisir un mode valide.", ["Espèces","Mobile Money","Virement"])
        session["new_request"]["payment_method"] = mapping[t]
        session["step"] = "MARKET_CONFIRM"
        d = session["new_request"]
        recap = (
            "📝 Récapitulatif de votre commande Marketplace :\n"
            f"• Produit : {d.get('market_choice')}\n"
            f"• Description : {d.get('description')}\n"
            f"• Paiement : {d.get('payment_method')}\n"
            "👉 Confirmez-vous la commande ?"
        )
        return build_response(recap, ["Confirmer","Annuler","Modifier"])

    # confirmation
    if step == "MARKET_CONFIRM":
        if t in {"confirmer","oui"}:
            return marketplace_create_as_coursier(session)
        if t in {"annuler","non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("❌ Commande annulée.", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"] = "MARKET_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit","Description","Paiement"])
        return build_response("👉 Répondez par Confirmer, Annuler ou Modifier.", ["Confirmer","Annuler","Modifier"])

    # fallback
    return ai_fallback(text, session.get("phone"))
