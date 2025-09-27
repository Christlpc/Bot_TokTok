# chatbot/conversation_flow_marketplace.py
from __future__ import annotations
import os, logging, requests, re
from typing import Dict, Any, Optional, List, Tuple
from .auth_core import get_session, build_response, normalize
from .conversation_flow import ai_fallback  # réutilise le même fallback

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()  # non utilisé ici
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

# -----------------------------
# Helpers UI
# -----------------------------
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
    # 1) by_category (corrige le double slash)
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

# -----------------------------
# Flow utils
# -----------------------------
def _begin_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    cats = _load_categories(session)
    if not cats:
        session["step"] = "MENU"
        return build_response(
            "🛍️ Marketplace indisponible pour l’instant (aucune catégorie).",
            MAIN_MENU_BTNS
        )

    session["market_categories"] = {str(i + 1): c for i, c in enumerate(cats)}
    session["step"] = "MARKET_CATEGORY"

    lignes = [f"{i + 1}. {c.get('nom') or c.get('name') or '—'}" for i, c in enumerate(cats)]
    # Affiche les numéros en boutons (max 3 gérés par build_response)
    btns = list(session["market_categories"].keys())[:3]
    return build_response(
        "🛍️ Choisissez une *catégorie* :\n" + "\n".join(lignes) + "\n\nVous pouvez répondre par le *numéro*.",
        btns
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

# -----------------------------
# Création commande Marketplace
# -----------------------------
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
                {"produit": int(produit.get("id", 0)), "quantite": 1}
            ]
        }

        logger.debug(f"[MARKET] Payload commande envoyé: {payload}")
        r = api_request(session, "POST", "/api/v1/marketplace/commandes/", json=payload)

        if not r.ok:
            logger.error(f"[MARKET] Erreur {r.status_code}: {r.text}")
            r.raise_for_status()

        order = r.json()
        _cleanup_marketplace_session(session)

        msg = (
            "🎉 *Commande enregistrée !*\n"
            f"🔖 Numéro : {order.get('numero_commande', '—')}\n"
            "🚚 Un·e livreur·se prendra la livraison très bientôt. "
            "Vous serez notifié dès l’affectation."
        )
        return build_response(msg, MAIN_MENU_BTNS)

    except Exception as e:
        logger.exception(f"[MARKET] create error: {e}")
        session["step"] = "MENU"
        return build_response(
            "😓 Impossible de finaliser la commande pour le moment. Réessayez un peu plus tard.",
            MAIN_MENU_BTNS
        )

def _cleanup_marketplace_session(session: Dict[str, Any]) -> None:
    """Nettoie toutes les données marketplace de la session."""
    session["step"] = "MENU"
    for key in [
        "new_request", "market_category", "market_categories",
        "market_merchant", "market_merchants", "market_products", "selected_product"
    ]:
        session.pop(key, None)

# -----------------------------
# Flow Marketplace principal
# -----------------------------
def flow_marketplace_handle(session: Dict[str, Any], text: str,
                            lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    """
    Flow Marketplace :
    Catégorie -> Marchand -> Produits -> Adresse de livraison -> Paiement -> Confirmation
    """
    step = session.get("step")
    t = (normalize(text) or "").lower()

    # Raccourcis utiles
    if t in {"menu", "accueil", "0"}:
        _cleanup_marketplace_session(session)
        return build_response("🏠 Menu principal — que souhaitez-vous faire ?", MAIN_MENU_BTNS)

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
            btns = list(categories.keys())[:3]
            return build_response("⚠️ Choix invalide. Répondez avec le *numéro* de la catégorie.", btns)
        selected = categories[t]
        session["market_category"] = selected
        session["step"] = "MARKET_MERCHANT"

        merchants = _load_merchants_by_category(session, selected)
        if not merchants:
            session["step"] = "MARKET_CATEGORY"
            btns = list(categories.keys())[:3]
            return build_response(
                f"😕 Aucun marchand trouvé dans *{selected.get('nom') or selected.get('name') or '—'}*.\n"
                "Choisissez une autre catégorie :",
                btns
            )

        merchants = merchants[:5]
        session["market_merchants"] = {str(i + 1): m for i, m in enumerate(merchants)}
        lignes = [f"{i + 1}. {_merchant_display_name(m)}" for i, m in enumerate(merchants)]
        btns = list(session["market_merchants"].keys())[:3] + ["Retour"]
        return build_response(
            "🏬 Marchands disponibles :\n" + "\n".join(lignes) + "\n\nRépondez par le *numéro* ou *Retour*.",
            btns
        )

    # -------- MARCHANDS --------
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})
        if t == "retour":
            session["step"] = "MARKET_CATEGORY"
            cats = session.get("market_categories", {})
            btns = list(cats.keys())[:3]
            return build_response("🔙 Retour aux catégories. Choisissez un *numéro* :", btns)

        if t not in merchants:
            btns = list(merchants.keys())[:3] + ["Retour"]
            return build_response("⚠️ Choix invalide. Sélectionnez le *numéro* du marchand.", btns)

        merchant = merchants[t]
        session["market_merchant"] = merchant
        session["step"] = "MARKET_PRODUCTS"

        # Charger les produits de ce marchand
        try:
            r = api_request(session, "GET", "/api/v1/marketplace/produits/")
            if r.ok:
                data = r.json()
                produits = data.get("results", []) if isinstance(data, dict) else (data or [])
                produits = [p for p in produits if p.get("entreprise") == merchant.get("id")]
            else:
                produits = []
        except Exception as e:
            logger.error(f"[MARKET] Erreur chargement produits: {e}")
            produits = []

        if not produits:
            btns = list(merchants.keys())[:3] + ["Retour"]
            return build_response(
                f"😕 Aucun produit disponible chez *{_merchant_display_name(merchant)}*.\n"
                "Choisissez un autre marchand :",
                btns
            )

        produits = produits[:5]
        session["market_products"] = {str(i + 1): p for i, p in enumerate(produits)}
        lignes = []
        for i, p in enumerate(produits, start=1):
            nom = p.get("nom", "—")
            prix = _fmt_fcfa(p.get("prix", 0))
            ligne = f"{i}. {nom} — {prix} FCFA"
            if p.get("image"):
                ligne += f"\n🖼️ {p['image']}"
            lignes.append(ligne)

        btns = list(session["market_products"].keys())[:3] + ["Retour"]
        return build_response(
            f"📦 Produits de *{_merchant_display_name(merchant)}* :\n" + "\n".join(lignes) +
            "\n\nRépondez par le *numéro* ou *Retour*.",
            btns
        )

    # -------- PRODUITS --------
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})

        if t == "retour":
            session["step"] = "MARKET_MERCHANT"
            merchants = session.get("market_merchants", {})
            btns = list(merchants.keys())[:3] + ["Retour"]
            return build_response("🔙 Choisissez un autre marchand :", btns)

        if t not in produits:
            btns = list(produits.keys())[:3] + ["Retour"]
            return build_response("⚠️ Choix invalide. Sélectionnez le *numéro* du produit.", btns)

        produit = produits[t]
        session["selected_product"] = produit
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = produit.get("nom")
        session["new_request"]["description"] = (produit.get("description") or "").strip()
        session["new_request"]["value_fcfa"] = produit.get("prix", 0)
        session["step"] = "MARKET_DESTINATION"

        resp = build_response(
            "📍 Où livrer la commande ?\n"
            "• Envoyez *l’adresse* (ex. `10 Avenue de la Paix, BZV`)\n"
            "• ou *partagez votre position*."
        )
        resp["ask_location"] = True
        return resp

    # -------- DESTINATION (CLIENT) --------
    if step == "MARKET_DESTINATION":
        if lat is not None and lng is not None:
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text:
            session.setdefault("new_request", {})
            session["new_request"]["depart"] = text
            session["new_request"]["coordonnees_gps"] = ""
        else:
            resp = build_response("⚠️ J’ai besoin d’une adresse ou de votre position pour livrer.")
            resp["ask_location"] = True
            return resp

        session["step"] = "MARKET_PAY"
        return build_response(
            "💳 Choisissez un mode de paiement :",
            ["Espèces", "Mobile Money", "Virement"]
        )

    # -------- PAIEMENT --------
    if step == "MARKET_PAY":
        mapping = {
            "espèces": "espèces", "especes": "espèces", "1": "espèces",
            "mobile money": "mobile_money", "mobile": "mobile_money", "2": "mobile_money",
            "virement": "virement", "3": "virement",
        }
        key = t.strip()
        if key not in mapping:
            return build_response(
                "🙏 Merci de choisir un mode valide.",
                ["Espèces", "Mobile Money", "Virement"]
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
        return build_response(recap, ["Confirmer", "Modifier", "Annuler"])

    # -------- CONFIRMATION --------
    if step == "MARKET_CONFIRM":
        if t in {"confirmer", "oui", "ok"}:
            # Petite transition douce
            interim = build_response("✨ Je finalise votre commande…")
            # On enchaîne tout de suite avec la création (pas d'attente async)
            result = marketplace_create_order(session)
            # On donne priorité au résultat final
            return result if result else interim

        if t in {"annuler", "non"}:
            _cleanup_marketplace_session(session)
            return build_response("✅ Commande annulée. Que souhaitez-vous faire ?", MAIN_MENU_BTNS)

        if t in {"modifier"}:
            session["step"] = "MARKET_EDIT"
            return build_response(
                "✏️ Que souhaitez-vous modifier ?",
                ["Produit", "Paiement", "Adresse de livraison", "Annuler"]
            )

        return build_response("👉 Répondez par *Confirmer*, *Modifier* ou *Annuler*.", ["Confirmer", "Modifier", "Annuler"])

    # -------- EDIT --------
    if step == "MARKET_EDIT":
        if t == "produit":
            session["step"] = "MARKET_PRODUCTS"
            produits = session.get("market_products", {})
            btns = list(produits.keys())[:3] + ["Retour"]
            return build_response("📦 Choisissez un autre produit :", btns)

        if t == "paiement":
            session["step"] = "MARKET_PAY"
            return build_response("💳 Choisissez un autre mode de paiement :", ["Espèces", "Mobile Money", "Virement"])

        if t in ["adresse de livraison", "adresse"]:
            session["step"] = "MARKET_DESTINATION"
            resp = build_response("📍 Nouvelle adresse de livraison ? Envoyez l’adresse ou partagez la position.")
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
            return build_response(recap, ["Confirmer", "Modifier", "Annuler"])

        # Choix non reconnu
        return build_response(
            "Je n’ai pas compris. Que souhaitez-vous modifier ?",
            ["Produit", "Paiement", "Adresse de livraison", "Annuler"]
        )

    # -------- FALLBACK --------
    if text:
        return ai_fallback(text, session.get("phone"))
    return build_response("🤖 Dites *Marketplace* ou *Menu* pour continuer.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Wrapper pour compatibilité avec le router
# ------------------------------------------------------
def handle_message(phone: str, text: str,
                   *, lat: Optional[float] = None,
                   lng: Optional[float] = None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)
    return flow_marketplace_handle(session, text, lat=lat, lng=lng)
