# chatbot/conversation_flow_marketplace.py
from __future__ import annotations
import os, logging, requests
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # fallback IA

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

# -----------------------------
# Helpers HTTP
# -----------------------------
def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-M] {method} {path} -> {r.status_code}")
    return r

# -----------------------------
# Flow utils
# -----------------------------
def _begin_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/categories/")
        r.raise_for_status()
        data = r.json()
        cats = data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.error(f"[MARKET] categories error: {e}")
        cats = []

    if not cats:
        session["step"] = "MENU"
        return build_response("❌ Aucune catégorie disponible pour le moment.", MAIN_MENU_BTNS)

    session["market_categories"] = {str(i + 1): c for i, c in enumerate(cats)}
    session["step"] = "MARKET_CATEGORY"

    lignes = [f"{i + 1}. {c.get('nom') or c.get('name') or '—'}" for i, c in enumerate(cats)]
    return build_response(
        "🛍️ *Marketplace*\n\n"
        "Choisissez une *catégorie* parmi celles disponibles :\n" + "\n".join(lignes),
        list(session["market_categories"].keys())
    )

def _merchant_display_name(ent: Dict[str, Any]) -> str:
    return (
        ent.get("nom_entreprise")
        or ent.get("nom")
        or ent.get("name")
        or ent.get("display_name")
        or ent.get("raison_sociale")
        or "—"
    )

def _merchant_pickup_info(ent: Dict[str, Any]) -> Tuple[str, str]:
    addr = ent.get("adresse") or ent.get("address") or ent.get("localisation") or _merchant_display_name(ent)
    lat = ent.get("latitude") or ent.get("lat")
    lng = ent.get("longitude") or ent.get("lng")
    coords = f"{lat},{lng}" if (lat is not None and lng is not None) else ""
    return str(addr), coords

def _cleanup_marketplace_session(session: Dict[str, Any]) -> None:
    session["step"] = "MENU"
    for k in [
        "new_request", "market_category", "market_categories",
        "market_merchant", "market_merchants",
        "market_products", "selected_product"
    ]:
        session.pop(k, None)

# -----------------------------
# Création commande
# -----------------------------
def marketplace_create_order(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        d = session.get("new_request", {})
        merchant = session.get("market_merchant", {})
        produit = session.get("selected_product", {})

        payload = {
            "entreprise": int(merchant.get("id", 0)),
            "adresse_livraison": d.get("depart") or "Adresse non précisée",
            "coordonnees_gps": d.get("coordonnees_gps") or "",
            "notes_client": d.get("description") or "",
            "details": [
                {"produit": int(produit.get("id", 0)), "quantite": 1}
            ]
        }

        r = api_request(session, "POST", "/api/v1/marketplace/commandes/", json=payload)
        r.raise_for_status()
        order = r.json()

        _cleanup_marketplace_session(session)

        msg = (
            "🎉 *Commande validée !*\n\n"
            f"🔖 Numéro de commande : *{order.get('numero_commande')}*\n"
            "🚚 Votre commande est en préparation, un livreur vous contactera bientôt.\n\n"
            "Merci de votre confiance 🙏"
        )
        return build_response(msg, MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[MARKET] create error: {e}")
        _cleanup_marketplace_session(session)
        return build_response("❌ Une erreur est survenue lors de la commande. Veuillez réessayer.", MAIN_MENU_BTNS)

# -----------------------------
# Flow Marketplace principal
# -----------------------------
def flow_marketplace_handle(session: Dict[str, Any], text: str,
                            lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    step = session.get("step")
    t = (normalize(text) or "").lower()

    # Démarrage
    if step not in {
        "MARKET_CATEGORY", "MARKET_MERCHANT", "MARKET_PRODUCTS",
        "MARKET_DESTINATION", "MARKET_PAY", "MARKET_CONFIRM", "MARKET_EDIT"
    }:
        return _begin_marketplace(session)

    # -------- CATEGORIES --------
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})
        if t not in categories:
            return build_response("⚠️ Choix invalide. Sélectionnez un numéro :", list(categories.keys()))
        selected = categories[t]
        session["market_category"] = selected
        session["step"] = "MARKET_MERCHANT"

        try:
            r = api_request(session, "GET", "/api/v1/auth/entreprises/")
            r.raise_for_status()
            data = r.json()
            ents = data.get("results", []) if isinstance(data, dict) else (data or [])
            merchants = [e for e in ents if e.get("type_entreprise") and str(e["type_entreprise"].get("id")) == str(selected["id"])]
        except Exception as e:
            logger.error(f"[MARKET] merchants error: {e}")
            merchants = []

        if not merchants:
            return build_response(f"❌ Aucun marchand trouvé dans *{selected.get('nom','—')}*.", list(categories.keys()))

        merchants = merchants[:5]
        session["market_merchants"] = {str(i + 1): m for i, m in enumerate(merchants)}
        lignes = [f"{i+1}. {_merchant_display_name(m)}" for i, m in enumerate(merchants)]
        return build_response(
            "🏬 *Marchands disponibles*\n\n" + "\n".join(lignes),
            list(session["market_merchants"].keys())
        )

    # -------- MARCHANDS --------
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})
        if t not in merchants:
            return build_response("⚠️ Choisissez un numéro valide :", list(merchants.keys()))
        merchant = merchants[t]
        session["market_merchant"] = merchant
        session["step"] = "MARKET_PRODUCTS"

        try:
            r = api_request(session, "GET", "/api/v1/marketplace/produits/")
            r.raise_for_status()
            data = r.json()
            produits = data.get("results", []) if isinstance(data, dict) else (data or [])
            produits = [p for p in produits if p.get("entreprise") == merchant["id"]]
        except Exception as e:
            logger.error(f"[MARKET] products error: {e}")
            produits = []

        if not produits:
            return build_response(f"❌ Aucun produit disponible chez *{_merchant_display_name(merchant)}*.", list(merchants.keys()))

        produits = produits[:5]
        session["market_products"] = {str(i+1): p for i,p in enumerate(produits)}
        lignes = []
        for i,p in enumerate(produits, start=1):
            ligne = f"{i}. {p.get('nom','—')} — {p.get('prix','0')} FCFA"
            if p.get("image"): ligne += f"\n🖼️ {p['image']}"
            lignes.append(ligne)

        return build_response(
            f"📦 *Produits de* {_merchant_display_name(merchant)} :\n\n" + "\n".join(lignes),
            list(session["market_products"].keys())
        )

    # -------- PRODUITS --------
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})
        if t not in produits:
            return build_response("⚠️ Choisissez un produit valide :", list(produits.keys()))
        produit = produits[t]
        session["selected_product"] = produit
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = produit.get("description","")
        session["new_request"]["value_fcfa"] = produit.get("prix",0)
        session["step"] = "MARKET_DESTINATION"
        resp = build_response("📍 *Adresse de livraison*\n\nEnvoyez votre adresse ou partagez votre localisation.")
        resp["ask_location"] = True
        return resp

    # -------- DESTINATION --------
    if step == "MARKET_DESTINATION":
        if lat is not None and lng is not None:
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text:
            session["new_request"]["depart"] = text
            session["new_request"]["coordonnees_gps"] = ""
        else:
            resp = build_response("❌ Veuillez indiquer une adresse ou partager votre localisation.")
            resp["ask_location"] = True
            return resp

        session["step"] = "MARKET_PAY"
        return build_response("💳 *Mode de paiement*\n\nChoisissez :", ["Espèces", "Mobile Money", "Virement"])

    # -------- PAIEMENT --------
    if step == "MARKET_PAY":
        mapping = {"espèces": "cash","especes": "cash","1":"cash",
                   "mobile money":"mobile_money","mobile":"mobile_money","2":"mobile_money",
                   "virement":"virement","3":"virement"}
        if t not in mapping:
            return build_response("⚠️ Choisissez un mode valide :", ["Espèces", "Mobile Money", "Virement"])
        session["new_request"]["payment_method"] = mapping[t]
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]
        merchant = session.get("market_merchant", {})
        pickup_addr, _ = _merchant_pickup_info(merchant)

        recap = (
            "📝 *Récapitulatif commande Marketplace*\n\n"
            f"🏬 Marchand : {_merchant_display_name(merchant)}\n"
            f"📦 Produit : {d.get('market_choice')} — {d.get('value_fcfa')} FCFA\n"
            f"🚏 Retrait : {pickup_addr}\n"
            f"📍 Livraison : {d.get('depart')}\n"
            f"💳 Paiement : {d.get('payment_method')}\n\n"
            "👉 Confirmez-vous la commande ?"
        )
        return build_response(recap, ["✅ Confirmer","❌ Annuler","✏️ Modifier"])

    # -------- CONFIRM --------
    if step == "MARKET_CONFIRM":
        if t in {"confirmer","oui"}: return marketplace_create_order(session)
        if t in {"annuler","non"}:
            _cleanup_marketplace_session(session)
            return build_response("❌ Commande annulée.\nRetour au menu principal.", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"] = "MARKET_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit","Paiement","Adresse","Annuler"])
        return build_response("👉 Répondez par : Confirmer, Annuler ou Modifier.", ["✅ Confirmer","❌ Annuler","✏️ Modifier"])

    # -------- EDIT --------
    if step == "MARKET_EDIT":
        if t == "produit":
            session["step"] = "MARKET_PRODUCTS"
            return build_response("📦 Choisissez un autre produit :", list(session.get("market_products",{}).keys()))
        if t == "paiement":
            session["step"] = "MARKET_PAY"
            return build_response("💳 Choisissez un autre mode de paiement :", ["Espèces","Mobile Money","Virement"])
        if t in {"adresse","adresse de livraison"}:
            session["step"] = "MARKET_DESTINATION"
            resp = build_response("📍 Indiquez la nouvelle adresse de livraison :")
            resp["ask_location"] = True
            return resp
        if t == "annuler":
            session["step"] = "MARKET_CONFIRM"
            return build_response("👉 Retour au récapitulatif.", ["✅ Confirmer","❌ Annuler","✏️ Modifier"])
        return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit","Paiement","Adresse","Annuler"])

    return ai_fallback(text, session.get("phone"))

# -----------------------------
# Wrapper
# -----------------------------
def handle_message(phone: str, text: str,
                   *, lat: Optional[float]=None,
                   lng: Optional[float]=None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_marketplace_handle(session, text, lat=lat, lng=lng)
