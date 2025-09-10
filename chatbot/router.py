# chatbot/router.py
from __future__ import annotations
import importlib, inspect, logging, time
from typing import Dict, Any, Optional
from .auth_core import get_session, ensure_auth_or_ask_password

logger = logging.getLogger("toktok.router")

# Map rôle -> chemin de module (avec fallback)
FLOW_MAP: Dict[str, str] = {
    "client":     "chatbot.conversation_flow",
    "livreur":    "chatbot.livreur_flow",     # fichier livreur_flow.py
    "entreprise": "chatbot.merchant_flow",    # alias "entreprise"
    "marchand":   "chatbot.merchant_flow",    # compat
}


def _import_handle(module_path: str):
    """Importe le module et renvoie la fonction handle_message(module)."""
    m = importlib.import_module(module_path)
    return getattr(m, "handle_message"), m

def _call_with_supported_args(fn, *args, **kwargs):
    """
    Appelle fn en ne passant que les kwargs supportés par sa signature.
    Évite TypeError: unexpected keyword argument 'lat'/'lng'.
    """
    sig = inspect.signature(fn)
    # si **kwargs présent dans la signature -> on passe tout
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return fn(*args, **kwargs)
    allowed = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(*args, **allowed)

def _mask_phone(p: str, visible: int = 3) -> str:
    if not p:
        return ""
    return p if len(p) <= visible * 2 else (p[:visible] + "****" + p[-visible:])

def _log_event(stage: str, phone: str, meta: Dict[str, Any]) -> None:
    """
    stage ∈ {"incoming","auth_prompt","dispatch","flow_resp","error"}
    meta peut contenir: msg_id, ts, type, role, step, text, buttons_count, flow, elapsed_ms
    """
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
    # métadonnées WhatsApp optionnelles:
    wa_message_id: Optional[str] = None,
    wa_timestamp: Optional[int] = None,
    wa_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Point d’entrée unique :
    1) Auth commune (Connexion / Inscription)
    2) Dispatch vers le flow selon rôle
    3) Logging détaillé
    """
    t0 = time.time()
    session = get_session(phone)

    _log_event("incoming", phone, {
        "msg_id": wa_message_id,
        "ts": wa_timestamp,
        "type": wa_type,
        "step": session.get("step"),
        "text": text,
    })

    # 1) Auth commune (peut retourner un message si non connecté / wizard en cours)
    maybe = ensure_auth_or_ask_password(phone, text)
    if maybe is not None:
        _log_event("auth_prompt", phone, {
            "step": session.get("step"),
            "resp_preview": str(maybe.get("response", ""))[:120],
            "buttons_count": len(maybe.get("buttons", [])),
        })
        return maybe

    # 2) Utilisateur authentifié -> dispatch par rôle
    role = (session.get("user") or {}).get("role") or "client"
    module_path = FLOW_MAP.get(role) or FLOW_MAP["client"]

    try:
        handle_fn, mod = _import_handle(module_path)
    except Exception as e:
        logger.exception("flow_import_error", extra={"flow": module_path, "err": str(e)})
        handle_fn, mod = _import_handle(FLOW_MAP["client"])

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
        # sécurité: toujours un dict minimal
        return resp if isinstance(resp, dict) else {"response": "❌ Erreur interne.", "buttons": ["Menu"]}

    except Exception as e:
        _log_event("error", phone, {
            "role": role,
            "flow": getattr(mod, "__name__", module_path),
            "err": str(e),
        })
        return {"response": "❌ Erreur interne.", "buttons": ["Menu"]}
