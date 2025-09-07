# router.py
from __future__ import annotations
import logging, time
from typing import Dict, Any, Optional
from .auth_core import get_session, ensure_auth_or_ask_password

# Tes flows
#import .conversation_flow
from .import livreur_Flow        # livreur
from .import merchant_flow       # marchand
from .import conversation_flow   # client

logger = logging.getLogger(__name__)

ROLE_TO_FLOW = {
    "client": conversation_flow,
    "livreur": livreur_Flow,
    "marchand": merchant_flow,
}

def _mask_phone(p: str, visible: int = 3) -> str:
    if not p: return ""
    if len(p) <= visible * 2:
        return "*" * len(p)
    return p[:visible] + "****" + p[-visible:]

def _log_event(stage: str, phone: str, meta: Dict[str, Any]) -> None:
    """
    stage ∈ {"incoming","auth_prompt","auth_ok","auth_fail","signup","dispatch","flow_resp","error"}
    meta peut contenir: msg_id, ts, type, role, step, text, buttons_count, flow
    """
    safe = {**meta}
    if "text" in safe:
        # évite log des mdp: nous ne mettons pas le texte quand step == LOGIN_WAIT_PASSWORD
        if safe.get("step") == "LOGIN_WAIT_PASSWORD":
            safe["text"] = "[REDACTED]"
        else:
            safe["text"] = str(safe["text"])[:200]
    safe["phone"] = _mask_phone(phone)
    logger.info(f"[ROUTER] {stage} | {safe}")

def handle_incoming(phone: str,
                    text: str,
                    *,
                    lat: Optional[float] = None,
                    lng: Optional[float] = None,
                    media_url: Optional[str] = None,
                    # métadonnées WhatsApp optionnelles:
                    wa_message_id: Optional[str] = None,
                    wa_timestamp: Optional[int] = None,
                    wa_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Point d’entrée unique :
    1) Auth commune (Connexion / Inscription)
    2) Dispatch vers le flow selon rôle
    3) Logging détaillé
    """
    t0 = time.time()
    session = get_session(phone)

    _log_event("incoming", phone, {
        "msg_id": wa_message_id, "ts": wa_timestamp, "type": wa_type,
        "step": session.get("step"), "text": text
    })

    # 1) Auth commune (peut retourner un message à afficher si non connecté / en signup)
    maybe = ensure_auth_or_ask_password(phone, text)
    if maybe is not None:
        _log_event("auth_prompt", phone, {
            "step": session.get("step"), "resp_preview": (maybe.get("response","")[:120]),
            "buttons_count": len(maybe.get("buttons", []))
        })
        return maybe

    # À ce stade, user connecté
    role = (session.get("user") or {}).get("role") or "client"
    flow = ROLE_TO_FLOW.get(role, conversation_flow)
    _log_event("dispatch", phone, {"role": role, "flow": flow.__name__, "step": session.get("step")})

    # 2) Dispatch au flow
    try:
        resp = flow.handle_message(phone, text, lat=lat, lng=lng, media_url=media_url)
        _log_event("flow_resp", phone, {
            "role": role, "flow": flow.__name__,
            "resp_preview": (resp.get("response","")[:120]),
            "buttons_count": len(resp.get("buttons", [])),
            "elapsed_ms": int((time.time()-t0)*1000)
        })
        return resp
    except Exception as e:
        _log_event("error", phone, {"role": role, "flow": flow.__name__, "err": str(e)})
        return {"response": "❌ Erreur interne.", "buttons": ["Menu"]}
