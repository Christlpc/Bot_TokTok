# auth_core.py
from __future__ import annotations
import os, logging, requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

# Mémoire de sessions (en prod: Redis/DB)
SESSIONS: Dict[str, Dict[str, Any]] = {}

# ---------- UI ----------
WELCOME_TEXT = (
    "🚚 Bienvenue sur *TokTok* !\n"
    "Choisissez *Connexion* ou *Inscription*."
)
WELCOME_BTNS = ["Connexion", "Inscription", "Aide"]
SIGNUP_ROLE_BTNS = ["Client", "Livreur", "Marchand"]

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
    return " ".join((s or "").split()).strip()

def _auth_headers(session: Dict[str, Any]) -> Dict[str, str]:
    h = {}
    tok = session.get("auth", {}).get("access")
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h

# ---------- Détection de rôle & profils ----------
def detect_role_via_profiles(session: Dict[str, Any]) -> Optional[str]:
    try:
        r = requests.get(f"{API_BASE}/api/v1/auth/clients/my_profile/", headers=_auth_headers(session), timeout=TIMEOUT)
        if r.status_code == 200: return "client"
    except: pass
    try:
        r = requests.get(f"{API_BASE}/api/v1/auth/livreurs/my_profile/", headers=_auth_headers(session), timeout=TIMEOUT)
        if r.status_code == 200: return "livreur"
    except: pass
    try:
        r = requests.get(f"{API_BASE}/api/v1/auth/marchands/my_profile/", headers=_auth_headers(session), timeout=TIMEOUT)
        if r.status_code == 200: return "marchand"
    except: pass
    return None

def fetch_role_profile(session: Dict[str, Any], role: str) -> Dict[str, Any]:
    url_map = {
        "client":   "/api/v1/auth/clients/my_profile/",
        "livreur":  "/api/v1/auth/livreurs/my_profile/",
        "marchand": "/api/v1/auth/marchands/my_profile/",
    }
    path = url_map.get(role)
    if not path: return {}
    r = requests.get(f"{API_BASE}{path}", headers=_auth_headers(session), timeout=TIMEOUT)
    return r.json() if r.status_code == 200 else {}

def route_to_role_menu(session: Dict[str, Any], role: str, intro_text: str) -> Dict[str, Any]:
    if role == "livreur":
        return build_response(
            intro_text + "\n- *Missions dispo*\n- *Mes missions*\n- *Basculer En ligne/Hors ligne*",
            ["Missions dispo","Mes missions","Basculer En ligne/Hors ligne"]
        )
    if role == "marchand":
        return build_response(
            intro_text + "\n- *Créer produit*\n- *Mes produits*\n- *Commandes*",
            ["Créer produit","Mes produits","Commandes"]
        )
    return build_response(
        intro_text + "\n- *Nouvelle demande*\n- *Suivre ma livraison*\n- *Marketplace*",
        ["Nouvelle demande","Suivre ma livraison","Marketplace"]
    )

# ---------- Login commun ----------
def login_common(session: Dict[str, Any], username: str, password: str) -> Dict[str, Any]:
    r = requests.post(f"{API_BASE}/api/v1/auth/login/",
                      json={"username": username, "password": password}, timeout=TIMEOUT)
    if r.status_code != 200:
        return build_response("❌ Identifiants incorrects.", ["Connexion","Aide"])

    data = r.json() or {}
    access = data.get("access") or data.get("token")
    refresh = data.get("refresh")
    if not access:
        return build_response("❌ Erreur technique : token manquant.")

    session["auth"]["access"] = access
    session["auth"]["refresh"] = refresh

    role = data.get("user_type") or data.get("role") or (data.get("user") or {}).get("role") \
           or detect_role_via_profiles(session) or "client"
    session["user"]["role"] = role

    display_name = (data.get("user", {}).get("first_name","") + " " + data.get("user", {}).get("last_name","")).strip()
    if not display_name:
        prof = fetch_role_profile(session, role)
        if role == "client":
            first = (prof.get("user") or {}).get("first_name",""); last = (prof.get("user") or {}).get("last_name","")
            display_name = (f"{first} {last}").strip() or (prof.get("user") or {}).get("username") or username
        elif role == "livreur":
            display_name = prof.get("nom_complet") or prof.get("nom") or username
        elif role == "marchand":
            display_name = prof.get("nom_entreprise") or prof.get("responsable","") or username

    session["user"]["display_name"] = display_name or username
    session["step"] = "AUTHENTICATED"
    logger.info(f"[LOGIN] {username} connecté en tant que {role}")
    return {"ok": True, "role": role, "display_name": session["user"]["display_name"]}

# ---------- Wizard d'inscription (Client / Livreur / Marchand) ----------
def signup_start(session: Dict[str, Any]):
    session["signup"] = {"role": None, "data": {}, "password": None}
    session["step"] = "SIGNUP_ROLE"
    return build_response("📝 Inscription — choisissez votre *rôle* :", SIGNUP_ROLE_BTNS)

def handle_signup_step(phone: str, text: str) -> Dict[str, Any]:
    session = get_session(phone)
    t = normalize(text); tl = t.lower()

    # Choix rôle
    if session["step"] == "SIGNUP_ROLE":
        m = {"client":"client","livreur":"livreur","marchand":"marchand"}
        role = m.get(tl)
        if not role:
            return build_response("Choisissez *Client*, *Livreur* ou *Marchand*.", SIGNUP_ROLE_BTNS)
        session["signup"]["role"] = role
        if role == "client":
            session["step"] = "SIGNUP_CLIENT_NAME"; return build_response("👤 *Client* — Votre *nom complet* ?")
        if role == "livreur":
            # champs: nom complet + infos véhicule/zone/permis
            session["step"] = "SIGNUP_LIVREUR_NAME"; return build_response("🚴 *Livreur* — Votre *nom complet* ?")
        if role == "marchand":
            session["step"] = "SIGNUP_MARCHAND_ENTREPRISE"; return build_response("🏪 *Marchand* — Nom de votre *entreprise* ?")

    # ----- Client (simple) -----
    if session["step"] == "SIGNUP_CLIENT_NAME":
        first, last = (t.split(" ", 1) + [""])[:2]
        session["signup"]["data"].update({"first_name": first, "last_name": last})
        session["step"] = "SIGNUP_CLIENT_EMAIL"; return build_response("📧 *Client* — Votre *email* ?")
    if session["step"] == "SIGNUP_CLIENT_EMAIL":
        session["signup"]["data"]["email"] = t
        session["step"] = "SIGNUP_CLIENT_ADDRESS"; return build_response("📍 *Client* — Votre *adresse principale* ?")
    if session["step"] == "SIGNUP_CLIENT_ADDRESS":
        session["signup"]["data"]["adresse"] = t
        session["step"] = "SIGNUP_CLIENT_PASSWORD"; return build_response("🔑 *Client* — Choisissez un *mot de passe*.")
    if session["step"] == "SIGNUP_CLIENT_PASSWORD":
        session["signup"]["password"] = t
        return signup_submit(session, phone)

    # ----- Livreur (avec les champs demandés) -----
    # user first/last/email → puis type_livreur / type_vehicule / numero_permis / zone_activite
    if session["step"] == "SIGNUP_LIVREUR_NAME":
        first, last = (t.split(" ", 1) + [""])[:2]
        session["signup"]["data"].update({"first_name": first, "last_name": last})
        session["step"] = "SIGNUP_LIVREUR_EMAIL"; return build_response("📧 *Livreur* — Votre *email* ?")
    if session["step"] == "SIGNUP_LIVREUR_EMAIL":
        session["signup"]["data"]["email"] = t
        session["step"] = "SIGNUP_LIVREUR_TYPE"; return build_response("🏷️ *Type livreur* ? (ex: independant)")
    if session["step"] == "SIGNUP_LIVREUR_TYPE":
        session["signup"]["data"]["type_livreur"] = t
        session["step"] = "SIGNUP_LIVREUR_VEHICULE"; return build_response("🛵 *Type de véhicule* ? (ex: moto)")
    if session["step"] == "SIGNUP_LIVREUR_VEHICULE":
        session["signup"]["data"]["type_vehicule"] = t
        session["step"] = "SIGNUP_LIVREUR_PERMIS"; return build_response("🧾 *Numéro de permis* ?")
    if session["step"] == "SIGNUP_LIVREUR_PERMIS":
        session["signup"]["data"]["numero_permis"] = t
        session["step"] = "SIGNUP_LIVREUR_ZONE"; return build_response("🗺️ *Zone d’activité* ?")
    if session["step"] == "SIGNUP_LIVREUR_ZONE":
        session["signup"]["data"]["zone_activite"] = t
        session["step"] = "SIGNUP_LIVREUR_PASSWORD"; return build_response("🔑 *Livreur* — Choisissez un *mot de passe*.")
    if session["step"] == "SIGNUP_LIVREUR_PASSWORD":
        session["signup"]["password"] = t
        return signup_submit(session, phone)

    # ----- Marchand (avec les champs demandés) -----
    if session["step"] == "SIGNUP_MARCHAND_ENTREPRISE":
        session["signup"]["data"]["nom_entreprise"] = t
        session["step"] = "SIGNUP_MARCHAND_TYPE"; return build_response("🏷️ *Type d’entreprise* ? (ex: restaurant)")
    if session["step"] == "SIGNUP_MARCHAND_TYPE":
        session["signup"]["data"]["type_entreprise"] = t
        session["step"] = "SIGNUP_MARCHAND_DESC"; return build_response("📝 *Description* ?")
    if session["step"] == "SIGNUP_MARCHAND_DESC":
        session["signup"]["data"]["description"] = t
        session["step"] = "SIGNUP_MARCHAND_ADR"; return build_response("📍 *Adresse* de l’entreprise ?")
    if session["step"] == "SIGNUP_MARCHAND_ADR":
        session["signup"]["data"]["adresse"] = t
        session["step"] = "SIGNUP_MARCHAND_GPS"; return build_response("📌 *Coordonnées GPS* (lat,lng) ?")
    if session["step"] == "SIGNUP_MARCHAND_GPS":
        session["signup"]["data"]["coordonnees_gps"] = t
        session["step"] = "SIGNUP_MARCHAND_RCCM"; return build_response("📄 *Numéro RCCM* ?")
    if session["step"] == "SIGNUP_MARCHAND_RCCM":
        session["signup"]["data"]["numero_rccm"] = t
        session["step"] = "SIGNUP_MARCHAND_HOR"; return build_response("⏰ *Horaires d’ouverture* ?")
    if session["step"] == "SIGNUP_MARCHAND_HOR":
        session["signup"]["data"]["horaires_ouverture"] = t
        session["step"] = "SIGNUP_MARCHAND_CONTACT"; return build_response("👤 *Prénom Nom* du responsable ?")
    if session["step"] == "SIGNUP_MARCHAND_CONTACT":
        first, last = (t.split(" ", 1) + [""])[:2]
        session["signup"]["data"].update({"first_name": first, "last_name": last})
        session["step"] = "SIGNUP_MARCHAND_EMAIL"; return build_response("📧 *Email* du responsable ?")
    if session["step"] == "SIGNUP_MARCHAND_EMAIL":
        session["signup"]["data"]["email"] = t
        session["step"] = "SIGNUP_MARCHAND_PASSWORD"; return build_response("🔑 *Marchand* — Choisissez un *mot de passe*.")
    if session["step"] == "SIGNUP_MARCHAND_PASSWORD":
        session["signup"]["password"] = t
        return signup_submit(session, phone)

    return build_response("ℹ️ Reprenez : *Inscription* puis choisissez un rôle.", SIGNUP_ROLE_BTNS)

def signup_submit(session: Dict[str, Any], phone: str) -> Dict[str, Any]:
    role = session["signup"]["role"]; data = session["signup"]["data"]; pwd = session["signup"]["password"]
    phone_e164 = phone

    try:
        if role == "client":
            payload = {
                "user": {
                    "username": phone_e164,
                    "email": data.get("email",""),
                    "first_name": data.get("first_name",""),
                    "last_name": data.get("last_name",""),
                    "phone_number": phone_e164,
                    "user_type": "client",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                "adresse_principale": data.get("adresse",""),
                "coordonnees_gps": "",
                "preferences_livraison": "Standard",
            }
            rr = requests.post(f"{API_BASE}/api/v1/auth/clients/", json=payload, timeout=TIMEOUT)

        elif role == "livreur":
            # 🧩 Champs demandés : type_livreur, type_vehicule, numero_permis, zone_activite
            payload = {
                "user": {
                    "username": phone_e164,
                    "email": data.get("email",""),
                    "first_name": data.get("first_name",""),
                    "last_name": data.get("last_name",""),
                    "phone_number": phone_e164,
                    "user_type": "livreur",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                "type_livreur": data.get("type_livreur","independant"),
                "type_vehicule": data.get("type_vehicule","moto"),
                "numero_permis": data.get("numero_permis",""),
                "zone_activite": data.get("zone_activite",""),
            }
            rr = requests.post(f"{API_BASE}/api/v1/auth/livreurs/", json=payload, timeout=TIMEOUT)

        elif role == "marchand":
            # 🧩 Champs demandés : type_entreprise, description, adresse, coordonnees_gps, numero_rccm, horaires_ouverture
            payload = {
                "user": {
                    "username": phone_e164,
                    "email": data.get("email",""),
                    "first_name": data.get("first_name",""),
                    "last_name": data.get("last_name",""),
                    "phone_number": phone_e164,
                    "user_type": "marchand",
                    "password": pwd,
                    "password_confirm": pwd,
                },
                "nom_entreprise": data.get("nom_entreprise",""),
                "type_entreprise": data.get("type_entreprise",""),
                "description": data.get("description",""),
                "adresse": data.get("adresse",""),
                "coordonnees_gps": data.get("coordonnees_gps",""),
                "numero_rccm": data.get("numero_rccm",""),
                "horaires_ouverture": data.get("horaires_ouverture",""),
            }
            rr = requests.post(f"{API_BASE}/api/v1/auth/entreprises/", json=payload, timeout=TIMEOUT)

        else:
            return build_response("❌ Rôle inconnu. Reprenez *Inscription*.", SIGNUP_ROLE_BTNS)

        if rr.status_code not in (200, 201):
            logger.warning(f"[SIGNUP] API status={rr.status_code} body={rr.text[:300]}")
            return build_response("❌ Inscription refusée. Vérifiez vos informations et réessayez.")

        # ✅ login auto
        resp = login_common(session, username=phone_e164, password=pwd)
        if not (isinstance(resp, dict) and resp.get("ok")):
            return build_response("✅ Inscription réussie. ❗ Mais la connexion a échoué, envoyez *Connexion* et votre mot de passe.")
        role_after = resp["role"]; dn = resp.get("display_name") or phone_e164
        return route_to_role_menu(session, role_after, f"🎉 Compte créé pour {dn} — rôle *{role_after}*.\n")

    except Exception as e:
        logger.exception(f"[SIGNUP] Exception: {e}")
        return build_response("❌ Erreur réseau pendant l’inscription. Réessayez plus tard.")

# ---------- Orchestrateur d’auth ----------
def ensure_auth_or_ask_password(phone: str, text: str):
    session = get_session(phone)
    t = normalize(text).lower()

    if session["step"].startswith("SIGNUP_"):
        return handle_signup_step(phone, text)

    if session["auth"]["access"]:
        return None

    if session["step"] == "WELCOME":
        session["step"] = "WELCOME_CHOICE"
        return build_response(WELCOME_TEXT, WELCOME_BTNS)

    if session["step"] == "WELCOME_CHOICE":
        if t in {"connexion","login"}:
            session["step"] = "LOGIN_WAIT_PASSWORD"
            return build_response("🔑 Entrez votre *mot de passe* (identifiant = votre numéro WhatsApp).")
        if t in {"inscription","s'inscrire","sinscrire","signup"}:
            return signup_start(session)
        if t in {"aide","help"}:
            return build_response("ℹ️ Envoyez *Connexion* pour vous connecter, ou *Inscription* pour créer un compte.")
        return build_response("👉 Choisissez *Connexion* ou *Inscription*.", WELCOME_BTNS)

    if session["step"] == "LOGIN_WAIT_PASSWORD":
        resp = login_common(session, username=phone, password=text)
        if isinstance(resp, dict) and resp.get("ok"):
            role = resp["role"]; dn = resp.get("display_name") or phone
            return route_to_role_menu(session, role, f"👋 Bonjour {dn}. Connecté en tant que *{role}*.\n")
        return resp

    return build_response(WELCOME_TEXT, WELCOME_BTNS)
