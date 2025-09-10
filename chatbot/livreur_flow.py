# chatbot/livreur_flow.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional, List
from .auth_core import get_session, build_response, normalize  # sessions/menus centralisés

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

# Boutons (≤ 20 caractères pour WhatsApp)
MAIN_MENU_BTNS = ["Missions dispo", "Mes missions", "Basculer statut"]
ACTIONS_BTNS   = ["Démarrer", "Arrivé pickup", "Arrivé livraison"]
GREETINGS = {"bonjour","salut","bjr","hello","bonsoir","hi","menu","accueil"}

STATUTS_VALIDES = {
    "en_attente","assignee","en_route_recuperation","arrive_recuperation",
    "recupere","en_route_livraison","arrive_livraison","livree","probleme","annulee"
}
# ---------- Utils API ----------
def api_request(session: Dict[str, Any], method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    token = (session.get("auth") or {}).get("access")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API] {method} {path} -> {r.status_code}")
    return r

# ---------- Disponibilité ----------
def toggle_disponibilite(session: Dict[str, Any]) -> Dict[str, Any]:
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("❌ Profil livreur introuvable. Reconnecte-toi.", MAIN_MENU_BTNS)
    lid = me.json().get("id")
    if not lid:
        return build_response("❌ Impossible de trouver ton identifiant livreur.", MAIN_MENU_BTNS)

    r = api_request(session, "POST", f"/api/v1/auth/livreurs/{lid}/toggle_disponibilite/", json={})
    if r.status_code in (200, 202):
        me2 = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
        dispo = me2.json().get("disponible", False) if me2.status_code == 200 else False
        return build_response(f"✅ Statut mis à jour : {'🟢 En ligne' if dispo else '🔴 Hors ligne'}.", MAIN_MENU_BTNS)
    return build_response("❌ Impossible de basculer le statut pour le moment.", MAIN_MENU_BTNS)

# ---------- Missions ----------
def list_missions_disponibles(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/disponibles/")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement des missions disponibles.", MAIN_MENU_BTNS)

    arr = r.json() or []
    if not arr:
        return build_response("😕 Aucune mission disponible pour l’instant.", MAIN_MENU_BTNS)

    # ⚡ On limite à 3 missions pour UX clair
    arr = arr[:3]
    session.setdefault("ctx", {})["last_list"] = [d.get("id") for d in arr]

    # Résumé texte
    lines = []
    for d in arr:
        mid = d.get("id")
        dep = d.get("adresse_recuperation") or "—"
        dest = d.get("adresse_livraison") or "—"
        cod = d.get("cod_montant") or d.get("montant_cod") or 0
        lines.append(f"#{mid} • {dep} → {dest}\n💵 COD: {cod} XAF")

    msg = "🆕 *Missions disponibles*\n" + "\n\n".join(lines)

    # Liste interactive (Accepter + Détails par mission)
    rows = []
    for d in arr:
        mid = d.get("id")
        dep = d.get("adresse_recuperation") or "—"
        dest = d.get("adresse_livraison") or "—"
        desc = f"{dep} → {dest}"[:72]

        rows.append({"id": f"accept_{mid}", "title": f"✅ Accepter #{mid}"[:24], "description": desc})
        rows.append({"id": f"details_{mid}", "title": f"ℹ️ Détails #{mid}"[:24], "description": desc})

    return {"response": msg, "list": {"title": "Choisir une mission", "rows": rows}}

def list_mes_missions(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/mes_missions/")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement de tes missions.", MAIN_MENU_BTNS)
    arr = r.json() or []
    if not arr:
        return build_response("📭 Aucune mission en cours.", MAIN_MENU_BTNS)

    lines = []
    for d in arr[:5]:
        mid  = d.get("id")
        st   = d.get("statut", "")
        dest = d.get("adresse_livraison", "—")
        lines.append(f"#{mid} — {st} → {dest}")
    return build_response("📦 *Mes missions*\n" + "\n".join(lines), ["Détails 123", "Menu"])

def details_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if r.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)

    d = r.json()
    session.setdefault("ctx", {})["current_mission_id"] = d.get("id")

    # Capture livraison liée
    liv_id = (d.get("livraison") or {}).get("id") or d.get("livraison_id")
    if liv_id:
        session["ctx"]["current_livraison_id"] = liv_id

    txt = (
        f"📄 *Mission #{d.get('id','?')}*\n"
        f"• Réf: {d.get('numero_mission','—')}\n"
        f"• Pickup: {d.get('adresse_recuperation','—')}\n"
        f"• Drop: {d.get('adresse_livraison','—')}\n"
        f"• Paiement: {d.get('type_paiement','—')}\n"
        f"• Statut: {d.get('statut','—')}\n"
        "👉 Actions: *Démarrer*, *Arrivé pickup*, *Arrivé livraison*, *Livrée*"
    )
    return build_response(txt, ACTIONS_BTNS)

# ---------- Missions ----------
def accepter_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mission_id}/accepter/")
    if r.status_code not in (200, 201):
        return build_response("❌ Impossible d’accepter cette mission (déjà prise ?).", MAIN_MENU_BTNS)

    session.setdefault("ctx", {})["current_mission_id"] = mission_id

    # Vérifie si une livraison est liée
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    liv_id = None
    if m.status_code == 200:
        mj = m.json()
        liv_id = (mj.get("livraison") or {}).get("id") or mj.get("livraison_id")
        if liv_id:
            session["ctx"]["current_livraison_id"] = liv_id

    txt = f"✅ Mission #{mission_id} acceptée."
    if liv_id:
        txt += f"\n🚚 Livraison associée : #{liv_id}\n👉 Tu peux *Démarrer* 🚀"
        return build_response(txt, ["Démarrer", "Mes missions", "Menu"])
    else:
        txt += "\n⚠️ Pas de livraison liée détectée."
        return build_response(txt, ["Mes missions", "Menu"])
# ---------- Mise à jour statuts ----------
def action_demarrer(session: Dict[str, Any]) -> Dict[str, Any]:
    """
    Au démarrage :
    - Si la mission est liée à une commande (coursier normal) → on envoie commande_id
    - Si la mission vient du marketplace → on envoie mission_id
    """
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", ["Mes missions", "Menu"])

    # Charger la mission
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mid}/")
    if m.status_code != 200:
        return build_response("❌ Impossible de charger les détails de la mission.", ["Mes missions", "Menu"])
    mj = m.json()

    # Préparer le payload en fonction de la source
    payload = {
        "adresse_recuperation": mj.get("adresse_recuperation", ""),
        "coordonnees_recuperation": mj.get("coordonnees_recuperation", ""),
        "adresse_livraison": mj.get("adresse_livraison", ""),
        "coordonnees_livraison": mj.get("coordonnees_livraison", ""),
        "distance_km": mj.get("distance_km", "0"),
        "duree_estimee_minutes": mj.get("duree_estimee_minutes", 0),
        "livreur": mj.get("livreur") or (session.get("user") or {}).get("id", 0),
    }

    # Cas 1 : mission liée à une commande (coursier normal)
    if mj.get("commande_id"):
        payload["commande_id"] = mj["commande_id"]

    # Cas 2 : mission marketplace → on envoie mission_id
    else:
        payload["mission_id"] = int(mid)

    # Appel API pour créer la livraison
    r = api_request(session, "POST", "/api/v1/livraisons/livraisons/", json=payload)
    if r.status_code not in (200, 201):
        return build_response("❌ Échec de création de la livraison. Réessaie plus tard.", ["Mes missions", "Menu"])

    livraison = r.json()
    liv_id = livraison.get("id")
    if liv_id:
        session.setdefault("ctx", {})["current_livraison_id"] = liv_id

    return build_response(
        f"✅ Livraison #{liv_id} créée et liée à la mission #{mid}.\n"
        "🚴 Tu es maintenant en route vers le point de récupération.",
        ["Arrivé pickup", "Mes missions", "Menu"]
    )

def action_arrive_pickup(session: Dict[str, Any]) -> Dict[str, Any]:
    resp = set_statut_simple(session, "arrive_recuperation")
    if "response" in resp:
        resp["response"] += "\n📍 Tu es arrivé au point de pickup.\n👉 Tape *Statut recupere* après avoir pris le colis."
    return resp

def action_arrive_drop(session: Dict[str, Any]) -> Dict[str, Any]:
    resp = set_statut_simple(session, "arrive_livraison")
    if "response" in resp:
        resp["response"] += "\n📍 Tu es arrivé au point de livraison."
    return resp

def action_livree(session: Dict[str, Any]) -> Dict[str, Any]:
    resp = set_statut_simple(session, "livree")
    if "response" in resp:
        resp["response"] += "\n✅ Livraison terminée avec succès."
    return resp

# ---------- Livraisons (statuts / position) ----------
def _ensure_livraison_id(session: Dict[str, Any]) -> Optional[str]:
    """
    Vérifie si on a déjà un livraison_id en mémoire, sinon tente de le récupérer via la mission courante.
    """
    liv_id = (session.get("ctx") or {}).get("current_livraison_id")
    if liv_id:
        return str(liv_id)

    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return None

    det = api_request(session, "GET", f"/api/v1/coursier/missions/{mid}/")
    if det.status_code == 200:
        dj = det.json()
        liv_id = (dj.get("livraison") or {}).get("id") or dj.get("livraison_id")
        if liv_id:
            session["ctx"]["current_livraison_id"] = liv_id
            return str(liv_id)

    return None

def _update_statut(session: Dict[str, Any], livraison_id: str, statut: str) -> Dict[str, Any]:
    payload = {
        "statut": statut,
        "content_type": 1,  # (si requis par votre backend)
        "object_id": int(livraison_id),
    }
    r = api_request(session, "POST", f"/api/v1/livraisons/livraisons/{livraison_id}/update_statut/", json=payload)
    if r.status_code not in (200, 202):
        return build_response("❌ Échec de mise à jour du statut.", ACTIONS_BTNS)
    return build_response(f"✅ Statut mis à jour: *{statut}*.", ACTIONS_BTNS)

def set_statut_simple(session: Dict[str, Any], statut: str) -> Dict[str, Any]:
    liv_id = _ensure_livraison_id(session)
    if not liv_id:
        return build_response("❌ Livraison liée introuvable pour cette mission.", ["Mes missions","Missions dispo","Menu"])
    if statut not in STATUTS_VALIDES:
        return build_response("❌ Statut invalide.", ACTIONS_BTNS)
    return _update_statut(session, liv_id, statut)

def update_position(session: Dict[str, Any], lat: float, lng: float, livraison_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Met à jour la position du livreur.
    ⚡ Amélioration : envoie sur coordonnees_livraison si on est en fin de course.
    """
    liv_id = livraison_id or (session.get("ctx") or {}).get("current_livraison_id")
    if not liv_id:
        return build_response("❌ Pas d’ID livraison courant.", ACTIONS_BTNS)

    # Détermine si pickup ou livraison
    statut = (session.get("ctx") or {}).get("last_statut", "")
    field = "coordonnees_recuperation"
    if statut in {"en_route_livraison","arrive_livraison","livree"}:
        field = "coordonnees_livraison"

    payload = {field: f"{lat},{lng}", "content_type": 1, "object_id": int(liv_id)}
    r = api_request(session, "POST", f"/api/v1/livraisons/livraisons/{liv_id}/update_position/", json=payload)

    if r.status_code not in (200, 202):
        return build_response("❌ Position non mise à jour.", ACTIONS_BTNS)
    return build_response("📡 Position mise à jour avec succès.", ACTIONS_BTNS)
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
    lat: Optional[float]=None,
    lng: Optional[float]=None,
    media_url: Optional[str]=None
) -> Dict[str, Any]:
    t = normalize(text); tl = t.lower()
    session = get_session(phone)

    # Ici, on suppose l’utilisateur **déjà connecté** avec rôle livreur (géré par router/auth_core)

    # Menu / salutations
    if tl in GREETINGS:
        session["step"] = "MENU"
        return build_response("Que veux-tu faire ?", MAIN_MENU_BTNS)

    # Localisation (maj position)
    if lat is not None and lng is not None:
        return update_position(session, lat, lng)

    # Intents simples
    if tl in {"basculer","toggle","en ligne","hors ligne","basculer en ligne","basculer hors ligne"} or tl.startswith("basculer"):
        return toggle_disponibilite(session)

    if tl in {"missions dispo","missions","disponibles"}:
        return list_missions_disponibles(session)

    if tl in {"mes missions","mes","mes courses"}:
        return list_mes_missions(session)

    if tl.startswith("détails ") or tl.startswith("détail "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ",1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Détails 123*")
        return details_mission(session, mid)

    if tl.startswith("accepter "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ",1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Accepter 123*")
        return accepter_mission(session, mid)

    if tl in {"démarrer","demarrer","start"}:
        return action_demarrer(session)

    if tl in {"arrivé pickup","arrive pickup"}:
        return action_arrive_pickup(session)

    if tl in {"arrivé livraison","arrive livraison"}:
        return action_arrive_drop(session)

    if tl in {"livrée","livree"}:
        return action_livree(session)

    if tl.startswith("statut "):
        s = tl.split(" ",1)[1].strip()
        if s not in STATUTS_VALIDES:
            return build_response("❌ Statut inconnu. Ex: en_route_recuperation, recupere, livree.")
        return set_statut_simple(session, s)

    if tl in {"historique","history"}:
        return handle_history(session)

    # Aide par défaut
    return build_response(
        "❓ Je n’ai pas compris.\n"
        "• *Missions dispo* • *Mes missions* • *Basculer statut*\n"
        "• *Détails <id>* • *Accepter <id>* • *Démarrer* • *Arrivé pickup* • *Arrivé livraison* • *Livrée*",
        MAIN_MENU_BTNS
    )
