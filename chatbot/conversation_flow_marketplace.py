# chatbot/conversation_flow_marketplace.py
# VERSION CORRIGÉE - Les bugs du mapping bouton/indice sont fixés
from __future__ import annotations
import os, logging, requests, re
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]


# ==================== HELPERS ====================
def _fmt_fcfa(n: Any) -> str:
    try:
        i = int(float(str(n)))
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n)


def _truncate_title(text: str, max_len: int = 24) -> str:
    """Tronque un titre pour WhatsApp (max 24 chars) - FIX BUG #131009"""
    if not text:
        return "—"
    text = str(text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len-1] + "…"


def _build_product_title(nom: str, prix: str) -> str:
    """Construit un titre produit qui respecte les limites WhatsApp (24 chars)"""
    if not nom:
        nom = "Produit"
    prix_str = f"{prix} FCFA"
    separateur = " - "
    # Calculer l'espace disponible pour le nom
    max_nom_length = max(8, 24 - len(prix_str) - len(separateur))
    title = f"{nom[:max_nom_length]} - {prix_str}"
    # Double sécurité: tronquer à 24
    return title[:24]


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
    """Crée une réponse avec liste WhatsApp native (même format que SIGNUP)"""
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
    lat = ent.get("latitude") or ent.get("lat")
    lng = ent.get("longitude") or ent.get("lng")
    coords = f"{lat},{lng}" if (lat is not None and lng is not None) else ""
    return str(addr), coords


# ==================== MARKETPLACE ORDER ====================
def marketplace_create_order(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        d = session.get("new_request", {})
        merchant = session.get("market_merchant", {})
        produit = session.get("selected_product", {})

        payload = {
            "entreprise": int(merchant.get("id", 0)),
            "adresse_livraison": d.get("depart") or "Adresse non précisée",
            "coordonnees_gps": d.get("coordonnees_gps") or "0,0",
            "notes_client": d.get("description") or "",
            "details": [{
                "produit": int(produit.get("id", 0)),
                "quantite": 1,
                "prix_unitaire": float(produit.get("prix", 0)),
            }],
            "status": "en_attente",
        }

        pay_method = d.get("payment_method", "espèces")
        payload["mode_paiement"] = pay_method

        r = api_request(session, "POST", "/api/v1/marketplace/commandes/", json=payload)

        if r.ok:
            order_data = r.json()
            order_id = order_data.get("id", "N/A")
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"

            recap = (
                "✅ *Commande créée avec succès* !\n\n"
                f"Numéro : *{order_id}*\n"
                f"Marchand : {_merchant_display_name(merchant)}\n"
                f"Livraison : {d.get('depart', '—')}\n"
                f"Total : {_fmt_fcfa(d.get('value_fcfa', 0))} FCFA"
            )
            return build_response(recap, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[MARKET] create_order failed: {e}")

    _cleanup_marketplace_session(session)
    session["step"] = "MENU"
    return build_response("❌ Erreur lors de la création.", MAIN_MENU_BTNS)


def _begin_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        categories = _load_categories(session)
        if not categories:
            session["step"] = "MENU"
            return build_response("❌ Pas de catégories disponibles.", MAIN_MENU_BTNS)

        session["market_categories"] = {str(i): c for i, c in enumerate(categories)}
        session["step"] = "MARKET_CATEGORY"

        rows = []
        for idx, cat in enumerate(categories):
            nom = cat.get("nom") or cat.get("name", "—")
            rows.append({
                "id": str(idx),
                "title": nom[:30]
            })

        return _build_list_response("🛍️ *Sélectionnez une catégorie*", rows, section_title="Catégories")
    except Exception as e:
        logger.error(f"[MARKET] begin failed: {e}")
        session["step"] = "MENU"
        return build_response("❌ Erreur Marketplace.", MAIN_MENU_BTNS)


def flow_marketplace_handle(session: Dict[str, Any], text: str,
                            *, lat: Optional[float] = None,
                            lng: Optional[float] = None) -> Dict[str, Any]:
    step = session.get("step", "MARKET_CATEGORY")
    t = normalize(text) if text else ""

    # ========== CATÉGORIES ==========
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})

        # FIX: Créer un mapping texte → indice pour les boutons interactifs
        category_name_to_id = {}
        for idx, cat in categories.items():
            cat_name = normalize(cat.get("nom") or cat.get("name") or "")
            if cat_name:  # Seulement si le nom normalisé n'est pas vide
                category_name_to_id[cat_name] = idx

        # Chercher d'abord par indice direct
        if t not in categories:
            # Ensuite par nom de catégorie (depuis bouton interactif)
            if t in category_name_to_id:
                t = category_name_to_id[t]
            else:
                # Vraiment invalide
                rows = []
                for k in sorted(categories.keys(), key=lambda x: int(x)):
                    cat = categories[k]
                    rows.append({
                        "id": k,
                        "title": (cat.get("nom") or cat.get("name", ""))[:30]
                    })
                msg = "⚠️ Choix invalide."
                return _build_list_response(msg, rows, section_title="Catégories")

        category = categories[t]
        merchants = _load_merchants_by_category(session, category)

        if not merchants:
            rows = []
            for k in sorted(categories.keys(), key=lambda x: int(x)):
                cat = categories[k]
                rows.append({
                    "id": k,
                    "title": (cat.get("nom") or cat.get("name", ""))[:30]
                })
            cat_name = category.get("nom") or category.get("name", "Catégorie")
            msg = f"❌ Aucun marchand pour *{cat_name}*."
            return _build_list_response(msg, rows, section_title="Catégories")

        merchants_indexed = {str(i): m for i, m in enumerate(merchants)}
        session["market_merchants"] = merchants_indexed
        session["market_category"] = category
        session["step"] = "MARKET_MERCHANT"

        rows = []
        for k in sorted(merchants_indexed.keys(), key=lambda x: int(x)):
            m = merchants_indexed[k]
            rows.append({
                "id": k,
                "title": _truncate_title(_merchant_display_name(m), 24),  # FIX: Limiter à 24 chars
                "description": m.get("raison_sociale", "")[:60] if m.get("raison_sociale") else ""
            })

        cat_name = category.get("nom") or category.get("name", "Catégorie")
        msg = f"🏪 *Marchands de {cat_name}*"
        return _build_list_response(msg, rows, section_title="Marchands")

    # ========== MARCHANDS ==========
    if step == "MARKET_MERCHANT":
        if _is_retour(text):
            session["step"] = "MARKET_CATEGORY"
            categories = session.get("market_categories", {})
            rows = []
            for k in sorted(categories.keys(), key=lambda x: int(x)):
                cat = categories[k]
                rows.append({
                    "id": k,
                    "title": (cat.get("nom") or cat.get("name", ""))[:30]
                })
            msg = "🔙 *Catégories*"
            return _build_list_response(msg, rows, section_title="Catégories")

        merchants = session.get("market_merchants", {})

        # FIX: Créer un mapping texte → indice pour les boutons interactifs
        merchant_name_to_id = {}
        for idx, merch in merchants.items():
            merch_name = normalize(_merchant_display_name(merch))
            if merch_name:
                merchant_name_to_id[merch_name] = idx

        # Chercher d'abord par indice direct
        if t not in merchants:
            # Ensuite par nom du marchand
            if t in merchant_name_to_id:
                t = merchant_name_to_id[t]
            else:
                # Vraiment invalide
                rows = []
                for k in sorted(merchants.keys(), key=lambda x: int(x)):
                    m = merchants[k]
                    rows.append({
                        "id": k,
                        "title": _merchant_display_name(m)[:24],
                        "description": m.get("raison_sociale", "")[:60] if m.get("raison_sociale") else ""
                    })
                msg = "⚠️ Choix invalide."
                return _build_list_response(msg, rows, section_title="Marchands")

        merchant = merchants[t]
        session["market_merchant"] = merchant
        produits = _load_products_by_category(session, merchant.get("id"))

        if not produits:
            rows = []
            for k in sorted(merchants.keys(), key=lambda x: int(x)):
                m = merchants[k]
                rows.append({
                    "id": k,
                    "title": _truncate_title(_merchant_display_name(m), 24),  # FIX: Limiter à 24 chars
                    "description": m.get("raison_sociale", "")[:60] if m.get("raison_sociale") else ""
                })
            msg = f"❌ Aucun produit."
            return _build_list_response(msg, rows, section_title="Marchands")

        produits = produits[:10]
        session["market_products"] = {str(i + 1): p for i, p in enumerate(produits)}
        session["step"] = "MARKET_PRODUCTS"

        rows = []
        for i, p in enumerate(produits, start=1):
            nom = p.get("nom", "—")
            prix = _fmt_fcfa(p.get("prix", 0))
            # FIX: Utiliser _build_product_title pour respecter la limite de 24 chars WhatsApp
            title = _build_product_title(nom, prix)
            rows.append({
                "id": str(i),
                "title": title,
                "description": p.get("description", "")[:60] if p.get("description") else ""
            })

        msg = f"📦 *Produits de {_merchant_display_name(merchant)}*"
        return _build_list_response(msg, rows, section_title="Produits")

    # ========== PRODUITS ==========
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})

        if _is_retour(text):
            session["step"] = "MARKET_MERCHANT"
            merchants = session.get("market_merchants", {})
            rows = []
            for k in sorted(merchants.keys(), key=lambda x: int(x)):
                m = merchants[k]
                rows.append({
                    "id": k,
                    "title": _truncate_title(_merchant_display_name(m), 24),  # FIX: Limiter à 24 chars
                    "description": m.get("raison_sociale", "")[:60] if m.get("raison_sociale") else ""
                })
            msg = "🔙 *Marchands*"
            return _build_list_response(msg, rows, section_title="Marchands")

        # FIX: Créer un mapping texte → indice pour les boutons interactifs
        product_name_to_id = {}
        for idx, prod in produits.items():
            prod_name = normalize(prod.get("nom") or "")
            if prod_name:
                product_name_to_id[prod_name] = idx

        # Chercher d'abord par indice direct
        if t not in produits:
            # Ensuite par nom du produit
            if t in product_name_to_id:
                t = product_name_to_id[t]
            else:
                # Vraiment invalide
                rows = []
                for k in sorted(produits.keys(), key=lambda x: int(x)):
                    p = produits[k]
                    nom = p.get("nom", "—")
                    prix = _fmt_fcfa(p.get("prix", 0))
                    # FIX: Utiliser _build_product_title pour respecter la limite WhatsApp
                    title = _build_product_title(nom, prix)
                    rows.append({
                        "id": k,
                        "title": title,
                        "description": p.get("description", "")[:60] if p.get("description") else ""
                    })
                msg = "⚠️ Choix invalide."
                return _build_list_response(msg, rows, section_title="Produits")

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
                nom = p.get("nom", "—")
                prix = _fmt_fcfa(p.get("prix", 0))
                # FIX: Utiliser _build_product_title pour respecter la limite WhatsApp
                title = _build_product_title(nom, prix)
                rows.append({
                    "id": k,
                    "title": title,
                    "description": p.get("description", "")[:60] if p.get("description") else ""
                })
            msg = "🔙 *Produits*"
            return _build_list_response(msg, rows, section_title="Produits")

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

        mapping = {
            "espèces": "espèces", "1": "espèces",
            "mobile money": "mobile_money", "2": "mobile_money",
            "virement": "virement", "3": "virement",
        }
        key = t.strip()
        if key not in mapping:
            return build_response("🙏 Choix invalide.",
                                  ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

        session.setdefault("new_request", {})["payment_method"] = mapping[key]
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]
        merchant = session.get("market_merchant", {})
        pickup_addr, _ = _merchant_pickup_info(merchant)
        prix = _fmt_fcfa(d.get("value_fcfa", 0))

        recap = (
            "📝 *Récapitulatif*\n"
            f"• Marchand : {_merchant_display_name(merchant)}\n"
            f"• Retrait : {pickup_addr}\n"
            f"• Livraison : {d.get('depart', '—')}\n"
            f"• Produit : {d.get('market_choice', '—')} — {prix} FCFA\n"
            f"• Paiement : {mapping[key]}"
        )
        return build_response(recap, ["Confirmer", "Modifier", "🔙 Retour"])

    # ========== CONFIRMATION ==========
    if step == "MARKET_CONFIRM":
        if _is_retour(text):
            session["step"] = "MARKET_PAY"
            return build_response("💳 Mode de paiement :",
                                  ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

        if t in {"confirmer", "oui"}:
            return marketplace_create_order(session)

        if t in {"annuler", "non"}:
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response("✅ Annulé.", MAIN_MENU_BTNS)

        if t == "modifier":
            session["step"] = "MARKET_PAY"
            return build_response("💳 Mode de paiement :",
                                  ["Espèces", "Mobile Money", "Virement", "🔙 Retour"])

        return build_response("👉 Confirmer / Modifier / Annuler",
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