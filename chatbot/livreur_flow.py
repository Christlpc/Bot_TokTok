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

    arr = arr[:3]
    session.setdefault("ctx", {})["last_list"] = [d.get("id") for d in arr]

    lines = []
    for d in arr:
        mid = d.get("id")
        dep = d.get("adresse_recuperation") or "—"
        dest = d.get("adresse_livraison") or "—"
        cod = d.get("cod_montant") or d.get("montant_cod") or 0
        lines.append(f"#{mid} • {dep} → {dest}\n💵 COD: {cod} XAF")

    msg = "🆕 *Missions disponibles*\n" + "\n\n".join(lines)

    rows = []
    for d in arr:
        mid = d.get("id")
        dep = d.get("adresse_recuperation") or "—"
        dest = d.get("adresse_livraison") or "—"
        desc = f"{dep} → {dest}"[:72]
        rows.append({"id": f"details_{mid}", "title": f"📄 Détails #{mid}"[:24], "description": desc})

    return {"response": msg, "list": {"title": "Choisir une mission", "rows": rows}}


def list_mes_missions(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/mes_missions/")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement de tes missions.", MAIN_MENU_BTNS)

    arr = r.json() or []
    if not arr:
        return build_response("📭 Aucune mission en cours.", MAIN_MENU_BTNS)

    # Résumé texte
    lines = []
    for d in arr[:5]:
        mid  = d.get("id")
        st   = d.get("statut", "")
        dest = d.get("adresse_livraison", "—")
        lines.append(f"#{mid} — {st} → {dest}")

    msg = "📦 *Mes missions*\n" + "\n".join(lines)

    # Liste interactive
    rows = []
    for d in arr[:5]:
        mid  = d.get("id")
        dest = d.get("adresse_livraison", "—")
        desc = f"{d.get('statut','')} → {dest}"[:72]
        rows.append({"id": f"details_{mid}", "title": f"📄 Détails #{mid}", "description": desc})

    return {"response": msg, "list": {"title": "Choisir une mission", "rows": rows}}

def details_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if r.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)

    d = r.json()
    session.setdefault("ctx", {})["current_mission_id"] = d.get("id")

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
    )

    # Boutons selon statut
    if d.get("statut") == "en_attente":
        return build_response(txt, [f"Accepter {d.get('id')}", f"Refuser {d.get('id')}", "Menu"])
    elif d.get("statut") == "assignee":
        return build_response(txt, ["Démarrer", "Mes missions", "Menu"])
    else:
        return build_response(txt, ["Mes missions", "Menu"])


def accepter_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    # Charger les détails de la mission
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if m.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)
    mj = m.json()

    # Récupérer l’ID du livreur connecté
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("❌ Profil livreur introuvable.", MAIN_MENU_BTNS)
    livreur_id = me.json().get("id")

    # Construire le payload complet
    payload = {
        "numero_mission": mj.get("numero_mission"),
        "entreprise_demandeur": mj.get("entreprise_demandeur"),
        "contact_entreprise": mj.get("contact_entreprise"),
        "adresse_recuperation": mj.get("adresse_recuperation"),
        "coordonnees_recuperation": mj.get("coordonnees_recuperation"),
        "adresse_livraison": mj.get("adresse_livraison"),
        "coordonnees_livraison": mj.get("coordonnees_livraison"),
        "nom_client_final": mj.get("nom_client_final"),
        "telephone_client_final": mj.get("telephone_client_final"),
        "description_produit": mj.get("description_produit"),
        "valeur_produit": mj.get("valeur_produit"),
        "montant_coursier": mj.get("montant_coursier"),
        "type_paiement": mj.get("type_paiement"),
        "statut": "pending",
        "is_haute_valeur": mj.get("is_haute_valeur", False),
        "livreur": livreur_id,
    }

    # Appel API pour accepter
    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mission_id}/accepter/", json=payload)
    if r.status_code not in (200, 201):
        return build_response(f"❌ Erreur API: {r.status_code}\n{r.text}", MAIN_MENU_BTNS)

    session.setdefault("ctx", {})["current_mission_id"] = mission_id

    txt = f"✅ Mission #{mission_id} acceptée.\n👉 Tu peux *Démarrer* 🚀"
    return build_response(txt, ["Démarrer", "Mes missions", "Menu"])




def refuser_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    return build_response(f"🚫 Mission #{mission_id} refusée.", MAIN_MENU_BTNS)

# ---------- Actions ----------
def action_demarrer(session: Dict[str, Any]) -> Dict[str, Any]:
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", ["Mes missions", "Menu"])

    # Charger mission pour construire le payload
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mid}/")
    if m.status_code != 200:
        return build_response("❌ Impossible de charger la mission.", ["Mes missions", "Menu"])
    mj = m.json()

    # Charger profil livreur
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("❌ Profil livreur introuvable.", ["Mes missions", "Menu"])
    livreur_id = me.json().get("id")

    payload = {
        "mission_id": int(mid),
        "commande_id": mj.get("commande_id") or 0,
        "adresse_recuperation": mj.get("adresse_recuperation") or "",
        "coordonnees_recuperation": mj.get("coordonnees_recuperation") or "",
        "adresse_livraison": mj.get("adresse_livraison") or "",
        "coordonnees_livraison": mj.get("coordonnees_livraison") or "",
        "distance_km": str(mj.get("distance_km") or "0"),
        "duree_estimee_minutes": mj.get("duree_estimee_minutes") or 0,
        "livreur": livreur_id,
    }

    # Création de la livraison
    r = api_request(session, "POST", "/api/v1/livraisons/livraisons/", json=payload)
    if r.status_code not in (200, 201):
        return build_response(f"❌ Échec de démarrage de la mission.\n{r.text}", ["Mes missions", "Menu"])

    livraison = r.json() or {}
    liv_id = livraison.get("id") or livraison.get("livraison_id")
    if liv_id:
        session.setdefault("ctx", {})["current_livraison_id"] = liv_id

    return build_response(
        f"✅ Livraison #{liv_id or '?'} créée et mission #{mid} démarrée.\n🚴 En route vers le pickup.",
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

# ---------- Helpers livraisons ----------
def _ensure_livraison_id(session: Dict[str, Any]) -> Optional[str]:
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
    payload = {"statut": statut}
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
    liv_id = livraison_id or (session.get("ctx") or {}).get("current_livraison_id")
    if not liv_id:
        return build_response("❌ Pas d’ID livraison courant.", ACTIONS_BTNS)

    statut = (session.get("ctx") or {}).get("last_statut", "")
    field = "coordonnees_recuperation"
    if statut in {"en_route_livraison", "arrive_livraison", "livree"}:
        field = "coordonnees_livraison"

    payload = {field: f"{lat},{lng}"}
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

    if tl in GREETINGS:
        session["step"] = "MENU"
        return build_response("Que veux-tu faire ?", MAIN_MENU_BTNS)

    if lat is not None and lng is not None:
        return update_position(session, lat, lng)

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

    if tl.startswith("refuser "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ",1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Refuser 123*")
        return refuser_mission(session, mid)

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

    return build_response(
        "❓ Je n’ai pas compris.\n"
        "• *Missions dispo* • *Mes missions* • *Basculer statut*\n"
        "• *Détails <id>* • *Accepter <id>* • *Refuser <id>*\n"
        "• *Démarrer* • *Arrivé pickup* • *Arrivé livraison* • *Livrée*",
        MAIN_MENU_BTNS
    )
