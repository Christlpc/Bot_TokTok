# chatbot/conversation_flow_marketplace.py
from __future__ import annotations
import os, logging, requests
from typing import Dict, Any, Optional
from .auth_core import get_session, build_response, normalize

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]

def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-MARKET] {method} {path} → {r.status_code}")
    return r

def handle_message(phone: str, text: str, lat: Optional[float] = None, lng: Optional[float] = None) -> Dict[str, Any]:
    session = get_session(phone)
    t = normalize(text).lower() if text else ""
    step = session.get("step")

    # Cas d’entrée depuis le menu : lancement du flow marketplace
    if step in {None, "MENU", "AUTHENTICATED"} and t in {"marketplace", "4"}:
        session["step"] = "MARKET_MERCHANT"  # ici on traitera “catégorie” + “marchands” ensemble
        # appeler l’API des entreprises (marchands / catégories)
        try:
            r = api_request(session, "GET", "/api/v1/auth/entreprises/")
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.error(f"[MARKET init entreprises] {e}")
            return build_response("❌ Impossible de charger les marchands.", MAIN_MENU_BTNS)

        entreprises = data.get("results", []) if isinstance(data, dict) else data
        if not entreprises:
            return build_response("❌ Aucun marchand disponible pour le moment.", MAIN_MENU_BTNS)

        # On peut considérer que chaque “entreprise” a une catégorie ou nom
        session["market_merchants"] = {str(i+1): ent for i, ent in enumerate(entreprises)}
        lignes = [f"{i + 1}. {ent.get('nom_entreprise') or ent.get('raison_sociale') or ent.get('nom') or '—'}"
                  for i, ent in enumerate(entreprises)]
        return build_response("🏬 Marchands disponibles :\n" + "\n".join(lignes),
                              list(session["market_merchants"].keys()))

    # Sélection du marchand (ou “entreprise”)
    if step == "MARKET_MERCHANT":
        merchants = session.get("market_merchants", {})
        if t not in merchants:
            return build_response("⚠️ Choisissez un numéro valide de marchand.", list(merchants.keys()))
        m = merchants[t]
        session["market_merchant"] = m
        session["step"] = "MARKET_PRODUCTS"

        # Récupérer les produits disponibles pour ce marchand
        # On peut appeler by_category si on a le champ catégorie ou simplement disponibles
        # Exemple : /api/v1/marketplace/produits/disponibles/?merchant_id=...
        # ou by_category si tu veux filtrer par catégorie
        merchant_id = m.get("id")
        # essayer avec l’endpoint “disponibles”
        path = f"/api/v1/marketplace/produits/disponibles/?merchant_id={merchant_id}"
        r = api_request(session, "GET", path)
        if r.status_code != 200:
            logger.error(f"[MARKET produits dispo API] status={r.status_code}, body={r.text}")
            return build_response("❌ Impossible de charger les produits.", MAIN_MENU_BTNS)

        data = r.json()
        produits = data.get("results", []) if isinstance(data, dict) else data
        if not produits:
            return build_response(f"❌ Aucun produit disponible chez *{m.get('nom','')}*.", MAIN_MENU_BTNS)

        produits = produits[:5]
        session["market_products"] = {str(i+1): p for i,p in enumerate(produits)}
        lignes = []
        for i, p in enumerate(produits, start=1):
            nom = p.get("nom", "—")
            prix = p.get("prix", "0")
            ligne = f"{i}. {nom} — {prix} FCFA"
            if p.get("photo_url"):
                ligne += f"\n🖼️ {p.get('photo_url')}"
            lignes.append(ligne)
        return build_response("📦 Produits disponibles :\n" + "\n".join(lignes),
                              list(session["market_products"].keys()))

    # Sélection du produit
    if step == "MARKET_PRODUCTS":
        produits = session.get("market_products", {})
        if t not in produits:
            return build_response("⚠️ Choisissez un numéro valide de produit.", list(produits.keys()))
        p = produits[t]
        session.setdefault("new_request", {})
        session["new_request"]["market_choice"] = p.get("nom")
        session["new_request"]["description"] = p.get("description", "")
        session["new_request"]["value_fcfa"] = p.get("prix", 0)
        session["step"] = "MARKETPLACE_LOCATION"
        resp = build_response("📍 Indiquez votre adresse de livraison ou partagez votre localisation.")
        resp["ask_location"] = True
        return resp

    # Localisation (adresse de livraison)
    if step == "MARKETPLACE_LOCATION":
        if lat is not None and lng is not None:
            session["new_request"]["depart"] = "Position actuelle"
            session["new_request"]["coordonnees_gps"] = f"{lat},{lng}"
        elif text:
            session["new_request"]["depart"] = text
        else:
            return build_response("❌ Veuillez fournir l’adresse ou partager la localisation.", MAIN_MENU_BTNS)

        session["step"] = "MARKET_PAY"
        return build_response("💳 Choisissez un mode de paiement :", ["Espèces", "Mobile Money", "Virement"])

    # Paiement
    if step == "MARKET_PAY":
        mapping = {"espèces": "cash", "mobile money": "mobile_money", "virement": "virement"}
        if t not in mapping:
            return build_response("Merci de choisir un mode valide.", ["Espèces", "Mobile Money", "Virement"])
        session["new_request"]["payment_method"] = mapping[t]
        session["step"] = "MARKET_CONFIRM"
        d = session["new_request"]
        recap = (
            "📝 Récapitulatif de votre commande :\n"
            f"• Produit : {d.get('market_choice')}\n"
            f"• Description : {d.get('description')}\n"
            f"• Paiement : {d.get('payment_method')}\n"
            "👉 Confirmez-vous cette commande ?"
        )
        return build_response(recap, ["Confirmer", "Annuler", "Modifier"])

    # Confirmation
    if step == "MARKET_CONFIRM":
        if t in {"confirmer", "oui"}:
            try:
                req = session["new_request"]
                payload = {
                    "entreprise_id": session["market_merchant"]["id"],
                    "produit_id": session["market_products"][next(iter(session["market_products"]))]["id"],
                    "adresse_livraison": req.get("depart"),
                    "coordonnes": req.get("coordonnees_gps", ""),
                    "mode_paiement": req.get("payment_method"),
                }
                # à adapter : utiliser l’endpoint de la création de commande dans ta doc
                r = api_request(session, "POST", "/api/v1/marketplace/commande/", json=payload)
                r.raise_for_status()
                session["step"] = "MENU"
                return build_response("✅ Votre commande a été passée avec succès !", MAIN_MENU_BTNS)
            except Exception as e:
                logger.error(f"[MARKET create commande] {e}")
                return build_response("❌ Erreur lors de la création de la commande.", MAIN_MENU_BTNS)

        if t in {"annuler", "non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("❌ Commande annulée.", MAIN_MENU_BTNS)

        if t in {"modifier"}:
            session["step"] = "MARKET_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit", "Description", "Paiement"])

        return build_response("👉 Confirmez, Annulez ou Modifiez.", ["Confirmer", "Annuler", "Modifier"])

    # fallback
    return build_response("❓ Je n’ai pas compris (marketplace).", MAIN_MENU_BTNS)
