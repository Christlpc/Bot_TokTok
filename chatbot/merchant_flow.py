# entreprise_flow.py (ex-marchand_flow.py)
from __future__ import annotations
import os, re, logging, requests
from typing import Dict, Any, Optional, List
from .auth_core import get_session, build_response, normalize

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com")
TIMEOUT  = int(os.getenv("TOKTOK_TIMEOUT", "15"))

MAIN_BTNS     = ["Créer produit", "Mes produits", "Commandes"]         # ≤20 chars (WhatsApp)
ORDER_BTNS    = ["Accepter", "Préparer", "Expédier"]                   # 3 max
PRODUCT_BTNS  = ["Publier", "Modifier", "Annuler"]                     # (Supprimer non-implémenté ici)

STATUTS_CMD = {"nouvelle","acceptee","preparee","expediee","livree","annulee"}

# -----------------------------
# Helpers UI
# -----------------------------
def _fmt_xaf(n: Any) -> str:
    try:
        i = int(float(str(n)))
        return f"{i:,}".replace(",", " ")
    except Exception:
        return str(n or 0)

def _btns(*items: str) -> List[str]:
    return [x for x in items if x][:3]

# -----------------------------
# Utils API
# -----------------------------
def api_request(session: Dict[str, Any], method: str, path: str, **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    tok = (session.get("auth") or {}).get("access")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    r = requests.request(method, url, headers=headers, timeout=TIMEOUT, **kwargs)
    logger.debug(f"[API-E] {method} {path} -> {r.status_code}")
    return r

def _ensure_entreprise_id(session: Dict[str, Any]) -> Optional[int]:
    """Récupère l’ID entreprise connecté."""
    me = api_request(session, "GET", "/api/v1/auth/entreprises/my_profile/")
    if me.status_code != 200:
        return None
    mid = (me.json() or {}).get("id")
    session.setdefault("user", {})["id"] = mid
    return mid

# -----------------------------
# Actions Boutique (ouverture/fermeture)
# -----------------------------
def toggle_boutique(session: Dict[str, Any]) -> Dict[str, Any]:
    eid = session.get("user", {}).get("id") or _ensure_entreprise_id(session)
    if not eid:
        return build_response("⚠️ Profil entreprise introuvable. Merci de vous reconnecter.", MAIN_BTNS)
    r = api_request(session, "POST", f"/api/v1/auth/entreprises/{eid}/toggle_actif/", json={})
    if r.status_code not in (200, 202):
        return build_response("😕 Impossible de changer l’état de la boutique pour le moment.", MAIN_BTNS)
    me = api_request(session, "GET", "/api/v1/auth/entreprises/my_profile/")
    actif = bool((me.json() or {}).get("actif", False)) if me.status_code == 200 else False
    return build_response(f"🏬 Boutique : {'🟢 Ouverte' if actif else '🔴 Fermée'}.", MAIN_BTNS)

# -----------------------------
# Produits
# -----------------------------
def list_my_products(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/marketplace/produits/?mine=1")
    if r.status_code != 200:
        return build_response("⚠️ Erreur lors du chargement de vos produits. Réessayez un peu plus tard.", MAIN_BTNS)
    arr = r.json() or []
    if isinstance(arr, dict) and "results" in arr:
        arr = arr["results"]
    if not arr:
        return build_response(
            "📦 Aucun produit publié.\n👉 Tapez *Créer produit* pour ajouter un article.",
            _btns("Créer produit","Commandes","Menu")
        )
    lines = []
    for p in arr[:5]:
        pid   = p.get("id")
        nom   = p.get("nom") or p.get("name") or f"Produit {pid}"
        prix  = _fmt_xaf(p.get("prix") or p.get("price") or 0)
        stock = p.get("stock", "-")
        actif = "✅" if p.get("actif", True) else "⛔"
        lines.append(f"#{pid} • {nom} • {prix} XAF • Stock {stock} {actif}")
    return build_response(
        "🗂️ *Mes produits*\n" + "\n".join(lines) + "\n\n👉 *Détail <id>* ou *Edit <id>*",
        _btns("Créer produit","Commandes","Menu")
    )

def product_detail(session: Dict[str, Any], pid: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/marketplace/produits/{pid}/")
    if r.status_code != 200:
        return build_response("❌ Produit introuvable.", MAIN_BTNS)
    p = r.json() or {}
    txt = (
        f"📄 *Produit #{p.get('id','—')}*\n"
        f"• Nom : {p.get('nom') or p.get('name','—')}\n"
        f"• Prix : {_fmt_xaf(p.get('prix') or p.get('price', 0))} XAF\n"
        f"• Catégorie : {p.get('categorie') or p.get('category','—')}\n"
        f"• Stock : {p.get('stock','—')}\n"
        f"• Actif : {'Oui' if p.get('actif', True) else 'Non'}\n"
        f"• Description : {p.get('description','—')}\n"
    )
    session.setdefault("ctx", {})["current_product_id"] = p.get("id")
    return build_response(txt, _btns("Mettre à jour","Mes produits","Menu"))

def product_patch(session: Dict[str, Any], pid: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "PATCH", f"/api/v1/marketplace/produits/{pid}/", json=fields)
    if r.status_code not in (200, 202):
        return build_response("😕 Mise à jour du produit impossible pour le moment.", _btns("Mes produits","Menu"))
    return product_detail(session, pid)

# ---------- Wizard création produit ----------
def create_start(session: Dict[str, Any]) -> Dict[str, Any]:
    session["step"] = "PROD_NAME"
    session.setdefault("ctx", {})["new_product"] = {
        "nom": None, "prix": None, "categorie_id": None, "stock": None,
        "description": None, "image_url": None, "actif": True,
    }
    return build_response("🆕 *Création produit* — Quel est le *nom* de l’article ?")

def handle_create_wizard(session: Dict[str, Any], t: str, media_url: Optional[str]) -> Dict[str, Any]:
    np = session["ctx"]["new_product"]
    step = session["step"]
    tt = (normalize(t) or "").strip()

    if step == "PROD_NAME":
        if not tt:
            return build_response("⚠️ Entrez un nom de produit.")
        np["nom"] = tt
        session["step"] = "PROD_PRICE"
        return build_response("💰 *Prix* (XAF) ? (ex. `4500`)")

    if step == "PROD_PRICE":
        amount = re.sub(r"[^0-9]", "", tt)
        if not amount:
            return build_response("⚠️ Entrez un nombre valide. Ex. `4500`")
        np["prix"] = int(amount)
        # Charger catégories
        r = api_request(session, "GET", "/api/v1/marketplace/categories/")
        cats = []
        try:
            data = r.json()
            cats = data.get("results", []) if isinstance(data, dict) else (data or [])
        except Exception:
            cats = []
        if not cats:
            return build_response("😕 Aucune catégorie disponible pour le moment.", _btns("Annuler","Menu"))
        session["ctx"]["categories"] = {str(i+1): c for i, c in enumerate(cats)}
        session["step"] = "PROD_CATEGORY_CHOICE"
        lignes = [f"{i+1}. {c.get('nom') or c.get('name') or '—'}" for i,c in enumerate(cats)]
        btns = list(session["ctx"]["categories"].keys())[:3]
        return build_response("🏷️ Choisissez une *catégorie* :\n" + "\n".join(lignes), btns)

    if step == "PROD_CATEGORY_CHOICE":
        cats = session["ctx"].get("categories", {})
        if tt not in cats:
            btns = list(cats.keys())[:3]
            return build_response("⚠️ Choisissez un *numéro* de catégorie valide.", btns)
        np["categorie_id"] = cats[tt].get("id")
        session["step"] = "PROD_STOCK"
        return build_response("📦 *Stock* initial ? (ex. `10`)")

    if step == "PROD_STOCK":
        q = re.sub(r"[^0-9]", "", tt)
        if not q:
            return build_response("⚠️ Entrez un entier. Ex. `10`")
        np["stock"] = int(q)
        session["step"] = "PROD_DESC"
        return build_response("📝 *Description courte* ? (une phrase suffit)")

    if step == "PROD_DESC":
        np["description"] = tt or ""
        session["step"] = "PROD_IMAGE"
        return build_response("🖼️ Envoyez *une image* maintenant (ou tapez *Passer*).")

    if step == "PROD_IMAGE":
        if media_url and media_url.startswith("http"):
            np["image_url"] = media_url
        session["step"] = "PROD_CONFIRM"
        recap = (
            "🧾 *Récap produit*\n"
            f"• Nom : {np['nom']}\n"
            f"• Prix : {_fmt_xaf(np['prix'])} XAF\n"
            f"• Stock : {np['stock']}\n"
            f"• Desc : {np['description'] or '—'}\n"
            f"• Image : {'Oui' if np.get('image_url') else 'Non'}\n\n"
            "Tout est bon ?"
        )
        return build_response(recap, PRODUCT_BTNS)

    if step == "PROD_CONFIRM":
        low = tt.lower()
        if low in {"publier","creer","confirmer"}:
            return create_submit(session)
        if low in {"modifier","edit"}:
            session["step"] = "PROD_NAME"
            return build_response("✏️ Reprenons : quel est le *nom* ?")
        if low in {"annuler","cancel"}:
            session["step"] = "ENTREPRISE_MENU"
            session["ctx"].pop("new_product", None)
            return build_response("❌ Création annulée.", MAIN_BTNS)
        return build_response("👉 Répondez par *Publier*, *Modifier* ou *Annuler*.", PRODUCT_BTNS)

    return build_response("👉 Tapez *Publier* pour créer, ou *Modifier* pour reprendre.", PRODUCT_BTNS)

def create_submit(session: Dict[str, Any]) -> Dict[str, Any]:
    np = session["ctx"]["new_product"]
    eid = session.get("user", {}).get("id") or _ensure_entreprise_id(session)
    if not eid:
        return build_response("⚠️ Impossible d’identifier votre entreprise. Reconnectez-vous.", MAIN_BTNS)

    payload = {
        "nom": np["nom"],
        "prix": np["prix"],
        "categorie_id": np.get("categorie_id"),
        "stock": np["stock"],
        "description": np["description"],
        "entreprise_id": eid,
        "actif": True,
    }
    if np.get("image_url"):
        payload["image_url"] = np["image_url"]

    r = api_request(session, "POST", "/api/v1/marketplace/produits/", json=payload)
    if r.status_code not in (200, 201):
        logger.warning(f"[ENTREPRISE] create product failed: {r.status_code}")
        return build_response("😕 Échec de création du produit. Vérifiez les champs et réessayez.", _btns("Mes produits","Menu"))

    p = r.json() or {}
    prod_id  = p.get("id") or (p.get("produit") or {}).get("id")
    prod_nom = p.get("nom") or (p.get("produit") or {}).get("nom") or "Produit"

    session["step"] = "ENTREPRISE_MENU"
    session["ctx"].pop("new_product", None)

    return build_response(
        f"✅ Produit #{prod_id} *{prod_nom}* créé avec succès.",
        _btns("Mes produits", "Commandes", "Menu")
    )

# -----------------------------
# Commandes
# -----------------------------
def list_my_orders(session: Dict[str, Any]) -> Dict[str, Any]:
    r = api_request(session, "GET", "/api/v1/marketplace/commandes/?mine=1")
    if r.status_code != 200:
        return build_response("⚠️ Erreur lors du chargement des commandes. Réessayez plus tard.", MAIN_BTNS)
    arr = r.json() or []
    if isinstance(arr, dict) and "results" in arr:
        arr = arr["results"]
    if not arr:
        return build_response("📭 Aucune commande pour le moment.", MAIN_BTNS)

    lines = []
    for c in arr[:5]:
        cid    = c.get("id")
        statut = c.get("statut") or "—"
        total  = _fmt_xaf(c.get("total_xaf") or c.get("montant") or 0)
        client = (c.get("client") or {}).get("username") or c.get("client_nom") or "—"
        lines.append(f"#{cid} • {statut} • {total} XAF • {client}")
    return build_response(
        "🧾 *Mes commandes*\n" + "\n".join(lines) + "\n\n👉 *Commande <id>* pour le détail",
        _btns("Commandes","Mes produits","Menu")
    )

def order_detail(session: Dict[str, Any], cid: str) -> Dict[str, Any]:
    r = api_request(session, "GET", f"/api/v1/marketplace/commandes/{cid}/")
    if r.status_code != 200:
        return build_response("❌ Commande introuvable.", MAIN_BTNS)
    c = r.json() or {}
    items = c.get("lignes") or c.get("items") or []
    lst = []
    for it in items[:6]:
        nom = (it.get("produit") or {}).get("nom") or it.get("nom","-")
        qte = it.get("quantite") or it.get("qty") or 1
        px  = _fmt_xaf(it.get("prix_unitaire") or it.get("prix") or 0)
        lst.append(f"• {nom} x{qte} — {px} XAF")
    txt = (
        f"📄 *Commande #{c.get('id','—')}*\n"
        f"• Statut : {c.get('statut','—')}\n"
        f"• Total : {_fmt_xaf(c.get('total_xaf') or c.get('montant', 0))} XAF\n"
        f"• Client : {(c.get('client') or {}).get('username') or c.get('client_nom','—')}\n"
        f"• Adresse : {c.get('adresse_livraison','—')}\n"
        f"• Téléphone : {c.get('telephone_livraison','—')}\n"
        + ("\n".join(lst) if lst else "\n• (Aucune ligne)")
        + "\n\nActions rapides : *Accepter*, *Préparer*, *Expédier*, *Livrée*, *Annuler*"
    )
    session.setdefault("ctx", {})["current_order_id"] = c.get("id")
    return build_response(txt, ORDER_BTNS)

def order_update_status(session: Dict[str, Any], cid: str, statut: str) -> Dict[str, Any]:
    s = (statut or "").lower()
    if s == "accepter": s = "acceptee"
    if s in {"préparer","preparer"}: s = "preparee"
    if s in {"expédier","expedier"}: s = "expediee"
    if s in {"livrée","livree"}: s = "livree"
    if s == "annuler": s = "annulee"
    if s not in STATUTS_CMD:
        return build_response("❌ Statut inconnu. (Accepter / Préparer / Expédier / Livrée / Annuler)")

    r = api_request(session, "POST", f"/api/v1/marketplace/commandes/{cid}/update_statut/", json={"statut": s})
    if r.status_code not in (200, 202):
        logger.warning(f"[ENTREPRISE] update order status failed: {r.status_code}")
        return build_response("😕 Mise à jour du statut impossible pour le moment.", _btns("Commandes","Menu"))
    return build_response(f"✅ Commande #{cid} → *{s}*.", _btns("Commandes","Mes produits","Menu"))

# -----------------------------
# Router texte
# -----------------------------
def handle_message(phone: str, text: str,
                   *, lat: Optional[float] = None,
                   lng: Optional[float] = None,
                   media_url: Optional[str] = None,
                   **_) -> Dict[str, Any]:
    t = (normalize(text) or "").lower()
    session = get_session(phone)

    # Salutations / Menu
    if t in {"menu","bonjour","salut","hello","hi","accueil","entreprise"}:
        session["step"] = "ENTREPRISE_MENU"
        return build_response("🏪 *Espace entreprise* — choisissez une action :", MAIN_BTNS)

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
        part = t.split(" ",1)[1] if " " in t else ""
        pid = re.sub(r"[^0-9]", "", part)
        if not pid:
            return build_response("❌ Id manquant. Ex. *Détail 123*")
        return product_detail(session, pid)

    if t.startswith("edit "):
        part = t.split(" ",1)[1] if " " in t else ""
        pid = re.sub(r"[^0-9]", "", part)
        if not pid:
            return build_response("❌ Id manquant. Ex. *Edit 123*")
        session.setdefault("ctx", {})["current_product_id"] = int(pid)
        session["step"] = "PROD_EDIT_FIELD"
        return build_response("✏️ Quel champ modifier ? (*prix*, *stock*, *nom*, *description*, *categorie*)")

    # Wizard (création & édition)
    if session.get("step") in {
        "PROD_NAME","PROD_PRICE","PROD_CATEGORY","PROD_CATEGORY_CHOICE",
        "PROD_STOCK","PROD_DESC","PROD_IMAGE","PROD_CONFIRM"
    }:
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
            return build_response("⚠️ Contexte perdu. Reprenez avec *Mes produits*.", MAIN_BTNS)
        value: Any = text
        if field in {"prix","stock"}:
            num = re.sub(r"[^0-9]", "", text or "")
            if not num:
                return build_response("⚠️ Entrez un nombre valide.")
            value = int(num)
        fields = {"prix": "prix", "stock": "stock", "nom": "nom", "description": "description", "categorie": "categorie_id"}
        session["step"] = "ENTREPRISE_MENU"
        return product_patch(session, str(pid), {fields[field]: value})

    # Commandes
    if t in {"commandes","mes commandes"}:
        return list_my_orders(session)

    if t.startswith("commande "):
        part = t.split(" ",1)[1] if " " in t else ""
        cid = re.sub(r"[^0-9]", "", part)
        if not cid:
            return build_response("❌ Id manquant. Ex. *Commande 123*")
        return order_detail(session, cid)

    if t in {"accepter","préparer","preparer","expédier","expedier","livrée","livree","annuler"}:
        cid = (session.get("ctx") or {}).get("current_order_id")
        if not cid:
            return build_response("⚠️ Aucune commande sélectionnée. Envoyez d’abord *Commande <id>*.", _btns("Commandes","Menu"))
        return order_update_status(session, str(cid), t)

    # Aide
    return build_response(
        "ℹ️ Commandes : *Commandes*, *Commande <id>*, *Accepter/Préparer/Expédier/Livrée/Annuler*\n"
        "ℹ️ Produits : *Créer produit*, *Mes produits*, *Détail <id>*, *Edit <id>*\n"
        "ℹ️ Boutique : *Basculer* (Ouvert/Fermé)\n"
        "👉 Tapez *menu* pour revenir.",
        _btns("Mes produits","Commandes","Menu")
    )
