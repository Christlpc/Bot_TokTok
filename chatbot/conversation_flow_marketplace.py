# chatbot/conversation_flow_marketplace.py
from __future__ import annotations
import os, logging, requests
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # réutilise le même fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT  = int(os.getenv("TOKTOK_TIMEOUT", "15"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()  # non utilisé ici
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

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
# Data loaders (robustes)
# -----------------------------
def _load_categories(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    1) Essaie l'endpoint officiel des catégories marketplace
    2) Si vide / indisponible, infère via les entreprises (champ type_entreprise)
    """
    cats: List[Dict[str, Any]] = []

    # 1) Endpoint catégories
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/categories/")
        if r.ok:
            data = r.json()
            cats = data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.warning(f"[MARKET] categories endpoint failed: {e}")

    if cats:
        return cats

    # 2) Fallback via entreprises -> type_entreprise
    try:
        r = api_request(session, "GET", "/api/v1/auth/entreprises/")
        if r.ok:
            data = r.json()
            ents = data.get("results", []) if isinstance(data, dict) else (data or [])
            tmp = {}
            for e in ents:
                te = e.get("type_entreprise")  # peut être dict ou str / id
                if isinstance(te, dict):
                    cid = te.get("id") or te.get("pk") or te.get("code") or str(te)
                    nom = te.get("nom") or te.get("name") or str(te)
                else:
                    cid = te if te is not None else str(e.get("id"))
                    nom = str(te) if te is not None else "Autres"
                if cid not in tmp:
                    tmp[cid] = {"id": cid, "nom": nom}
            cats = list(tmp.values())
    except Exception as e:
        logger.error(f"[MARKET] fallback categories via entreprises failed: {e}")

    return cats

def _load_merchants_by_category(session: Dict[str, Any], category: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Charge toutes les entreprises puis filtre par category via le champ type_entreprise.
    """
    try:
        r = api_request(session, "GET", "/api/v1/auth/entreprises/")
        if not r.ok:
            return []
        data = r.json()
        ents = data.get("results", []) if isinstance(data, dict) else (data or [])
        cid = category.get("id")
        cnom = (category.get("nom") or category.get("name") or "").strip().lower()

        def _match(ent: Dict[str, Any]) -> bool:
            te = ent.get("type_entreprise")
            # cas dict
            if isinstance(te, dict):
                tid = te.get("id") or te.get("pk") or te.get("code") or te.get("slug")
                tnom = (te.get("nom") or te.get("name") or "").strip().lower()
                return (cid is not None and (str(tid) == str(cid))) or (cnom and tnom == cnom)
            # cas str / int
            if isinstance(te, (str, int)):
                return (cid is not None and str(te) == str(cid)) or (cnom and str(te).strip().lower() == cnom)
            return False

        return [e for e in ents if _match(e)]
    except Exception as e:
        logger.error(f"[MARKET] load merchants failed: {e}")
        return []

def _load_products_by_category(session: Dict[str, Any], category_id: Any) -> List[Dict[str, Any]]:
    """
    Utilise l'endpoint produits par catégorie (si dispo), sinon produits disponibles.
    """
    # 1) by_category
    try:
        path = f"/api/v1/marketplace/produits//{category_id}/"
        r = api_request(session, "GET", path)
        if r.ok:
            data = r.json()
            prods = data.get("results", []) if isinstance(data, dict) else (data or [])
            if prods:
                return prods
    except Exception as e:
        logger.warning(f"[MARKET] produits by_category failed: {e}")

    # 2) disponibles (fallback)
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/produits/disponibles/")
        if r.ok:
            data = r.json()
            return data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.error(f"[MARKET] produits disponibles failed: {e}")

    return []

# -----------------------------
# Flow utils
# -----------------------------
def _begin_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    cats = _load_categories(session)
    if not cats:
        session["step"] = "MENU"
        return build_response("❌ Aucune catégorie disponible pour le moment.", MAIN_MENU_BTNS)

    # stocker mapping pour saisie par numéro
    session["market_categories"] = {str(i+1): c for i, c in enumerate(cats)}
    session["step"] = "MARKET_CATEGORY"

    lignes = [f"{i+1}. {c.get('nom') or c.get('name') or '—'}" for i, c in enumerate(cats)]
    return build_response("🛍️ Choisissez une *catégorie* :\n" + "\n".join(lignes),
                          list(session["market_categories"].keys()))

def _merchant_display_name(ent: Dict[str, Any]) -> str:
    return (
        ent.get("nom_entreprise")      # <-- priorité
        or ent.get("nom")
        or ent.get("name")
        or ent.get("display_name")
        or ent.get("raison_sociale")
        or "—"
    )

def _merchant_pickup_info(ent: Dict[str, Any]) -> Tuple[str, str]:
    """
    Retourne (adresse_recuperation_text, coordonnees_recuperation_str)
    On essaye d'être robustes sur les champs possibles côté API.
    """
    addr = ent.get("adresse") or ent.get("address") or ent.get("localisation") or _merchant_display_name(ent)
    lat = ent.get("latitude") or ent.get("lat")
    lng = ent.get("longitude") or ent.get("lng")
    coords = f"{lat},{lng}" if (lat is not None and lng is not None) else ""
    return str(addr), coords

# -----------------------------
# Création mission (réutilise coursier)
# -----------------------------
def _marketplace_create_mission(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prépare new_request pour ressembler à une mission coursier:
    - adresse_recuperation = marchand
    - adresse_livraison   = client (destination saisie)
    """
    nr = session.setdefault("new_request", {})
    merchant = session.get("market_merchant") or {}

    pickup_addr, pickup_coords = _merchant_pickup_info(merchant)

    # overwrite explicit pour éviter mélange
    nr["depart"] = pickup_addr
    nr["coordonnees_gps"] = pickup_coords  # côté coursier: 'coordonnees_recuperation'

    # la destination a été demandée à l'étape MARKET_DESTINATION
    # (nr["destination"] est déjà posé)

    from .conversation_flow_coursier import courier_create
    return courier_create(session)

# -----------------------------
# Flow Marketplace principal
# -----------------------------
def flow_marketplace_handle(session: Dict[str, Any], text: str,
                            lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    """
    Flow Marketplace:
    Catégorie -> Entreprise -> Produits -> Adresse de livraison (client) -> Paiement -> Confirmation
    """
    step = session.get("step")
    t = (normalize(text) or "").lower()

    marketplace_steps = {
        "MARKET_CATEGORY", "MARKET_MERCHANT", "MARKET_PRODUCTS",
        "MARKET_DESTINATION", "MARKET_PAY", "MARKET_CONFIRM", "MARKET_EDIT"
    }

    # Démarrage du flow si on n'est pas déjà dedans
    if step not in marketplace_steps:
        return _begin_marketplace(session)

    # -------- CATEGORIES --------
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})
        if t not in categories:
            return build_response("⚠️ Catégorie invalide. Choisissez un numéro :", list(categories.keys()))
        selected = categories[t]
        session["market_category"] = selected
        session["step"] = "MARKET_MERCHANT"

        merchants = _load_merchants_by_category(session, selected)
        if not merchants:
            # On revient au choix des catégories
            session["step"] = "MARKET_CATEGORY"
            return build_response(f"❌ Aucun marchand dans *{selected.get('nom') or selected.get('name') or '—'}*.",
                                  list(categories.keys()))

        merchants = merchants[:5]
        session["market_merchants"] = {str(i+1): m for i, m in enumerate(merchants)}
        lignes = [f"{i+1}. {_merchant_display_name(m)}" for i, m in enumerate(merchants)]
        return build_response("🏬 Marchands disponibles :\n" + "\n".join(lignes),
                              list(session["market_merchants"].keys()))

    # -------- MARCHANDS --------
    # -------- MARCHANDS --------
    # -------- MARCHANDS --------
    if step == "MARKET_MERCHANT":
        logger.debug(
            f"[MARKET] Step=MARKET_MERCHANT | Input={t} | Merchants keys={list(session.get('market_merchants', {}).keys())}")

        merchants = session.get("market_merchants", {})
        if t not in merchants:
            logger.warning(f"[MARKET] Invalid merchant choice '{t}' | Available={list(merchants.keys())}")
            return build_response("⚠️ Choisissez un numéro valide de marchand.", list(merchants.keys()))

        merchant = merchants[t]
        session["market_merchant"] = merchant
        session["step"] = "MARKET_PRODUCTS"

        logger.info(f"[MARKET] Merchant selected: {merchant}")

        # récupérer tous les produits
        r = api_request(session, "GET", "/api/v1/marketplace/produits/")
        logger.debug(f"[MARKET] API produits status={r.status_code}")
        try:
            data = r.json()
        except Exception as e:
            logger.error(f"[MARKET] JSON decode error: {e}")
            return build_response("❌ Erreur lors de la récupération des produits.", MAIN_MENU_BTNS)

        logger.debug(f"[MARKET] Produits bruts: {data}")

        produits = data.get("results", []) if isinstance(data, dict) else data
        produits = [p for p in produits if p.get("entreprise_id") == merchant["id"]]

        logger.info(f"[MARKET] Produits filtrés pour entreprise_id={merchant['id']} -> count={len(produits)}")

        if not produits:
            return build_response(f"❌ Aucun produit disponible chez *{merchant.get('nom_entreprise', '—')}*.",
                                  MAIN_MENU_BTNS)

        produits = produits[:5]
        session["market_products"] = {str(i + 1): p for i, p in enumerate(produits)}

        lignes = []
        for i, p in enumerate(produits, start=1):
            nom = p.get("nom", "—")
            prix = p.get("prix", "0")
            ligne = f"{i}. {nom} — {prix} FCFA"
            if p.get("photo_url"):
                ligne += f"\n🖼️ {p['photo_url']}"
            lignes.append(ligne)

        logger.debug(f"[MARKET] Produits affichés: {lignes}")

        return build_response(f"📦 Produits de *{merchant.get('nom_entreprise', '—')}* :\n" + "\n".join(lignes),
                              list(session["market_products"].keys()))

    # -------- PRODUITS --------
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})
        if t not in produits:
            return build_response("⚠️ Choisissez un numéro valide de produit.", list(produits.keys()))
        produit = produits[t]
        nr = session.setdefault("new_request", {})
        nr["market_choice"] = produit.get("nom") or produit.get("name")
        nr["description"]   = produit.get("description", "") or produit.get("details", "")
        nr["value_fcfa"]    = produit.get("prix", 0) or produit.get("price", 0)

        # pas de mélange : pour Marketplace, on demandera la DESTINATION (client)
        session["step"] = "MARKET_DESTINATION"
        resp = build_response("📍 Où livrer la commande ? Envoyez l’adresse ou partagez votre localisation.")
        resp["ask_location"] = True
        return resp

    # -------- DESTINATION (CLIENT) --------
    if step == "MARKET_DESTINATION":
        nr = session.setdefault("new_request", {})
        if lat is not None and lng is not None:
            nr["destination"] = "Ma position"
            # on NE PASSE PAS ces coords en 'coordonnees_gps' pour éviter le mélange (côté coursier = pickup)
            # si l'API supporte coordonnees_livraison, on pourrait l'ajouter ici sous une autre clé,
            # mais courier_create actuel ne l'envoie pas. On reste textuel.
        elif text:
            nr["destination"] = text
        else:
            return build_response("❌ Merci d’indiquer l’adresse de livraison (ou partagez la localisation).",
                                  ["Annuler"])

        session["step"] = "MARKET_PAY"
        return build_response("💳 Choisissez un mode de paiement :", ["Espèces", "Mobile Money", "Virement"])

    # -------- PAIEMENT --------
    if step == "MARKET_PAY":
        mapping = {
            "espèces": "cash",
            "especes": "cash",
            "1": "cash",
            "mobile money": "mobile_money",
            "mobile": "mobile_money",
            "2": "mobile_money",
            "virement": "virement",
            "3": "virement",
        }
        key = t.strip()
        if key not in mapping:
            return build_response("Merci de choisir un mode valide.", ["Espèces", "Mobile Money", "Virement"])

        session.setdefault("new_request", {})["payment_method"] = mapping[key]
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]
        merchant = session.get("market_merchant") or {}
        pickup_addr, _ = _merchant_pickup_info(merchant)

        recap = (
            "📝 Récapitulatif de votre commande Marketplace :\n"
            f"• Marchand : {_merchant_display_name(merchant)}\n"
            f"• Retrait (pickup) : {pickup_addr}\n"
            f"• Livraison (vous) : {d.get('destination','—')}\n"
            f"• Produit : {d.get('market_choice','—')} — {d.get('value_fcfa',0)} FCFA\n"
            f"• Paiement : {d.get('payment_method','—')}\n\n"
            "👉 Confirmez-vous la commande ?"
        )
        return build_response(recap, ["Confirmer", "Annuler", "Modifier"])

    # -------- CONFIRMATION --------
    if step == "MARKET_CONFIRM":
        if t in {"confirmer", "oui"}:
            return _marketplace_create_mission(session)
        if t in {"annuler", "non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            # on nettoie le contexte marketplace
            for k in ["market_category", "market_categories", "market_merchant", "market_merchants", "market_products"]:
                session.pop(k, None)
            return build_response("❌ Commande annulée.", MAIN_MENU_BTNS)
        if t in {"modifier"}:
            session["step"] = "MARKET_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit", "Paiement", "Adresse de livraison"])
        return build_response("👉 Répondez par Confirmer, Annuler ou Modifier.", ["Confirmer", "Annuler", "Modifier"])

    # -------- EDIT (optionnel simple) --------
    if step == "MARKET_EDIT":
        # pour rester simple on renvoie vers le début des choix principaux
        return _begin_marketplace(session)

    # -------- FALLBACK --------
    return ai_fallback(text, session.get("phone"))

# ------------------------------------------------------
# Wrapper pour compatibilité avec le router
# ------------------------------------------------------
def handle_message(phone: str, text: str,
                   *, lat: Optional[float] = None,
                   lng: Optional[float] = None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_marketplace_handle(session, text, lat=lat, lng=lng)
