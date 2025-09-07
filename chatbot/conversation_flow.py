from __future__ import annotations
import re, os, requests, logging
from typing import Dict, Any, Optional, List
from urllib.parse import quote_plus
from openai import OpenAI   # ✅ Agent IA
from .auth_core import get_session, build_response, normalize


logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

user_sessions: Dict[str, Dict[str, Any]] = {}

WELCOME_TEXT = (
    "🚚 Bienvenue sur *TokTok Delivery* !\n"
    "✨ Votre plateforme de livraison à Brazzaville."
)
WELCOME_BTNS = ["Connexion", "Inscription"]

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma livraison", "Marketplace"]
GREETINGS = ["bonjour", "salut", "bjr", "hello", "bonsoir", "hi"]

# ------------------------------------------------------
# Helpers
# ------------------------------------------------------


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def build_response(text: str, buttons: Optional[List[str]] = None) -> Dict[str, Any]:
    r = {"response": text}
    if buttons:
        r["buttons"] = buttons[:3]
    return r

def start_session(phone: str) -> Dict[str, Any]:
    user_sessions[phone] = {
        "phone_number": phone,
        "step": "WELCOME",
        "profile": {},
        "auth_token": None,
        "new_request": {
            "depart": None,
            "destination": None,
            "photo": None,
            "value_fcfa": None,
            "description": None,
            "market_choice": None,
            "payment_method": None,
        },
    }
    logger.info(f"[SESSION] Nouvelle session pour {mask_sensitive(phone)}")
    return user_sessions[phone]

def get_session(phone: str) -> Dict[str, Any]:
    return user_sessions.get(phone) or start_session(phone)

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    if session.get("auth_token"):
        headers["Authorization"] = f"Bearer {session['auth_token']}"
    r = requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=15, **kwargs)
    logger.debug(f"[API] {method} {path} -> {r.status_code}")
    return r

def mask_sensitive(value: str, visible: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]

# ------------------------------------------------------
# Authentification & Inscription
# ------------------------------------------------------

def handle_register_start(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "REGISTER_FIRSTNAME"
    return build_response("👤 Bienvenue ! Quel est votre *prénom* ?")

def handle_register_firstname(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["profile"]["first_name"] = text.strip().capitalize()
    session["step"] = "REGISTER_LASTNAME"
    return build_response("✍️ Merci. Quel est votre *nom de famille* ?")

def handle_register_lastname(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["profile"]["last_name"] = text.strip().capitalize()
    session["step"] = "REGISTER_EMAIL"
    return build_response("📧 Merci. Quelle est votre adresse email ?")

def handle_register_email(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["profile"]["email"] = text.strip()
    session["step"] = "REGISTER_ADDRESS"
    return build_response("📍 Quelle est votre adresse principale ?")

def handle_register_address(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["profile"]["address"] = text.strip()
    session["step"] = "REGISTER_PWD"
    return build_response("🔑 Choisissez un mot de passe pour votre compte.")

def handle_register_pwd(session: Dict[str, Any], pwd: str) -> Dict[str, Any]:
    try:
        # Génération d’un username basé sur prénom.nom
        first = session["profile"].get("first_name", "").lower()
        last = session["profile"].get("last_name", "").lower()
        base_username = f"{first}.{last}".strip(".")
        if not base_username:
            base_username = session["phone_number"]

        username = base_username

        payload = {
            "user": {
                "username": username,
                "email": session["profile"]["email"],
                "first_name": session["profile"]["first_name"],
                "last_name": session["profile"]["last_name"],
                "phone_number": session["phone_number"],
                "user_type": "client",
                "password": pwd,
                "password_confirm": pwd,
            },
            "adresse_principale": session["profile"]["address"],
            "coordonnees_gps": session["profile"].get("gps", ""),
            "preferences_livraison": session["profile"].get("preferences", "Standard"),
        }
        r = requests.post(f"{API_BASE}/api/v1/auth/clients/", json=payload, timeout=10)
        logger.debug(f"[REGISTER] statut {r.status_code}")

        if r.status_code in [200, 201]:
            logger.info(f"[REGISTER] Succès inscription pour {mask_sensitive(session['phone_number'])}")
            return handle_login_password(session, pwd)

        logger.warning(f"[REGISTER] Erreur inscription pour {mask_sensitive(session['phone_number'])}")
        return build_response("❌ Erreur d'inscription. Vérifiez vos informations et réessayez.")

    except Exception as e:
        logger.error(f"[REGISTER] Exception: {str(e)}")
        return build_response("❌ Erreur réseau. Réessayez plus tard.")

def handle_login(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "WELCOME_CHOICE"
    return build_response(WELCOME_TEXT, WELCOME_BTNS)

def handle_login_password(session: Dict[str, Any], pwd: str) -> Dict[str, Any]:
    try:
        r = requests.post(
            f"{API_BASE}/api/v1/auth/login/",
            json={"username": session["phone_number"], "password": pwd},
            timeout=10
        )
        logger.debug(f"[LOGIN] statut {r.status_code}")

        if r.status_code != 200:
            logger.warning(f"[LOGIN] Échec connexion pour {mask_sensitive(session['phone_number'])}")
            return build_response("❌ Mot de passe incorrect.\n👉 Réessayez ou envoyez *S'inscrire*.")

        data = r.json()
        token = data.get("access") or data.get("token")
        if not token:
            return build_response("❌ Erreur technique : token manquant.")

        session["auth_token"] = token
        session["step"] = "MENU"

        try:
            profile = api_request(session, "GET", "/api/v1/auth/clients/my_profile/").json()
            first = profile.get("user", {}).get("first_name", "")
            last = profile.get("user", {}).get("last_name", "")
            nom = (first + " " + last).strip() or session["phone_number"]
            session["profile"]["name"] = nom
        except:
            nom = session["phone_number"]

        logger.info(f"[LOGIN] Succès connexion pour {mask_sensitive(session['phone_number'])}")
        return build_response(
            f"👋 Bonjour {session['profile'].get('name', nom)}, heureux de vous revoir 🚚✨\n\n"
            "👉 Choisissez une option :", MAIN_MENU_BTNS
        )

    except Exception as e:
        logger.error(f"[LOGIN] Exception: {str(e)}")
        return build_response("❌ Erreur réseau. Réessayez plus tard.")


# ------------------------------------------------------
# IA Fallback
# ------------------------------------------------------

def ai_fallback(user_message: str, phone: str) -> Dict[str, Any]:
    """
    Appel OpenAI pour gérer les cas où le message utilisateur
    n’est pas reconnu par les flows.
    """
    try:
        prompt = f"""
        Tu es **TokTokBot**, l’assistant WhatsApp de TokTok Delivery 🚚.
        Règles :
        - Réponds en français, style WhatsApp (clair, simple, professionnel).
        - Si la question concerne une livraison, redirige gentiment vers le menu.
        - Toujours proposer des options claires et courtes.

        Message reçu de {mask_sensitive(phone)} : "{user_message}"
        """

        completion = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_message}
            ]
        )

        ai_reply = completion.choices[0].message.content.strip()
        return build_response(ai_reply, MAIN_MENU_BTNS)

    except Exception as e:
        logger.error(f"[AI_FALLBACK] Erreur IA: {str(e)}")
        return build_response("❌ Je n’ai pas compris.\n👉 Tapez *menu* pour revenir.", MAIN_MENU_BTNS)


# ------------------------------------------------------
# Coursier / Missions
# ------------------------------------------------------

def courier_create(session: Dict[str, Any]) -> Dict[str, Any]:
    d = session["new_request"]
    try:
        payload = {
            "entreprise_demandeur": session["profile"].get("name") or "Client TokTok",
            "contact_entreprise": session["phone_number"],
            "adresse_recuperation": d["depart"],
            "coordonnees_recuperation": str(d.get("coordonnees_gps", "")),
            "adresse_livraison": d["destination"],
            "coordonnees_livraison": "",
            "nom_client_final": session["profile"].get("name") or "Client",
            "telephone_client_final": session["phone_number"],
            "description_produit": d["description"],
            "valeur_produit": str(d["value_fcfa"] or 0),
            "type_paiement": "entreprise_paie",
        }

        r = api_request(session, "POST", "/api/v1/coursier/missions/", json=payload)
        r.raise_for_status()
        mission = r.json()
        mission_id = mission.get("id")

        session["step"] = "MENU"
        logger.info(f"[COURIER] Mission {mission_id} créée pour {mask_sensitive(session['phone_number'])}")
        return build_response(
            f"✅ Mission #{mission_id} créée avec succès.\n🚴 Un livreur va bientôt accepter la course.",
            MAIN_MENU_BTNS
        )
    except Exception as e:
        logger.error(f"[COURIER] Erreur création mission: {str(e)}")
        return build_response("❌ Erreur lors de la création de la mission.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Suivi & Historique
# ------------------------------------------------------

def handle_follow(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "FOLLOW_WAIT"
    return build_response("🔎 Entrez l'ID de votre livraison.")

def follow_lookup(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    try:
        r = api_request(session, "GET", f"/api/v1/livraisons/livraisons/{text}/")
        if r.status_code == 404:
            return build_response("❌ Livraison introuvable.", MAIN_MENU_BTNS)
        r.raise_for_status()
        d = r.json()
        return build_response(
            f"📦 Livraison #{d['id']}\n"
            f"Statut: {d.get('statut')}\n"
            f"Départ: {d.get('adresse_recuperation')}\n"
            f"Arrivée: {d.get('adresse_livraison')}",
            MAIN_MENU_BTNS,
        )
    except Exception as e:
        logger.error(f"[FOLLOW] Exception: {str(e)}")
        return build_response("❌ Erreur lors du suivi.", MAIN_MENU_BTNS)

def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        data = r.json()
        if not data:
            return build_response("🗂️ Aucun historique disponible.")
        lines = [f"#{d['id']} — {d.get('statut','')} → {d.get('adresse_livraison','')}" for d in data[:5]]
        return build_response("🗂️ Vos 5 dernières livraisons :\n" + "\n".join(lines), MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[HISTORY] Exception: {str(e)}")
        return build_response("❌ Erreur lors du chargement de l'historique.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Marketplace
# ------------------------------------------------------

def handle_marketplace(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["step"] = "MARKET_SEARCH"
    return build_response("🛍️ Quel produit recherchez-vous ?")

def handle_marketplace_search(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/marketplace/produits/?search={quote_plus(text)}")
    produits = r.json()
    items = produits.get("results", [])
    if not items:
        return build_response("❌ Aucun produit trouvé.", ["Menu principal"])
    lines = [f"• {p['nom']} — {p['prix']} FCFA" for p in items[:5]]
    session["step"] = "MARKET_CHOICE"
    return build_response("🛍️ Produits trouvés :\n" + "\n".join(lines) + "\n\n👉 Indiquez le nom du produit choisi.")

def handle_marketplace_choice(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["new_request"]["market_choice"] = text
    session["step"] = "MARKET_DESC"
    return build_response(f"📦 Vous avez choisi *{text}*.\nSouhaitez-vous ajouter une description ?")

def handle_marketplace_desc(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    session["new_request"]["description"] = text
    session["step"] = "MARKET_PAY"
    return build_response("💳 Choisissez un mode de paiement :", ["Cash", "Mobile Money", "Virement"])

def handle_marketplace_pay(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    mapping = {
        "cash": "cash",
        "mobile money": "mobile_money",
        "virement": "virement",
    }
    t = text.lower()
    if t not in mapping:
        return build_response("Merci de choisir un mode valide.", ["Cash", "Mobile Money", "Virement"])
    session["new_request"]["payment_method"] = mapping[t]
    d = session["new_request"]
    session["step"] = "MARKET_CONFIRM"
    recap = (
        f"📝 Commande Marketplace :\n"
        f"• Produit : {d['market_choice']}\n"
        f"• Description : {d['description']}\n"
        f"• Paiement : {d['payment_method']}\n"
        "👉 Confirmez-vous la commande ?"
    )
    return build_response(recap, ["Confirmer", "Annuler", "Modifier"])

def handle_marketplace_confirm(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    t = text.lower()
    if t in ["confirmer", "oui"]:
        session["step"] = "MENU"
        return build_response("✅ Commande Marketplace enregistrée avec succès !", MAIN_MENU_BTNS)
    if t in ["annuler", "non"]:
        session["step"] = "MENU"
        return build_response("❌ Commande annulée.", MAIN_MENU_BTNS)
    if t in ["modifier", "edit"]:
        session["step"] = "MARKET_EDIT"
        return build_response("✏️ Que souhaitez-vous modifier ?", ["Produit", "Description", "Paiement"])
    return build_response("👉 Répondez par Confirmer, Annuler ou Modifier.",
                          ["Confirmer", "Annuler", "Modifier"])

def handle_marketplace_edit(session: Dict[str, Any], text: str) -> Dict[str, Any]:
    t = text.lower()
    if t == "produit":
        session["step"] = "MARKET_SEARCH"
        return build_response("🛍️ Quel nouveau produit recherchez-vous ?")
    if t == "description":
        session["step"] = "MARKET_DESC"
        return build_response("📦 Entrez la nouvelle description du produit.")
    if t == "paiement":
        session["step"] = "MARKET_PAY"
        return build_response("💳 Choisissez un nouveau mode de paiement.", ["Cash", "Mobile Money", "Virement"])
    return build_response("👉 Choisissez ce que vous voulez modifier.", ["Produit", "Description", "Paiement"])

# ------------------------------------------------------
# Router principal
# ------------------------------------------------------

def handle_message(phone: str, text: str,
                   photo_present: bool = False,
                   photo_url: Optional[str] = None,
                   price_value: Optional[float] = None) -> Dict[str, Any]:
    text = normalize(text)
    t = text.lower()
    session = get_session(phone)

    # Auth
    if not session.get("auth_token"):
        if session["step"] == "WELCOME":
            return handle_login(session)

        if session["step"] == "WELCOME_CHOICE":
            if t in ["connexion", "login"]:
                session["step"] = "LOGIN_WAIT_PWD"
                return build_response("🔑 Veuillez entrer votre mot de passe pour vous connecter.")
            if t in ["inscription", "s'inscrire", "sinscrire"]:
                return handle_register_start(session)
            return build_response("👉 Choisissez Connexion ou Inscription.", WELCOME_BTNS)

        if session["step"] == "LOGIN_WAIT_PWD":
            return handle_login_password(session, text)

        if session["step"] == "REGISTER_FIRSTNAME":
            return handle_register_firstname(session, text)
        if session["step"] == "REGISTER_LASTNAME":
            return handle_register_lastname(session, text)
        if session["step"] == "REGISTER_EMAIL":
            return handle_register_email(session, text)
        if session["step"] == "REGISTER_ADDRESS":
            return handle_register_address(session, text)
        if session["step"] == "REGISTER_PWD":
            return handle_register_pwd(session, text)

        return build_response(WELCOME_TEXT, WELCOME_BTNS)

    # Menu principal
    if t in GREETINGS or t in ["menu", "accueil"]:
        session["step"] = "MENU"
        return build_response(
            "👉 Choisissez une option :\n"
            "- *1* Nouvelle demande\n"
            "- *2* Suivre ma livraison\n"
            "- *3* Historique\n"
            "- *4* Marketplace",
            MAIN_MENU_BTNS
        )

    if t in ["1", "nouvelle demande", "coursier"]:
        session["step"] = "COURIER_DEPART"
        return build_response("📍 Partagez la *localisation de départ* ou entrez l’adresse manuellement.")

    if t in ["2", "suivre"]:
        return handle_follow(session)

    if t in ["3", "historique"]:
        return handle_history(session)

    if t in ["4", "marketplace"]:
        return handle_marketplace(session, text)


    # Coursier flow
    if session["step"] == "COURIER_DEPART":
        session["new_request"]["depart"] = text
        session["step"] = "COURIER_DEST"
        return build_response("📍 Quelle est l'adresse de destination ?")

    if session["step"] == "COURIER_DEST":
        session["new_request"]["destination"] = text
        session["step"] = "COURIER_VALUE"
        return build_response("💰 Quelle est la valeur du colis (FCFA) ?")

    if session["step"] == "COURIER_VALUE":
        amt = int(re.sub(r"[^0-9]", "", text)) if re.sub(r"[^0-9]", "", text) else None
        if amt:
            session["new_request"]["value_fcfa"] = amt
            session["step"] = "COURIER_DESC"
            return build_response("📦 Merci. Pouvez-vous décrire le colis ?")
        return build_response("⚠️ Montant invalide. Entrez un nombre (ex: 15000).")

    if session["step"] == "COURIER_DESC":
        session["new_request"]["description"] = text
        session["step"] = "COURIER_CONFIRM"
        d = session["new_request"]
        recap = (
            f"📝 Détails de votre demande :\n"
            f"• Départ : {d['depart']}\n"
            f"• Destination : {d['destination']}\n"
            f"• Valeur : {d['value_fcfa']} FCFA\n"
            f"• Description : {d['description']}\n\n"
            "👉 Confirmez-vous la mission ?"
        )
        return build_response(recap, ["Confirmer", "Annuler", "Modifier"])

    if session["step"] == "COURIER_CONFIRM":
        if t in ["confirmer", "oui"]:
            return courier_create(session)
        if t in ["annuler", "non"]:
            session["step"] = "MENU"
            return build_response("✅ Demande annulée.", MAIN_MENU_BTNS)
        if t in ["modifier", "edit"]:
            session["step"] = "COURIER_EDIT"
            return build_response("✏️ Que souhaitez-vous modifier ?", ["Départ", "Destination", "Valeur", "Description"])
        return build_response("👉 Répondez par Confirmer, Annuler ou Modifier.", ["Confirmer", "Annuler", "Modifier"])

    if session["step"] == "COURIER_EDIT":
        if t == "départ":
            session["step"] = "COURIER_DEPART"
            return build_response("📍 Entrez la nouvelle adresse de départ.")
        if t == "destination":
            session["step"] = "COURIER_DEST"
            return build_response("📍 Entrez la nouvelle adresse de destination.")
        if t == "valeur":
            session["step"] = "COURIER_VALUE"
            return build_response("💰 Entrez la nouvelle valeur du colis (FCFA).")
        if t == "description":
            session["step"] = "COURIER_DESC"
            return build_response("📦 Entrez la nouvelle description du colis.")
        return build_response("👉 Choisissez ce que vous voulez modifier.", ["Départ", "Destination", "Valeur", "Description"])

    # Marketplace flow
    if session["step"] == "MARKET_SEARCH":
        return handle_marketplace_search(session, text)
    if session["step"] == "MARKET_CHOICE":
        return handle_marketplace_choice(session, text)
    if session["step"] == "MARKET_DESC":
        return handle_marketplace_desc(session, text)
    if session["step"] == "MARKET_PAY":
        return handle_marketplace_pay(session, text)
    if session["step"] == "MARKET_CONFIRM":
        return handle_marketplace_confirm(session, text)
    if session["step"] == "MARKET_EDIT":
        return handle_marketplace_edit(session, text)

    # --------------------------------------------------
    # Fallback IA
    # --------------------------------------------------
    return ai_fallback(text, phone)