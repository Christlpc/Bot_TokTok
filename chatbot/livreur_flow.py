# chatbot/livreur_flow.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional, List
from .auth_core import get_session, build_response, normalize  # sessions/menus centralisés

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

# Boutons (≤ 20 caractères pour WhatsApp). On garde 2–3 boutons contextuels max.
MAIN_MENU_BTNS = ["📋 Missions", "🚴 Mes missions", "🔄 Statut"]
# Ces libellés sont utilisés dynamiquement selon le contexte:
BTN_DEMARRER = "▶️ Démarrer"
BTN_PICKUP   = "📍 Pickup"
BTN_LIVREE   = "✅ Livrée"
BTN_MENU     = "⬅️ Menu"

GREETINGS = {"bonjour", "salut", "bjr", "bonsoir", "menu", "accueil", "start"}

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

def _buttons(*btns: str) -> List[str]:
    """Filtre les boutons vides et garde 3 max (WhatsApp)."""
    out = [b for b in btns if b]
    return out[:3]

# ---------- Disponibilité ----------
def toggle_disponibilite(session: Dict[str, Any]) -> Dict[str, Any]:
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("❌ Profil introuvable. Merci de te reconnecter.", MAIN_MENU_BTNS)

    lid = me.json().get("id")
    if not lid:
        return build_response("❌ Impossible de retrouver ton identifiant livreur.", MAIN_MENU_BTNS)

    r = api_request(session, "POST", f"/api/v1/auth/livreurs/{lid}/toggle_disponibilite/", json={})
    if r.status_code in (200, 202):
        me2 = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
        dispo = me2.json().get("disponible", False) if me2.status_code == 200 else False
        etat = "🟢 Disponible (En ligne)" if dispo else "🔴 Indisponible (Hors ligne)"
        return build_response(f"✅ Statut mis à jour : {etat}", MAIN_MENU_BTNS)

    return build_response("⚠️ Impossible de changer ton statut pour le moment.", MAIN_MENU_BTNS)

# ---------- Missions disponibles ----------
def list_missions_disponibles(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/disponibles/")
    if r.status_code != 200:
        return build_response("⚠️ Erreur lors du chargement des missions disponibles.", MAIN_MENU_BTNS)

    arr = r.json() or []
    if not arr:
        return build_response(
            "😕 Aucune mission disponible pour l’instant.\n⏳ Reste en ligne pour recevoir de nouvelles opportunités.",
            MAIN_MENU_BTNS
        )

    arr = arr[:3]
    session.setdefault("ctx", {})["last_list"] = [d.get("id") for d in arr]

    lines, rows = [], []
    for d in arr:
        mid  = d.get("id")
        dep  = d.get("adresse_recuperation") or "Adresse inconnue"
        dest = d.get("adresse_livraison") or "Adresse inconnue"
        cod  = d.get("cod_montant") or d.get("montant_cod") or 0
        lines.append(f"#{mid} • {dep} → {dest}\n💵 Paiement à la livraison : {cod} XAF")
        rows.append({
            "id": f"details_{mid}",
            "title": f"📄 Mission #{mid}",
            "description": (f"{dep} → {dest}")[:72]
        })

    msg = "🆕 *Missions disponibles*\n\n" + "\n\n".join(lines)
    return {"response": msg, "list": {"title": "👉 Choisis une mission", "rows": rows}}

# ---------- Mes missions ----------
def list_mes_missions(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/mes_missions/")
    if r.status_code != 200:
        return build_response("⚠️ Erreur lors du chargement de tes missions.", MAIN_MENU_BTNS)

    arr = r.json() or []
    if not arr:
        return build_response("📭 Tu n’as aucune mission en cours.", MAIN_MENU_BTNS)

    # On ne liste pas les missions livrées/annulées
    en_cours = [d for d in arr if (d.get("statut") or "").lower() not in {"livree", "annulee"}]
    if not en_cours:
        return build_response("📭 Tu n’as aucune mission en cours.", MAIN_MENU_BTNS)

    lines, rows = [], []
    for d in en_cours[:5]:
        mid  = d.get("id")
        st   = d.get("statut", "")
        dest = d.get("adresse_livraison", "—")
        lines.append(f"#{mid} — {st} → {dest}")
        rows.append({"id": f"details_{mid}", "title": f"📄 Mission #{mid}", "description": (f"{st} → {dest}")[:72]})

    return {"response": "📦 *Tes missions en cours*\n" + "\n".join(lines),
            "list": {"title": "👉 Choisis une mission", "rows": rows}}

# ---------- Détails mission ----------
def details_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if r.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)

    d = r.json()
    session.setdefault("ctx", {})["current_mission_id"] = d.get("id")

    # Pour compat : mémoriser l'id livraison si déjà lié
    liv_id = (d.get("livraison") or {}).get("id") or d.get("livraison_id")
    if liv_id:
        session["ctx"]["current_livraison_id"] = liv_id

    txt = (
        f"📄 *Mission #{d.get('id','?')}*\n"
        f"• Référence : {d.get('numero_mission','—')}\n"
        f"• Départ : {d.get('adresse_recuperation','—')}\n"
        f"• Destination : {d.get('adresse_livraison','—')}\n"
        f"• Paiement : {d.get('type_paiement','—')}\n"
        f"• Statut actuel : {d.get('statut','—')}"
    )

    st = (d.get("statut") or "").lower()
    if st == "en_attente":
        return build_response(txt, _buttons(f"✅ Accepter {d.get('id')}", f"❌ Refuser {d.get('id')}", BTN_MENU))
    elif st in {"assignee", "assigned"}:
        return build_response(txt, _buttons(BTN_DEMARRER, "🚴 Mes missions", BTN_MENU))
    else:
        # mission déjà engagée : propose actions principales via menu perso
        return build_response(txt, _buttons("🚴 Mes missions", BTN_MENU))

# ---------- Accepter / Refuser ----------
def accepter_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    # Charger détails
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if m.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS)
    mj = m.json()

    # Profil livreur
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("❌ Profil livreur introuvable.", MAIN_MENU_BTNS)
    livreur_id = me.json().get("id")

    # Payload attendu par l’API d’acceptation
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

    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mission_id}/accepter/", json=payload)
    if r.status_code not in (200, 201):
        return build_response(f"❌ Impossible d’accepter (déjà prise ?).\n{r.text}", MAIN_MENU_BTNS)

    session.setdefault("ctx", {})["current_mission_id"] = mission_id
    return build_response(f"✅ Mission #{mission_id} acceptée.\n👉 Tu peux *{BTN_DEMARRER}*.", _buttons(BTN_DEMARRER, "🚴 Mes missions", BTN_MENU))

def refuser_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    # Selon API, on pourrait appeler un endpoint /refuser/ si disponible.
    return build_response(f"🚫 Mission #{mission_id} refusée.", MAIN_MENU_BTNS)

# ---------- Actions de mission ----------
def action_demarrer(session: Dict[str, Any]) -> Dict[str, Any]:
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", _buttons("🚴 Mes missions", BTN_MENU))

    # 1) Charger mission (pour payload)
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mid}/")
    if m.status_code != 200:
        return build_response("❌ Impossible de charger la mission.", _buttons("🚴 Mes missions", BTN_MENU))
    mj = m.json()

    # 2) Profil livreur
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("❌ Profil livreur introuvable.", _buttons("🚴 Mes missions", BTN_MENU))
    livreur_id = me.json().get("id")

    # 3) Payload exigé pour créer la livraison (lien mission ↔ livraison)
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

    r = api_request(session, "POST", "/api/v1/livraisons/livraisons/", json=payload)
    if r.status_code not in (200, 201, 202):
        return build_response(f"❌ Échec du démarrage.\n{r.text}", _buttons("🚴 Mes missions", BTN_MENU))

    # Chercher l'id livraison
    livraison = {}
    try:
        livraison = r.json() or {}
    except Exception:
        livraison = {}

    liv_id = livraison.get("id") or livraison.get("livraison_id") or livraison.get("pk")
    if not liv_id:
        loc = r.headers.get("Location") or r.headers.get("Content-Location")
        if loc:
            mloc = re.search(r"/(\d+)/?$", loc)
            if mloc:
                liv_id = mloc.group(1)

    if not liv_id:
        m2 = api_request(session, "GET", f"/api/v1/coursier/missions/{mid}/")
        if m2.status_code == 200:
            mj2 = m2.json()
            liv_id = (mj2.get("livraison") or {}).get("id") or mj2.get("livraison_id")

    if liv_id:
        session.setdefault("ctx", {})["current_livraison_id"] = liv_id

    # On considère que le livreur part vers le pickup
    session.setdefault("ctx", {})["last_statut"] = "en_route_recuperation"

    return build_response(
        f"✅ Mission #{mid} démarrée • Livraison #{liv_id or '?'} créée.\n🚴 En route vers le *point de récupération*.",
        _buttons(BTN_PICKUP, "🚴 Mes missions", BTN_MENU)
    )

def action_arrive_pickup(session: Dict[str, Any]) -> Dict[str, Any]:
    """Au pickup: l'API attend /marquer_recupere/. On passe ensuite directement à Livrée quand la remise est faite."""
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", _buttons("🚴 Mes missions", BTN_MENU))

    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mid}/marquer_recupere/", json={})
    if r.status_code not in (200, 201, 202):
        return build_response(f"❌ Erreur au point de récupération : {r.status_code}\n{r.text}", _buttons("🚴 Mes missions", BTN_MENU))

    # Mémoriser statut pour update_position
    session.setdefault("ctx", {})["last_statut"] = "recupere"

    return build_response(
        f"📍 Mission #{mid} marquée *Pickup effectué*.\n👉 Dirige-toi vers le client et finalise la livraison.",
        _buttons(BTN_LIVREE, "🚴 Mes missions", BTN_MENU)
    )

def action_livree(session: Dict[str, Any]) -> Dict[str, Any]:
    """Finalisation: marquer livrée côté mission."""
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", _buttons("🚴 Mes missions", BTN_MENU))

    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mid}/marquer_livre/", json={})
    if r.status_code not in (200, 201, 202):
        return build_response(f"❌ Erreur lors de la finalisation : {r.status_code}\n{r.text}", _buttons("🚴 Mes missions", BTN_MENU))

    # Mission terminée, on peut nettoyer le contexte livraison courant
    ctx = session.setdefault("ctx", {})
    ctx["last_statut"] = "livree"

    return build_response(
        f"✅ Mission #{mid} *livrée avec succès* 🚚\nMerci pour ton professionnalisme 👏",
        MAIN_MENU_BTNS
    )

# ---------- Helpers livraisons / statut / position ----------
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
        return build_response("⚠️ Échec de mise à jour du statut.", _buttons("🚴 Mes missions", BTN_MENU))
    session.setdefault("ctx", {})["last_statut"] = statut
    return build_response(f"✅ Statut mis à jour : *{statut}*.", _buttons("🚴 Mes missions", BTN_MENU))

def set_statut_simple(session: Dict[str, Any], statut: str) -> Dict[str, Any]:
    liv_id = _ensure_livraison_id(session)
    if not liv_id:
        return build_response("❌ Livraison liée introuvable pour cette mission.", _buttons("🚴 Mes missions", "📋 Missions", BTN_MENU))
    if statut not in STATUTS_VALIDES:
        return build_response("❌ Statut invalide.", _buttons("🚴 Mes missions", BTN_MENU))
    return _update_statut(session, liv_id, statut)

def update_position(session: Dict[str, Any], lat: float, lng: float, livraison_id: Optional[str] = None) -> Dict[str, Any]:
    liv_id = livraison_id or (session.get("ctx") or {}).get("current_livraison_id")
    if not liv_id:
        return build_response("❌ Pas d’ID livraison courant.", _buttons("🚴 Mes missions", BTN_MENU))

    # Choisir le champ selon la phase
    statut = (session.get("ctx") or {}).get("last_statut", "")
    field = "coordonnees_recuperation"
    if statut in {"en_route_livraison", "arrive_livraison", "livree"}:
        field = "coordonnees_livraison"

    payload = {field: f"{lat},{lng}"}
    r = api_request(session, "POST", f"/api/v1/livraisons/livraisons/{liv_id}/update_position/", json=payload)
    if r.status_code not in (200, 202):
        return build_response("⚠️ Position non mise à jour.", _buttons("🚴 Mes missions", BTN_MENU))
    return build_response("📡 Position mise à jour.", _buttons("🚴 Mes missions", BTN_MENU))

# ---------- Historique ----------
def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/livraisons/livraisons/mes_livraisons/")
    if r.status_code != 200:
        return build_response("⚠️ Erreur lors du chargement de l’historique.", MAIN_MENU_BTNS)
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
    # Normalisation
    t = normalize(text); tl = t.lower().strip()
    session = get_session(phone)

    # Salutations / raccourcis menu
    if tl in GREETINGS:
        session["step"] = "MENU"
        return build_response(
            "👋 Bienvenue livreur ! Que souhaites-tu faire ?",
            MAIN_MENU_BTNS
        )

    # Position envoyée (partage localisation)
    if lat is not None and lng is not None:
        return update_position(session, lat, lng)

    # Disponibilité (toggle)
    if tl in {
        "basculer","toggle","statut","en ligne","hors ligne",
        "basculer en ligne","basculer hors ligne","🔄 statut"
    }:
        return toggle_disponibilite(session)

    # Menus
    if tl in {"📋 missions","missions","missions dispo","disponibles","📋 missions dispo"}:
        return list_missions_disponibles(session)

    if tl in {"🚴 mes missions","mes missions","mes","mes courses"}:
        return list_mes_missions(session)

    # Détails / Accepter / Refuser (texte libre ou boutons)
    if tl.startswith("détails ") or tl.startswith("détail ") or tl.startswith("details "):
        # Ex: "Détails 123"
        mid = re.sub(r"[^0-9]", "", tl.split(" ",1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Détails 123*", MAIN_MENU_BTNS)
        return details_mission(session, mid)

    if tl.startswith("✅ accepter ") or tl.startswith("accepter "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ",1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Accepter 123*", MAIN_MENU_BTNS)
        return accepter_mission(session, mid)

    if tl.startswith("❌ refuser ") or tl.startswith("refuser "):
        mid = re.sub(r"[^0-9]", "", tl.split(" ",1)[1])
        if not mid:
            return build_response("❌ Id manquant. Ex: *Refuser 123*", MAIN_MENU_BTNS)
        return refuser_mission(session, mid)

    # Actions directes
    if tl in {"▶️ démarrer","démarrer","demarrer","start"}:
        return action_demarrer(session)

    if tl in {"📍 pickup","pickup","arrivé pickup","arrive pickup"}:
        return action_arrive_pickup(session)

    if tl in {"✅ livrée","livree","livrée"}:
        return action_livree(session)

    # Mise à jour simple de statut (avancé)
    if tl.startswith("statut "):
        s = tl.split(" ",1)[1].strip()
        if s not in STATUTS_VALIDES:
            return build_response("❌ Statut inconnu. Ex: en_route_recuperation, recupere, livree.", MAIN_MENU_BTNS)
        return set_statut_simple(session, s)

    if tl in {"historique","history"}:
        return handle_history(session)

    # Fallback d’aide
    aide = (
        "❓ Je n’ai pas compris. Essaye l’un de ces choix :\n"
        "• *📋 Missions* — voir les missions disponibles\n"
        "• *🚴 Mes missions* — reprendre une mission en cours\n"
        "• *🔄 Statut* — te rendre disponible/indisponible\n"
        "• *Détails <id>* • *Accepter <id>* • *Refuser <id>*\n"
        f"• *{BTN_DEMARRER}* • *{BTN_PICKUP}* • *{BTN_LIVREE}*"
    )
    return build_response(aide, MAIN_MENU_BTNS)
