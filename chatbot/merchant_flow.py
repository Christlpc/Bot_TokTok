# entreprise_flow.py (ex-marchand_flow.py)
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional, List
from .auth_core import get_session, build_response, normalize

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT  = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_BTNS     = ["Créer produit", "Mes produits", "Commandes"]         # ≤20 chars OK
ORDER_BTNS    = ["Accepter", "Préparer", "Expédier"]
PRODUCT_BTNS  = ["Publier", "Mettre à jour", "Supprimer"]  # (Supprimer non-implémenté ici)

STATUTS_CMD = {"nouvelle","acceptee","preparee","expediee","livree","annulee"}

# -----------------------------
# Utils API
# -----------------------------
def api_request(session: Dict[str, Any], method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    tok = (session.get("auth") or {}).get("access")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)

def _ensure_entreprise_id(session: Dict[str, Any]) -> Optional[int]:
    """Récupère l’ID entreprise connecté (ex-marchand)."""
    me = api_request(session, "GET", "/api/v1/auth/entreprises/my_profile/")
    if me.status_code != 200:
        return None
    mid = me.json().get("id")
    session.setdefault("user", {})["id"] = mid
    return mid

# -----------------------------
# Actions Boutique
# -----------------------------
def toggle_boutique(session: Dict[str, Any]) -> Dict[str, Any]:
    eid = session.get("user", {}).get("id") or _ensure_entreprise_id(session)
    if not eid:
        return build_response("❌ Profil entreprise introuvable. Reconnectez-vous.", MAIN_BTNS)
    r = api_request(session, "POST", f"/api/v1/auth/entreprises/{eid}/toggle_actif/", json={})
    if r.status_code not in (200, 202):
        return build_response("❌ Impossible de basculer l’état de la boutique.", MAIN_BTNS)
    me = api_request(session, "GET", "/api/v1/auth/entreprises/my_profile/")
    actif = False
    if me.status_code == 200:
        actif = bool(me.json().get("actif", False))
    return build_response(f"🏬 Boutique : {'🟢 Ouverte' if actif else '🔴 Fermée'}.", MAIN_BTNS)

# -----------------------------
# Produits
# -----------------------------
def list_my_products(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/marketplace/produits/?mine=1")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement des produits.", MAIN_BTNS)
    arr = r.json() or []
    if isinstance(arr, dict) and "results" in arr:
        arr = arr["results"]
    if not arr:
        return build_response(
            "📦 Aucun produit publié.\n👉 Tapez *Créer produit* pour ajouter un article.",
            ["Créer produit","Commandes","Menu"]
        )
    lines = []
    for p in arr[:5]:
        pid = p.get("id")
        nom = p.get("nom") or p.get("name") or f"Produit {pid}"
        prix = p.get("prix") or p.get("price") or 0
        stock = p.get("stock", "-")
        actif = "✅" if p.get("actif", True) else "⛔"
        lines.append(f"#{pid} • {nom} • {prix} XAF • stock {stock} {actif}")
    return build_response(
        "🗂️ *Mes produits*\n" + "\n".join(lines) + "\n\n👉 *Détail <id>* ou *Edit <id>*",
        ["Créer produit","Commandes","Menu"]
    )

def product_detail(session: Dict[str, Any], pid: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/marketplace/produits/{pid}/")
    if r.status_code != 200:
        return build_response("❌ Produit introuvable.", MAIN_BTNS)
    p = r.json()
    txt = (
        f"📄 *Produit #{p.get('id')}*\n"
        f"• Nom: {p.get('nom') or p.get('name')}\n"
        f"• Prix: {p.get('prix') or p.get('price')} XAF\n"
        f"• Catégorie: {p.get('categorie') or p.get('category','-')}\n"
        f"• Stock: {p.get('stock','-')}\n"
        f"• Actif: {'Oui' if p.get('actif', True) else 'Non'}\n"
        f"• Desc: {p.get('description','-')}\n"
    )
    session.setdefault("ctx", {})["current_product_id"] = p.get("id")
    return build_response(txt, ["Mettre à jour","Mes produits","Menu"])

def product_patch(session: Dict[str, Any], pid: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "PATCH", f"/api/v1/marketplace/produits/{pid}/", json=fields)
    if r.status_code not in (200, 202):
        return build_response("❌ Échec mise à jour produit.")
    return product_detail(session, pid)

# Wizard création produit
def create_start(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "PROD_NAME"
    session.setdefault("ctx", {})["new_product"] = {
        "nom": None,
        "prix": None,
        "categorie": None,
        "stock": None,
        "description": None,
        "image_url": None,
        "actif": True,
    }
    return build_response("🆕 *Création produit* — Quel est le *nom* de l’article ?")

def handle_create_wizard(session: Dict[str, Any], t: str, media_url: Optional[str]) -> Dict[str, Any]:
    np = session["ctx"]["new_product"]
    step = session["step"]

    if step == "PROD_NAME":
        np["nom"] = t
        session["step"] = "PROD_PRICE"
        return build_response("💰 *Prix* (XAF) ? (ex: 4500)")

    if step == "PROD_PRICE":
        amount = re.sub(r"[^0-9]", "", t)
        if not amount:
            return build_response("⚠️ Entrez un nombre. Ex: 4500")
        np["prix"] = int(amount)
        session["step"] = "PROD_CATEGORY"
        return build_response("🏷️ *Catégorie* ? (ex: Restauration, Électro…)")

    if step == "PROD_CATEGORY":
        np["categorie"] = t
        session["step"] = "PROD_STOCK"
        return build_response("📦 *Stock* initial ? (ex: 10)")

    if step == "PROD_STOCK":
        q = re.sub(r"[^0-9]", "", t)
        if not q:
            return build_response("⚠️ Entrez un entier. Ex: 10")
        np["stock"] = int(q)
        session["step"] = "PROD_DESC"
        return build_response("📝 *Description* courte ?")

    if step == "PROD_DESC":
        np["description"] = t
        session["step"] = "PROD_IMAGE"
        return build_response("🖼️ Envoyez *une image* (ou tapez *Passer*)")

    if step == "PROD_IMAGE":
        if media_url and media_url.startswith("http"):
            np["image_url"] = media_url
        # recap
        session["step"] = "PROD_CONFIRM"
        recap = (
            "🧾 *Récap produit* :\n"
            f"• Nom: {np['nom']}\n"
            f"• Prix: {np['prix']} XAF\n"
            f"• Catégorie: {np['categorie']}\n"
            f"• Stock: {np['stock']}\n"
            f"• Desc: {np['description']}\n"
            f"• Image: {'Oui' if np['image_url'] else 'Non'}\n\n"
            "👉 *Publier* pour créer, ou *Modifier*."
        )
        return build_response(recap, ["Publier","Modifier","Annuler"])

    if step == "PROD_CONFIRM":
        tt = t.lower()
        if tt in {"publier","creer","confirmer"}:
            return create_submit(session)
        if tt in {"modifier","edit"}:
            session["step"] = "PROD_NAME"
            return build_response("✏️ Reprenons : quel est le *nom* ?")
        if tt in {"annuler","cancel"}:
            session["step"] = "ENTREPRISE_MENU"
            session["ctx"].pop("new_product", None)
            return build_response("❌ Création annulée.", MAIN_BTNS)
        return build_response("👉 Répondez par *Publier*, *Modifier* ou *Annuler*.", ["Publier","Modifier","Annuler"])

    # fallback
    return build_response("Tapez *Publier* pour créer, ou *Modifier* pour reprendre.")

def create_submit(session: Dict[str, Any]) -> Dict[str, Any]:
    np = session["ctx"]["new_product"]

    # Vérifie l’entreprise connectée
    eid = session.get("user", {}).get("id") or _ensure_entreprise_id(session)
    if not eid:
        return build_response("❌ Impossible de retrouver votre entreprise. Reconnectez-vous.", MAIN_BTNS)

    # ⚠️ Ici il faut mapper la catégorie : soit via un lookup API, soit un ID fixe
    categorie_id = np.get("categorie")
    # Si l’API attend un ID, il faudra ajouter une étape avant (ex: choix dans liste des catégories)

    payload = {
        "nom": np["nom"],
        "prix": np["prix"],
        "categorie_id": categorie_id,  # 🔑 Utiliser _id au lieu de string
        "stock": np["stock"],
        "description": np["description"],
        "entreprise_id": eid,          # 🔑 Important !
        "actif": True,
    }
    if np.get("image_url"):
        payload["image_url"] = np["image_url"]

    r = api_request(session, "POST", "/api/v1/marketplace/produits/", json=payload)

    if r.status_code not in (200, 201):
        logger.error(f"Erreur API création produit: {r.status_code} - {r.text}")
        return build_response("❌ Échec de création du produit. Vérifiez vos champs.", ["Mes produits","Menu"])

    p = r.json()
    session["step"] = "ENTREPRISE_MENU"
    session["ctx"].pop("new_product", None)
    return build_response(
        f"✅ Produit #{p.get('id')} *{p.get('nom')}* créé.",
        ["Mes produits","Commandes","Menu"]
    )

# -----------------------------
# Commandes
# -----------------------------
def list_my_orders(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/marketplace/commandes/?mine=1")
    if r.status_code != 200:
        return build_response("❌ Erreur lors du chargement des commandes.", MAIN_BTNS)
    arr = r.json() or []
    if isinstance(arr, dict) and "results" in arr:
        arr = arr["results"]
    if not arr:
        return build_response("📭 Aucune commande pour le moment.", MAIN_BTNS)
    lines = []
    for c in arr[:5]:
        cid = c.get("id")
        statut = c.get("statut") or "-"
        total = c.get("total_xaf") or c.get("montant") or "-"
        client = (c.get("client") or {}).get("username") or c.get("client_nom") or "-"
        lines.append(f"#{cid} • {statut} • {total} XAF • {client}")
    return build_response(
        "🧾 *Mes commandes*\n" + "\n".join(lines) + "\n\n👉 *Commande <id>* pour le détail",
        ["Commande 123","Menu","Mes produits"]
    )

def order_detail(session: Dict[str, Any], cid: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/marketplace/commandes/{cid}/")
    if r.status_code != 200:
        return build_response("❌ Commande introuvable.", MAIN_BTNS)
    c = r.json()
    items = c.get("lignes") or c.get("items") or []
    lst = []
    for it in items[:6]:
        nom = (it.get("produit") or {}).get("nom") or it.get("nom","-")
        qte = it.get("quantite") or it.get("qty") or 1
        px  = it.get("prix_unitaire") or it.get("prix") or "-"
        lst.append(f"• {nom} x{qte} — {px} XAF")
    txt = (
        f"📄 *Commande #{c.get('id')}*\n"
        f"• Statut: {c.get('statut')}\n"
        f"• Total: {c.get('total_xaf') or c.get('montant','-')} XAF\n"
        f"• Client: {(c.get('client') or {}).get('username') or c.get('client_nom','-')}\n"
        f"• Adresse: {c.get('adresse_livraison','-')}\n"
        f"• Téléphone: {c.get('telephone_livraison','-')}\n"
        + ("\n".join(lst) if lst else "\n• (Pas de lignes)")
        + "\n\nActions: *Accepter*, *Préparer*, *Expédier*, *Livrée*, *Annuler*"
    )
    session.setdefault("ctx", {})["current_order_id"] = c.get("id")
    return build_response(txt, ["Accepter","Préparer","Expédier"])

def order_update_status(session: Dict[str, Any], cid: str, statut: str) -> Dict[str, Any]:
    statut = statut.lower()
    if statut == "accepter":
        statut = "acceptee"
    if statut in {"préparer", "preparer"}:
        statut = "preparee"
    if statut in {"expédier", "expedier"}:
        statut = "expediee"
    if statut in {"livrée", "livree"}:
        statut = "livree"
    if statut == "annuler":
        statut = "annulee"
    if statut not in STATUTS_CMD:
        return build_response("❌ Statut inconnu. (Accepter/Préparer/Expédier/Livrée/Annuler)")

    r = api_request(session, "POST", f"/api/v1/marketplace/commandes/{cid}/update_statut/", json={"statut": statut})
    if r.status_code not in (200, 202):
        return build_response("❌ Échec de mise à jour du statut.")
    return build_response(f"✅ Commande #{cid} → *{statut}*.", ["Commandes","Mes produits","Menu"])

# -----------------------------
# Router texte
# -----------------------------
def handle_message(phone: str, text: str,
                   *, lat: Optional[float] = None,
                   lng: Optional[float] = None,
                   media_url: Optional[str] = None,
                   **_) -> Dict[str, Any]:
    t = normalize(text).lower()
    session = get_session(phone)

    # Salutations/Menu
    if t in {"menu","bonjour","salut","hello","hi","accueil"}:
        session["step"] = "ENTREPRISE_MENU"
        return build_response("🏪 *Espace entreprise* — choisissez :", MAIN_BTNS)

    # Toggle boutique (ouvert/fermé)
    if t in {"basculer","toggle","ouvrir","fermer","basculer ouvert","basculer ferme"} or t.startswith("basculer"):
        return toggle_boutique(session)

    # Produits
    if t in {"mes produits","produits","catalogue"}:
        session["step"] = "ENTREPRISE_MENU"
        return list_my_products(session)

    if t in {"créer produit","creer produit","nouveau produit","ajouter produit"}:
        return create_start(session)

    if t.startswith("detail ") or t.startswith("détail "):
        pid = re.sub(r"[^0-9]", "", t.split(" ",1)[1])
        if not pid:
            return build_response("❌ Id manquant. Ex: *Détail 123*")
        return product_detail(session, pid)

    if t.startswith("edit "):
        pid = re.sub(r"[^0-9]", "", t.split(" ",1)[1])
        if not pid:
            return build_response("❌ Id manquant. Ex: *Edit 123*")
        session.setdefault("ctx", {})["current_product_id"] = int(pid)
        session["step"] = "PROD_EDIT_FIELD"
        return build_response("✏️ Quel champ modifier ? (*prix*, *stock*, *nom*, *description*, *categorie*)")

    if session.get("step") in {"PROD_NAME","PROD_PRICE","PROD_CATEGORY","PROD_STOCK","PROD_DESC","PROD_IMAGE","PROD_CONFIRM"}:
        # Wizard création produit
        return handle_create_wizard(session, text, media_url)

    if session.get("step") == "PROD_EDIT_FIELD":
        field = t
        allowed = {"prix","stock","nom","description","categorie"}
        if field not in allowed:
            return build_response("👉 Choisissez parmi *prix*, *stock*, *nom*, *description*, *categorie*.")
        session.setdefault("ctx", {})["edit_field"] = field
        session["step"] = "PROD_EDIT_VALUE"
        return build_response(f"Entrez la *nouvelle valeur* pour {field} :")

    if session.get("step") == "PROD_EDIT_VALUE":
        pid = (session.get("ctx") or {}).get("current_product_id")
        field = (session.get("ctx") or {}).get("edit_field")
        if not pid or not field:
            session["step"] = "ENTREPRISE_MENU"
            return build_response("❌ Contexte perdu. Reprenez avec *Mes produits*.")
        value: Any = text
        if field in {"prix","stock"}:
            num = re.sub(r"[^0-9]", "", text)
            if not num:
                return build_response("⚠️ Entrez un nombre valide.")
            value = int(num)
        fields = { "prix": "prix", "stock": "stock", "nom": "nom", "description": "description", "categorie": "categorie" }
        session["step"] = "ENTREPRISE_MENU"
        return product_patch(session, str(pid), {fields[field]: value})

    # Commandes
    if t in {"commandes","mes commandes"}:
        return list_my_orders(session)

    if t.startswith("commande "):
        cid = re.sub(r"[^0-9]", "", t.split(" ",1)[1])
        if not cid:
            return build_response("❌ Id manquant. Ex: *Commande 123*")
        return order_detail(session, cid)

    if t in {"accepter","préparer","preparer","expédier","expedier","livrée","livree","annuler"}:
        cid = (session.get("ctx") or {}).get("current_order_id")
        if not cid:
            return build_response("❌ Aucune commande sélectionnée. Envoie *Commande <id>* d’abord.", ["Commandes","Menu"])
        return order_update_status(session, str(cid), t)

    # Aide
    return build_response(
        "ℹ️ Commandes: *Commandes*, *Commande <id>*, *Accepter/Préparer/Expédier/Livrée/Annuler*\n"
        "ℹ️ Produits: *Créer produit*, *Mes produits*, *Détail <id>*, *Edit <id>*\n"
        "ℹ️ Boutique: *Basculer* (Ouvert/Fermé)\n"
        "👉 Tapez *menu* pour revenir.",
        ["Mes produits","Commandes","Menu"]
    )
