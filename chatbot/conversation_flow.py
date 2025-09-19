# chatbot/conversation_flow.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional, List
from urllib.parse import quote_plus
from datetime import datetime
from openai import OpenAI
from .auth_core import get_session, build_response, normalize

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT  = int(os.getenv("TOKTOK_TIMEOUT", "15"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
openai_client  = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

WELCOME_TEXT = (
    "🚚 Bienvenue sur *TokTok Delivery* !\n"
    "✨ Votre plateforme de livraison à Brazzaville."
)
WELCOME_BTNS = ["Connexion", "Inscription"]

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]
GREETINGS = {"bonjour","salut","bjr","hello","bonsoir","hi","menu","accueil"}

# ------------------------------------------------------
# Helpers
# ------------------------------------------------------
def _headers(session: Dict[str, Any]) -> Dict[str, str]:
    tok = (session.get("auth") or {}).get("access")
    return {"Authorization": f"Bearer {tok}"} if tok else {}

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = {**_headers(session), **kwargs.pop("headers", {})}
    url = f"{API_BASE}{path}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API] {method} {path} -> {r.status_code}")
    return r

def mask_sensitive(value: str, visible: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]

def format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z",""))
        return dt.strftime("%d/%m/%Y à %Hh%M")
    except Exception:
        return iso_str

def _extract_results(payload):
    """Tolère API qui renvoie list ou dict{results: list}"""
    if isinstance(payload, dict) and "results" in payload and isinstance(payload["results"], list):
        return payload["results"]
    if isinstance(payload, list):
        return payload
    return []

# ------------------------------------------------------
# IA Fallback (OpenAI)
# ------------------------------------------------------
def ai_fallback(user_message: str, phone: str) -> Dict[str, Any]:
    if not openai_client:
        return build_response(
            "❓ Je n’ai pas compris.\n👉 Tapez *menu* pour les options.",
            MAIN_MENU_BTNS
        )
    try:
        system = (
            "Tu es TokTokBot, assistant WhatsApp pour TokTok Delivery.\n"
            "- Réponds en français, court et pro.\n"
            "- Si la demande concerne une livraison, propose les options du menu.\n"
            "- Suggère des actions valides: Nouvelle demande, Suivre ma demande, Marketplace."
        )
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message}
            ],
            temperature=0.3,
            max_tokens=220,
        )
        ai_reply = (completion.choices[0].message.content or "").strip()
        return build_response(ai_reply, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[AI_FALLBACK] {e}")
        return build_response("❌ Je n’ai pas compris.\n👉 Tapez *menu* pour revenir.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Création mission coursier (côté client)
# ------------------------------------------------------
def courier_create(session: Dict[str, Any]) -> Dict[str, Any]:
    d = session.setdefault("new_request", {})
    try:
        payload = {
            "entreprise_demandeur": (session.get("user") or {}).get("display_name") or "Client TokTok",
            "contact_entreprise": session.get("phone") or (session.get("user") or {}).get("username"),
            "adresse_recuperation": d.get("depart"),
            "coordonnees_recuperation": str(d.get("coordonnees_gps", "")),
            "adresse_livraison": d.get("destination"),
            "coordonnees_livraison": "",
            "nom_client_final": (session.get("user") or {}).get("display_name") or "Client",
            "telephone_client_final": session.get("phone"),
            "description_produit": d.get("description"),
            "valeur_produit": str(d.get("value_fcfa") or 0),
            "type_paiement": "entreprise_paie",
        }
        r = api_request(session, "POST", "/api/v1/coursier/missions/", json=payload)
        r.raise_for_status()
        mission = r.json()
        session["step"] = "MENU"

        # UX: ne jamais exposer l'ID BDD — on communique la référence publique
        ref = mission.get("numero_mission") or f"M-{mission.get('id','')}"
        msg = (
            "✅ Demande enregistrée.\n"
            f"🔖 *Référence* : {ref}\n"
            "🚴 Un livreur va accepter la course."
        )
        return build_response(msg, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[COURIER] create error: {e}")
        return build_response("❌ Erreur lors de la création de la demande.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Suivi & Historique (côté client)
# ------------------------------------------------------
def handle_follow(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "FOLLOW_WAIT"
    return build_response("🔎 Entrez la *référence* de votre demande (ex: COUR-20250919-001).")

def follow_lookup(session: Dict[str, Any], ref_input: str) -> Dict[str, Any]:
    """
    ⚠️ L'API n'accepte que l'ID en /{id}/.
    → Stratégie: on liste les missions du client via GET /api/v1/coursier/missions/
      puis on retrouve localement celle dont numero_mission == ref_input.
      Ensuite, on appelle /{id}/ pour le détail.
    """
    try:
        user = session.get("user") or {}
        if not user.get("id"):
            return build_response("⚠️ Vous devez être connecté pour suivre vos demandes.", MAIN_MENU_BTNS)

        # 1) Lister les missions de CE client
        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        missions = _extract_results(r.json())

        # 2) Retrouver par référence (case-sensitive côté API le plus souvent)
        ref = (ref_input or "").strip()
        mission = next((m for m in missions if (m.get("numero_mission") or "").strip() == ref), None)
        if not mission:
            session["step"] = "MENU"
            return build_response("❌ Demande introuvable. Vérifiez la *référence* saisie.", MAIN_MENU_BTNS)

        mission_id = mission.get("id")
        if not mission_id:
            session["step"] = "MENU"
            return build_response("❌ Référence invalide.", MAIN_MENU_BTNS)

        # 3) Détail par ID
        r = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
        r.raise_for_status()
        d = r.json()

        # 4) Récap UX (2 étapes)
        recap = (
            f"📦 Demande *{d.get('numero_mission','-')}* — *{d.get('statut','-')}*\n"
            f"🚏 *Départ* : {d.get('adresse_recuperation','-')}\n"
            f"📍 *Arrivée* : {d.get('adresse_livraison','-')}\n"
            f"💰 *Valeur* : {d.get('valeur_produit','-')} FCFA\n"
        )

        if d.get("statut") in {"assigned", "en_route", "completed"}:
            recap += f"\n📅 *Créée le* : {format_date(d.get('created_at','-'))}\n"
            if d.get("livreur_nom"):
                recap += f"🚴 *Livreur* : {d['livreur_nom']} ({d.get('livreur_telephone','-')})\n"
            if d.get("distance_estimee"):
                recap += f"📏 *Distance estimée* : {d['distance_estimee']}\n"

        session["step"] = "MENU"
        # UX: proposer CTA utiles
        return build_response(recap.strip(), ["Nouvelle demande", "Suivre ma demande", "Marketplace"])

    except Exception as e:
        logger.error(f"[FOLLOW] {e}")
        session["step"] = "MENU"
        return build_response("❌ Erreur lors du suivi.", MAIN_MENU_BTNS)

def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        user = session.get("user") or {}
        if not user.get("id"):
            return build_response("⚠️ Impossible de charger l’historique (non connecté).", MAIN_MENU_BTNS)

        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        data = _extract_results(r.json())

        if not data:
            return build_response("🗂️ Aucun historique disponible.", MAIN_MENU_BTNS)

        # Top 5, avec référence uniquement (pas d'ID BDD)
        lines = []
        for d in data[:5]:
            ref = d.get("numero_mission", "—")
            statut = d.get("statut", "—")
            dest = d.get("adresse_livraison", "—")
            lines.append(f"• {ref} — {statut} → {dest}")

        return build_response("🗂️ Vos 5 dernières demandes :\n" + "\n".join(lines), MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[HISTORY] {e}")
        return build_response("❌ Erreur lors du chargement de l'historique.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Marketplace
# ------------------------------------------------------
def handle_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "MARKET_CATEGORY"
    CATEGORIES = ["Restauration", "Mode", "Pharmacie"]
    return build_response("🛍️ Choisissez une *catégorie* :", CATEGORIES)

def handle_marketplace_category(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    t = text.lower().strip()
    mapping = {"restauration": "Restauration", "mode": "Mode", "pharmacie": "Pharmacie"}
    if t not in mapping:
        return build_response("⚠️ Catégorie invalide. Choisissez :", list(mapping.values()))

    cat = mapping[t]
    session["market_category"] = cat
    session["step"] = "MARKET_MERCHANT"

    r = api_request(session, "GET", f"/api/v1/marketplace/merchants/?categorie={quote_plus(cat)}")
    try:
        data = r.json()
    except Exception:
        data = []

    merchants = data.get("results", []) if isinstance(data, dict) else data
    if not merchants:
        return build_response(f"❌ Aucun marchand trouvé dans la catégorie *{cat}*.", ["Menu"])

    merchants = merchants[:5]
    session["market_merchants"] = {str(i+1): m for i, m in enumerate(merchants)}

    lines = [f"{i+1}. {m.get('nom','—')}" for i, m in enumerate(merchants)]
    return build_response(
        f"🏬 Marchands disponibles en *{cat}* :\n" + "\n".join(lines) + "\n\n👉 Tapez le *numéro* du marchand choisi."
    )

def handle_marketplace_merchant(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    merchants = session.get("market_merchants") or {}
    if text not in merchants:
        return build_response("⚠️ Choisissez un numéro valide de marchand.", list(merchants.keys()))

    merchant = merchants[text]
    session["market_merchant"] = merchant
    session["step"] = "MARKET_PRODUCTS"

    r = api_request(session, "GET", f"/api/v1/marketplace/produits/?merchant_id={merchant.get('id')}")
    try:
        data = r.json()
    except Exception:
        data = []

    produits = data.get("results", []) if isinstance(data, dict) else data
    if not produits:
        return build_response(f"❌ Aucun produit trouvé pour *{merchant.get('nom','—')}*.", ["Menu"])

    produits = produits[:5]
    session["market_products"] = {str(i+1): p for i, p in enumerate(produits)}

    lines = []
    for i, p in enumerate(produits, start=1):
        nom = p.get("nom", "—")
        prix = p.get("prix", "0")
        line = f"{i}. {nom} — {prix} FCFA"
        if p.get("photo_url"):
            line += f"\n🖼️ {p['photo_url']}"
        lines.append(line)

    return build_response(
        f"📦 Produits de *{merchant.get('nom','—')}* :\n" + "\n".join(lines) + "\n\n👉 Tapez le *numéro* du produit choisi."
    )

def handle_marketplace_product(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    produits = session.get("market_products") or {}
    if text not in produits:
        return build_response("⚠️ Choisissez un numéro valide de produit.", list(produits.keys()))

    produit = produits[text]
    session["new_request"] = {
        "market_choice": produit.get("nom"),
        "description": produit.get("description",""),
    }
    session["step"] = "MARKET_PAY"

    return build_response(
        f"📦 Vous avez choisi *{produit.get('nom')}* ({produit.get('prix')} FCFA).\n💳 Choisissez un mode de paiement :",
        ["Cash", "Mobile Money", "Virement"]
    )

def handle_marketplace_desc(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["new_request"]["description"] = text
    session["step"] = "MARKET_PAY"
    return build_response("💳 Choisissez un mode de paiement :", ["Cash", "Mobile Money", "Virement"])

def handle_marketplace_pay(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    mapping = {"cash": "cash", "mobile money": "mobile_money", "virement": "virement"}
    t = text.lower().strip()
    if t not in mapping:
        return build_response("Merci de choisir un mode valide.", ["Cash", "Mobile Money", "Virement"])
    session["new_request"]["payment_method"] = mapping[t]
    d = session["new_request"]
    session["step"] = "MARKET_CONFIRM"
    recap = (
        "📝 Commande Marketplace :\n"
        f"• Produit : {d.get('market_choice')}\n"
        f"• Description : {d.get('description')}\n"
        f"• Paiement : {d.get('payment_method')}\n"
        "👉 Confirmez-vous la commande ?"
    )
    return build_response(recap, ["Confirmer", "Annuler", "Modifier"])

def handle_marketplace_confirm(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    t = text.lower()
    if t in {"confirmer","oui"}:
        session["step"] = "MENU"
        return build_response("✅ Commande Marketplace enregistrée !", MAIN_MENU_BTNS)
    if t in {"annuler","non"}:
        session["step"] = "MENU"
        return build_response("❌ Commande annulée.", MAIN_MENU_BTNS)
    if t in {"modifier","edit"}:
        session["step"] = "MARKET_EDIT"
        return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit","Description","Paiement"])
    return build_response("👉 Répondez par Confirmer, Annuler ou Modifier.", ["Confirmer","Annuler","Modifier"])

def handle_marketplace_edit(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    t = text.lower()
    if t == "produit":
        session["step"] = "MARKET_SEARCH"; return build_response("🛍️ Quel *nouveau* produit recherchez-vous ?")
    if t == "description":
        session["step"] = "MARKET_DESC";   return build_response("📦 Entrez la *nouvelle* description du produit.")
    if t == "paiement":
        session["step"] = "MARKET_PAY";    return build_response("💳 Choisissez un *nouveau* mode de paiement.", ["Cash","Mobile Money","Virement"])
    return build_response("👉 Choisissez *Produit*, *Description* ou *Paiement*.", ["Produit","Description","Paiement"])

# ------------------------------------------------------
# Router principal (client)
# ------------------------------------------------------
def handle_message(
    phone: str,
    text: str,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    photo_present: bool = False,
    photo_url: Optional[str] = None,
    price_value: Optional[float] = None,
    **_,
) -> Dict[str, Any]:
    session = get_session(phone)
    t = normalize(text).lower()

    # Auth
    if not (session.get("auth") or {}).get("access"):
        session["step"] = "WELCOME"
        return build_response(WELCOME_TEXT, WELCOME_BTNS)

    # Menu
    if t in GREETINGS:
        session["step"] = "MENU"
        return build_response(
            "👉 Choisissez une option :\n"
            "- *1* Nouvelle demande\n"
            "- *2* Suivre ma demande\n"
            "- *3* Historique\n"
            "- *4* Marketplace",
            MAIN_MENU_BTNS
        )

    # Entrée menu rapide
    if t in {"1","nouvelle demande","coursier"}:
        session["step"] = "COURIER_DEPART"
        resp = build_response("📍 Partagez votre *localisation de départ* ou entrez l’adresse manuellement.")
        resp["ask_location"] = "📍 Merci de partager votre localisation."
        return resp

    if t in {"2","suivre","suivre ma demande","suivre ma livraison"}:
        return handle_follow(session)

    if t in {"3","historique"}:
        return handle_history(session)

    if t in {"4","marketplace"}:
        return handle_marketplace(session)

    # --- Localisation ---
    if lat is not None and lng is not None:
        if session.get("step") == "COURIER_DEPART":
            nr = session.setdefault("new_request", {})
            nr["depart"] = f"{lat},{lng}"
            nr["coordonnees_gps"] = f"{lat},{lng}"
            session["step"] = "COURIER_DEST"
            return build_response("✅ Localisation enregistrée.\n📍 Maintenant, quelle est l’adresse de *destination* ?")

    # --- Wizard création mission ---
    if session.get("step") == "COURIER_DEPART":
        session.setdefault("new_request", {})["depart"] = text
        session["step"] = "COURIER_DEST"
        return build_response("📍 Quelle est l'adresse de *destination* ?")

    if session.get("step") == "COURIER_DEST":
        session["new_request"]["destination"] = text
        session["step"] = "COURIER_VALUE"
        return build_response("💰 Quelle est la *valeur* du colis (FCFA) ?")

    if session.get("step") == "COURIER_VALUE":
        digits = re.sub(r"[^0-9]", "", text)
        amt = int(digits) if digits else None
        if not amt:
            return build_response("⚠️ Montant invalide. Entrez un nombre (ex: 15000).")
        session["new_request"]["value_fcfa"] = amt
        session["step"] = "COURIER_DESC"
        return build_response("📦 Merci. Pouvez-vous *décrire* le colis ?")

    if session.get("step") == "COURIER_DESC":
        session["new_request"]["description"] = text
        d = session["new_request"]
        session["step"] = "COURIER_CONFIRM"
        recap = (
            "📝 Détails de votre demande :\n"
            f"• Départ : {d.get('depart')}\n"
            f"• Destination : {d.get('destination')}\n"
            f"• Valeur : {d.get('value_fcfa')} FCFA\n"
            f"• Description : {d.get('description')}\n\n"
            "👉 Confirmez-vous la mission ?"
        )
        return build_response(recap, ["Confirmer","Annuler","Modifier"])

    if session.get("step") == "COURIER_CONFIRM":
        if t in {"confirmer","oui"}:
            return courier_create(session)
        if t in {"annuler","non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("✅ Demande annulée.", MAIN_MENU_BTNS)
        if t in {"modifier","edit"}:
            session["step"] = "COURIER_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?", ["Départ","Destination","Valeur","Description"])
        return build_response("👉 Répondez par *Confirmer*, *Annuler* ou *Modifier*.", ["Confirmer","Annuler","Modifier"])

    if session.get("step") == "COURIER_EDIT":
        if t in {"départ","depart"}:
            session["step"] = "COURIER_DEPART"
            resp = build_response("📍 Entrez la nouvelle adresse de *départ* ou partagez votre *localisation*.")
            resp["ask_location"] = True
            return resp
        if t == "destination":
            session["step"] = "COURIER_DEST"
            return build_response("📍 Entrez la nouvelle *destination*.")
        if t == "valeur":
            session["step"] = "COURIER_VALUE"
            return build_response("💰 Entrez la *nouvelle valeur* du colis (FCFA).")
        if t == "description":
            session["step"] = "COURIER_DESC"
            return build_response("📦 Entrez la *nouvelle description* du colis.")
        return build_response("👉 Choisissez *Départ*, *Destination*, *Valeur* ou *Description*.", ["Départ","Destination","Valeur","Description"])

    # --- Suivi par référence ---
    if session.get("step") == "FOLLOW_WAIT":
        return follow_lookup(session, text)

    # --- Marketplace flow ---
    if session.get("step") == "MARKET_CATEGORY":
        return handle_marketplace_category(session, text)
    if session.get("step") == "MARKET_MERCHANT":
        return handle_marketplace_merchant(session, text)
    if session.get("step") == "MARKET_PRODUCTS":
        return handle_marketplace_product(session, text)

    # Fallback IA
    return ai_fallback(text, phone)
