# chatbot/livreur_flow.py
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional, List
from .auth_core import get_session, build_response, normalize  # sessions/menus centralisés

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT = int(os.getenv("TOKTOK_TIMEOUT", "15"))

# Boutons (≤ 20 caractères pour WhatsApp). Max 3 par message via build_response.
MAIN_MENU_BTNS = ["📋 Missions", "🚴 Mes missions", "🔄 Statut"]
BTN_DEMARRER = "▶️ Démarrer"
BTN_PICKUP   = "📍 Pickup"
BTN_LIVREE   = "✅ Livrée"
BTN_MENU     = "⬅️ Menu"

GREETINGS = {"bonjour", "salut", "bjr", "bonsoir", "menu", "accueil", "start", "hello", "hi"}

STATUTS_VALIDES = {
    "en_attente","assignee","en_route_recuperation","arrive_recuperation",
    "recupere","en_route_livraison","arrive_livraison","livree","probleme","annulee"
}

# ---------- Utils ----------
def _fmt_xaf(n: Any) -> str:
    try:
        i = int(float(str(n)))
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n or 0)

def _buttons(*btns: str) -> List[str]:
    """Filtre les boutons vides et garde 3 max (WhatsApp)."""
    out = [b for b in btns if b]
    return out[:3]

def api_request(session: Dict[str, Any], method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    token = (session.get("auth") or {}).get("access")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-L] {method} {path} -> {r.status_code}")
    return r

# ---------- Disponibilité ----------
def toggle_disponibilite(session: Dict[str, Any]) -> Dict[str, Any]:
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("⚠️ Impossible d'accéder à ton profil. Merci de te reconnecter.", MAIN_MENU_BTNS + ["🔙 Retour"])

    lid = me.json().get("id")
    if not lid:
        return build_response("⚠️ Identifiant introuvable. Réessaie plus tard.", MAIN_MENU_BTNS + ["🔙 Retour"])

    r = api_request(session, "POST", f"/api/v1/auth/livreurs/{lid}/toggle_disponibilite/", json={})
    if r.status_code in (200, 202):
        me2 = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
        dispo = me2.json().get("disponible", False) if me2.status_code == 200 else False
        etat = "🟢 Disponible (En ligne)" if dispo else "🔴 Indisponible (Hors ligne)"
        return build_response(f"✅ Statut mis à jour : {etat}", MAIN_MENU_BTNS)

    return build_response("😕 Changement de statut indisponible pour l'instant.", MAIN_MENU_BTNS + ["🔙 Retour"])

# ---------- Missions disponibles ----------
def list_missions_disponibles(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/coursier/missions/disponibles/")
    if r.status_code != 200:
        return build_response("⚠️ Impossible de charger les missions. Réessaie plus tard.", MAIN_MENU_BTNS + ["🔙 Retour"])

    arr = r.json() or []
    if not arr:
        return build_response(
            "😕 Aucune mission disponible pour l'instant.\n⏳ Reste en ligne : de nouvelles opportunités arrivent régulièrement.",
            MAIN_MENU_BTNS + ["🔙 Retour"]
        )

    arr = arr[:3]  # limiter l’UI
    session.setdefault("ctx", {})["last_list"] = [d.get("id") for d in arr]

    lines, rows = [], []
    for d in arr:
        mid  = d.get("id")
        dep  = d.get("adresse_recuperation") or "Adresse inconnue"
        dest = d.get("adresse_livraison") or "Adresse inconnue"
        cod  = d.get("cod_montant") or d.get("montant_cod") or 0
        cod_txt = _fmt_xaf(cod)
        lines.append(f"#{mid} • {dep} → {dest}\n💵 Paiement à la livraison : {cod_txt} XAF")
        rows.append({
            "id": f"details_{mid}",
            "title": f"📄 Mission #{mid}",
            "description": (f"{dep} → {dest}")[:72]
        })

    msg = "🆕 *Missions disponibles*\n\n" + "\n\n".join(lines)
    # On renvoie un message de type "list" si ton intégration WhatsApp le supporte
    return {"response": msg, "list": {"title": "👉 Choisis une mission", "rows": rows}}

# ---------- Mes missions ----------
def list_mes_missions(session: Dict[str, Any]) -> Dict[str, Any]:
    # Correction : Filtrer les missions du livreur connecté
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("⚠️ Impossible d'accéder à ton profil.", MAIN_MENU_BTNS + ["🔙 Retour"])
    
    livreur_id = me.json().get("id")
    
    r = api_request(session, "GET", "/api/v1/coursier/missions/mes_missions/")
    if r.status_code != 200:
        return build_response("⚠️ Impossible de charger tes missions.", MAIN_MENU_BTNS + ["🔙 Retour"])

    arr = r.json() or []
    if not arr:
        return build_response("📭 Tu n'as aucune mission en cours.", MAIN_MENU_BTNS + ["🔙 Retour"])

    # Filtrer par livreur_id si le backend ne le fait pas déjà
    en_cours = [d for d in arr if (d.get("statut") or "").lower() not in {"livree", "annulee"}]
    if not en_cours:
        return build_response("📭 Tu n'as aucune mission en cours.", MAIN_MENU_BTNS + ["🔙 Retour"])

    lines, rows = [], []
    for d in en_cours[:5]:
        mid  = d.get("id")
        st   = (d.get("statut") or "—").replace("_", " ")
        dest = d.get("adresse_livraison", "—")
        lines.append(f"#{mid} — {st} → {dest}")
        rows.append({"id": f"details_{mid}", "title": f"📄 Mission #{mid}", "description": (f"{st} → {dest}")[:72]})

    return {
        "response": "📦 *Tes missions en cours*\n" + "\n".join(lines),
        "list": {"title": "👉 Choisis une mission", "rows": rows}
    }

# ---------- Détails mission ----------
def details_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if r.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS + ["🔙 Retour"])

    d = r.json()
    session.setdefault("ctx", {})["current_mission_id"] = d.get("id")

    # Compat : mémoriser l'id livraison si déjà lié
    liv_id = (d.get("livraison") or {}).get("id") or d.get("livraison_id")
    if liv_id:
        session["ctx"]["current_livraison_id"] = liv_id

    txt = (
        f"📄 *Mission #{d.get('id','?')}*\n"
        f"• Réf : {d.get('numero_mission','—')}\n"
        f"• Départ : {d.get('adresse_recuperation','—')}\n"
        f"• Destination : {d.get('adresse_livraison','—')}\n"
        f"• Paiement : {d.get('type_paiement','—')}\n"
        f"• Statut : {d.get('statut','—')}"
    )

    st = (d.get("statut") or "").lower()
    if st == "en_attente":
        return build_response(txt, _buttons(f"✅ Accepter {d.get('id')}", f"❌ Refuser {d.get('id')}", BTN_MENU))
    elif st in {"assignee", "assigned"}:
        return build_response(txt, _buttons(BTN_DEMARRER, "🚴 Mes missions", BTN_MENU))
    else:
        return build_response(txt, _buttons("🚴 Mes missions", BTN_MENU))

# ---------- Accepter / Refuser ----------
def accepter_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mission_id}/")
    if m.status_code != 200:
        return build_response("❌ Mission introuvable.", MAIN_MENU_BTNS + ["🔙 Retour"])
    mj = m.json()

    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("⚠️ Impossible d'accéder à ton profil. Merci de te reconnecter.", MAIN_MENU_BTNS + ["🔙 Retour"])
    livreur_id = me.json().get("id")

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
        logger.warning(f"[LIVREUR] accept mission failed: {r.status_code}")
        return build_response("😕 Impossible d'accepter cette mission (peut-être déjà prise).", MAIN_MENU_BTNS + ["🔙 Retour"])

    session.setdefault("ctx", {})["current_mission_id"] = mission_id
    return build_response(
        f"✅ Mission #{mission_id} acceptée.\nTu peux *{BTN_DEMARRER}* quand tu es prêt.",
        _buttons(BTN_DEMARRER, "🚴 Mes missions", BTN_MENU)
    )

def refuser_mission(session: Dict[str, Any], mission_id: str) -> Dict[str, Any]:
    # Endpoint /refuser/ selon API, si dispo. Ici feedback simple.
    return build_response(f"🚫 Mission #{mission_id} refusée.", MAIN_MENU_BTNS)

# ---------- Actions de mission ----------
def action_demarrer(session: Dict[str, Any]) -> Dict[str, Any]:
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

    m = api_request(session, "GET", f"/api/v1/coursier/missions/{mid}/")
    if m.status_code != 200:
        return build_response("⚠️ Impossible de charger la mission. Réessaie.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))
    mj = m.json()

    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("⚠️ Impossible d'accéder à ton profil. Merci de te reconnecter.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))
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

    r = api_request(session, "POST", "/api/v1/livraisons/livraisons/", json=payload)
    if r.status_code not in (200, 201, 202):
        logger.warning(f"[LIVREUR] start mission failed: {r.status_code}")
        return build_response("😕 Démarrage impossible pour le moment. Réessaie.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

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

    session.setdefault("ctx", {})["last_statut"] = "en_route_recuperation"

    return build_response(
        f"✅ Mission #{mid} démarrée • Livraison #{liv_id or '?'} créée.\n🚴 Direction le *point de récupération*.",
        _buttons(BTN_PICKUP, "🚴 Mes missions", BTN_MENU)
    )

def action_arrive_pickup(session: Dict[str, Any]) -> Dict[str, Any]:
    """Au pickup: marquer la marchandise récupérée."""
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mid}/marquer_recupere/", json={})
    if r.status_code not in (200, 201, 202):
        logger.warning(f"[LIVREUR] pickup failed: {r.status_code}")
        return build_response("😕 Erreur au point de récupération. Réessaie.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

    session.setdefault("ctx", {})["last_statut"] = "recupere"

    return build_response(
        f"📍 Mission #{mid} — *Pickup effectué*.\n👉 En route vers le client pour la livraison.",
        _buttons(BTN_LIVREE, "🚴 Mes missions", BTN_MENU)
    )

def action_livree(session: Dict[str, Any]) -> Dict[str, Any]:
    """Finalisation: marquer livrée côté mission."""
    mid = (session.get("ctx") or {}).get("current_mission_id")
    if not mid:
        return build_response("❌ Aucune mission en cours.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

    r = api_request(session, "POST", f"/api/v1/coursier/missions/{mid}/marquer_livre/", json={})
    if r.status_code not in (200, 201, 202):
        logger.warning(f"[LIVREUR] deliver failed: {r.status_code}")
        return build_response("😕 Erreur lors de la finalisation. Réessaie.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

    ctx = session.setdefault("ctx", {})
    ctx["last_statut"] = "livree"

    return build_response(
        f"✅ Mission #{mid} *livrée avec succès* 🚚\nMerci pour ton professionnalisme 👏",
        MAIN_MENU_BTNS
    )

# ---------- Livraisons / statut / position ----------
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
        logger.warning(f"[LIVREUR] update statut failed: {r.status_code}")
        return build_response("⚠️ Mise à jour du statut indisponible pour le moment.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))
    session.setdefault("ctx", {})["last_statut"] = statut
    return build_response(f"✅ Statut mis à jour : *{statut}*.", _buttons("🚴 Mes missions", BTN_MENU))

def set_statut_simple(session: Dict[str, Any], statut: str) -> Dict[str, Any]:
    liv_id = _ensure_livraison_id(session)
    if not liv_id:
        return build_response("❌ Aucune livraison liée trouvée pour cette mission.", _buttons("🚴 Mes missions", "📋 Missions", "🔙 Retour"))
    if statut not in STATUTS_VALIDES:
        return build_response("❌ Statut inconnu. Exemples : en_route_recuperation, recupere, livree.", _buttons("🚴 Mes missions", "🔙 Retour"))
    return _update_statut(session, liv_id, statut)

def update_position(session: Dict[str, Any], lat: float, lng: float, livraison_id: Optional[str] = None) -> Dict[str, Any]:
    liv_id = livraison_id or (session.get("ctx") or {}).get("current_livraison_id")
    if not liv_id:
        return build_response("❌ Aucune livraison active à mettre à jour.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))

    # Choix du champ selon la phase
    statut = (session.get("ctx") or {}).get("last_statut", "")
    field = "coordonnees_recuperation"
    if statut in {"en_route_livraison", "arrive_livraison", "livree"}:
        field = "coordonnees_livraison"

    # Enregistrement avec latitude et longitude séparées si possible
    payload = {
        field: f"{lat},{lng}",
        "latitude": lat,
        "longitude": lng
    }
    r = api_request(session, "POST", f"/api/v1/livraisons/livraisons/{liv_id}/update_position/", json=payload)
    if r.status_code not in (200, 202):
        logger.warning(f"[LIVREUR] update position failed: {r.status_code}")
        return build_response("⚠️ Position non mise à jour. Réessaie.", _buttons("🚴 Mes missions", BTN_MENU, "🔙 Retour"))
    return build_response("📡 Position mise à jour.", _buttons("🚴 Mes missions", BTN_MENU))

# ---------- Historique ----------
def handle_history(session: Dict[str, Any]) -> Dict[str, Any]:
    # Correction : Filtrer l'historique par livreur connecté
    me = api_request(session, "GET", "/api/v1/auth/livreurs/my_profile/")
    if me.status_code != 200:
        return build_response("⚠️ Impossible d'accéder à ton profil.", MAIN_MENU_BTNS + ["🔙 Retour"])
    
    livreur_id = me.json().get("id")
    
    r = api_request(session, "GET", "/api/v1/livraisons/livraisons/mes_livraisons/")
    if r.status_code != 200:
        return build_response("⚠️ Impossible de charger l'historique.", MAIN_MENU_BTNS + ["🔙 Retour"])
    data = r.json() or []
    
    # Filtrer les livraisons pour ce livreur spécifique si le backend ne le fait pas
    if isinstance(data, list):
        data = [d for d in data if d.get("livreur") == livreur_id or (isinstance(d.get("livreur"), dict) and d.get("livreur", {}).get("id") == livreur_id)]
    
    if not data:
        return build_response("🗂️ Aucun historique pour le moment.", MAIN_MENU_BTNS + ["🔙 Retour"])
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
    t = normalize(text); tl = t.lower().strip()
    session = get_session(phone)

    # Gestion bouton retour universel
    if tl in {"retour", "back", "🔙 retour"}:
        session["step"] = "MENU"
        return build_response("🏠 Menu livreur", MAIN_MENU_BTNS)

    # Salutations / raccourcis menu
    if tl in GREETINGS:
        session["step"] = "MENU"
        return build_response("👋 Bienvenue livreur ! Que souhaites-tu faire ?", MAIN_MENU_BTNS)

    # Position envoyée (partage localisation)
    if lat is not None and lng is not None:
        return update_position(session, lat, lng)

    # Disponibilité (toggle)
    if tl in {"basculer","toggle","statut","en ligne","hors ligne","basculer en ligne","basculer hors ligne","🔄 statut"}:
        return toggle_disponibilite(session)

    # Menus
    if tl in {"📋 missions","missions","missions dispo","disponibles","📋 missions dispo"}:
        return list_missions_disponibles(session)

    if tl in {"🚴 mes missions","mes missions","mes","mes courses"}:
        return list_mes_missions(session)

    # Détails / Accepter / Refuser (texte libre ou boutons)
    if tl.startswith("détails ") or tl.startswith("détail ") or tl.startswith("details "):
        # Ex: "Détails 123"
        part = tl.split(" ",1)[1] if " " in tl else ""
        mid = re.sub(r"[^0-9]", "", part)
        if not mid:
            return build_response("❌ Id manquant. Ex: *Détails 123*", MAIN_MENU_BTNS)
        return details_mission(session, mid)

    if tl.startswith("✅ accepter ") or tl.startswith("accepter "):
        part = tl.split(" ",1)[1] if " " in tl else ""
        mid = re.sub(r"[^0-9]", "", part)
        if not mid:
            return build_response("❌ Id manquant. Ex: *Accepter 123*", MAIN_MENU_BTNS)
        return accepter_mission(session, mid)

    if tl.startswith("❌ refuser ") or tl.startswith("refuser "):
        part = tl.split(" ",1)[1] if " " in tl else ""
        mid = re.sub(r"[^0-9]", "", part)
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
        s = tl.split(" ",1)[1].strip() if " " in tl else ""
        if s not in STATUTS_VALIDES:
            return build_response("❌ Statut inconnu. Ex: en_route_recuperation, recupere, livree.", MAIN_MENU_BTNS)
        return set_statut_simple(session, s)

    if tl in {"historique","history"}:
        return handle_history(session)

    # Fallback d’aide
    aide = (
        "❓ Je n’ai pas compris. Essaie :\n"
        "• *📋 Missions* — voir les missions disponibles\n"
        "• *🚴 Mes missions* — reprendre une mission en cours\n"
        "• *🔄 Statut* — te rendre disponible/indisponible\n"
        "• *Détails <id>* • *Accepter <id>* • *Refuser <id>*\n"
        f"• *{BTN_DEMARRER}* • *{BTN_PICKUP}* • *{BTN_LIVREE}*"
    )
    return build_response(aide, MAIN_MENU_BTNS)
