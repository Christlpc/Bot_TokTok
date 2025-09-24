# chatbot/conversation_flow.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional
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
    "🚚 Bienvenue sur *TokTok* !\n"
    "✨ Votre service de livraison simple et rapide à Brazzaville."
)
WELCOME_BTNS = ["Connexion", "Inscription"]

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma demande", "Marketplace"]
GREETINGS = {"bonjour","salut","bjr","bonsoir","coucou","allo","menu","accueil"}

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

def format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z",""))
        return dt.strftime("%d/%m/%Y à %Hh%M")
    except Exception:
        return iso_str

def _extract_results(payload):
    if isinstance(payload, dict) and "results" in payload and isinstance(payload["results"], list):
        return payload["results"]
    if isinstance(payload, list):
        return payload
    return []

# ------------------------------------------------------
# IA Fallback
# ------------------------------------------------------
def ai_fallback(user_message: str, phone: str) -> Dict[str, Any]:
    if not openai_client:
        return build_response(
            "❓ Désolé, je n’ai pas compris.\n👉 Tapez *menu* pour voir les choix disponibles.",
            MAIN_MENU_BTNS
        )
    try:
        system = (
            "Tu es TokTokBot, assistant WhatsApp pour TokTok Delivery.\n"
            "- Réponds uniquement en français, de façon claire et professionnelle.\n"
            "- Si la demande concerne une livraison, propose les options du menu.\n"
            "- Les options valides sont : Nouvelle demande, Suivre ma demande, Marketplace."
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
        return build_response(
            "❌ Je n’ai pas compris.\n👉 Tapez *menu* pour revenir au choix principal.",
            MAIN_MENU_BTNS
        )

# ------------------------------------------------------
# Création demande
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
            "nom_client_final": d.get("destinataire_nom") or (session.get("user") or {}).get("display_name") or "Client",
            "telephone_client_final": d.get("destinataire_tel") or session.get("phone"),
            "description_produit": d.get("description"),
            "valeur_produit": str(d.get("value_fcfa") or 0),
            "type_paiement": d.get("payment_method", "entreprise_paie"),
        }
        r = api_request(session, "POST", "/api/v1/coursier/missions/", json=payload)
        r.raise_for_status()
        mission = r.json()
        session["step"] = "MENU"

        ref = mission.get("numero_mission") or f"M-{mission.get('id','')}"
        msg = (
            "✅ Votre demande a été enregistrée.\n"
            f"🔖 Référence : {ref}\n"
            "🚴 Un livreur prendra en charge la course très bientôt."
        )
        return build_response(msg, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[COURIER] create error: {e}")
        return build_response("❌ Une erreur est survenue lors de la création de la demande.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Suivi & Historique
# ------------------------------------------------------
def handle_follow(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "FOLLOW_WAIT"
    try:
        if not (session.get("auth") or {}).get("access"):
            return build_response("⚠️ Vous devez être connecté pour suivre vos demandes.", MAIN_MENU_BTNS)

        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        data = r.json() or {}
        missions = data.get("results", [])[:3]

        if not missions:
            return build_response("🗂️ Vous n’avez aucune demande en cours.", MAIN_MENU_BTNS)

        lignes = []
        for m in missions:
            ref_long = m.get("numero_mission", "-")
            suffixe = ref_long.split("-")[-1] if ref_long else "?"
            ref_courte = f"#{suffixe}"
            statut = m.get("statut", "-")
            dest = m.get("adresse_livraison", "-")
            lignes.append(f"{ref_courte} → {dest} ({statut})")

        txt = (
            "🔎 Entrez la *référence* de votre demande "
            "(ex: COUR-20250919-003 ou #003).\n\n"
            "👉 Vos dernières demandes :\n" + "\n".join(lignes)
        )
        return build_response(txt)

    except Exception as e:
        logger.error(f"[FOLLOW_LIST] {e}")
        return build_response("❌ Impossible de charger vos demandes.", MAIN_MENU_BTNS)

def follow_lookup(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    try:
        if not (session.get("auth") or {}).get("access"):
            return build_response("⚠️ Vous devez être connecté pour suivre vos demandes.", MAIN_MENU_BTNS)

        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        data = r.json() or {}
        all_missions = data.get("results", [])

        if not all_missions:
            return build_response("❌ Vous n’avez aucune demande enregistrée.", MAIN_MENU_BTNS)

        ref = text.strip()
        mission = None

        mission = next((m for m in all_missions if m.get("numero_mission") == ref), None)
        if not mission and ref.lstrip("#").isdigit():
            suffixe = ref.lstrip("#")
            mission = next(
                (m for m in all_missions if m.get("numero_mission", "").endswith(f"-{suffixe}")),
                None
            )
        if not mission and ref.upper().startswith("M-") and ref[2:].isdigit():
            alias = ref[2:]
            mission = next(
                (m for m in all_missions if str(m.get("id")) == alias),
                None
            )

        if not mission:
            return build_response(f"❌ Aucune demande trouvée avec la référence *{ref}*.", MAIN_MENU_BTNS)

        mission_id = mission.get("id")
        r2 = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
        r2.raise_for_status()
        d = r2.json()

        depart_aff = "Position actuelle" if d.get("coordonnees_recuperation") else d.get("adresse_recuperation","-")

        recap = (
            f"📦 Demande {d.get('numero_mission','-')} — {d.get('statut','-')}\n"
            f"🚏 Départ : {depart_aff}\n"
            f"📍 Arrivée : {d.get('adresse_livraison','-')}\n"
            f"👤 Destinataire : {d.get('nom_client_final','-')} ({d.get('telephone_client_final','-')})\n"
            f"💰 Valeur : {d.get('valeur_produit','-')} FCFA\n"
        )

        if d.get("statut") in {"assigned", "en_route", "completed"}:
            recap += f"\n📅 Créée le : {format_date(d.get('created_at','-'))}\n"
            if d.get("livreur_nom"):
                recap += f"🚴 Livreur : {d['livreur_nom']} ({d['livreur_telephone']})\n"
            if d.get("distance_estimee"):
                recap += f"📏 Distance estimée : {d['distance_estimee']}\n"

        return build_response(recap.strip(), MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[FOLLOW_LOOKUP] {e}")
        return build_response("❌ Erreur lors du suivi de la demande.", MAIN_MENU_BTNS)

def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        data = _extract_results(r.json())

        if not data:
            return build_response("🗂️ Aucun historique disponible.", MAIN_MENU_BTNS)

        lignes = []
        for d in data[:5]:
            ref = d.get("numero_mission", "—")
            statut = d.get("statut", "—")
            dest = d.get("adresse_livraison", "—")
            lignes.append(f"• {ref} — {statut} → {dest}")

        return build_response("🗂️ Vos 5 dernières demandes :\n" + "\n".join(lignes), MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[HISTORY] {e}")
        return build_response("❌ Erreur lors du chargement de l'historique.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Marketplace
# ------------------------------------------------------
def handle_marketplace(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "MARKET_CATEGORY"
    try:
        r = api_request(session, "GET", "/api/v1/marketplace/categories/")
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"[MARKETPLACE] API error: {e}")
        data = []
    categories = data.get("results", []) if isinstance(data, dict) else data
    if not categories:
        return build_response("❌ Aucune catégorie disponible pour le moment.", ["Menu"])
    session["market_categories"] = {str(i+1): c for i,c in enumerate(categories)}
    lignes = [f"{i+1}. {c.get('nom','—')}" for i,c in enumerate(categories)}
    return build_response("🛍️ Choisissez une *catégorie* :\n" + "\n".join(lignes),
                          list(session["market_categories"].keys()))

def handle_marketplace_category(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    categories = session.get("market_categories", {})
    if text not in categories:
        return build_response("⚠️ Catégorie invalide. Choisissez un numéro :", list(categories.keys()))
    selected_category = categories[text]
    session["market_category"] = selected_category
    session["step"] = "MARKET_MERCHANT"
    try:
        r = api_request(session, "GET", f"/api/v1/marketplace/merchants/?categorie={selected_category['id']}")
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"[MARKETPLACE_MERCHANTS] API error: {e}")
        data = []
    merchants = data.get("results", []) if isinstance(data, dict) else data
    if not merchants:
        return build_response(f"❌ Aucun marchand trouvé dans *{selected_category.get('nom','—')}*.", ["Menu"])
    merchants = merchants[:5]
    session["market_merchants"] = {str(i+1): m for i,m in enumerate(merchants)}
    lignes = [f"{i+1}. {m.get('nom','—')}" for i,m in enumerate(merchants)]
    return build_response(f"🏬 Marchands en *{selected_category.get('nom','—')}* :\n" + "\n".join(lignes),
                          list(session["market_merchants"].keys()))

def handle_marketplace_merchant(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    merchants = session.get("market_merchants") or {}
    if text not in merchants:
        return build_response("⚠️ Choisissez un numéro valide de marchand.", list(merchants.keys()))
    merchant = merchants[text]
    session["market_merchant"] = merchant
    session["step"] = "MARKET_PRODUCTS"
    try:
        r = api_request(session, "GET", f"/api/v1/marketplace/produits/?merchant_id={merchant['id']}")
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.error(f"[MARKETPLACE_PRODUCTS] API error: {e}")
        data = []
    produits = data.get("results", []) if isinstance(data, dict) else data
    if not produits:
        return build_response(f"❌ Aucun produit trouvé pour *{merchant.get('nom','—')}*.", ["Menu"])
    produits = produits[:5]
    session["market_products"] = {str(i+1): p for i,p in enumerate(produits)}
    lignes = []
    for i,p in enumerate(produits, start=1):
        nom = p.get("nom","—")
        prix = p.get("prix","0")
        ligne = f"{i}. {nom} — {prix} FCFA"
        if p.get("photo_url"):
            ligne += f"\n🖼️ {p['photo_url']}"
        lignes.append(ligne)
    return build_response(f"📦 Produits de *{merchant.get('nom','—')}* :\n" + "\n".join(lignes) +
                          "\n\n👉 Tapez le numéro du produit choisi.",
                          list(session["market_products"].keys()))

def handle_marketplace_product(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    produits = session.get("market_products") or {}
    if text not in produits:
        return build_response("⚠️ Choisissez un numéro valide de produit.", list(produits.keys()))
    produit = produits[text]
    session.setdefault("new_request", {})
    session["new_request"]["market_choice"] = produit.get("nom")
    session["new_request"]["description"] = produit.get("description","")
    session["new_request"]["value_fcfa"] = produit.get("prix",0)
    session["step"] = "MARKETPLACE_LOCATION"
    resp = build_response("📍 Indiquez votre adresse de départ ou partagez votre localisation.")
    resp["ask_location"] = True
    return resp

def handle_marketplace_location(session: Dict[str, Any], text: str=None, lat: float=None, lng: float=None) -> Dict[str, Any]:
    if lat is not None and lng is not None:
        location = f"{lat},{lng}"
        session.setdefault("new_request", {})["depart"] = "Position actuelle"
        session["new_request"]["coordonnees_gps"] = location
    elif text:
        session.setdefault("new_request", {})["depart"] = text
    else:
        return build_response("❌ Veuillez fournir votre localisation.", ["Menu"])
    session["step"] = "DEST_NOM"
    return build_response("👤 Quel est le *nom du destinataire* ?")

# ------------------------------------------------------
# Router principal
# ------------------------------------------------------
def handle_message(phone: str, text: str,
                   *, lat: Optional[float]=None,
                   lng: Optional[float]=None,
                   **_) -> Dict[str, Any]:
    session = get_session(phone)
    t = normalize(text).lower() if text else ""

    # Vérif auth
    if not (session.get("auth") or {}).get("access"):
        session["step"] = "WELCOME"
        return build_response(WELCOME_TEXT, WELCOME_BTNS)

    # Salutations
    if t in GREETINGS:
        session["step"] = "MENU"
        session.pop("new_request", None)
        return build_response("👉 Choisissez une option :", MAIN_MENU_BTNS)

    # Menu principal
    if t in {"1","nouvelle demande"}:
        session["step"] = "COURIER_DEPART"
        resp = build_response("📍 Indiquez votre adresse de départ ou partagez votre localisation.")
        resp["ask_location"] = True
        return resp
    if t in {"2","suivre","suivre ma demande"}:
        return handle_follow(session)
    if t in {"3","historique"}:
        return handle_history(session)
    if t in {"4","marketplace"}:
        return handle_marketplace(session)

    # Gestion localisation
    if lat is not None and lng is not None:
        if session.get("step") == "COURIER_DEPART":
            nr = session.setdefault("new_request", {})
            nr["depart"] = "Position actuelle"
            nr["coordonnees_gps"] = f"{lat},{lng}"
            session["step"] = "COURIER_DEST"
            return build_response("✅ Localisation enregistrée.\n📍 Quelle est l’adresse de destination ?")
        if session.get("step") == "MARKETPLACE_LOCATION":
            return handle_marketplace_location(session, lat=lat, lng=lng)

    # Flow coursier
    step = session.get("step")
    if step == "COURIER_DEPART":
        session.setdefault("new_request", {})["depart"] = text
        session["step"] = "COURIER_DEST"
        return build_response("📍 Quelle est l’adresse de destination ?")
    if step == "COURIER_DEST":
        session["new_request"]["destination"] = text
        session["step"] = "DEST_NOM"
        return build_response("👤 Quel est le *nom du destinataire* ?")
    if step == "DEST_NOM":
        session["new_request"]["destinataire_nom"] = text
        session["step"] = "DEST_TEL"
        return build_response("📞 Quel est le *numéro de téléphone du destinataire* ?")
    if step == "DEST_TEL":
        session["new_request"]["destinataire_tel"] = text
        session["step"] = "COURIER_VALUE"
        return build_response("💰 Quelle est la valeur du colis (en FCFA) ?")
    if step == "COURIER_VALUE":
        digits = re.sub(r"[^0-9]", "", text)
        amt = int(digits) if digits else None
        if not amt:
            return build_response("⚠️ Montant invalide. Entrez un nombre (ex: 15000).")
        session["new_request"]["value_fcfa"] = amt
        session["step"] = "COURIER_DESC"
        return build_response("📦 Merci. Décrivez brièvement le colis.")
    if step == "COURIER_DESC":
        session["new_request"]["description"] = text
        session["step"] = "COURIER_CONFIRM"
        d = session["new_request"]
        recap = (
            "📝 Récapitulatif de votre demande :\n"
            f"• Départ : {d.get('depart')}\n"
            f"• Destination : {d.get('destination')}\n"
            f"• Destinataire : {d.get('destinataire_nom')} ({d.get('destinataire_tel')})\n"
            f"• Valeur : {d.get('value_fcfa')} FCFA\n"
            f"• Description : {d.get('description')}\n\n"
            "👉 Confirmez-vous cette demande ?"
        )
        return build_response(recap, ["Confirmer","Annuler","Modifier"])
    if step == "COURIER_CONFIRM":
        if t in {"confirmer","oui"}:
            return courier_create(session)
        if t in {"annuler","non"}:
            session["step"] = "MENU"
            session.pop("new_request", None)
            return build_response("✅ Demande annulée.", MAIN_MENU_BTNS)

    # Flow marketplace
    if step == "MARKET_CATEGORY":
        return handle_marketplace_category(session, text)
    if step == "MARKET_MERCHANT":
        return handle_marketplace_merchant(session, text)
    if step == "MARKET_PRODUCTS":
        return handle_marketplace_product(session, text)
    if step == "MARKETPLACE_LOCATION":
        return handle_marketplace_location(session, text=text)

    return ai_fallback(text, phone)
