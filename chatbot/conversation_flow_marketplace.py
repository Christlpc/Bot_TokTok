# chatbot/conversation_flow_marketplace.py
# VERSION FINALE CORRIGÉE - Tous les bugs fixes appliqués
from __future__ import annotations
import os, logging, requests, re
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback
from .analytics import analytics
from .smart_fallback import (
    extract_structured_data,
    smart_validate,
    detect_intent_change,
    generate_smart_error_message
)

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

# ==================== CONSTANTS ====================
PAYMENT_METHODS = {
    # Espèces variants
    "espèces": "espèces",
    "cash": "espèces",
    "1": "espèces",

    # Mobile Money variants
    "mobile money": "mobile_money",
    "mobile": "mobile_money",
    "mtn": "mobile_money",
    "2": "mobile_money",

    # Virement variants
    "virement": "virement",
    "transfer": "virement",
    "bank": "virement",
    "3": "virement",
}


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
    return text[:max_len - 1] + "…"


def _build_product_title_and_desc(nom: str, prix: Any, description: str = "") -> tuple[str, str]:
    """
    Construit un titre et une description pour un produit WhatsApp.
    - Title (max 24 chars) : Nom du produit uniquement
    - Description (max 72 chars) : Prix + description du produit
    
    Returns: (title, description)
    """
    if not nom:
        nom = "Produit"
    
    # Title = Nom du produit (tronqué à 24 chars si nécessaire)
    title = _truncate_title(nom, 24)
    
    # Description = Prix + description produit
    prix_formatted = _fmt_fcfa(prix)
    desc_parts = [f"💰 {prix_formatted} FCFA"]
    
    if description and description.strip():
        # Ajouter la description du produit si elle existe
        # On garde de la place pour le prix (environ 20 chars)
        remaining_space = 72 - len(desc_parts[0]) - 3  # -3 pour " • "
        if remaining_space > 10:
            desc_clean = description.strip()[:remaining_space]
            desc_parts.append(desc_clean)
    
    final_desc = " • ".join(desc_parts)
    return title, final_desc[:72]  # Sécurité limite WhatsApp


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
    txt_lower = txt.strip().lower()
    if "🔙" in txt or txt_lower in {"retour", "back", "🔙 retour"}:
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
                "quantite": int(d.get("quantity", 1)),
                "prix_unitaire": float(produit.get("prix", 0)),
            }],
            "status": "en_attente",
        }

        pay_method = d.get("payment_method", "espèces")
        payload["mode_paiement"] = pay_method

        r = api_request(session, "POST", "/api/v1/marketplace/commandes/", json=payload)

        if r.ok:
            order_data = r.json()
            logger.info(f"[MARKET] create_order response: {order_data}")
            
            # Récupérer la référence commande (numero_commande en priorité, sinon ID)
            import time
            order_ref = None
            
            # Tentative 1: numero_commande direct
            if not order_ref and order_data.get("numero_commande"):
                order_ref = order_data.get("numero_commande")
            
            # Tentative 2: numero_commande dans objet commande imbriqué
            if not order_ref and isinstance(order_data.get("commande"), dict):
                order_ref = order_data.get("commande", {}).get("numero_commande")
            
            # Tentative 3-5: IDs divers
            if not order_ref and order_data.get("id"):
                order_ref = f"CMD-{order_data['id']}"
            elif not order_ref and order_data.get("commande_id"):
                order_ref = f"CMD-{order_data['commande_id']}"
            elif not order_ref and order_data.get("order_id"):
                order_ref = f"CMD-{order_data['order_id']}"
            
            # Dernier recours: générer une référence temporaire unique
            if not order_ref:
                timestamp = int(time.time()) % 10000
                phone_suffix = session.get("phone", "0000")[-4:]
                order_ref = f"CMD-{phone_suffix}-{timestamp}"
            
            logger.info(f"[MARKET] order_ref extracted: {order_ref}")
            
            # Track conversion
            try:
                value = float(d.get("value_fcfa", 0))
                analytics.track_conversion(
                    session.get("phone"),
                    "order_created",
                    value,
                    {"order_ref": order_ref, "product": d.get("market_choice")}
                )
            except Exception as e:
                logger.warning(f"[MARKET] Could not track conversion: {e}")
            
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"

            recap = (
                "🎉 *COMMANDE CRÉÉE AVEC SUCCÈS !*\n\n"
                f"*Référence :* `{order_ref}`\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "*🏪 MARCHAND*\n"
                f"_{_merchant_display_name(merchant)}_\n\n"
                "*📍 LIVRAISON*\n"
                f"_{d.get('depart', '—')}_\n\n"
                "*📦 PRODUIT*\n"
                f"_{d.get('market_choice', '—')}_\n"
                f"Quantité : *{d.get('quantity', 1)}*\n\n"
                "*💰 TOTAL*\n"
                f"*{_fmt_fcfa(d.get('value_fcfa', 0))} FCFA*\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "✨ _Votre commande sera préparée et livrée dans les meilleurs délais._"
            )
            return build_response(recap, MAIN_MENU_BTNS)
        else:
            # Erreur API
            logger.error(f"[MARKET] create_order API error: status={r.status_code}, response={r.text[:500]}")
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response("❌ Impossible de créer la commande. Veuillez réessayer.", MAIN_MENU_BTNS)
            
    except Exception as e:
        logger.exception(f"[MARKET] create_order exception: {e}")

    _cleanup_marketplace_session(session)
    session["step"] = "MENU"
    return build_response("❌ Erreur lors de la création de la commande.", MAIN_MENU_BTNS)


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
    
    # === SMART FALLBACK : Détection d'intention ===
    intent_change = detect_intent_change(text, "marketplace")
    if intent_change and intent_change != "marketplace":
        logger.info(f"[SMART] Intent change detected: marketplace → {intent_change}")
        
        if intent_change == "coursier":
            from .conversation_flow_coursier import flow_coursier_handle
            session["step"] = "COURIER_POSITION_TYPE"
            # Ne pas passer le texte original
            return flow_coursier_handle(session, "")
        
        elif intent_change == "follow":
            from .conversation_flow_coursier import handle_follow
            return handle_follow(session)
        
        elif intent_change == "menu":
            session["step"] = "MENU"
            _cleanup_marketplace_session(session)
            return build_response("🏠 Menu principal", MAIN_MENU_BTNS)

    # ========== CATÉGORIES ==========
    if step == "MARKET_CATEGORY":
        categories = session.get("market_categories", {})

        # Si les catégories ne sont pas chargées, les charger maintenant
        if not categories:
            return _begin_marketplace(session)

        # Si le texte est vide (redirection depuis autre flow), afficher les catégories
        if not t:
            rows = []
            for k in sorted(categories.keys(), key=lambda x: int(x)):
                cat = categories[k]
                rows.append({
                    "id": k,
                    "title": (cat.get("nom") or cat.get("name", ""))[:30]
                })
            msg = "🛍️ *Sélectionnez une catégorie*"
            return _build_list_response(msg, rows, section_title="Catégories")

        # FIX #1: Créer un mapping texte → indice pour les boutons interactifs
        category_name_to_id = {}
        for idx, cat in categories.items():
            cat_name = normalize(cat.get("nom") or cat.get("name") or "")
            if cat_name:
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
                "title": _truncate_title(_merchant_display_name(m), 24),
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

        # FIX #1: Créer un mapping texte → indice pour les boutons interactifs
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
                        "title": _truncate_title(_merchant_display_name(m), 24),
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
                    "title": _truncate_title(_merchant_display_name(m), 24),
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
            prix = p.get("prix", 0)
            desc_produit = p.get("description", "")
            # FIX UX: Séparer nom et prix pour éviter la troncature
            title, description = _build_product_title_and_desc(nom, prix, desc_produit)
            rows.append({
                "id": str(i),
                "title": title,
                "description": description
            })

        msg = f"📦 *Produits de {_merchant_display_name(merchant)}*"
        return _build_list_response(msg, rows, section_title="Produits")

    # ========== PRODUITS ==========
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})
        logger.info(f"[MARKET] PRODUCTS step - received text: '{text}', normalized: '{t}'")
        logger.info(f"[MARKET] Available product indices: {list(produits.keys())}")

        if _is_retour(text):
            session["step"] = "MARKET_MERCHANT"
            merchants = session.get("market_merchants", {})
            rows = []
            for k in sorted(merchants.keys(), key=lambda x: int(x)):
                m = merchants[k]
                rows.append({
                    "id": k,
                    "title": _truncate_title(_merchant_display_name(m), 24),
                    "description": m.get("raison_sociale", "")[:60] if m.get("raison_sociale") else ""
                })
            msg = "🔙 *Marchands*"
            return _build_list_response(msg, rows, section_title="Marchands")

        # Chercher par indice direct (l'ID est maintenant envoyé depuis views.py)
        if t not in produits:
            # Fallback : créer un mapping texte → indice au cas où
            product_name_to_id = {}
            for idx, prod in produits.items():
                prod_name = normalize(prod.get("nom") or "")
                if prod_name:
                    product_name_to_id[prod_name] = idx
            
            # Essayer de trouver par nom
            if t in product_name_to_id:
                t = product_name_to_id[t]
            else:
                # Vraiment invalide
                rows = []
                for k in sorted(produits.keys(), key=lambda x: int(x)):
                    p = produits[k]
                    nom = p.get("nom", "—")
                    prix = p.get("prix", 0)
                    desc_produit = p.get("description", "")
                    # FIX UX: Séparer nom et prix pour éviter la troncature
                    title, description = _build_product_title_and_desc(nom, prix, desc_produit)
                    rows.append({
                        "id": k,
                        "title": title,
                        "description": description
                    })
                msg = "⚠️ Choix invalide."
                return _build_list_response(msg, rows, section_title="Produits")

        produit = produits[t]
        session["selected_product"] = produit
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = (produit.get("description") or "").strip()
        # Convertir le prix en float dès le départ pour éviter les erreurs de multiplication
        # Le prix peut être "2 500 FCFA" ou "2500" ou 2500
        prix_raw = produit.get("prix", 0)
        try:
            if isinstance(prix_raw, str):
                # Nettoyer: enlever espaces, "FCFA", etc.
                prix_clean = prix_raw.replace(" ", "").replace("FCFA", "").replace("fcfa", "").strip()
                prix_float = float(prix_clean) if prix_clean else 0
            else:
                prix_float = float(prix_raw) if prix_raw else 0
        except (ValueError, TypeError):
            logger.warning(f"[MARKET] Impossible de convertir prix: {prix_raw}")
            prix_float = 0
        
        session["new_request"]["unit_price"] = prix_float
        session["step"] = "MARKET_QUANTITY"

        # Si le produit a une image, l'afficher
        image_url = produit.get("image") or produit.get("photo")
        resp = build_response(
            "*📦 QUANTITÉ*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"*Produit :* _{produit.get('nom', '—')}_\n"
            f"*Prix unitaire :* {_fmt_fcfa(produit.get('prix', 0))} FCFA\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔢 *Combien en voulez-vous ?*\n\n"
            "_Tapez un nombre_\n"
            "_Exemple :_ `2`",
            ["🔙 Retour"]
        )
        
        # Ajouter l'image si disponible
        if image_url and isinstance(image_url, str) and image_url.startswith("http"):
            resp["media"] = {
                "type": "image",
                "url": image_url,
                "caption": f"📦 {produit.get('nom', '—')}\n💰 {_fmt_fcfa(produit.get('prix', 0))} FCFA"
            }
        
        return resp

    # ========== QUANTITÉ ==========
    if step == "MARKET_QUANTITY":
        if _is_retour(text):
            session["step"] = "MARKET_PRODUCTS"
            # Réafficher la liste des produits
            produits = session.get("market_products_list", [])
            if not produits:
                return build_response("⚠️ Liste de produits vide.", ["🔙 Retour"])
            
            rows = []
            for idx, p in enumerate(produits, start=1):
                title, description = _build_product_title_and_desc(p)
                rows.append({"id": str(idx), "title": title, "description": description})
            
            resp = build_response("📦 *Produits de " + _merchant_display_name(session.get("market_merchant", {})) + "*")
            resp["list"] = {"rows": rows[:10], "button": "Voir produits", "title": "Produits"}
            return resp
        
        # === SMART FALLBACK : Validation intelligente de la quantité ===
        is_valid, qty, error_msg = smart_validate(text, "quantity", step)
        
        if not is_valid:
            error = generate_smart_error_message(text, "quantity", step)
            return build_response(error, ["🔙 Retour"])
        
        # Enregistrer la quantité et calculer le total
        session.setdefault("new_request", {})
        session["new_request"]["quantity"] = qty
        
        # Le unit_price devrait déjà être un float (converti à l'étape MARKET_PRODUCTS)
        unit_price = session["new_request"].get("unit_price", 0)
        
        # Sécurité supplémentaire : s'assurer que c'est bien un nombre
        if not isinstance(unit_price, (int, float)):
            try:
                unit_price = float(unit_price)
            except (ValueError, TypeError):
                unit_price = 0
        
        total_price = unit_price * qty
        session["new_request"]["value_fcfa"] = total_price
        
        session["step"] = "MARKET_DESTINATION"
        
        resp = build_response(
            "*📍 ADRESSE DE LIVRAISON*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "✍️ *Tapez votre adresse*\n"
            "_Exemple :_ `25 Rue Malanda, Poto-Poto`\n\n"
            "*OU*\n\n"
            "📱 *Partagez votre position*\n"
            "💡 _Appuyez sur le 📎 puis \"Position\"_"
        )
        resp["ask_location"] = True
        return resp

    # ========== ADRESSE ==========
    if step == "MARKET_DESTINATION":
        if _is_retour(text):
            session["step"] = "MARKET_QUANTITY"
            produit = session.get("selected_product", {})
            return build_response(
                "*📦 QUANTITÉ*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"*Produit :* _{produit.get('nom', '—')}_\n"
                f"*Prix unitaire :* {_fmt_fcfa(produit.get('prix', 0))} FCFA\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "🔢 *Combien en voulez-vous ?*\n\n"
                "_Tapez un nombre_\n"
                "_Exemple :_ `2`",
                ["🔙 Retour"]
            )
        
        if text and not _is_retour(text) and text.strip().upper() != "LOCATION_SHARED":
            produits = session.get("market_products", {})
            rows = []
            for k in sorted(produits.keys(), key=lambda x: int(x)):
                p = produits[k]
                nom = p.get("nom", "—")
                prix = p.get("prix", 0)
                desc_produit = p.get("description", "")
                # FIX UX: Séparer nom et prix pour éviter la troncature
                title, description = _build_product_title_and_desc(nom, prix, desc_produit)
                rows.append({
                    "id": k,
                    "title": title,
                    "description": description
                })
            msg = "🔙 *Produits*"
            return _build_list_response(msg, rows, section_title="Produits")

        # Gérer la localisation partagée
        if (lat is not None and lng is not None) or (text and text.strip().upper() == "LOCATION_SHARED"):
            # Si on a pas lat/lng mais text="LOCATION_SHARED", récupérer depuis session
            if lat is None or lng is None:
                last_loc = session.get("last_location", {})
                lat = last_loc.get("latitude")
                lng = last_loc.get("longitude")
            
            if lat and lng:
                session.setdefault("new_request", {})
                session["new_request"]["depart"] = "Position actuelle"
                session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
                session["new_request"]["latitude"] = lat
                session["new_request"]["longitude"] = lng
                session["step"] = "MARKET_PAY"
                return build_response(
                    "*💳 MODE DE PAIEMENT*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "_Choisissez votre mode de paiement :_",
                    ["💵 Espèces", "📱 Mobile Money", "🏦 Virement", "🔙 Retour"]
                )
        
        # Gérer l'adresse textuelle
        if text and not _is_retour(text) and text.strip().upper() != "LOCATION_SHARED":
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = text
            session["new_request"]["coordonnees_gps"] = ""
            session["step"] = "MARKET_PAY"
            return build_response(
                "*💳 MODE DE PAIEMENT*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "_Choisissez votre mode de paiement :_",
                ["💵 Espèces", "📱 Mobile Money", "🏦 Virement", "🔙 Retour"]
            )
        
        # Sinon redemander
        resp = build_response("⚠️ Besoin d'une adresse ou position.")
        resp["ask_location"] = True
        return resp

    # ========== PAIEMENT ==========
    if step == "MARKET_PAY":
        if _is_retour(text):
            session["step"] = "MARKET_DESTINATION"
            resp = build_response("📍 Nouvelle adresse ?")
            resp["ask_location"] = True
            return resp

        # FIX #3: Utiliser PAYMENT_METHODS avec normalize()
        key = normalize(text)
        if key not in PAYMENT_METHODS:
            return build_response(
                "⚠️ *Choix invalide*\n\n"
                "_Veuillez sélectionner un mode de paiement :_",
                ["💵 Espèces", "📱 Mobile Money", "🏦 Virement", "🔙 Retour"]
            )

        payment_method = PAYMENT_METHODS[key]
        session.setdefault("new_request", {})["payment_method"] = payment_method
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]
        merchant = session.get("market_merchant", {})
        pickup_addr, _ = _merchant_pickup_info(merchant)
        qty = d.get("quantity", 1)
        unit_price = d.get("unit_price", 0)
        total_price = d.get("value_fcfa", 0)

        # FIX #3: Utiliser PAYMENT_METHODS pour afficher le label correct
        payment_label = "Espèces" if payment_method == "espèces" else \
            "Mobile Money" if payment_method == "mobile_money" else \
                "Virement"

        recap = (
            "*📝 RÉCAPITULATIF DE VOTRE COMMANDE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*🏪 MARCHAND*\n"
            f"_{_merchant_display_name(merchant)}_\n\n"
            "*📍 ITINÉRAIRE*\n"
            f"🏪 Retrait : _{pickup_addr}_\n"
            f"🎯 Livraison : _{d.get('depart', '—')}_\n\n"
            "*📦 PRODUIT*\n"
            f"_{d.get('market_choice', '—')}_\n"
            f"• Quantité : *{qty}*\n"
            f"• Prix unitaire : {_fmt_fcfa(unit_price)} FCFA\n"
            f"• *Total : {_fmt_fcfa(total_price)} FCFA*\n\n"
            "*💳 PAIEMENT*\n"
            f"_{payment_label}_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "✅ _Tout est correct ?_"
        )
        return build_response(recap, ["✅ Confirmer", "✏️ Modifier", "🔙 Retour"])

    # ========== CONFIRMATION ==========
    if step == "MARKET_CONFIRM":
        if _is_retour(text):
            session["step"] = "MARKET_PAY"
            return build_response(
                "*💳 MODE DE PAIEMENT*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "_Choisissez votre mode de paiement :_",
                ["💵 Espèces", "📱 Mobile Money", "🏦 Virement", "🔙 Retour"]
            )

        # FIX #4: Vérifier la confirmation EN PREMIER avec tous les variants
        t_lower = normalize(text)

        # Confirmer l'ordre
        if t_lower in {"confirmer", "oui", "valider", "ok", "yes", "1"}:
            return marketplace_create_order(session)

        # Modifier
        if t_lower in {"modifier", "editer", "change", "changer", "2"}:
            session["step"] = "MARKET_PAY"
            return build_response(
                "*💳 MODE DE PAIEMENT*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "_Choisissez votre mode de paiement :_",
                ["💵 Espèces", "📱 Mobile Money", "🏦 Virement", "🔙 Retour"]
            )

        # Annuler
        if t_lower in {"annuler", "non", "cancel", "no", "3"}:
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response("✅ Commande annulée.", MAIN_MENU_BTNS)

        # Fallback - aucune option reconnue
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