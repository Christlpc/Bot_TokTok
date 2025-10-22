# chatbot/conversation_flow_marketplace.py
# VERSION CORRIGÉE - TOUS LES BUGS + UX/UI AMÉLIORÉ

from __future__ import annotations
import os, logging, requests, re
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

# ==================== CONSTANTS ====================
PAYMENT_METHODS = {
    # Espèces variants
    "especes": "espèces",  # ← SANS ACCENTS dans les clés
    "cash": "espèces",
    "1": "espèces",

    # Mobile Money variants
    "mobile money": "mobile_money",
    "mobile": "mobile_money",
    "mtn": "mobile_money",
    "2": "mobile_money",

    # Virement variants
    "virement": "virement",  # ← SANS ACCENTS dans les clés
    "transfer": "virement",
    "bank": "virement",
    "3": "virement",
}


# ==================== HELPERS ====================

# 🔧 BUG FIX #1: Améliorer normalize() pour enlever accents
def normalize(s: str) -> str:
    """
    Normalise un texte pour comparaison.
    - Supprime les espaces multiples
    - Convertit en minuscules
    - Enlève les accents
    """
    import unicodedata

    s = " ".join((s or "").split()).strip().lower()

    # Enlever les accents
    s = ''.join(
        c for c in unicodedata.normalize('NFD', s)
        if unicodedata.category(c) != 'Mn'
    )

    return s


def _fmt_fcfa(n: Any) -> str:
    try:
        i = int(float(str(n)))
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n)


# 🎨 UX/UI FIX: Nouvelle fonction pour affichage optimisé
def _build_product_display(nom: str, prix: float, description: str = "") -> Tuple[str, str]:
    """
    Crée un affichage optimisé pour WhatsApp List.

    Bonnes pratiques UX/UI :
    - Titre : nom du produit SEUL (lisible, scannable)
    - Description : prix + info (hiérarchie claire)

    Returns: (title, description_formatted)
    """
    if not nom:
        nom = "Produit"

    # TITRE : Juste le nom, truncate à 20 chars (lisibilité)
    title = str(nom).strip()
    if len(title) > 20:
        title = title[:17] + "…"

    # DESCRIPTION : Prix + info
    prix_str = f"💰 {_fmt_fcfa(prix)} FCFA"

    # Ajouter la description courte si disponible
    desc_part = ""
    if description and description.strip():
        desc_clean = description.strip()[:40]  # Max 40 chars
        desc_part = f"\n{desc_clean}"

    description_final = prix_str + desc_part

    return title, description_final


def _build_merchant_display(nom: str, raison_sociale: str = "") -> Tuple[str, str]:
    """Optimise l'affichage des marchands"""
    if not nom:
        nom = "Marchand"

    title = str(nom).strip()
    if len(title) > 22:
        title = title[:19] + "…"

    description = ""
    if raison_sociale and raison_sociale.strip():
        description = str(raison_sociale).strip()[:50]
    else:
        description = "Restaurant"

    return title, description


def _truncate_title(text: str, max_len: int = 24) -> str:
    """Tronque un titre pour WhatsApp (max 24 chars) - FIX BUG #131009"""
    if not text:
        return "—"
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-M] {method} {path} -> {r.status_code}")
    return r


def _cleanup_marketplace_session(session: Dict[str, Any]) -> None:
    keys = ["market_categories", "market_category", "market_merchants",
            "market_merchant", "market_products", "selected_product", "new_request"]
    for key in keys:
        session.pop(key, None)


def _build_list_response(text: str, rows: List[dict], section_title: str = "Options") -> Dict[str, Any]:
    """Crée une réponse avec liste WhatsApp native"""
    return {
        "response": text,
        "list": {
            "title": section_title,
            "rows": rows
        }
    }


def _is_retour(txt: str) -> bool:
    if not txt:
        return False
    if "🔙" in txt or txt.strip().lower() in {"retour", "back"}:
        return True
    return normalize(txt) == "retour"


# ==================== DATA LOADERS ====================
def _load_categories(session: Dict[str, Any]) -> List[Dict[str, Any]]:
    cats: List[Dict[str, Any]] = []
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/categories/")
        if r.ok:
            data = r.json()
            cats = data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.warning(f"[MARKET] categories failed: {e}")

    if cats:
        return cats

    try:
        r = api_request(session, "GET", "/api/v1/auth/entreprises/")
        if r.ok:
            data = r.json()
            ents = data.get("results", []) if isinstance(data, dict) else (data or [])
            tmp = {}
            for e in ents:
                te = e.get("type_entreprise")
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
        logger.error(f"[MARKET] fallback failed: {e}")

    return cats


def _load_merchants_by_category(session: Dict[str, Any], category: Dict[str, Any]) -> List[Dict[str, Any]]:
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
            if isinstance(te, dict):
                tid = te.get("id") or te.get("pk") or te.get("code") or te.get("slug")
                tnom = (te.get("nom") or te.get("name") or "").strip().lower()
                return (cid is not None and (str(tid) == str(cid))) or (cnom and tnom == cnom)
            if isinstance(te, (str, int)):
                return (cid is not None and str(te) == str(cid)) or (cnom and str(te).strip().lower() == cnom)
            return False

        return [e for e in ents if _match(e)]
    except Exception as e:
        logger.error(f"[MARKET] load merchants failed: {e}")
        return []


def _load_products_by_category(session: Dict[str, Any], category_id: Any) -> List[Dict[str, Any]]:
    try:
        path = f"/api/v1/marketplace/produits/{category_id}/"
        r = api_request(session, "GET", path)
        if r.ok:
            data = r.json()
            prods = data.get("results", []) if isinstance(data, dict) else (data or [])
            if prods:
                return prods
    except Exception as e:
        logger.warning(f"[MARKET] produits by_category failed: {e}")

    try:
        r = api_request(session, "GET", "/api/v1/marketplace/produits/disponibles/")
        if r.ok:
            data = r.json()
            return data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.error(f"[MARKET] produits disponibles failed: {e}")

    return []


# ==================== FLOW HELPERS ====================
def _merchant_display_name(ent: Dict[str, Any]) -> str:
    return (ent.get("nom_entreprise") or ent.get("nom") or ent.get("name")
            or ent.get("display_name") or ent.get("raison_sociale") or "—")


def _merchant_pickup_info(ent: Dict[str, Any]) -> Tuple[str, str]:
    addr = ent.get("adresse") or ent.get("address") or ent.get("localisation") or _merchant_display_name(ent)
    phone = ent.get("phone") or ent.get("telephone") or ""
    return addr, phone


def marketplace_create_order(session: Dict[str, Any]) -> Dict[str, Any]:
    """Crée la commande via l'API"""
    try:
        req_data = session.get("new_request", {})
        merchant = session.get("market_merchant", {})

        payload = {
            "market_choice": req_data.get("market_choice"),
            "description": req_data.get("description"),
            "value_fcfa": req_data.get("value_fcfa"),
            "payment_method": req_data.get("payment_method"),
            "depart": req_data.get("depart"),
            "coordonnees_gps": req_data.get("coordonnees_gps"),
        }

        r = api_request(session, "POST", "/api/v1/marketplace/orders/", json=payload)

        if r.ok:
            order = r.json()
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response(
                f"✅ Commande créée !\n"
                f"Numéro : {order.get('id', '—')}\n"
                f"Suivi : /track/{order.get('id', '')}",
                MAIN_MENU_BTNS
            )
        else:
            logger.error(f"[MARKET] order creation failed: {r.status_code}")
            return build_response("❌ Erreur lors de la création.", MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[MARKET] create_order exception: {e}")
        return build_response("❌ Erreur lors de la création.", MAIN_MENU_BTNS)


# ==================== FLOW PRINCIPAL ====================
def _begin_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    """Initialise le flow marketplace"""
    categories = _load_categories(session)

    if not categories:
        return build_response("❌ Marketplace indisponible.", MAIN_MENU_BTNS)

    session["market_categories"] = {str(i + 1): c for i, c in enumerate(categories)}
    session["step"] = "MARKET_CATEGORY"

    rows = []
    for i, cat in enumerate(categories, start=1):
        nom = cat.get("nom") or cat.get("name") or "—"
        rows.append({
            "id": str(i),
            "title": _truncate_title(nom, 22),
            "description": cat.get("description", "")[:50] if cat.get("description") else ""
        })

    return _build_list_response("🛍️ *Catégories*", rows, section_title="Catégories")


def flow_marketplace_handle(session: Dict[str, Any], text: str,
                            *, lat: Optional[float] = None,
                            lng: Optional[float] = None) -> Dict[str, Any]:
    """Gère le flow marketplace"""

    step = session.get("step", "MENU")
    t = normalize(text) if text else ""

    # ========== CATÉGORIES ==========
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})

        if t not in categories:
            rows = []
            for i, cat in enumerate(categories.values(), start=1):
                nom = cat.get("nom") or cat.get("name") or "—"
                rows.append({
                    "id": str(i),
                    "title": _truncate_title(nom, 22),
                    "description": cat.get("description", "")[:50] if cat.get("description") else ""
                })
            return _build_list_response("⚠️ Choix invalide.", rows, section_title="Catégories")

        category = categories[t]
        session["market_category"] = category

        merchants = _load_merchants_by_category(session, category)
        if not merchants:
            return build_response("❌ Pas de marchands.", MAIN_MENU_BTNS)

        session["market_merchants"] = {str(i + 1): m for i, m in enumerate(merchants)}
        session["step"] = "MARKET_MERCHANT"

        rows = []
        for k in sorted(session["market_merchants"].keys(), key=lambda x: int(x)):
            m = session["market_merchants"][k]
            # 🎨 UX/UI: Utiliser la nouvelle fonction
            title, description = _build_merchant_display(
                _merchant_display_name(m),
                m.get("raison_sociale", "")
            )
            rows.append({
                "id": k,
                "title": title,
                "description": description
            })

        return _build_list_response("🏪 *Marchands*", rows, section_title="Marchands")

    # ========== MARCHANDS ==========
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})

        if _is_retour(text):
            session["step"] = "MARKET_CATEGORY"
            categories = session.get("market_categories", {})
            rows = []
            for i, cat in enumerate(categories.values(), start=1):
                nom = cat.get("nom") or cat.get("name") or "—"
                rows.append({
                    "id": str(i),
                    "title": _truncate_title(nom, 22),
                    "description": cat.get("description", "")[:50] if cat.get("description") else ""
                })
            return _build_list_response("🔙 *Catégories*", rows, section_title="Catégories")

        if t not in merchants:
            rows = []
            for k in sorted(merchants.keys(), key=lambda x: int(x)):
                m = merchants[k]
                title, description = _build_merchant_display(
                    _merchant_display_name(m),
                    m.get("raison_sociale", "")
                )
                rows.append({
                    "id": k,
                    "title": title,
                    "description": description
                })
            return _build_list_response("⚠️ Choix invalide.", rows, section_title="Marchands")

        merchant = merchants[t]
        session["market_merchant"] = merchant

        produits = _load_products_by_category(session, merchant.get("id") or merchant.get("pk"))
        if not produits:
            return build_response("❌ Pas de produits.", MAIN_MENU_BTNS)

        session["market_products"] = {str(i + 1): p for i, p in enumerate(produits)}
        session["step"] = "MARKET_PRODUCTS"

        rows = []
        for i, p in enumerate(produits, start=1):
            # 🎨 UX/UI: Utiliser la nouvelle fonction
            title, description = _build_product_display(
                nom=p.get("nom", "—"),
                prix=p.get("prix", 0),
                description=p.get("description", "")
            )
            rows.append({
                "id": str(i),
                "title": title,
                "description": description
            })

        msg = f"📦 *Produits de {_merchant_display_name(merchant)}*"
        return _build_list_response(msg, rows, section_title="Produits disponibles")

    # ========== PRODUITS ==========
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})

        if _is_retour(text):
            session["step"] = "MARKET_MERCHANT"
            merchants = session.get("market_merchants", {})
            rows = []
            for k in sorted(merchants.keys(), key=lambda x: int(x)):
                m = merchants[k]
                title, description = _build_merchant_display(
                    _merchant_display_name(m),
                    m.get("raison_sociale", "")
                )
                rows.append({
                    "id": k,
                    "title": title,
                    "description": description
                })
            return _build_list_response("🔙 *Marchands*", rows, section_title="Marchands")

        # BUG FIX #2: Créer un mapping texte → indice avec normalize()
        product_name_to_id = {}
        for idx, prod in produits.items():
            prod_name = normalize(prod.get("nom") or "")
            if prod_name:
                product_name_to_id[prod_name] = idx

        # BUG FIX #3: Extraire le nom si c'est au format "NOM - PRIX FCFA"
        if " - " in text and "FCFA" in text:
            text = text.rsplit(" - ", 1)[0]  # Prendre avant le dernier " - "

        # Chercher par indice direct
        if t not in produits:
            # BUG FIX #2: Chercher par nom avec normalize()
            if t in product_name_to_id:
                t = product_name_to_id[t]
            else:
                # Invalide
                rows = []
                for k in sorted(produits.keys(), key=lambda x: int(x)):
                    p = produits[k]
                    title, description = _build_product_display(
                        nom=p.get("nom", "—"),
                        prix=p.get("prix", 0),
                        description=p.get("description", "")
                    )
                    rows.append({
                        "id": k,
                        "title": title,
                        "description": description
                    })
                return _build_list_response("⚠️ Choix invalide.", rows, section_title="Produits")

        produit = produits[t]
        session["selected_product"] = produit
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = (produit.get("description") or "").strip()
        session["new_request"]["value_fcfa"] = produit.get("prix", 0)
        session["step"] = "MARKET_DESTINATION"

        resp = build_response(
            "📍 Où livrer ?\n"
            "• Envoyez *l'adresse*\n"
            "• ou *partagez votre position*"
        )
        resp["ask_location"] = True
        return resp

    # ========== ADRESSE ==========
    if step == "MARKET_DESTINATION":
        if _is_retour(text):
            session["step"] = "MARKET_PRODUCTS"
            produits = session.get("market_products", {})
            rows = []
            for k in sorted(produits.keys(), key=lambda x: int(x)):
                p = produits[k]
                title, description = _build_product_display(
                    nom=p.get("nom", "—"),
                    prix=p.get("prix", 0),
                    description=p.get("description", "")
                )
                rows.append({
                    "id": k,
                    "title": title,
                    "description": description
                })
            return _build_list_response("🔙 *Produits*", rows, section_title="Produits disponibles")

        if lat is not None and lng is not None:
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text and not _is_retour(text):
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = text
            session["new_request"]["coordonnees_gps"] = ""
        else:
            resp = build_response("⚠️ Besoin d'une adresse ou position.")
            resp["ask_location"] = True
            return resp

        session["step"] = "MARKET_PAY"
        return build_response("💳 Mode de paiement :",
                              ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

    # ========== PAIEMENT ==========
    if step == "MARKET_PAY":
        if _is_retour(text):
            session["step"] = "MARKET_DESTINATION"
            resp = build_response("📍 Nouvelle adresse ?")
            resp["ask_location"] = True
            return resp

        # BUG FIX #1: Utiliser normalize() pour comparer avec PAYMENT_METHODS
        key = normalize(text)
        if key not in PAYMENT_METHODS:
            return build_response("🙏 Choix invalide. Choisissez:",
                                  ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

        payment_method = PAYMENT_METHODS[key]
        session.setdefault("new_request", {})["payment_method"] = payment_method
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]
        merchant = session.get("market_merchant", {})
        pickup_addr, _ = _merchant_pickup_info(merchant)
        prix = _fmt_fcfa(d.get("value_fcfa", 0))

        payment_label = "Espèces" if payment_method == "espèces" else \
            "Mobile Money" if payment_method == "mobile_money" else \
                "Virement"

        recap = (
            "📝 *Récapitulatif*\n"
            f"• Marchand : {_merchant_display_name(merchant)}\n"
            f"• Retrait : {pickup_addr}\n"
            f"• Livraison : {d.get('depart', '—')}\n"
            f"• Produit : {d.get('market_choice', '—')} — {prix} FCFA\n"
            f"• Paiement : {payment_label}"
        )
        return build_response(recap, ["Confirmer", "Modifier", "🔙 Retour"])

    # ========== CONFIRMATION ==========
    if step == "MARKET_CONFIRM":
        if _is_retour(text):
            session["step"] = "MARKET_PAY"
            return build_response("💳 Mode de paiement :",
                                  ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

        # BUG FIX #1: Utiliser normalize() pour tous les textes
        t_lower = normalize(text)

        # Confirmer l'ordre
        if t_lower in {"confirmer", "oui", "valider", "ok", "yes", "1"}:
            return marketplace_create_order(session)

        # Modifier
        if t_lower in {"modifier", "editer", "change", "changer", "2"}:
            session["step"] = "MARKET_PAY"
            return build_response("💳 Mode de paiement :",
                                  ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

        # Annuler
        if t_lower in {"annuler", "non", "cancel", "no", "3"}:
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response("✅ Commande annulée.", MAIN_MENU_BTNS)

        # Fallback
        return build_response("👉 Merci de choisir une option.",
                              ["Confirmer", "Modifier", "Annuler", "🔙 Retour"])

    if text:
        return ai_fallback(text, session.get("phone"))
    return build_response("Marketplace en attente.", MAIN_MENU_BTNS)


def handle_message(phone: str, text: str,
                   *, lat: Optional[float] = None,
                   lng: Optional[float] = None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)

    if not session.get("market_categories") and not session.get("step", "").startswith("MARKET_"):
        return _begin_marketplace(session)

    return flow_marketplace_handle(session, text, lat=lat, lng=lng)