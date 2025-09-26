# chatbot/conversation_flow_marketplace.py
from __future__ import annotations
import os, logging, requests
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # réutilise le même fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT  = int(os.getenv("TOKTOK_TIMEOUT", "15"))

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
# Data loaders
# -----------------------------
def _load_categories(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/categories/")
        if r.ok:
            data = r.json()
            return data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.warning(f"[MARKET] categories endpoint failed: {e}")
    return []

def _load_merchants_by_category(session: Dict[str, Any], category: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        r = api_request(session, "GET", "/api/v1/auth/entreprises/")
        if not r.ok:
            return []
        data = r.json()
        ents = data.get("results", []) if isinstance(data, dict) else (data or [])
        cid = category.get("id")
        cname = (category.get("nom") or category.get("name") or "").strip().lower()

        def _match(ent: Dict[str, Any]) -> bool:
            te = ent.get("type_entreprise")
            if isinstance(te, dict):
                tid = str(te.get("id") or te.get("code") or te.get("slug") or "")
                tnom = (te.get("nom") or te.get("name") or "").strip().lower()
                return (cid and tid == str(cid)) or (cname and tnom == cname)
            if isinstance(te, (str, int)):
                return (cid and str(te) == str(cid)) or (cname and str(te).lower() == cname)
            return False

        return [e for e in ents if _match(e)]
    except Exception as e:
        logger.error(f"[MARKET] load merchants failed: {e}")
        return []

# -----------------------------
# Utils affichage
# -----------------------------
def _merchant_display_name(ent: Dict[str, Any]) -> str:
    return (
        ent.get("nom_entreprise")
        or ent.get("nom")
        or ent.get("name")
        or ent.get("display_name")
        or "—"
    )

def _merchant_pickup_info(ent: Dict[str, Any]) -> Tuple[str, str]:
    addr = ent.get("adresse") or ent.get("localisation") or _merchant_display_name(ent)
    coords = ent.get("coordonnees_gps", "")
    return str(addr), coords

# -----------------------------
# Création commande Marketplace
# -----------------------------
def marketplace_create_order(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        d = session.get("new_request", {})
        merchant = session.get("market_merchant", {})
        produit = session.get("selected_product", {})

        payload = {
            "entreprise": merchant.get("id"),
            "adresse_livraison": d.get("depart", ""),
            "coordonnees_gps": d.get("coordonnees_gps", ""),
            "notes_client": d.get("description", ""),
            "details": [
                {"produit": produit.get("id"), "quantite": 1}
            ]
        }

        logger.debug(f"[MARKET] Payload commande: {payload}")
        r = api_request(session, "POST", "/api/v1/marketplace/commandes/", json=payload)
        r.raise_for_status()
        order = r.json()
        session["step"] = "MENU"

        msg = (
            "✅ Votre commande Marketplace a été enregistrée.\n"
            f"🔖 Numéro: {order.get('id')}\n"
            "🚚 Un livreur prendra en charge la livraison très bientôt."
        )
        return build_response(msg, MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[MARKET] create error: {e}")
        return build_response("❌ Une erreur est survenue lors de la création de la commande.", MAIN_MENU_BTNS)

# -----------------------------
# Flow principal Marketplace
# -----------------------------
def flow_marketplace_handle(session: Dict[str, Any], text: str,
                            lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    step = session.get("step")
    t = (normalize(text) or "").lower()

    if step not in {"MARKET_CATEGORY","MARKET_MERCHANT","MARKET_PRODUCTS",
                    "MARKET_DESTINATION","MARKET_PAY","MARKET_CONFIRM","MARKET_EDIT"}:
        return _load_start(session)

    # -------- CATÉGORIES --------
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})
        if t not in categories:
            return build_response("⚠️ Catégorie invalide. Choisissez un numéro :", list(categories.keys()))
        selected = categories[t]
        session["market_category"] = selected
        session["step"] = "MARKET_MERCHANT"

        merchants = _load_merchants_by_category(session, selected)
        if not merchants:
            session["step"] = "MARKET_CATEGORY"
            return build_response("❌ Aucun marchand trouvé.", list(categories.keys()))

        session["market_merchants"] = {str(i+1): m for i,m in enumerate(merchants[:5])}
        lignes = [f"{i+1}. {_merchant_display_name(m)}" for i,m in enumerate(merchants[:5])]
        return build_response("🏬 Marchands disponibles :\n" + "\n".join(lignes),
                              list(session["market_merchants"].keys()))

    # -------- MARCHANDS --------
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})
        if t not in merchants:
            return build_response("⚠️ Choisissez un numéro valide de marchand.", list(merchants.keys()))
        merchant = merchants[t]
        session["market_merchant"] = merchant
        session["step"] = "MARKET_PRODUCTS"

        r = api_request(session, "GET", "/api/v1/marketplace/produits/")
        produits = r.json().get("results", []) if r.ok and isinstance(r.json(), dict) else []
        produits = [p for p in produits if p.get("entreprise") == merchant["id"]]

        if not produits:
            return build_response(f"❌ Aucun produit disponible chez *{_merchant_display_name(merchant)}*.", MAIN_MENU_BTNS)

        session["market_products"] = {str(i+1): p for i,p in enumerate(produits[:5])}
        lignes = []
        for i,p in enumerate(produits[:5], start=1):
            ligne = f"{i}. {p.get('nom','—')} — {p.get('prix','0')} FCFA"
            if p.get("image"): ligne += f"\n🖼️ {p['image']}"
            lignes.append(ligne)
        return build_response(f"📦 Produits de *{_merchant_display_name(merchant)}* :\n" + "\n".join(lignes),
                              list(session["market_products"].keys()))

    # -------- PRODUITS --------
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})
        if t not in produits:
            return build_response("⚠️ Choisissez un numéro valide de produit.", list(produits.keys()))
        produit = produits[t]
        session["selected_product"] = produit
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = produit.get("description","")
        session["new_request"]["value_fcfa"] = produit.get("prix",0)

        session["step"] = "MARKET_DESTINATION"
        resp = build_response("📍 Où livrer la commande ? Envoyez l’adresse ou partagez votre localisation.")
        resp["ask_location"] = True
        return resp

    # -------- DESTINATION --------
    if step == "MARKET_DESTINATION":
        if lat and lng:
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text:
            session["new_request"]["depart"] = text
        else:
            return build_response("❌ Veuillez fournir une adresse ou une localisation.", MAIN_MENU_BTNS)

        session["step"] = "MARKET_PAY"
        return build_response("💳 Choisissez un mode de paiement :", ["Espèces","Mobile Money","Virement"])

    # -------- PAIEMENT --------
    if step == "MARKET_PAY":
        mapping = {"espèces":"cash","especes":"cash","1":"cash",
                   "mobile money":"mobile_money","2":"mobile_money",
                   "virement":"virement","3":"virement"}
        if t not in mapping:
            return build_response("Merci de choisir un mode valide.", ["Espèces","Mobile Money","Virement"])

        session["new_request"]["payment_method"] = mapping[t]
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]; merchant = session.get("market_merchant") or {}
        pickup_addr,_ = _merchant_pickup_info(merchant)
        recap = (
            "📝 Récapitulatif :\n"
            f"• Marchand : {_merchant_display_name(merchant)}\n"
            f"• Retrait : {pickup_addr}\n"
            f"• Livraison : {d.get('depart','—')}\n"
            f"• Produit : {d.get('market_choice')} — {d.get('value_fcfa')} FCFA\n"
            f"• Paiement : {mapping[t]}\n"
            "👉 Confirmez-vous la commande ?"
        )
        return build_response(recap, ["Confirmer","Annuler","Modifier"])

    # -------- CONFIRM --------
    if step == "MARKET_CONFIRM":
        if t in {"confirmer","oui"}:
            return marketplace_create_order(session)
        if t in {"annuler","non"}:
            session["step"]="MENU"; session.pop("new_request",None)
            return build_response("❌ Commande annulée.", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"]="MARKET_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?",["Produit","Paiement","Adresse de livraison"])
        return build_response("👉 Répondez par Confirmer, Annuler ou Modifier.", ["Confirmer","Annuler","Modifier"])

    # -------- EDIT --------
    if step == "MARKET_EDIT":
        return _load_start(session)

    return ai_fallback(text, session.get("phone"))

# ------------------------------------------------------
# Wrapper
# ------------------------------------------------------
def handle_message(phone: str, text: str, *,
                   lat: Optional[float]=None, lng: Optional[float]=None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_marketplace_handle(session, text, lat=lat, lng=lng)
