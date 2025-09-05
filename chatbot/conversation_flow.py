from __future__ import annotations
import re, os, requests
from typing import Dict, Any, Optional, List
from urllib.parse import quote_plus

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")

# Sessions en mémoire (⚠️ à mettre en DB en prod)
user_sessions: Dict[str, Dict[str, Any]] = {}

WELCOME_TEXT = (
    "🚚 Bienvenue sur *TokTok Delivery* !\n"
    "✨ Votre plateforme de livraison à Brazzaville.\n\n"
    "🔐 Tapez votre mot de passe pour vous connecter,\n"
    "ou envoyez *s'inscrire* pour créer un compte."
)

MAIN_MENU_BTNS = ["Nouvelle demande", "Suivre ma livraison", "Historique", "Marketplace"]
GREETINGS = ["bonjour", "salut", "bjr", "hello", "bonsoir", "hi"]

# ------------------------------------------------------
# Helpers
# ------------------------------------------------------

def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()

def build_response(text: str, buttons: Optional[List[str]] = None) -> Dict[str, Any]:
    r = {"response": text}
    if buttons:
        r["buttons"] = buttons
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
    return user_sessions[phone]

def get_session(phone: str) -> Dict[str, Any]:
    return user_sessions.get(phone) or start_session(phone)

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    if session.get("auth_token"):
        headers["Authorization"] = f"Bearer {session['auth_token']}"
    r = requests.request(method, f"{API_BASE}{path}", headers=headers, timeout=15, **kwargs)
    print(f"[DEBUG] API {method} {path} ->", r.status_code, r.text[:200])
    return r

# ------------------------------------------------------
# Connexion / Inscription
# ------------------------------------------------------

def handle_login(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "LOGIN_WAIT_PWD"
    return build_response(WELCOME_TEXT)

def handle_login_password(session: Dict[str, Any], pwd: str) -> Dict[str, Any]:
    try:
        r = requests.post(
            f"{API_BASE}/api/v1/auth/login/",
            json={"username": session["phone_number"], "password": pwd},
            timeout=10
        )
        print("[DEBUG] login status:", r.status_code, r.text)

        if r.status_code != 200:
            if "username" in r.text or "non trouvé" in r.text.lower():
                session["step"] = "REGISTER_NAME"
                return build_response(
                    "⚠️ Ce numéro n'est pas encore enregistré.\n"
                    "👉 Créons un compte. Quel est votre nom complet ?"
                )
            return build_response("❌ Mot de passe incorrect.\n👉 Réessayez ou envoyez *Réinitialiser* pour changer votre mot de passe.")

        # Succès login
        data = r.json()
        token = data.get("access") or data.get("token")
        if not token:
            return build_response("❌ Erreur technique : impossible de récupérer le token.")
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

        return build_response(
            f"👋 Bonjour {nom}, heureux de vous revoir 🚚✨\n\n"
            "👉 Choisissez une option ci-dessous :",
            MAIN_MENU_BTNS,
        )

    except Exception as e:
        print("[ERROR] login exception:", e)
        return build_response("❌ Erreur réseau. Veuillez réessayer.")

def handle_register_pwd(session: Dict[str, Any], pwd: str) -> Dict[str, Any]:
    try:
        payload = {
            "user": {
                "username": session["phone_number"],
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
        print("[DEBUG] register status:", r.status_code, r.text)

        if r.status_code in [200, 201]:
            return handle_login_password(session, pwd)

        # Gestion erreurs UX
        data = r.json()
        details = data.get("details", {})

        if "phone_number" in details.get("user", {}):
            session["step"] = "LOGIN_WAIT_PWD"
            return build_response(
                "⚠️ Ce numéro est déjà associé à un compte.\n"
                "👉 Tapez votre mot de passe pour vous connecter,\n"
                "ou envoyez *Réinitialiser* pour changer le mot de passe."
            )

        if "username" in details.get("user", {}):
            return build_response(
                "⚠️ Un compte existe déjà avec ce numéro.\n"
                "👉 Essayez de vous connecter avec votre mot de passe."
            )

        if "password" in details.get("user", {}):
            return build_response(
                "❌ Mot de passe invalide.\n\n"
                "👉 Votre mot de passe doit contenir :\n"
                "   • Minimum 8 caractères\n"
                "   • 1 majuscule (A-Z)\n"
                "   • 1 minuscule (a-z)\n"
                "   • 1 chiffre (0-9)\n"
                "   • 1 caractère spécial (!@#...)\n\n"
                "Veuillez réessayer."
            )

        return build_response("❌ Erreur d'inscription. Vérifiez vos informations et réessayez.")

    except Exception as e:
        print("[ERROR] register exception:", e)
        return build_response("❌ Erreur réseau. Veuillez réessayer plus tard.")

# ------------------------------------------------------
# Flows Livraison / Coursier
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
        return build_response(
            f"✅ Mission #{mission_id} créée avec succès.\n"
            "🚴 Un livreur va bientôt accepter la course.",
            MAIN_MENU_BTNS
        )
    except Exception as e:
        print("[ERROR] courier_create:", e)
        return build_response("❌ Erreur lors de la création de la mission.", MAIN_MENU_BTNS)

# ------------------------------------------------------
# Historique & Suivi
# ------------------------------------------------------

def handle_follow(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "FOLLOW_WAIT"
    return build_response("🔎 Entrez l'ID de votre livraison.")

def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    try:
        r = api_request(session, "GET", "/api/v1/coursier/missions/")
        r.raise_for_status()
        data = r.json()
        if not data:
            return build_response("🗂️ Aucun historique disponible.", MAIN_MENU_BTNS)
        lines = [f"#{d['id']} — {d.get('statut','')} → {d.get('adresse_livraison','')}" for d in data[:5]]
        return build_response("🗂️ Vos 5 dernières livraisons :\n" + "\n".join(lines), MAIN_MENU_BTNS)
    except Exception as e:
        print("[ERROR] handle_history:", e)
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

# ------------------------------------------------------
# Router Principal (simplifié ici pour clarté)
# ------------------------------------------------------

def handle_message(phone: str, text: str,
                   photo_present: bool = False,
                   photo_url: Optional[str] = None,
                   price_value: Optional[float] = None) -> Dict[str, Any]:
    text = normalize(text)
    t = text.lower()
    session = get_session(phone)

    # 🔐 Auth
    if not session.get("auth_token"):
        if session["step"] == "WELCOME":
            return handle_login(session)
        if session["step"] == "LOGIN_WAIT_PWD":
            if t in ["sinscrire", "s'inscrire", "inscrire", "je veux m'inscrire"]:
                return handle_register_start(session)
            return handle_login_password(session, text)
        if session["step"] == "REGISTER_PWD":
            return handle_register_pwd(session, text)
        return build_response(WELCOME_TEXT)

    # Menu
    if t in GREETINGS or t in ["menu", "accueil"]:
        session["step"] = "MENU"
        return build_response("👉 Choisissez une option :", MAIN_MENU_BTNS)

    if t in ["1", "nouvelle demande", "coursier"]:
        session["step"] = "COURIER_DEPART"
        return build_response("📍 Partagez la *localisation de départ* ou entrez l’adresse manuellement.")

    if t in ["2", "suivre"]:
        return handle_follow(session)

    if t in ["3", "historique"]:
        return handle_history(session)

    if t in ["4", "marketplace"]:
        return handle_marketplace(session, text)

    return build_response("❓ Je n’ai pas compris.\n👉 Tapez *menu* pour revenir au menu principal.", MAIN_MENU_BTNS)
