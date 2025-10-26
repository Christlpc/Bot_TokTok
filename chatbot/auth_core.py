# chatbot/auth_core.py
from __future__ import annotations
import os, logging, requests, unicodedata
from typing import Dict, Any, Optional, List

logger = logging.getLogger("toktok.auth")

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

# Mémoire de sessions (en prod: Redis/DB)
SESSIONS: Dict[str, Dict[str, Any]] = {}

# ---------- UI ----------
WELCOME_TEXT = (
    "👋 Bienvenue sur *TokTok Delivery* !\n"
    "Prêt·e à envoyer ou recevoir un colis ?\n"
    "Commencez par vous *connecter* ou *créer un compte*."
)

WELCOME_BTNS = ["Connexion", "Inscription", "Aide"]
SIGNUP_ROLE_BTNS = ["Client", "Livreur", "Entreprise"]

# ---------- Helpers ----------
def get_session(phone: str) -> Dict[str, Any]:
    s = SESSIONS.get(phone)
    if not s:
        s = {
            "phone": phone,
            "step": "WELCOME",
            "auth": {"access": None, "refresh": None},
            "user": {"role": None, "id": None, "display_name": None},
            "ctx": {},
        }
        SESSIONS[phone] = s
    return s

def build_response(text: str, buttons: Optional[List[str]] = None) -> Dict[str, Any]:
    r = {"response": text}
    if buttons:
        r["buttons"] = buttons[:3]
    return r

def normalize(s: str) -> str:
    return " ".join((s or "").split()).strip().lower()

def _auth_headers(session: Dict[str, Any]) -> Dict[str, str]:
    h: Dict[str, str] = {}
    tok = session.get("auth", {}).get("access")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

def _strip_accents(text: str) -> str:
    if not text:
        return text
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", text)

# ---------- Normalisations des choix (évite les 400) ----------
_ALLOWED_TYPE_LIVREUR = {"independant", "societe", "autoentrepreneur"}
def _norm_type_livreur(raw: str) -> Optional[str]:
    t = _strip_accents((raw or "").strip().lower())
    alias = {
        "independant": "independant",
        "indépendant": "independant",
        "indep": "independant",
        "solo": "independant",
        "societe": "societe",
        "société": "societe",
        "company": "societe",
        "autoentrepreneur": "autoentrepreneur",
        "auto-entrepreneur": "autoentrepreneur",
        "auto entrepreneur": "autoentrepreneur",
    }
    t = alias.get(t, t)
    return t if t in _ALLOWED_TYPE_LIVREUR else None

_ALLOWED_TYPE_VEHICULE = {"moto", "voiture", "velo", "camionnette"}
def _norm_type_vehicule(raw: str) -> Optional[str]:
    t = _strip_accents((raw or "").strip().lower())
    alias = {
        "moto": "moto",
        "scooter": "moto",
        "2 roues": "moto",
        "deux roues": "moto",
        "voiture": "voiture",
        "auto": "voiture",
        "car": "voiture",
        "velo": "velo",
        "vélo": "velo",
        "bicycle": "velo",
        "camionnette": "camionnette",
        "pickup": "camionnette",
        "fourgon": "camionnette",
    }
    t = alias.get(t, t)
    return t if t in _ALLOWED_TYPE_VEHICULE else None

# ---------- Détection de rôle & profils ----------
def detect_role_via_profiles(session: Dict[str, Any]) -> Optional[str]:
    try:
        r = requests.get(f"{API_BASE}/api/v1/auth/clients/my_profile/", headers=_auth_headers(session), timeout=TIMEOUT)
        if r.status_code == 200: return "client"
    except Exception:
        pass
    try:
        r = requests.get(f"{API_BASE}/api/v1/auth/livreurs/my_profile/", headers=_auth_headers(session), timeout=TIMEOUT)
        if r.status_code == 200: return "livreur"
    except Exception:
        pass
    try:
        r = requests.get(f"{API_BASE}/api/v1/auth/entreprises/my_profile/", headers=_auth_headers(session), timeout=TIMEOUT)
        if r.status_code == 200: return "entreprise"
    except Exception:
        pass
    return None

def fetch_role_profile(session: Dict[str, Any], role: str) -> Dict[str, Any]:
    url_map = {
        "client":     "/api/v1/auth/clients/my_profile/",
        "livreur":    "/api/v1/auth/livreurs/my_profile/",
        "entreprise": "/api/v1/auth/entreprises/my_profile/",
    }
    path = url_map.get(role)
    if not path:
        return {}
    r = requests.get(f"{API_BASE}{path}", headers=_auth_headers(session), timeout=TIMEOUT)
    return r.json() if r.status_code == 200 else {}

def route_to_role_menu(session: Dict[str, Any], role: str, intro_text: str) -> Dict[str, Any]:
    if role == "livreur":
        return build_response(
            intro_text + "\n- *Missions dispo*\n- *Mes missions*\n- *Basculer statut*",
            ["Missions dispo", "Mes missions", "Basculer statut"]
        )
    if role == "entreprise":
        return build_response(
            intro_text + "\n- *Créer produit*\n- *Mes produits*\n- *Commandes*",
            ["Créer produit", "Mes produits", "Commandes"]
        )
    # client par défaut
    return build_response(
        intro_text + "\n- *Nouvelle demande*\n- *Suivre ma demande*\n- *Marketplace*",
        ["Nouvelle demande", "Suivre ma demande", "Marketplace"]
    )

# ---------- Login commun ----------
def login_common(session: Dict[str, Any], username: str, password: str) -> Dict[str, Any]:
    r = requests.post(
        f"{API_BASE}/api/v1/auth/login/",
        json={"username": username, "password": password},
        timeout=TIMEOUT
    )
    if r.status_code != 200:
        logger.info("login_failed", extra={"event": "login_failed", "phone": username, "status_code": r.status_code})
        return build_response("⛔ Mot de passe incorrect ou compte introuvable.\nRéessayez ou tapez *Aide* si besoin.", ["Connexion", "Aide", "🔙 Retour"])

    data = r.json() or {}
    access = data.get("access") or data.get("token")
    refresh = data.get("refresh")
    if not access:
        logger.warning("login_no_token", extra={"event": "login_no_token", "phone": username})
        return build_response("⚠️ Une erreur technique est survenue.\nVeuillez réessayer dans quelques instants.", ["Connexion", "🔙 Retour"]
)

    session["auth"]["access"] = access
    session["auth"]["refresh"] = refresh

    # priorité: backend -> profils -> client
    role = (
        data.get("user_type") or data.get("role") or (data.get("user") or {}).get("role")
        or detect_role_via_profiles(session) or "client"
    )
    if role == "marchand":
        role = "entreprise"
    session["user"]["role"] = role

    display_name = (data.get("user", {}).get("first_name", "") + " " + data.get("user", {}).get("last_name", "")).strip()
    prof = fetch_role_profile(session, role)
    if role == "client":
        first = (prof.get("user") or {}).get("first_name", "")
        last = (prof.get("user") or {}).get("last_name", "")
        display_name = (f"{first} {last}").strip() or (prof.get("user") or {}).get("username") or username
    elif role == "livreur":
        display_name = prof.get("nom_complet") or prof.get("nom") or username
    elif role == "entreprise":
        display_name = prof.get("nom_entreprise") or prof.get("responsable", "") or username

    # ✅ stocker dans la session pour réutiliser
    session["profile"] = prof
    session["user"]["display_name"] = display_name or username
    session["step"] = "AUTHENTICATED"
    logger.info("login_ok", extra={"event": "login_ok", "phone": username, "role": role})
    return {"ok": True, "role": role, "display_name": session["user"]["display_name"]}

# ---------- Parsing erreurs API ----------
def _parse_api_errors(resp_json: dict) -> str:
    if not isinstance(resp_json, dict):
        return "Données invalides."
    details = resp_json.get("details") or resp_json.get("errors") or {}
    msg = resp_json.get("message") or ""
    if isinstance(details, dict) and details:
        items = []
        for field, msgs in details.items():
            if isinstance(msgs, list):
                item = "; ".join(str(m) for m in msgs)
            else:
                item = str(msgs)
            items.append(f"- {field}: {item}")
        suffix = "\n".join(items)
        return (msg + "\n" + suffix).strip() if msg else ("🚫 Certains champs sont invalides :\n" + suffix
)
    return msg or "Données invalides."

# ---------- Wizard d'inscription (Client / Livreur / Entreprise) ----------
def signup_start(session: Dict[str, Any]):
    session["signup"] = {"role": None, "data": {}, "password": None}
    session["step"] = "SIGNUP_ROLE"
    return build_response("📝 Super ! Pour commencer, indiquez votre rôle sur TokTok :"
, SIGNUP_ROLE_BTNS + ["🔙 Retour"])

def handle_signup_step(phone: str, text: str) -> Dict[str, Any]:
    session = get_session(phone)
    t = normalize(text)
    tl = _strip_accents(t.lower())

    # Gestion bouton retour contextuel - étape par étape
    if tl in {"retour", "back", "🔙 retour"}:
        current_step = session.get("step", "")
        role = session.get("signup", {}).get("role")
        
        # Navigation contexuelle selon l'étape
        if current_step == "SIGNUP_ROLE":
            session["step"] = "WELCOME_CHOICE"
            session.pop("signup", None)
            return build_response(WELCOME_TEXT, WELCOME_BTNS)
        
        # Pour les inscriptions : retour step par step selon le rôle
        if current_step.startswith("SIGNUP_CLIENT_"):
            step_order = ["SIGNUP_CLIENT_NAME", "SIGNUP_CLIENT_EMAIL", "SIGNUP_CLIENT_ADDRESS", "SIGNUP_CLIENT_PASSWORD"]
            try:
                current_idx = step_order.index(current_step)
                if current_idx > 0:
                    session["step"] = step_order[current_idx - 1]
                    # Reformuler la question de l'étape précédente
                    if step_order[current_idx - 1] == "SIGNUP_CLIENT_NAME":
                        return build_response("👤 *Client* — Votre *nom complet* ?\nExemple : `Jean Mbemba`", ["🔙 Retour"])
                    elif step_order[current_idx - 1] == "SIGNUP_CLIENT_EMAIL":
                        return build_response("📧 *Client* — Votre *email* ?\nExemple : `nom.prenom@gmail.com`", ["🔙 Retour"])
                    elif step_order[current_idx - 1] == "SIGNUP_CLIENT_ADDRESS":
                        return build_response("🏠 Quelle est votre adresse principale ?\nExemple : `25 Avenue de la Paix, Brazzaville`", ["🔙 Retour"])
                else:
                    session["step"] = "SIGNUP_ROLE"
                    return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])
            except ValueError:
                session["step"] = "SIGNUP_ROLE"
                return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])
        
        elif current_step.startswith("SIGNUP_LIVREUR_"):
            step_order = ["SIGNUP_LIVREUR_NAME", "SIGNUP_LIVREUR_EMAIL", "SIGNUP_LIVREUR_TYPE", 
                         "SIGNUP_LIVREUR_VEHICULE", "SIGNUP_LIVREUR_PERMIS", "SIGNUP_LIVREUR_ZONE", "SIGNUP_LIVREUR_PASSWORD"]
            try:
                current_idx = step_order.index(current_step)
                if current_idx > 0:
                    session["step"] = step_order[current_idx - 1]
                    # Reformuler selon l'étape
                    prev_step = step_order[current_idx - 1]
                    if prev_step == "SIGNUP_LIVREUR_NAME":
                        return build_response("🚴 *Livreur* — Votre *nom complet* ?\nExemple : `Paul Ngoma`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_LIVREUR_EMAIL":
                        return build_response("📧 *Livreur* — Votre *email* ?\nExemple : `livreur.exemple@gmail.com`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_LIVREUR_TYPE":
                        return build_response("🏷️ *Type livreur* ?\nExemples : `independant`, `societe`, `autoentrepreneur`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_LIVREUR_VEHICULE":
                        return build_response("🛵 *Type de véhicule* ?\nExemples : `moto`, `voiture`, `velo`, `camionnette`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_LIVREUR_PERMIS":
                        return build_response("🧾 *Numéro de permis* ?\nExemple : `BZV-123456-2025`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_LIVREUR_ZONE":
                        return build_response("🗺️ *Zone d'activité* ?\nExemples : `Brazzaville Centre`, `Poto-Poto`, `Talangaï`", ["🔙 Retour"])
                else:
                    session["step"] = "SIGNUP_ROLE"
                    return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])
            except ValueError:
                session["step"] = "SIGNUP_ROLE"
                return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])
        
        elif current_step.startswith("SIGNUP_MARCHAND_"):
            # Ordre des étapes entreprise
            step_order = ["SIGNUP_MARCHAND_ENTREPRISE", "SIGNUP_MARCHAND_TYPE", "SIGNUP_MARCHAND_DESC",
                         "SIGNUP_MARCHAND_ADR", "SIGNUP_MARCHAND_GPS", "SIGNUP_MARCHAND_RCCM",
                         "SIGNUP_MARCHAND_HOR", "SIGNUP_MARCHAND_CONTACT", "SIGNUP_MARCHAND_EMAIL", "SIGNUP_MARCHAND_PASSWORD"]
            try:
                current_idx = step_order.index(current_step)
                if current_idx > 0:
                    session["step"] = step_order[current_idx - 1]
                    prev_step = step_order[current_idx - 1]
                    # Reformuler selon l'étape
                    if prev_step == "SIGNUP_MARCHAND_ENTREPRISE":
                        return build_response("🏪 *Entreprise* — Nom de votre *entreprise* ?\nExemple : `Savana Restaurant`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_MARCHAND_TYPE":
                        resp = {
                            "response": "🏷️ *Type d'entreprise* ?\nChoisissez une catégorie dans la liste ci-dessous :",
                            "list": {
                                "title": "Catégories",
                                "rows": [
                                    {"id": "restaurant", "title": "Restaurant", "description": "🍽️ Restaurant, café, fast-food"},
                                    {"id": "pharmacie", "title": "Pharmacie", "description": "💊 Pharmacie, parapharmacie"},
                                    {"id": "supermarche", "title": "Supermarché", "description": "🛒 Supermarché, épicerie"},
                                    {"id": "boutique", "title": "Boutique", "description": "👕 Vêtements, accessoires"},
                                    {"id": "electronique", "title": "Électronique", "description": "📱 High-tech, électroménager"},
                                    {"id": "autre", "title": "Autre", "description": "🏢 Autre type d'activité"}
                                ]
                            }
                        }
                        return resp
                    elif prev_step == "SIGNUP_MARCHAND_DESC":
                        return build_response("📝 *Description* ?\nExemple : `Restaurant spécialisé en grillades africaines`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_MARCHAND_ADR":
                        return build_response("📍 *Adresse* de l'entreprise ?\nExemple : `Avenue des 3 Martyrs, Brazzaville`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_MARCHAND_GPS":
                        resp = build_response("📍 Pour vous localiser précisément, vous pouvez *envoyer votre position GPS* ou taper *Passer* pour continuer.", ["Passer", "🔙 Retour"])
                        resp["ask_location"] = "📌 Envoyez votre *position GPS* ou tapez *Passer*."
                        return resp
                    elif prev_step == "SIGNUP_MARCHAND_RCCM":
                        return build_response("🧾 *Numéro RCCM* ?\nExemple : `CG-BZV-01-2024-B12-00123`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_MARCHAND_HOR":
                        return build_response("⏰ *Horaires d'ouverture* ?\nExemple : `Lun-Sam 08h-20h`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_MARCHAND_CONTACT":
                        return build_response("👤 *Prénom Nom* du responsable ?\nExemple : `Pierre Mabiala`", ["🔙 Retour"])
                    elif prev_step == "SIGNUP_MARCHAND_EMAIL":
                        return build_response("📧 *Email* du responsable ?\nExemple : `responsable@entreprise.com`", ["🔙 Retour"])
                else:
                    session["step"] = "SIGNUP_ROLE"
                    return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])
            except ValueError:
                session["step"] = "SIGNUP_ROLE"
                return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])
        
        # Défaut : retour au choix du rôle
        session["step"] = "SIGNUP_ROLE"
        return build_response("📝 Indiquez votre rôle sur TokTok :", SIGNUP_ROLE_BTNS + ["🔙 Retour"])

    # Choix rôle
    if session.get("step", "").startswith("SIGNUP_ROLE"):
        m = {"client": "client", "livreur": "livreur", "entreprise": "entreprise"}
        if tl == "marchand":  # compat saisie utilisateur
            tl = "entreprise"
        role = m.get(tl)
        if not role:
            return build_response("🙏 Je n'ai pas compris ce choix. Vous êtes *Client*, *Livreur* ou *Entreprise* ?"
, SIGNUP_ROLE_BTNS + ["🔙 Retour"])
        session["signup"]["role"] = role
        if role == "client":
            session["step"] = "SIGNUP_CLIENT_NAME"
            return build_response("👤 *Client* — Votre *nom complet* ?\nExemple : `Jean Mbemba`", ["🔙 Retour"])
        if role == "livreur":
            session["step"] = "SIGNUP_LIVREUR_NAME"
            return build_response("🚴 *Livreur* — Votre *nom complet* ?\nExemple : `Paul Ngoma`", ["🔙 Retour"])
        if role == "entreprise":
            session["step"] = "SIGNUP_MARCHAND_ENTREPRISE"
            return build_response("🏪 *Entreprise* — Nom de votre *entreprise* ?\nExemple : `Savana Restaurant`", ["🔙 Retour"])

    # ----- Client -----
    if session["step"] == "SIGNUP_CLIENT_NAME":
        first, last = (t.split(" ", 1) + [""])[:2]
        session["signup"]["data"].update({"first_name": first, "last_name": last})
        session["step"] = "SIGNUP_CLIENT_EMAIL"
        return build_response("📧 *Client* — Votre *email* ?\nExemple : `nom.prenom@gmail.com`", ["🔙 Retour"])
    if session["step"] == "SIGNUP_CLIENT_EMAIL":
        session["signup"]["data"]["email"] = t
        session["step"] = "SIGNUP_CLIENT_ADDRESS"
        return build_response("🏠 Quelle est votre adresse principale ?\nExemple : `25 Avenue de la Paix, Brazzaville`", ["🔙 Retour"]
)
    if session["step"] == "SIGNUP_CLIENT_ADDRESS":
        session["signup"]["data"]["adresse"] = t
        session["step"] = "SIGNUP_CLIENT_PASSWORD"
        return build_response(
            "🔐 Créez un mot de passe sécurisé (au moins 8 caractères, avec majuscules, chiffres et symboles)."
            "\n\nExemples : `Toktok2025!`, `M@Maison123`",
            ["🔙 Retour"]
        )
    if session["step"] == "SIGNUP_CLIENT_PASSWORD":
        session["signup"]["password"] = t
        return signup_submit(session, phone)

    # ----- Livreur -----
    if session["step"] == "SIGNUP_LIVREUR_NAME":
        first, last = (t.split(" ", 1) + [""])[:2]
        session["signup"]["data"].update({"first_name": first, "last_name": last})
        session["step"] = "SIGNUP_LIVREUR_EMAIL"
        return build_response("📧 *Livreur* — Votre *email* ?\nExemple : `livreur.exemple@gmail.com`", ["🔙 Retour"])
    if session["step"] == "SIGNUP_LIVREUR_EMAIL":
        session["signup"]["data"]["email"] = t
        session["step"] = "SIGNUP_LIVREUR_TYPE"
        return build_response("🏷️ *Type livreur* ?\nExemples : `independant`, `societe`, `autoentrepreneur`", ["🔙 Retour"])
    if session["step"] == "SIGNUP_LIVREUR_TYPE":
        norm = _norm_type_livreur(t)
        if not norm:
            return build_response("⚠️ Type invalide. Choisissez: *independant*, *societe*, *autoentrepreneur*.", ["🔙 Retour"])
        session["signup"]["data"]["type_livreur"] = norm
        session["step"] = "SIGNUP_LIVREUR_VEHICULE"
        return build_response("🛵 *Type de véhicule* ?\nExemples : `moto`, `voiture`, `velo`, `camionnette`", ["🔙 Retour"])
    if session["step"] == "SIGNUP_LIVREUR_VEHICULE":
        norm = _norm_type_vehicule(t)
        if not norm:
            return build_response("⚠️ Type véhicule invalide. Exemples: *moto*, *voiture*, *velo*, *camionnette*.", ["🔙 Retour"])
        session["signup"]["data"]["type_vehicule"] = norm
        session["step"] = "SIGNUP_LIVREUR_PERMIS"
        return build_response("🧾 *Numéro de permis* ?\nExemple : `BZV-123456-2025`", ["🔙 Retour"])
    if session["step"] == "SIGNUP_LIVREUR_PERMIS":
        session["signup"]["data"]["numero_permis"] = t
        session["step"] = "SIGNUP_LIVREUR_ZONE"
        return build_response("🗺️ *Zone d'activité* ?\nExemples : `Brazzaville Centre`, `Poto-Poto`, `Talangaï`", ["🔙 Retour"])
    if session["step"] == "SIGNUP_LIVREUR_ZONE":
        session["signup"]["data"]["zone_activite"] = t
        session["step"] = "SIGNUP_LIVREUR_PASSWORD"
        return build_response(
            "🔑 *Livreur* — Choisissez un *mot de passe*.\n"
            "Exemples : `Toktok2025!`, `M@Maison123`, `Brazzaville#95`",
            ["🔙 Retour"]
        )
    if session["step"] == "SIGNUP_LIVREUR_PASSWORD":
        session["signup"]["password"] = t
        return signup_submit(session, phone)

    # ----- Entreprise -----
    if session["step"] == "SIGNUP_MARCHAND_ENTREPRISE":
        session["signup"]["data"]["nom_entreprise"] = t
        session["step"] = "SIGNUP_MARCHAND_TYPE"

        # Construction de la réponse avec liste interactive
        resp = {
            "response": "🏷️ *Type d'entreprise* ?\nChoisissez une catégorie dans la liste ci-dessous :",
            "list": {
                "title": "Catégories",
                "rows": [
                    {
                        "id": "restaurant",
                        "title": "Restaurant",
                        "description": "🍽️ Restaurant, café, fast-food"
                    },
                    {
                        "id": "pharmacie",
                        "title": "Pharmacie",
                        "description": "💊 Pharmacie, parapharmacie"
                    },
                    {
                        "id": "supermarche",
                        "title": "Supermarché",
                        "description": "🛒 Supermarché, épicerie"
                    },
                    {
                        "id": "boutique",
                        "title": "Boutique",
                        "description": "👕 Vêtements, accessoires"
                    },
                    {
                        "id": "electronique",
                        "title": "Électronique",
                        "description": "📱 High-tech, électroménager"
                    },
                    {
                        "id": "autre",
                        "title": "Autre",
                        "description": "🏢 Autre type d'activité"
                    }
                ]
            }
        }
        return resp

    if session["step"] == "SIGNUP_MARCHAND_TYPE":
        session["signup"]["data"]["type_entreprise"] = _strip_accents(t.lower().strip())
        session["step"] = "SIGNUP_MARCHAND_DESC"
        return build_response("📝 *Description* ?\nExemple : `Restaurant spécialisé en grillades africaines`", ["🔙 Retour"])

    if session["step"] == "SIGNUP_MARCHAND_DESC":
        session["signup"]["data"]["description"] = t
        session["step"] = "SIGNUP_MARCHAND_ADR"
        return build_response("📍 *Adresse* de l'entreprise ?\nExemple : `Avenue des 3 Martyrs, Brazzaville`", ["🔙 Retour"])

    if session["step"] == "SIGNUP_MARCHAND_ADR":
        session["signup"]["data"]["adresse"] = t
        session["step"] = "SIGNUP_MARCHAND_GPS"
        resp = build_response(
            "📍 Pour vous localiser précisément, vous pouvez *envoyer votre position GPS* ou taper *Passer* pour continuer.", ["Passer", "🔙 Retour"])
        resp["ask_location"] = "📌 Envoyez votre *position GPS* ou tapez *Passer*."
        return resp

    if session["step"] == "SIGNUP_MARCHAND_GPS":
        # Si l'utilisateur a tapé "Passer", on continue sans GPS
        if tl in {"passer", "skip", "suivant", "continuer"}:
            session["signup"]["data"]["coordonnees_gps"] = ""
            session["step"] = "SIGNUP_MARCHAND_RCCM"
            return build_response("🧾 *Numéro RCCM* ?\nExemple : `CG-BZV-01-2024-B12-00123`", ["🔙 Retour"])
        # Si localisation partagée (gérée dans views.py)
        if tl == "location_shared":
            session["step"] = "SIGNUP_MARCHAND_RCCM"
            return build_response("✅ Localisation enregistrée.\n🧾 *Numéro RCCM* ?\nExemple : `CG-BZV-01-2024-B12-00123`", ["🔙 Retour"])
        # Sinon on attend la localisation
        return build_response("⚠️ Partagez votre localisation ou tapez *Passer*.", ["Passer", "🔙 Retour"])

    if session["step"] == "SIGNUP_MARCHAND_RCCM":
        session["signup"]["data"]["numero_rccm"] = t
        session["step"] = "SIGNUP_MARCHAND_HOR"
        return build_response("⏰ *Horaires d'ouverture* ?\nExemple : `Lun-Sam 08h-20h`", ["🔙 Retour"])

    if session["step"] == "SIGNUP_MARCHAND_HOR":
        session["signup"]["data"]["horaires_ouverture"] = t
        session["step"] = "SIGNUP_MARCHAND_CONTACT"
        return build_response("👤 *Prénom Nom* du responsable ?\nExemple : `Pierre Mabiala`", ["🔙 Retour"])

    if session["step"] == "SIGNUP_MARCHAND_CONTACT":
        first, last = (t.split(" ", 1) + [""])[:2]
        session["signup"]["data"].update({"first_name": first, "last_name": last})
        session["step"] = "SIGNUP_MARCHAND_EMAIL"
        return build_response("📧 *Email* du responsable ?\nExemple : `responsable@entreprise.com`", ["🔙 Retour"])

    if session["step"] == "SIGNUP_MARCHAND_EMAIL":
        session["signup"]["data"]["email"] = t
        session["step"] = "SIGNUP_MARCHAND_PASSWORD"
        return build_response(
            "🔑 *Entreprise* — Choisissez un *mot de passe*.\n"
            "Exemples : `Toktok2025!`, `M@Maison123`, `Brazzaville#95`",
            ["🔙 Retour"]
        )

    if session["step"] == "SIGNUP_MARCHAND_PASSWORD":
        session["signup"]["password"] = t
        return signup_submit(session, phone)
def signup_submit(session: Dict[str, Any], phone: str) -> Dict[str, Any]:
    role = session["signup"]["role"]
    data = session["signup"]["data"]
    pwd = session["signup"]["password"]
    phone_e164 = phone

    try:
        if role == "client":
            payload = {
                "user": {
                    "username": phone_e164,
                    "email": data.get("email", ""),
                    "first_name": data.get("first_name", ""),
                    "last_name": data.get("last_name", ""),
                    "phone_number": phone_e164,
                    "user_type": "client",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                "adresse_principale": data.get("adresse", ""),
                "coordonnees_gps": "",
                "preferences_livraison": "Standard",
            }
            rr = requests.post(f"{API_BASE}/api/v1/auth/clients/", json=payload, timeout=TIMEOUT)

        elif role == "livreur":
            payload = {
                "user": {
                    "username": phone_e164,
                    "email": data.get("email", ""),
                    "first_name": data.get("first_name", ""),
                    "last_name": data.get("last_name", ""),
                    "phone_number": phone_e164,
                    "user_type": "livreur",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                "type_livreur": data.get("type_livreur", "independant"),
                "type_vehicule": data.get("type_vehicule", "moto"),
                "numero_permis": data.get("numero_permis", ""),
                "zone_activite": data.get("zone_activite", ""),
            }
            rr = requests.post(f"{API_BASE}/api/v1/auth/livreurs/", json=payload, timeout=TIMEOUT)

        elif role == "entreprise":
            payload = {
                "user": {
                    "username": phone_e164,
                    "email": data.get("email", ""),
                    "first_name": data.get("first_name", ""),
                    "last_name": data.get("last_name", ""),
                    "phone_number": phone_e164,
                    "user_type": "entreprise",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                "nom_entreprise": data.get("nom_entreprise", ""),
                "type_entreprise": data.get("type_entreprise", ""),
                "description": data.get("description", ""),
                "adresse": data.get("adresse", ""),
                "coordonnees_gps": data.get("coordonnees_gps", ""),
                "numero_rccm": data.get("numero_rccm", ""),
                "horaires_ouverture": data.get("horaires_ouverture", ""),
            }
            rr = requests.post(f"{API_BASE}/api/v1/auth/entreprises/", json=payload, timeout=TIMEOUT)

        else:
            return build_response("❌ Rôle inconnu. Reprenez *Inscription*.", SIGNUP_ROLE_BTNS)

        if rr.status_code not in (200, 201):
            try:
                j = rr.json()
            except Exception:
                j = {"message": "Erreur serveur"}
            msg = _parse_api_errors(j)
            logger.warning(
                "signup_failed",
                extra={
                    "event": "signup_failed",
                    "status_code": rr.status_code,
                    "role": role,
                    "phone": phone,
                    "api_message": j.get("message"),
                    "api_details": j.get("details"),
                },
            )
            return build_response("🙁 Impossible de finaliser votre inscription.\n\n" + msg + "\n\nVérifiez les infos saisies ou réessayez plus tard.", ["🔙 Retour"])

        # ✅ login auto
        resp = login_common(session, username=phone_e164, password=pwd)
        if not (isinstance(resp, dict) and resp.get("ok")):
            return build_response("✅ Inscription réussie. ❗ Mais la connexion a échoué, envoyez *Connexion* et votre mot de passe.")
        role_after = resp["role"]
        dn = resp.get("display_name") or phone_e164
        return route_to_role_menu(session, role_after, f"🎉 Bienvenue {dn} ! Votre compte *{role_after}* est prêt.\nVous pouvez maintenant commencer à utiliser TokTok."
)

    except Exception as e:
        logger.exception("signup_exception", extra={"event": "signup_exception", "role": role, "phone": phone, "err": str(e)})
        return build_response("😓 Une erreur réseau a interrompu l'inscription.\nMerci de réessayer dans quelques minutes.", ["🔙 Retour"]
)

# ---------- Orchestrateur d’auth ----------
def ensure_auth_or_ask_password(phone: str, text: str):
    session = get_session(phone)
    t = normalize(text).lower()

    # Wizard d’inscription en cours ?
    current_step = session.get("step") or ""
    if current_step.startswith("SIGNUP_"):
        return handle_signup_step(phone, text)

    # Déjà connecté ?
    if session.get("auth", {}).get("access"):
        return None

    if session["step"] == "WELCOME":
        session["step"] = "WELCOME_CHOICE"
        return build_response(WELCOME_TEXT, WELCOME_BTNS)

    if session["step"] == "WELCOME_CHOICE":
        if t in {"connexion", "login"}:
            session["step"] = "LOGIN_WAIT_PASSWORD"
            return build_response("🔑 Entrez votre *mot de passe*.")
        if t in {"inscription", "s'inscrire", "sinscrire", "signup"}:
            return signup_start(session)
        if t in {"aide", "help"}:
            return build_response("ℹ️ Envoyez *Connexion* pour vous connecter, ou *Inscription* pour créer un compte.")
        return build_response("👉 Choisissez *Connexion* ou *Inscription*.", WELCOME_BTNS)

    if session["step"] == "LOGIN_WAIT_PASSWORD":
        resp = login_common(session, username=phone, password=text)
        if isinstance(resp, dict) and resp.get("ok"):
            role = resp["role"]
            dn = resp.get("display_name") or phone
            return route_to_role_menu(session, role, f"👋 Ravi de vous revoir, {dn} !\nVous êtes connecté en tant que *{role}*.\n\nQue souhaitez-vous faire maintenant ?\n\n"
)
        return resp

    return build_response(WELCOME_TEXT, WELCOME_BTNS)
