# chatbot/conversation_flow_marketplace.py
from __future__ import annotations
import os, logging, requests, re
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # réutilise le même fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]


# ========================================
# Helpers UI & WhatsApp Lists
# ========================================
def _fmt_fcfa(n: Any) -> str:
    try:
        i = int(float(str(n)))
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n)


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
    """Nettoie les données de marketplace de la session."""
    keys_to_clean = [
        "market_categories", "market_category", "market_merchants",
        "market_merchant", "market_products", "selected_product",
        "new_request"
    ]
    for key in keys_to_clean:
        session.pop(key, None)


def _build_list_response(title: str, items: List[Tuple[str, str]], footer: str = "", include_back: bool = True) -> Dict[
    str, Any]:
    """
    Crée une réponse avec liste WhatsApp native (jusqu'à 10 items).

    items: List[Tuple[id, display_text)]
    """
    # Construire les sections avec un max de 10 items
    sections = []
    rows = []

    for item_id, display_text in items:
        rows.append({
            "id": str(item_id),
            "title": display_text[:24],  # Limite WhatsApp
            "description": ""
        })

    if rows:
        sections.append({
            "title": "Sélectionnez une option",
            "rows": rows
        })

    # Ajouter option Retour si demandé
    if include_back:
        sections.append({
            "title": "Navigation",
            "rows": [
                {
                    "id": "retour",
                    "title": "🔙 Retour",
                    "description": "Revenir à l'étape précédente"
                }
            ]
        })

    resp = build_response(title, [])  # Pas de boutons, on va utiliser liste
    resp["type"] = "list"  # Type personnalisé pour list_message
    resp["title"] = title
    resp["body"] = title
    resp["footer"] = footer or ""
    resp["sections"] = sections

    return resp


# ========================================
# Data loaders (robustes)
# ========================================
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
        logger.error(f"[MARKET] fallback categories via entreprises failed: {e}")

    return cats


def _load_merchants_by_category(session: Dict[str, Any], category: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Charge toutes les entreprises puis filtre par category via le champ type_entreprise."""
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
    """
    Utilise l'endpoint produits par catégorie (si dispo), sinon produits disponibles.
    """
    # 1) by_category
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

    # 2) disponibles (fallback)
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/produits/disponibles/")
        if r.ok:
            data = r.json()
            return data.get("results", []) if isinstance(data, dict) else (data or [])
    except Exception as e:
        logger.error(f"[MARKET] produits disponibles failed: {e}")

    return []


# ========================================
# Flow utils
# ========================================
def _begin_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    cats = _load_categories(session)
    if not cats:
        session["step"] = "MENU"
        return build_response(
            "🛍️ Marketplace indisponible pour l'instant (aucune catégorie).",
            MAIN_MENU_BTNS
        )

    session["market_categories"] = {str(i + 1): c for i, c in enumerate(cats)}
    session["step"] = "MARKET_CATEGORY"

    # Créer la liste des catégories avec ID numérique
    cat_items = [(str(i + 1), f"{c.get('nom') or c.get('name') or '—'}") for i, c in enumerate(cats)]

    return _build_list_response(
        "🛍️ Choisissez une catégorie",
        cat_items,
        footer="Sélectionnez dans la liste"
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
    """Retourne (adresse_recuperation_text, coordonnees_recuperation_str)."""
    addr = ent.get("adresse") or ent.get("address") or ent.get("localisation") or _merchant_display_name(ent)
    lat = ent.get("latitude") or ent.get("lat")
    lng = ent.get("longitude") or ent.get("lng")
    coords = f"{lat},{lng}" if (lat is not None and lng is not None) else ""
    return str(addr), coords


# ========================================
# Création commande Marketplace
# ========================================
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
            "details": [
                {
                    "produit": int(produit.get("id", 0)),
                    "quantite": 1,
                    "prix_unitaire": float(produit.get("prix", 0)),
                }
            ],
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
                f"Numéro de commande : *{order_id}*\n"
                f"Marchand : {_merchant_display_name(merchant)}\n"
                f"Produit : {d.get('market_choice', '—')}\n"
                f"Montant : {_fmt_fcfa(d.get('value_fcfa', 0))} FCFA\n"
                f"Mode paiement : {pay_method}\n\n"
                "Vous pouvez suivre votre commande avec le bouton 'Suivre ma demande'."
            )
            return build_response(recap, MAIN_MENU_BTNS)
        else:
            error_msg = r.text if r.text else "Erreur de création"
            logger.error(f"[MARKET] order creation failed: {error_msg}")
            return build_response(
                f"❌ Erreur lors de la création de la commande.\n{error_msg}",
                MAIN_MENU_BTNS
            )

    except Exception as e:
        logger.error(f"[MARKET] exception in marketplace_create_order: {e}")
        return build_response(
            f"❌ Une erreur s'est produite : {str(e)}",
            MAIN_MENU_BTNS
        )


# ========================================
# Main flow handler
# ========================================
def flow_marketplace_handle(session: Dict[str, Any], text: str = "",
                            lat: Optional[float] = None,
                            lng: Optional[float] = None) -> Dict[str, Any]:
    """
    Gère tout le flux Marketplace avec support du Retour à chaque étape.
    """
    step = session.get("step", "MENU")
    t = normalize(text) if text else ""

    # ====== CATÉGORIES ======
    if step == "MARKET_CATEGORY":
        cats = session.get("market_categories", {})

        # ✅ Reconnaître le retour
        if t == "retour":
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response("✅ Retour au menu principal.", MAIN_MENU_BTNS)

        if t not in cats:
            cat_items = [(str(i + 1), f"{c.get('nom') or c.get('name') or '—'}") for i, c in
                         enumerate([cats.get(k) for k in sorted(cats.keys(), key=lambda x: int(x))])]
            return _build_list_response(
                "⚠️ Choix invalide. Veuillez sélectionner une catégorie.",
                cat_items
            )

        cat = cats[t]
        session["market_category"] = cat
        merchants = _load_merchants_by_category(session, cat)

        if not merchants:
            session["step"] = "MARKET_CATEGORY"
            cat_items = [(str(i + 1), f"{c.get('nom') or c.get('name') or '—'}") for i, c in
                         enumerate([cats.get(k) for k in sorted(cats.keys(), key=lambda x: int(x))])]
            return _build_list_response(
                f"❌ Aucun marchand pour *{cat.get('nom', '—')}*.",
                cat_items
            )

        session["market_merchants"] = {str(i + 1): m for i, m in enumerate(merchants)}
        session["step"] = "MARKET_MERCHANT"

        merchant_items = [(str(i + 1), _merchant_display_name(m)) for i, m in enumerate(merchants)]
        return _build_list_response(
            f"🏪 Marchands de *{cat.get('nom', '—')}*",
            merchant_items,
            footer="Sélectionnez un marchand"
        )

    # ====== MARCHANDS ======
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})

        # ✅ Reconnaître le retour
        if t == "retour":
            session["step"] = "MARKET_CATEGORY"
            cats = session.get("market_categories", {})
            cat_items = [(str(i + 1), f"{c.get('nom') or c.get('name') or '—'}") for i, c in
                         enumerate([cats.get(k) for k in sorted(cats.keys(), key=lambda x: int(x))])]
            return _build_list_response(
                "🔙 Choisissez une autre catégorie",
                cat_items
            )

        if t not in merchants:
            merchant_items = [(k, _merchant_display_name(merchants.get(k))) for k in
                              sorted(merchants.keys(), key=lambda x: int(x))]
            return _build_list_response(
                "⚠️ Choix invalide. Veuillez sélectionner un marchand.",
                merchant_items
            )

        merchant = merchants[t]
        session["market_merchant"] = merchant
        produits = _load_products_by_category(session, merchant.get("id"))

        if not produits:
            session["step"] = "MARKET_MERCHANT"
            merchant_items = [(k, _merchant_display_name(merchants.get(k))) for k in
                              sorted(merchants.keys(), key=lambda x: int(x))]
            return _build_list_response(
                f"❌ Aucun produit chez {_merchant_display_name(merchant)}.",
                merchant_items
            )

        produits = produits[:10]  # WhatsApp supporte jusqu'à 10 items
        session["market_products"] = {str(i + 1): p for i, p in enumerate(produits)}

        product_items = [(str(i + 1), f"{p.get('nom', '—')} — {_fmt_fcfa(p.get('prix', 0))} FCFA") for i, p in
                         enumerate(produits)]
        return _build_list_response(
            f"📦 Produits de *{_merchant_display_name(merchant)}*",
            product_items,
            footer="Sélectionnez un produit"
        )

    # ====== PRODUITS ======
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})

        # ✅ Reconnaître le retour
        if t == "retour":
            session["step"] = "MARKET_MERCHANT"
            merchants = session.get("market_merchants", {})
            merchant_items = [(k, _merchant_display_name(merchants.get(k))) for k in
                              sorted(merchants.keys(), key=lambda x: int(x))]
            return _build_list_response(
                "🔙 Choisissez un autre marchand",
                merchant_items
            )

        if t not in produits:
            product_items = [
                (k, f"{produits.get(k).get('nom', '—')} — {_fmt_fcfa(produits.get(k).get('prix', 0))} FCFA") for k in
                sorted(produits.keys(), key=lambda x: int(x))]
            return _build_list_response(
                "⚠️ Choix invalide. Veuillez sélectionner un produit.",
                product_items
            )

        produit = produits[t]
        session["selected_product"] = produit
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = (produit.get("description") or "").strip()
        session["new_request"]["value_fcfa"] = produit.get("prix", 0)
        session["step"] = "MARKET_DESTINATION"

        resp = build_response(
            "📍 Où livrer la commande ?\n"
            "• Envoyez *l'adresse* (ex. `10 Avenue de la Paix, BZV`)\n"
            "• ou *partagez votre position*.\n"
            "• Tapez *Retour* pour revenir."
        )
        resp["ask_location"] = True
        return resp

    # ====== DESTINATION (CLIENT) ======
    if step == "MARKET_DESTINATION":
        # ✅ Reconnaître le retour
        if t == "retour":
            session["step"] = "MARKET_PRODUCTS"
            produits = session.get("market_products", {})
            product_items = [
                (k, f"{produits.get(k).get('nom', '—')} — {_fmt_fcfa(produits.get(k).get('prix', 0))} FCFA") for k in
                sorted(produits.keys(), key=lambda x: int(x))]
            return _build_list_response(
                "🔙 Choisissez un autre produit",
                product_items
            )

        if lat is not None and lng is not None:
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text and t not in {"retour"}:
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = text
            session["new_request"]["coordonnees_gps"] = ""
        else:
            resp = build_response(
                "⚠️ J'ai besoin d'une adresse ou de votre position pour livrer.\n"
                "(Tapez *Retour* pour revenir.)"
            )
            resp["ask_location"] = True
            return resp

        session["step"] = "MARKET_PAY"
        return build_response(
            "💳 Choisissez un mode de paiement :",
            ["Espèces", "Mobile Money", "Virement", "🔙 Retour"]
        )

    # ====== PAIEMENT ======
    if step == "MARKET_PAY":
        # ✅ Reconnaître le retour
        if t == "retour":
            session["step"] = "MARKET_DESTINATION"
            resp = build_response(
                "📍 Nouvelle adresse de livraison ?\n"
                "• Envoyez *l'adresse*\n"
                "• ou *partagez votre position*.\n"
                "(Tapez *Retour* pour revenir.)"
            )
            resp["ask_location"] = True
            return resp

        mapping = {
            "espèces": "espèces", "especes": "espèces", "1": "espèces",
            "mobile money": "mobile_money", "mobile": "mobile_money", "2": "mobile_money",
            "virement": "virement", "3": "virement",
        }
        key = t.strip()
        if key not in mapping:
            return build_response(
                "🙏 Merci de choisir un mode valide.",
                ["Espèces", "Mobile Money", "Virement", "🔙 Retour"]
            )

        session.setdefault("new_request", {})["payment_method"] = mapping[key]
        session["step"] = "MARKET_CONFIRM"

        d = session["new_request"]
        merchant = session.get("market_merchant", {})
        pickup_addr, _ = _merchant_pickup_info(merchant)
        prix = _fmt_fcfa(d.get("value_fcfa", 0))
        pay_label = {
            "espèces": "Espèces",
            "mobile_money": "Mobile Money",
            "virement": "Virement",
        }.get(d.get("payment_method", ""), "—")

        recap = (
            "📝 *Récapitulatif de votre commande*\n"
            f"• Marchand : {_merchant_display_name(merchant)}\n"
            f"• Retrait : {pickup_addr}\n"
            f"• Livraison : {d.get('depart', '—')}\n"
            f"• Produit : {d.get('market_choice', '—')} — {prix} FCFA\n"
            f"• Paiement : {pay_label}\n\n"
            "Tout est bon ?"
        )
        return build_response(recap, ["Confirmer", "Modifier", "🔙 Retour"])

    # ====== CONFIRMATION ======
    if step == "MARKET_CONFIRM":
        # ✅ Reconnaître le retour
        if t == "retour":
            session["step"] = "MARKET_PAY"
            return build_response(
                "💳 Choisissez un mode de paiement :",
                ["Espèces", "Mobile Money", "Virement", "🔙 Retour"]
            )

        if t in {"confirmer", "oui", "ok"}:
            interim = build_response("✨ Je finalise votre commande…")
            result = marketplace_create_order(session)
            return result if result else interim

        if t in {"annuler", "non"}:
            _cleanup_marketplace_session(session)
            session["step"] = "MENU"
            return build_response("✅ Commande annulée. Que souhaitez-vous faire ?", MAIN_MENU_BTNS)

        if t in {"modifier"}:
            session["step"] = "MARKET_EDIT"
            return build_response(
                "✏️ Que souhaitez-vous modifier ?",
                ["Produit", "Paiement", "Adresse de livraison", "Annuler", "🔙 Retour"]
            )

        return build_response(
            "👉 Répondez par *Confirmer*, *Modifier* ou *Annuler*.",
            ["Confirmer", "Modifier", "Annuler", "🔙 Retour"]
        )

    # ====== EDIT ======
    if step == "MARKET_EDIT":
        # ✅ Reconnaître le retour
        if t == "retour":
            session["step"] = "MARKET_CONFIRM"
            d = session.get("new_request", {})
            merchant = session.get("market_merchant", {})
            pickup_addr, _ = _merchant_pickup_info(merchant)
            prix = _fmt_fcfa(d.get("value_fcfa", 0))
            pay_label = {
                "espèces": "Espèces",
                "mobile_money": "Mobile Money",
                "virement": "Virement",
            }.get(d.get("payment_method", ""), "—")

            recap = (
                "📝 *Récapitulatif de votre commande*\n"
                f"• Marchand : {_merchant_display_name(merchant)}\n"
                f"• Retrait : {pickup_addr}\n"
                f"• Livraison : {d.get('depart', '—')}\n"
                f"• Produit : {d.get('market_choice', '—')} — {prix} FCFA\n"
                f"• Paiement : {pay_label}\n\n"
                "Tout est bon ?"
            )
            return build_response(recap, ["Confirmer", "Modifier", "🔙 Retour"])

        if t == "produit":
            session["step"] = "MARKET_PRODUCTS"
            produits = session.get("market_products", {})
            product_items = [
                (k, f"{produits.get(k).get('nom', '—')} — {_fmt_fcfa(produits.get(k).get('prix', 0))} FCFA") for k in
                sorted(produits.keys(), key=lambda x: int(x))]
            return _build_list_response(
                "📦 Choisissez un autre produit",
                product_items
            )

        if t == "paiement":
            session["step"] = "MARKET_PAY"
            return build_response(
                "💳 Choisissez un autre mode de paiement :",
                ["Espèces", "Mobile Money", "Virement", "🔙 Retour"]
            )

        if t in ["adresse de livraison", "adresse"]:
            session["step"] = "MARKET_DESTINATION"
            resp = build_response(
                "📍 Nouvelle adresse de livraison ?\n"
                "• Envoyez *l'adresse*\n"
                "• ou *partagez votre position*.\n"
                "(Tapez *Retour* pour revenir.)"
            )
            resp["ask_location"] = True
            return resp

        if t == "annuler":
            session["step"] = "MARKET_CONFIRM"
            d = session.get("new_request", {})
            merchant = session.get("market_merchant", {})
            pickup_addr, _ = _merchant_pickup_info(merchant)
            prix = _fmt_fcfa(d.get("value_fcfa", 0))
            pay_label = {
                "espèces": "Espèces",
                "mobile_money": "Mobile Money",
                "virement": "Virement",
            }.get(d.get("payment_method", ""), "—")

            recap = (
                "📝 *Récapitulatif de votre commande*\n"
                f"• Marchand : {_merchant_display_name(merchant)}\n"
                f"• Retrait : {pickup_addr}\n"
                f"• Livraison : {d.get('depart', '—')}\n"
                f"• Produit : {d.get('market_choice', '—')} — {prix} FCFA\n"
                f"• Paiement : {pay_label}\n\n"
                "Tout est bon ?"
            )
            return build_response(recap, ["Confirmer", "Modifier", "🔙 Retour"])

        return build_response(
            "Je n'ai pas compris. Que souhaitez-vous modifier ?",
            ["Produit", "Paiement", "Adresse de livraison", "Annuler", "🔙 Retour"]
        )

    # ====== FALLBACK ======
    if text:
        return ai_fallback(text, session.get("phone"))
    return build_response("🤖 Dites *Marketplace* ou *Menu* pour continuer.", MAIN_MENU_BTNS)


# ========================================
# Wrapper pour compatibilité avec le router
# ========================================
def handle_message(phone: str, text: str,
                   *, lat: Optional[float] = None,
                   lng: Optional[float] = None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)

    # 🔑 Si on n'a JAMAIS touché à la marketplace, initialiser
    if not session.get("market_categories") and not session.get("step", "").startswith("MARKET_"):
        return _begin_marketplace(session)

    return flow_marketplace_handle(session, text, lat=lat, lng=lng)