# chatbot/router.py
from __future__ import annotations
import importlib, inspect, logging, time
from typing import Dict, Any, Optional
from .auth_core import get_session, ensure_auth_or_ask_password

logger = logging.getLogger("toktok.router")

# On ne l'utilise plus pour le "client" car on dispatchera manuellement selon le step
FLOW_MAP: Dict[str, str] = {
    "livreur": "chatbot.livreur_flow",
    "entreprise": "chatbot.merchant_flow",
    "marchand": "chatbot.merchant_flow",
    # "client" n'apparaît pas ici car on gère lui-même les deux flows dans "client"
}


def _import_handle(module_path: str):
    """Importe le module et renvoie la fonction handle_message(module)."""
    m = importlib.import_module(module_path)
    return getattr(m, "handle_message"), m


def _call_with_supported_args(fn, *args, **kwargs):
    """
    Appelle fn en ne passant que les kwargs supportés par sa signature.
    Évite TypeError: unexpected keyword argument 'lat' / 'lng'.
    """
    sig = inspect.signature(fn)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(*args, **kwargs)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(*args, **allowed)


def _mask_phone(p: str, visible: int = 3) -> str:
    if not p:
        return ""
    return p if len(p) <= visible * 2 else (p[:visible] + "****" + p[-visible:])


def _log_event(stage: str, phone: str, meta: Dict[str, Any]) -> None:
    safe = dict(meta or {})
    if "text" in safe:
        if safe.get("step") == "LOGIN_WAIT_PASSWORD":
            safe["text"] = "[REDACTED]"
        else:
            safe["text"] = str(safe["text"])[:200]
    safe["phone"] = _mask_phone(phone)
    logger.info(f"[ROUTER] {stage} | {safe}")


def handle_incoming(
        phone: str,
        text: str,
        *,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        media_url: Optional[str] = None,
        wa_message_id: Optional[str] = None,
        wa_timestamp: Optional[int] = None,
        wa_type: Optional[str] = None,
) -> Dict[str, Any]:
    t0 = time.time()
    session = get_session(phone)

    _log_event("incoming", phone, {
        "msg_id": wa_message_id,
        "ts": wa_timestamp,
        "type": wa_type,
        "step": session.get("step"),
        "text": text,
    })

    # 1) Auth commune
    maybe = ensure_auth_or_ask_password(phone, text)
    if maybe is not None:
        _log_event("auth_prompt", phone, {
            "step": session.get("step"),
            "resp_preview": str(maybe.get("response", ""))[:120],
            "buttons_count": len(maybe.get("buttons", [])),
        })
        return maybe

    # 2) On est authentifié — dispatch selon rôle ou selon step "marketplace" ou non
    role = (session.get("user") or {}).get("role") or "client"

    # Si ce n'est pas "client", on peut utiliser FLOW_MAP directement
    if role != "client" and role in FLOW_MAP:
        module_path = FLOW_MAP[role]
        handle_fn, mod = _import_handle(module_path)
        _log_event("dispatch", phone, {
            "role": role,
            "flow": getattr(mod, "__name__", module_path),
            "step": session.get("step"),
        })
        try:
            resp = _call_with_supported_args(
                handle_fn,
                phone,
                text,
                lat=lat,
                lng=lng,
                media_url=media_url,
            )
            _log_event("flow_resp", phone, {
                "role": role,
                "flow": getattr(mod, "__name__", module_path),
                "resp_preview": str((resp or {}).get("response", ""))[:120],
                "buttons_count": len((resp or {}).get("buttons", [])),
                "elapsed_ms": int((time.time() - t0) * 1000),
            })
            return resp if isinstance(resp, dict) else {"response": "❌ Erreur interne.", "buttons": ["Menu"]}
        except Exception as e:
            _log_event("error", phone, {
                "role": role,
                "flow": getattr(mod, "__name__", module_path),
                "err": str(e),
            })
            return {"response": "❌ Erreur interne.", "buttons": ["Menu"]}

    # Si rôle = client, on décide manuellement entre coursier / marketplace
    # Importer les deux handlers
    from .conversation_flow_coursier import handle_message as handle_coursier
    from .conversation_flow_marketplace import handle_message as handle_marketplace

    # on log le dispatch
    _log_event("dispatch", phone, {
        "role": role,
        "flow": "client_flow_dispatch",
        "step": session.get("step"),
    })

    # CORRECTION: Liste complète et correcte des étapes marketplace
    marketplace_steps = {
        "MARKET_CATEGORY",
        "MARKET_MERCHANT",
        "MARKET_PRODUCTS",
        "MARKET_DESTINATION",  # ← AJOUTÉ (c'était manquant)
        "MARKET_PAY",
        "MARKET_CONFIRM",
        "MARKET_EDIT"
        # Supprimé les anciennes étapes incorrectes:
        # "MARKETPLACE_LOCATION", "DEST_NOM", "DEST_TEL"
    }

    # Conditions pour aller vers marketplace
    tnorm = (text or "").lower().strip()
    current_step = session.get("step")

    # Debug log pour comprendre le routage
    logger.debug(
        f"[ROUTER-DEBUG] current_step='{current_step}', text='{tnorm}', is_marketplace_step={current_step in marketplace_steps}")

    # Si l'utilisateur a tapé "marketplace" ou on est déjà dans un flow marketplace
    if tnorm in {"marketplace", "3"} or current_step in marketplace_steps:
        # appeler le flow marketplace
        try:
            resp = _call_with_supported_args(handle_marketplace, phone, text, lat=lat, lng=lng)
            _log_event("flow_resp", phone, {
                "role": role,
                "flow": "marketplace",
                "resp_preview": str(resp.get("response", ""))[:120],
                "buttons_count": len(resp.get("buttons", [])),
                "elapsed_ms": int((time.time() - t0) * 1000),
            })
            return resp
        except Exception as e:
            logger.error(f"[ROUTER] Erreur marketplace: {e}")
            _log_event("error", phone, {
                "role": role,
                "flow": "marketplace",
                "err": str(e),
            })
            # Fallback vers coursier en cas d'erreur
            resp = _call_with_supported_args(handle_coursier, phone, text, lat=lat, lng=lng)
            _log_event("flow_resp", phone, {
                "role": role,
                "flow": "coursier_fallback",
                "resp_preview": str(resp.get("response", ""))[:120],
            })
            return resp

    # Sinon, on appelle le flow coursier
    try:
        resp = _call_with_supported_args(handle_coursier, phone, text, lat=lat, lng=lng)
        _log_event("flow_resp", phone, {
            "role": role,
            "flow": "coursier",
            "resp_preview": str(resp.get("response", ""))[:120],
            "buttons_count": len(resp.get("buttons", [])),
            "elapsed_ms": int((time.time() - t0) * 1000),
        })
        return resp
    except Exception as e:
        logger.error(f"[ROUTER] Erreur coursier: {e}")
        _log_event("error", phone, {
            "role": role,
            "flow": "coursier",
            "err": str(e),
        })
        return {"response": "❌ Erreur interne.", "buttons": ["Menu"]}