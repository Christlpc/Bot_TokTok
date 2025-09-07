# merchant_flow.py
# -*- coding: utf-8 -*-
"""
Merchant (Entreprise) conversation flow for TokTok Delivery (Marketplace side).
- Compatible with a WhatsApp webhook handler.
- Uses the Delivery Platform API (OpenAPI 3, Congo) endpoints found in /api/v1.
- Keeps UI minimal (buttons/options) for WhatsApp UX.

Assumptions
-----------
- A session store exists (dict-like) keyed by phone (or WA user id).
- A `send_whatsapp_message(to, text)` util exists (see utils.py provided by user).
- ENV variables: TOKTOK_BASE_URL, TOKTOK_API_KEY (optional), WHATSAPP_* already configured.
- This module exposes:
    - handle_merchant_message(phone: str, text: str) -> dict(response, buttons)
    - start_merchant_login(phone: str) -> dict(...)
    - reset_merchant_session(phone: str) -> None

Author: Projet TokTok (GPT Assistant)
"""
from __future__ import annotations
import os, re, json, logging, requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

API_BASE = os.getenv("TOKTOK_BASE_URL", "https://toktok-bsfz.onrender.com").rstrip("/")
API_KEY  = os.getenv("TOKTOK_API_KEY", "")  # Optional header if your API uses it

# -------------------------------
# Simple in-memory session store
# -------------------------------
_SESS: Dict[str, Dict[str, Any]] = {}

def _S(phone: str) -> Dict[str, Any]:
    s = _SESS.get(phone) or {}
    _SESS[phone] = s
    s.setdefault("role", "merchant")
    s.setdefault("auth", {"access": None})
    s.setdefault("state", "INIT")
    s.setdefault("tmp", {})
    return s

def reset_merchant_session(phone: str) -> None:
    _SESS.pop(phone, None)

# -------------------------------
# Helpers
# -------------------------------
def normalize(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def build_response(text: str, buttons: Optional[List[str]] = None) -> Dict[str, Any]:
    r = {"response": text}
    if buttons:
        r["buttons"] = buttons
    return r

def _auth_headers(token: Optional[str] = None) -> Dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-KEY"] = API_KEY
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _r(method: str, path: str, token: Optional[str] = None, **kwargs) -> requests.Response:
    url = f"{API_BASE}{path}"
    headers = kwargs.pop("headers", {})
    headers.update(_auth_headers(token))
    resp = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    # Log and raise if necessary
    try:
        j = resp.json()
        logger.debug("API %s %s -> %s", method, path, json.dumps(j)[:500])
    except Exception:
        logger.debug("API %s %s -> %s", method, path, resp.text[:300])
    if not resp.ok:
        raise requests.HTTPError(f"{resp.status_code} {resp.reason}: {resp.text}")
    return resp

# -------------------------------
# API Client (subset for merchants)
# -------------------------------
class MerchantAPI:
    @staticmethod
    def login(email: str, password: str) -> Dict[str, Any]:
        # POST /api/v1/auth/login/
        payload = {"email": email, "password": password}
        r = _r("POST", "/api/v1/auth/login/", json=payload)
        return r.json()  # expects access, refresh, user info

    @staticmethod
    def my_profile(token: str) -> Dict[str, Any]:
        # GET /api/v1/auth/entreprises/my_profile/
        r = _r("GET", "/api/v1/auth/entreprises/my_profile/", token=token)
        return r.json()

    # Products
    @staticmethod
    def list_categories(token: str) -> List[Dict[str, Any]]:
        r = _r("GET", "/api/v1/marketplace/categories/", token=token)
        return r.json().get("results", []) if isinstance(r.json(), dict) else r.json()

    @staticmethod
    def list_products(token: str, page: int = 1, page_size: int = 10) -> Dict[str, Any]:
        params = {"page": page, "page_size": page_size}
        r = _r("GET", "/api/v1/marketplace/produits/", token=token, params=params)
        return r.json()

    @staticmethod
    def create_product(token: str, nom: str, prix: float, categorie_id: int, description: str = "", stock: int = 0) -> Dict[str, Any]:
        payload = {
            "nom": nom,
            "prix": prix,
            "categorie_id": categorie_id,
            "description": description,
            "stock": stock,
        }
        r = _r("POST", "/api/v1/marketplace/produits/", token=token, json=payload)
        return r.json()

    @staticmethod
    def update_product(token: str, produit_id: int, **fields) -> Dict[str, Any]:
        r = _r("PATCH", f"/api/v1/marketplace/produits/{produit_id}/", token=token, json=fields)
        return r.json()

    @staticmethod
    def delete_product(token: str, produit_id: int) -> None:
        _r("DELETE", f"/api/v1/marketplace/produits/{produit_id}/", token=token)

    @staticmethod
    def update_stock(token: str, produit_id: int, stock: int) -> Dict[str, Any]:
        payload = {"stock": stock}
        r = _r("POST", f"/api/v1/marketplace/produits/{produit_id}/update_stock/", token=token, json=payload)
        return r.json()

    # Orders
    @staticmethod
    def list_orders(token: str, statut: Optional[str] = None, only_mine: bool = True) -> Dict[str, Any]:
        path = "/api/v1/marketplace/commandes/mes_commandes/" if only_mine else "/api/v1/marketplace/commandes/"
        params = {"statut": statut} if statut else {}
        r = _r("GET", path, token=token, params=params)
        return r.json()

    @staticmethod
    def confirm_order(token: str, commande_id: int) -> Dict[str, Any]:
        r = _r("POST", f"/api/v1/marketplace/commandes/{commande_id}/confirmer/", token=token, json={})
        return r.json()

    @staticmethod
    def cancel_order(token: str, commande_id: int, motif: str = "") -> Dict[str, Any]:
        payload = {"motif": motif}
        r = _r("POST", f"/api/v1/marketplace/commandes/{commande_id}/annuler/", token=token, json=payload)
        return r.json()

    # Stats (optional nice-to-have)
    @staticmethod
    def revenus_resume(token: str) -> Dict[str, Any]:
        r = _r("GET", "/api/v1/paiements/revenus/resume_mensuel/", token=token)
        return r.json()

# -------------------------------
# Conversation Flow (State Machine)
# -------------------------------
WELCOME = (
    "👋 *TokTok Marchands* \n"
    "Gérez vos *commandes* et *produits* directement ici.\n"
    "Veuillez vous *connecter* pour continuer."
)
MENU = [
    "📦 Commandes",
    "🛍️ Produits",
    "📊 Statistiques",
    "⚙️ Paramètres",
    "🚪 Déconnexion",
]

def start_merchant_login(phone: str) -> Dict[str, Any]:
    s = _S(phone)
    s["state"] = "LOGIN_EMAIL"
    return build_response(
        "🔐 Connexion marchand\nEntrez votre *email* :",
        buttons=None
    )

def _ensure_auth(phone: str) -> Optional[str]:
    s = _S(phone)
    token = s.get("auth", {}).get("access")
    return token

def _goto_menu(phone: str) -> Dict[str, Any]:
    s = _S(phone)
    s["state"] = "MENU"
    return build_response("✅ Connecté. Que souhaitez-vous faire ?", MENU)

def _format_orders_list(payload: Dict[str, Any]) -> str:
    items = payload.get("results") if isinstance(payload, dict) else payload
    if not items:
        return "Aucune commande trouvée."
    lines = []
    for cmd in items[:10]:
        cid = cmd.get("id")
        statut = cmd.get("statut", "inconnu")
        total = cmd.get("total", "—")
        client = (cmd.get("client") or {}).get("nom", "Client")
        lines.append(f"• #{cid} – {client} – {total} – {statut}")
    return "\n".join(lines)

def _format_products_list(payload: Dict[str, Any]) -> str:
    items = payload.get("results") if isinstance(payload, dict) else payload
    if not items:
        return "Aucun produit."
    lines = []
    for p in items[:10]:
        lines.append(f"• [{p.get('id')}] {p.get('nom')} – {p.get('prix')} FCFA – stock:{p.get('stock', 0)}")
    return "\n".join(lines)

def handle_merchant_message(phone: str, text: str) -> Dict[str, Any]:
    text_n = normalize(text).lower()
    s = _S(phone)

    # Entry points
    if s["state"] == "INIT":
        return build_response(WELCOME, ["🔑 Connexion"])

    if text_n in ("connexion", "🔑 connexion"):
        return start_merchant_login(phone)

    # Login flow
    if s["state"] == "LOGIN_EMAIL":
        s["tmp"]["email"] = normalize(text)
        s["state"] = "LOGIN_PASSWORD"
        return build_response("Entrez votre *mot de passe* :", None)

    if s["state"] == "LOGIN_PASSWORD":
        email = s["tmp"].get("email")
        password = text
        try:
            auth = MerchantAPI.login(email, password)
            s["auth"]["access"] = auth.get("access")
            s["state"] = "MENU"
            return _goto_menu(phone)
        except Exception as e:
            logger.exception("Login failed")
            s["state"] = "INIT"
            return build_response("❌ Échec de connexion. Réessayez : 'Connexion'", ["🔑 Connexion"])

    # Require auth afterward
    token = _ensure_auth(phone)
    if not token:
        return build_response("Session expirée. Veuillez vous reconnecter.", ["🔑 Connexion"])

    # Menu routing
    if s["state"] == "MENU":
        if text_n.startswith("📦") or "commande" in text_n:
            s["state"] = "ORDERS_MENU"
            return build_response("📦 *Commandes* – choisissez :", ["En attente", "En cours", "Historique", "⬅️ Retour"])
        if text_n.startswith("🛍️") or "produit" in text_n:
            s["state"] = "PRODUCTS_MENU"
            return build_response("🛍️ *Produits* – choisissez :", ["Lister", "Ajouter", "Modifier", "Supprimer", "Stock", "⬅️ Retour"])
        if text_n.startswith("📊") or "stat" in text_n:
            try:
                stats = MerchantAPI.revenus_resume(token)
                txt = f"📊 *Revenus (mois)*\nTotal: {stats.get('total', '—')} FCFA\nCommandes: {stats.get('nb_commandes', '—')}"
            except Exception:
                txt = "📊 Statistiques indisponibles pour le moment."
            return build_response(txt, ["⬅️ Retour"])
        if text_n.startswith("⚙️") or "param" in text_n:
            return build_response("⚙️ Paramètres (à gérer dans le backoffice pour l’instant).", ["⬅️ Retour"])
        if text_n.startswith("🚪") or "deconn" in text_n:
            reset_merchant_session(phone)
            return build_response("Vous êtes déconnecté.", ["🔑 Connexion"])
        # default
        return build_response("Choisissez une option :", MENU)

    # Orders sub-flow
    if s["state"] == "ORDERS_MENU":
        if text_n.startswith("en attente"):
            try:
                data = MerchantAPI.list_orders(token, statut="en_attente")
                lst = _format_orders_list(data)
                s["state"] = "ORDERS_ACTION"
                return build_response(f"🟡 *En attente*\n{lst}\n\nAction ? (ex: `confirmer 123` ou `annuler 123 raison`)",
                                      ["⬅️ Retour", "↻ Rafraîchir"])
            except Exception:
                return build_response("Erreur lors du chargement des commandes.", ["⬅️ Retour"])
        if text_n.startswith("en cours"):
            try:
                data = MerchantAPI.list_orders(token, statut="en_cours")
                lst = _format_orders_list(data)
                s["state"] = "ORDERS_ACTION"
                return build_response(f"🔵 *En cours*\n{lst}\n\nAction ? (ex: `confirmer 123`)",
                                      ["⬅️ Retour", "↻ Rafraîchir"])
            except Exception:
                return build_response("Erreur lors du chargement des commandes.", ["⬅️ Retour"])
        if text_n.startswith("historique"):
            try:
                data = MerchantAPI.list_orders(token, statut="livree", only_mine=True)
                lst = _format_orders_list(data)
                s["state"] = "ORDERS_ACTION"
                return build_response(f"✅ *Historique livrées*\n{lst}", ["⬅️ Retour"])
            except Exception:
                return build_response("Erreur lors du chargement de l’historique.", ["⬅️ Retour"])
        if "retour" in text_n:
            s["state"] = "MENU"
            return _goto_menu(phone)

    if s["state"] == "ORDERS_ACTION":
        if text_n.startswith("↻"):
            s["state"] = "ORDERS_MENU"
            return build_response("Rafraîchi. Choisissez :", ["En attente", "En cours", "Historique", "⬅️ Retour"])
        if text_n.startswith("confirmer"):
            m = re.search(r"confirmer\s+(\d+)", text_n)
            if not m:
                return build_response("Format attendu: `confirmer <id>`", ["⬅️ Retour"])
            cid = int(m.group(1))
            try:
                res = MerchantAPI.confirm_order(token, cid)
                return build_response(f"✅ Commande #{cid} confirmée.\nUn livreur sera assigné automatiquement.", ["⬅️ Retour", "↻ Rafraîchir"])
            except Exception:
                return build_response("❌ Échec confirmation.", ["⬅️ Retour"])
        if text_n.startswith("annuler"):
            m = re.search(r"annuler\s+(\d+)\s*(.*)", text_n)
            if not m:
                return build_response("Format attendu: `annuler <id> <motif>`", ["⬅️ Retour"])
            cid = int(m.group(1)); motif = m.group(2) or "Non précisé"
            try:
                res = MerchantAPI.cancel_order(token, cid, motif)
                return build_response(f"🛑 Commande #{cid} annulée.", ["⬅️ Retour", "↻ Rafraîchir"])
            except Exception:
                return build_response("❌ Échec annulation.", ["⬅️ Retour"])
        if "retour" in text_n:
            s["state"] = "ORDERS_MENU"
            return build_response("Choisissez :", ["En attente", "En cours", "Historique", "⬅️ Retour"])

    # Products sub-flow
    if s["state"] == "PRODUCTS_MENU":
        if text_n.startswith("lister"):
            try:
                data = MerchantAPI.list_products(token)
                lst = _format_products_list(data)
                s["state"] = "PRODUCTS_MENU"
                return build_response(f"📋 *Produits*\n{lst}", ["Ajouter", "Modifier", "Supprimer", "Stock", "⬅️ Retour"])
            except Exception:
                return build_response("Erreur lors du listing produits.", ["⬅️ Retour"])
        if text_n.startswith("ajouter"):
            s["state"] = "PRODUCT_ADD_NAME"
            s["tmp"] = {}
            return build_response("Nom du produit ?", None)
        if text_n.startswith("modifier"):
            s["state"] = "PRODUCT_EDIT_ID"
            return build_response("ID du produit à modifier ?", None)
        if text_n.startswith("supprimer"):
            s["state"] = "PRODUCT_DELETE_ID"
            return build_response("ID du produit à supprimer ?", None)
        if text_n.startswith("stock"):
            s["state"] = "PRODUCT_STOCK_ID"
            return build_response("ID du produit pour mise à jour du stock ?", None)
        if "retour" in text_n:
            s["state"] = "MENU"
            return _goto_menu(phone)

    if s["state"] == "PRODUCT_ADD_NAME":
        s["tmp"]["nom"] = normalize(text)
        s["state"] = "PRODUCT_ADD_PRICE"
        return build_response("Prix (en FCFA) ?", None)

    if s["state"] == "PRODUCT_ADD_PRICE":
        # Accept formats: 80000, 80 000, 80.000
        price_txt = normalize(text).replace(" ", "").replace(".", "")
        if not price_txt.isdigit():
            return build_response("Montant invalide. Exemple: 80 000", None)
        s["tmp"]["prix"] = float(price_txt)
        # load categories quick
        try:
            cats = MerchantAPI.list_categories(_ensure_auth(phone))
            s["tmp"]["_cats"] = {str(c.get("id")): c.get("nom") for c in cats}
            cats_list = ", ".join([f"{cid}:{name}" for cid, name in list(s['tmp']['_cats'].items())[:10]])
            s["state"] = "PRODUCT_ADD_CATEGORY"
            return build_response(f"ID Catégorie ? (ex: {cats_list})", None)
        except Exception:
            s["state"] = "PRODUCT_ADD_CATEGORY"
            return build_response("ID Catégorie ?", None)

    if s["state"] == "PRODUCT_ADD_CATEGORY":
        cat = normalize(text)
        s["tmp"]["categorie_id"] = int(re.sub(r"[^0-9]", "", cat) or "0")
        s["state"] = "PRODUCT_ADD_DESC"
        return build_response("Description (optionnel) ?", None)

    if s["state"] == "PRODUCT_ADD_DESC":
        s["tmp"]["description"] = normalize(text)
        s["state"] = "PRODUCT_ADD_STOCK"
        return build_response("Stock initial (nombre) ?", None)

    if s["state"] == "PRODUCT_ADD_STOCK":
        stock_txt = re.sub(r"[^0-9]", "", normalize(text))
        if not stock_txt:
            stock = 0
        else:
            stock = int(stock_txt)
        try:
            token = _ensure_auth(phone)
            created = MerchantAPI.create_product(token, s["tmp"]["nom"], s["tmp"]["prix"], s["tmp"]["categorie_id"], s["tmp"]["description"], stock)
            s["state"] = "PRODUCTS_MENU"
            return build_response(f"✅ Produit créé: [{created.get('id')}] {created.get('nom')}", ["Lister", "Ajouter", "Modifier", "Supprimer", "Stock", "⬅️ Retour"])
        except Exception as e:
            logger.exception("create_product failed")
            s["state"] = "PRODUCTS_MENU"
            return build_response("❌ Échec création produit.", ["Lister", "Ajouter", "⬅️ Retour"])

    if s["state"] == "PRODUCT_EDIT_ID":
        pid_txt = re.sub(r"[^0-9]", "", normalize(text))
        if not pid_txt:
            return build_response("ID invalide.", ["⬅️ Retour"])
        s["tmp"]["pid"] = int(pid_txt)
        s["state"] = "PRODUCT_EDIT_FIELD"
        return build_response("Quel champ ? (nom / prix / description / categorie_id)", None)

    if s["state"] == "PRODUCT_EDIT_FIELD":
        field = normalize(text).lower()
        if field not in ("nom","prix","description","categorie_id"):
            return build_response("Champ invalide. Choisissez: nom / prix / description / categorie_id", None)
        s["tmp"]["field"] = field
        s["state"] = "PRODUCT_EDIT_VALUE"
        return build_response(f"Nouvelle valeur pour *{field}* ?", None)

    if s["state"] == "PRODUCT_EDIT_VALUE":
        field = s["tmp"]["field"]
        val = normalize(text)
        try:
            token = _ensure_auth(phone)
            pid = s["tmp"]["pid"]
            payload = {}
            if field == "prix":
                val = float(val.replace(" ","").replace(".",""))
            if field == "categorie_id":
                val = int(re.sub(r"[^0-9]", "", val) or "0")
            payload[field] = val
            updated = MerchantAPI.update_product(token, pid, **payload)
            s["state"] = "PRODUCTS_MENU"
            return build_response(f"✅ Produit [{pid}] mis à jour.", ["Lister", "Ajouter", "Modifier", "Supprimer", "Stock", "⬅️ Retour"])
        except Exception:
            return build_response("❌ Échec modification.", ["⬅️ Retour"])

    if s["state"] == "PRODUCT_DELETE_ID":
        pid_txt = re.sub(r"[^0-9]", "", normalize(text))
        if not pid_txt:
            return build_response("ID invalide.", ["⬅️ Retour"])
        pid = int(pid_txt)
        try:
            MerchantAPI.delete_product(token, pid)
            s["state"] = "PRODUCTS_MENU"
            return build_response(f"🗑️ Produit [{pid}] supprimé.", ["Lister", "Ajouter", "Modifier", "Supprimer", "Stock", "⬅️ Retour"])
        except Exception:
            return build_response("❌ Échec suppression.", ["⬅️ Retour"])

    if s["state"] == "PRODUCT_STOCK_ID":
        pid_txt = re.sub(r"[^0-9]", "", normalize(text))
        if not pid_txt:
            return build_response("ID invalide.", ["⬅️ Retour"])
        s["tmp"]["pid"] = int(pid_txt)
        s["state"] = "PRODUCT_STOCK_VALUE"
        return build_response("Nouveau stock (nombre) ?", None)

    if s["state"] == "PRODUCT_STOCK_VALUE":
        qty_txt = re.sub(r"[^0-9]", "", normalize(text))
        if not qty_txt:
            return build_response("Valeur invalide.", ["⬅️ Retour"])
        qty = int(qty_txt)
        try:
            pid = s["tmp"]["pid"]
            MerchantAPI.update_stock(token, pid, qty)
            s["state"] = "PRODUCTS_MENU"
            return build_response(f"📦 Stock de [{pid}] mis à jour: {qty}", ["Lister", "Ajouter", "Modifier", "Supprimer", "Stock", "⬅️ Retour"])
        except Exception:
            return build_response("❌ Échec mise à jour stock.", ["⬅️ Retour"])

    # Fallback
    return build_response("Je n'ai pas compris. Reprenez depuis le menu :", MENU)
