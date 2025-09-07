from __future__ import annotations
import os, re, json, logging, requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))
# Fallback IA (OpenAI) — optionnel
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()

# Mémoire sessions (remplacer par Redis/DB en prod)
sessions: Dict[str, Dict[str, Any]] = {}

# ---------- UI ----------
WELCOME_TEXT = (
    "🚚 Bienvenue sur *TokTok Livreur* !\n"
    "Gère tes missions, ta dispo et ton suivi en quelques messages."
)
WELCOME_BTNS = ["Connexion", "Aide"]
MAIN_MENU_BTNS = ["Missions dispo", "Mes missions", "Basculer En ligne/Hors ligne"]
ACTIONS_BTNS = ["Démarrer", "Arrivé pickup", "Arrivé livraison"]
GREETINGS = {"bonjour", "salut", "bjr", "hello", "bonsoir", "hi", "menu", "accueil"}

# ---------- Helpers ----------
def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def mask_sensitive(value: str, visible: int = 3) -> str:
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return value[:visible] + "****" + value[-visible:]

def build_response(text: str, buttons: Optional[List[str]] = None) -> Dict[str, Any]:
    payload = {"response": text}
    if buttons:
        payload["buttons"] = buttons[:3]
    return payload

def get_session(phone: str) -> Dict[str, Any]:
    if phone not in sessions:
        sessions[phone] = {
            "phone": phone,
            "step": "WELCOME",
            "auth": {"access": None, "refresh": None},
            "profile": {},  # {id, name, disponible}
            "ctx": {
                "current_mission_id": None,
                "last_list": [],
                "history": [],  # [(role, content)]
            },
        }
        logger.info(f"[SESSION] Nouvelle session {mask_sensitive(phone)}")
    return sessions[phone]

def _ctx_add_history(session: Dict[str, Any], role: str, content: str, max_items: int = 12) -> None:
    hist = session["ctx"].setdefault("history", [])
    hist.append((role, content))
    if len(hist) > max_items:
        del hist[0:len(hist)-max_items]

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    token = session.get("auth", {}).get("access")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API] {method} {path} -> {r.status_code}")
    # Refresh auto
    if r.status_code == 401 and session.get("auth", {}).get("refresh"):
        if _try_refresh(session):
            headers["Authorization"] = f"Bearer {session['auth']['access']}"
            r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
            logger.debug(f"[API:retry] {method} {path} -> {r.status_code}")
    return r

def _try_refresh(session: Dict[str, Any]) -> bool:
    try:
        rr = requests.post(
            f"{API_BASE}/api/v1/auth/refresh/",
            json={"refresh": session["auth"]["refresh"]},
            timeout=TIMEOUT,
        )
        if rr.status_code == 200:
            session["auth"]["access"] = rr.json().get("access")
            logger.info("[AUTH] Token refresh OK")
            return True
        logger.warning("[AUTH] Token refresh KO")
    except Exception as e:
        logger.error(f"[AUTH] Refresh exception: {e}")
    return False

# ---------- Fallback IA ----------
def ai_fallback(session: Dict[str, Any], user_text: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        return build_response(
            "❓ Je n’ai pas compris.\n"
            "• *Missions dispo* • *Mes missions* • *Basculer En ligne/Hors ligne*\n"
            "• *Détails <id>* • *Accepter <id>* • *Démarrer* • *Arrivé pickup* • *Arrivé livraison* • *Livrée*",
            MAIN_MENU_BTNS,
        )

    system_prompt = (
        "Tu es *TokTok Livreur*, assistant WhatsApp pour des coursiers à Brazzaville.\n"
        "- Réponds en **français**, brièvement (1–3 phrases), style WhatsApp.\n"
        "- Propose des *actions valides* du bot si utile : "
        "« Missions dispo », « Mes missions », « Basculer En ligne/Hors ligne », "
        "« Détails <id> », « Accepter <id> », « Démarrer », « Arrivé pickup », "
        "« Arrivé livraison », « Livrée ».\n"
        "- Reste strictement dans le cadre livreur."
    )

    messages = [{"role": "system", "content": system_prompt}]
    for role, content in session["ctx"].get("history", [])[-8:]:
        if content:
            messages.append({"role": role, "content": content[:800]})
    messages.append({"role": "user", "content": user_text[:800]})

    try:
        base = OPENAI_BASE_URL or "https://api.openai.com/v1"
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": OPENAI_MODEL, "messages": messages, "temperature": 0.3, "max_tokens": 200}
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code != 200:
            logger.warning(f"[AI] {resp.status_code}: {resp.text[:200]}")
            return build_response(
                "❓ Je n’ai pas compris.\n"
                "• *Missions dispo* • *Mes missions* • *Basculer En ligne/Hors ligne*\n"
                "• *Détails <id>* • *Accepter <id>* • *Démarrer* • *Arrivé pickup* • *Arrivé livraison* • *Livrée*",
                MAIN_MENU_BTNS,
            )
        data = resp.json()
        content = (data.get("choices", [{}])[0].get("message", {}).get("content", "") or "OK.").strip()
        _ctx_add_history(session, "assistant", content)
        return build_response(content, MAIN_MENU_BTNS)
    except Exception as e:
        logger.error(f"[AI] Exception: {e}")
        return build_response(
            "❓ Je n’ai pas compris.\n"
            "• *Missions dispo* • *Mes missions* • *Basculer En ligne/Hors ligne*\n"
            "• *Détails <id>* • *Accepter <id>* • *Démarrer* • *Arrivé pickup* • *Arrivé livraison* • *Livrée*",
            MAIN_MENU_BTNS,
        )

# ---------- Auth ----------
def handle_login_start(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "LOGIN_WAIT_PASSWORD"
    return build_response("🔑 Envoie ton *mot de passe* pour te connecter.\n(Identifiant = ton numéro WhatsApp)")

def handle_login_password(session: Dict[str, Any], pwd: str) -> Dict[str, Any]:
    try:
        r = requests.post(
            f"{API_BASE}/api/v1/auth/login/",
            json={"username": session["phone"], "password": pwd},
            timeout=TIMEOUT,
        )
        logger.debug(f"[LOGIN] statut {r.status_code}")
        if r.status_code != 200:
            return build_response("❌ Mot de passe incorrect. Réessaie ou tape *Aide*.", WELCOME_BTNS)

        data = r.json()
        session["auth"]["access"] = data.get("access")
        session["auth"]["refresh"] = data.get("refresh")

        me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
        name = session["phone"]
        dispo = False
        if me.status_code == 200:
            jp = me.json()
            session["profile"]["id"] = jp.get("id")
            name = jp.get("nom_complet") or jp.get("nom") or session["phone"]
            dispo = jp.get("disponible", False)
            session["profile"]["name"] = name
            session["profile"]["disponible"] = dispo

        session["step"] = "MENU"
        _ctx_add_history(session, "assistant", f"Connecté en tant que {name}.")
        return build_response(
            f"👋 Bonjour {name}.\nStatut actuel : {'🟢 En ligne' if dispo else '🔴 Hors ligne'}.\n\n"
            "Que veux-tu faire ?", MAIN_MENU_BTNS
        )
    except Exception as e:
        logger.error(f"[LOGIN] Exception: {e}")
        return build_response("❌ Erreur réseau. Réessaie plus tard.", WELCOME_BTNS)

# ---------- Disponibilité ----------
def toggle_disponibilite(session: Dict[str, Any]) -> Dict[str, Any]:
    livreur_id = session.get("profile", {}).get("id")
    if not livreur_id:
        return build_response("❌ Profil livreur introuvable. Reconnecte-toi.", WELCOME_BTNS)
    r = api_request(session, "POST", f"/api/v1/auth/livreurs/{livreur_id}/toggle_disponibilite/", json={})
    if r.status_code in (200, 202):
        me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
        dispo = False
        if me.status_code == 200:
            dispo = me.json().get("disponible", False)
            session["profile"]["disponible"] = dispo
        return build_response(f"✅ Statut mis à jour : {'🟢 En ligne' if dispo else '🔴 Hors ligne'}.", MAIN_MENU_BTNS)
    return build_response("❌ Impossible de basculer le statut pour le moment.", MAIN_MENU_BTNS)

# ---------- Missions ----------
def list_missions_disponibles(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/disponibles/")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement des missions disponibles.", MAIN_MENU_BTNS)
    arr = r.json() or []
    session["ctx"]["last_list"] = [d.get("id") for d in arr]
    if not arr:
        return build_response("😕 Aucune mission disponible pour l’instant.", MAIN_MENU_BTNS)

    lines = []
    for d in arr[:3]:
        mid = d.get("id")
        dep = d.get("adresse_recuperation", "—")
        dest = d.get("adresse_livraison", "—")
        cod = d.get("cod_montant") or d.get("montant_cod") or "0"
        lines.append(f"#{mid} • {dep} → {dest} • COD {cod} XAF")
    txt = "🆕 *Missions disponibles*\n" + "\n".join(lines) + "\n\n" \
          "👉 Réponds: *Accepter <id>* ou *Détails <id>*"
    return build_response(txt, ["Accepter 123", "Détails 123", "Menu"])

def list_mes_missions(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/mes_missions/")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement de tes missions.", MAIN_MENU_BTNS)
    arr = r.json() or []
    if not arr:
        return build_response("📭 Aucune mission en cours.", MAIN_MENU_BTNS)
    lines = []
    for d in arr[:5]:
        mid = d.get("id")
        st = d.get("statut", "")
        dest = d.get("adresse_livraison", "—")
        lines.append(f"#{mid} — {st} → {dest}")
    return build_response("📦 *Mes missions*\n" + "\n".join(lines), ["Détails 123", "Menu"])

def details_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if r.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)
    d = r.json()
    session["ctx"]["current_mission_id"] = d.get("id")
    txt = (
        f"📄 *Mission #{d.get('id')}*\n"
        f"• Réf: {d.get('numero_mission')}\n"
        f"• Pickup: {d.get('adresse_recuperation')}\n"
        f"• Drop: {d.get('adresse_livraison')}\n"
        f"• Paiement: {d.get('type_paiement','-')}\n"
        f"• Statut: {d.get('statut','-')}\n"
        "Actions: *Démarrer*, *Arrivé pickup*, *Arrivé livraison*, *Livrée*\n"
        "Ou tape *Statut en_route_recuperation* / *Statut recupere* / etc."
    )
    return build_response(txt, ACTIONS_BTNS)

def accepter_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    g = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if g.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)
    m = g.json()
    payload = {
        "numero_mission": m.get("numero_mission") or str(mission_id),
        "entreprise_demandeur": m.get("entreprise_demandeur") or "TokTok",
        "contact_entreprise": m.get("contact_entreprise") or session["phone"],
        "adresse_recuperation": m.get("adresse_recuperation") or "",
        "coordonnees_recuperation": m.get("coordonnees_recuperation") or "",
        "adresse_livraison": m.get("adresse_livraison") or "",
        "coordonnees_livraison": m.get("coordonnees_livraison") or "",
        "nom_client_final": m.get("nom_client_final") or "Client",
        "telephone_client_final": m.get("telephone_client_final") or session["phone"],
        "description_produit": m.get("description_produit") or "-",
        "type_paiement": m.get("type_paiement") or "entreprise_paie",
    }
    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mission_id}/accepter/", json=payload)
    if r.status_code not in (200, 201):
        return build_response("❌ Impossible d’accepter cette mission (déjà prise ?).", MAIN_MENU_BTNS)
    session["ctx"]["current_mission_id"] = mission_id
    return build_response(f"✅ Mission #{mission_id} acceptée.\nTu peux *Démarrer* 🚀", ["Démarrer", "Mes missions", "Menu"])

# ---------- Livraisons (statuts / tracking) ----------
STATUTS_VALIDES = {
    "en_attente", "assignee", "en_route_recuperation", "arrive_recuperation",
    "recupere", "en_route_livraison", "arrive_livraison", "livree", "probleme", "annulee"
}

def _update_statut(session: Dict[str, Any], livraison_id: str, statut: str) -> Dict[str, Any]:
    payload = {
        "statut": statut,
        "content_type": 1,  # id du modèle Livraison côté Django
        "object_id": int(livraison_id),
    }
    r = api_request(session, "POST", f"/api/v1/livraisons/livraisons/{livraison_id}/update_statut/", json=payload)
    if r.status_code not in (200, 202):
        return build_response("❌ Échec de mise à jour du statut.", ACTIONS_BTNS)
    return build_response(f"✅ Statut mis à jour: *{statut}*.", ACTIONS_BTNS)

def set_statut_simple(session: Dict[str, Any], statut: str) -> Dict[str, Any]:
    mid = session["ctx"].get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission sélectionnée. Envoie *Détails <id>* d’abord.", ["Mes missions", "Missions dispo", "Menu"])
    r = api_request(session, "GET", f"/api/v1/livraisons/livraisons/{mid}/")
    livraison_id = str(mid) if r.status_code != 200 else str(r.json().get("id", mid))
    if statut not in STATUTS_VALIDES:
        return build_response("❌ Statut invalide.", ACTIONS_BTNS)
    return _update_statut(session, livraison_id, statut)

def action_demarrer(session: Dict[str, Any]) -> Dict[str, Any]:
    return set_statut_simple(session, "en_route_recuperation")

def action_arrive_pickup(session: Dict[str, Any]) -> Dict[str, Any]:
    return set_statut_simple(session, "arrive_recuperation")

def action_arrive_drop(session: Dict[str, Any]) -> Dict[str, Any]:
    return set_statut_simple(session, "arrive_livraison")

def action_livree(session: Dict[str, Any]) -> Dict[str, Any]:
    return set_statut_simple(session, "livree")

def update_position(session: Dict[str, Any], lat: float, lng: float, livraison_id: Optional[str] = None) -> Dict[str, Any]:
    if not livraison_id:
        mid = session["ctx"].get("current_mission_id")
        if not mid:
            return build_response("❌ Pas d’ID livraison courant.", ACTIONS_BTNS)
        livraison_id = str(mid)
    payload = {
        # astuce : on envoie côté pickup par défaut ; adapte si besoin par étape
        "coordonnees_recuperation": f"{lat},{lng}",
        "content_type": 1,
        "object_id": int(livraison_id),
    }
    r = api_request(session, "POST", f"/api/v1/livraisons/livraisons/{livraison_id}/update_position/", json=payload)
    if r.status_code not in (200, 202):
        return build_response("❌ Position non mise à jour.", ACTIONS_BTNS)
    return build_response("📡 Position mise à jour.", ACTIONS_BTNS)

# ---------- Historique ----------
def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/livraisons/livraisons/mes_livraisons/")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement de l’historique.")
    data = r.json() or []
    if not data:
        return build_response("🗂️ Aucun historique pour le moment.", MAIN_MENU_BTNS)
    lines = [f"#{d.get('id')} — {d.get('statut','')} → {d.get('adresse_livraison','')}" for d in data[:5]]
    return build_response("🗂️ *5 dernières livraisons*\n" + "\n".join(lines), MAIN_MENU_BTNS)

# ---------- Router principal ----------
def handle_message(
    phone: str,
    text: str,
    *,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    media_url: Optional[str] = None,
) -> Dict[str, Any]:
    t = normalize(text)
    tl = t.lower()
    session = get_session(phone)

    if t:
        _ctx_add_history(session, "user", t[:800])

    # Non connecté
    if not session["auth"]["access"]:
        if session["step"] == "WELCOME":
            session["step"] = "WELCOME_CHOICE"
            return build_response(WELCOME_TEXT, WELCOME_BTNS)

        if session["step"] == "WELCOME_CHOICE":
            if tl in {"connexion", "login"}:
                return handle_login_start(session)
            if tl in {"aide", "help"}:
                return build_response("📘 Envoie *Connexion* pour te connecter. Ton identifiant est ton numéro WhatsApp.")
            return ai_fallback(session, t)

        if session["step"] == "LOGIN_WAIT_PASSWORD":
            return handle_login_password(session, t)

        return build_response(WELCOME_TEXT, WELCOME_BTNS)

    # Menu / navigation
    if tl in GREETINGS:
        session["step"] = "MENU"
        return build_response("Que veux-tu faire ?", MAIN_MENU_BTNS)

    # Position fournie
    if lat is not None and lng is not None:
        return update_position(session, lat, lng)

    # Intents simples
    if tl in {"basculer", "toggle", "en ligne", "hors ligne", "basculer en ligne", "basculer hors ligne"} or tl.startswith("basculer"):
        return toggle_disponibilite(session)

    if tl in {"missions dispo", "missions", "disponibles"}:
        return list_missions_disponibles(session)

    if tl in {"mes missions", "mes", "mes courses"}:
        return list_mes_missions(session)

    if tl.startswith("détails "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ", 1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Détails 123*")
        return details_mission(session, mid)

    if tl.startswith("accepter "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ", 1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Accepter 123*")
        return accepter_mission(session, mid)

    if tl in {"démarrer", "demarrer", "start"}:
        return action_demarrer(session)

    if tl in {"arrivé pickup", "arrive pickup"}:
        return action_arrive_pickup(session)

    if tl in {"arrivé livraison", "arrive livraison"}:
        return action_arrive_drop(session)

    if tl in {"livrée", "livree"}:
        return action_livree(session)

    if tl.startswith("statut "):
        s = tl.split(" ", 1)[1].strip()
        if s not in STATUTS_VALIDES:
            return build_response("❌ Statut inconnu. Exemples: en_route_recuperation, recupere, livree.")
        return set_statut_simple(session, s)

    if tl in {"historique", "history"}:
        return handle_history(session)

    # Fallback IA
    return ai_fallback(session, t)
