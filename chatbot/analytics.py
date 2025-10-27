# chatbot/analytics.py
"""
Système d'analytics et monitoring pour TokTok Delivery
Tracking des métriques, conversions, et insights en temps réel
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from collections import defaultdict, Counter
import json

logger = logging.getLogger(__name__)


class AnalyticsTracker:
    """
    Tracker centralisé pour toutes les métriques du chatbot
    En production, utiliser Redis ou une vraie DB pour la persistance
    """
    
    def __init__(self):
        # Métriques en mémoire (remplacer par Redis en prod)
        self.sessions = {}  # phone -> session_data
        self.events = []  # Liste des événements
        self.metrics = defaultdict(int)  # Compteurs globaux
        self.conversions = defaultdict(list)  # Conversions par type
        self.response_times = []  # Temps de réponse
        self.errors = []  # Erreurs rencontrées
        
    def track_session_start(self, phone: str, role: str = "client"):
        """Enregistre le début d'une session"""
        self.sessions[phone] = {
            "phone": phone,
            "role": role,
            "start_time": datetime.now().isoformat(),
            "messages_count": 0,
            "last_activity": datetime.now().isoformat(),
            "flow": None,
            "step": "WELCOME"
        }
        self.metrics["sessions_total"] += 1
        self.metrics[f"sessions_{role}"] += 1
        logger.info(f"[ANALYTICS] Session started: {phone} ({role})")
    
    def track_message(self, phone: str, msg_type: str, flow: str = None, step: str = None):
        """Enregistre un message échangé"""
        if phone in self.sessions:
            self.sessions[phone]["messages_count"] += 1
            self.sessions[phone]["last_activity"] = datetime.now().isoformat()
            if flow:
                self.sessions[phone]["flow"] = flow
            if step:
                self.sessions[phone]["step"] = step
        
        self.metrics["messages_total"] += 1
        self.metrics[f"messages_{msg_type}"] += 1
        
        event = {
            "timestamp": datetime.now().isoformat(),
            "phone": phone,
            "type": "message",
            "msg_type": msg_type,
            "flow": flow,
            "step": step
        }
        self.events.append(event)
        
    def track_conversion(self, phone: str, conversion_type: str, value: float = 0, metadata: Dict = None):
        """
        Enregistre une conversion
        
        Types:
        - mission_created
        - order_created
        - mission_completed
        - order_completed
        """
        conversion = {
            "timestamp": datetime.now().isoformat(),
            "phone": phone,
            "type": conversion_type,
            "value": value,
            "metadata": metadata or {}
        }
        self.conversions[conversion_type].append(conversion)
        self.metrics[f"conversion_{conversion_type}"] += 1
        self.metrics[f"revenue_{conversion_type}"] += value
        
        logger.info(f"[ANALYTICS] Conversion: {conversion_type} - {value} FCFA")
        
    def track_response_time(self, duration_ms: int, flow: str = None):
        """Enregistre le temps de réponse"""
        self.response_times.append({
            "timestamp": datetime.now().isoformat(),
            "duration_ms": duration_ms,
            "flow": flow
        })
        self.metrics["response_time_total_ms"] += duration_ms
        self.metrics["response_time_count"] += 1
        
    def track_error(self, error_type: str, error_msg: str, phone: str = None, context: Dict = None):
        """Enregistre une erreur"""
        error = {
            "timestamp": datetime.now().isoformat(),
            "type": error_type,
            "message": error_msg,
            "phone": phone,
            "context": context or {}
        }
        self.errors.append(error)
        self.metrics[f"error_{error_type}"] += 1
        self.metrics["errors_total"] += 1
        
        logger.error(f"[ANALYTICS] Error tracked: {error_type} - {error_msg}")
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Retourne un résumé des métriques"""
        active_sessions = len([s for s in self.sessions.values() 
                               if self._is_session_active(s)])
        
        avg_response_time = (
            self.metrics["response_time_total_ms"] / self.metrics["response_time_count"]
            if self.metrics["response_time_count"] > 0 else 0
        )
        
        return {
            "sessions": {
                "total": self.metrics["sessions_total"],
                "active": active_sessions,
                "by_role": {
                    "client": self.metrics.get("sessions_client", 0),
                    "livreur": self.metrics.get("sessions_livreur", 0),
                    "entreprise": self.metrics.get("sessions_entreprise", 0)
                }
            },
            "messages": {
                "total": self.metrics["messages_total"],
                "by_type": {
                    "text": self.metrics.get("messages_text", 0),
                    "interactive": self.metrics.get("messages_interactive", 0),
                    "location": self.metrics.get("messages_location", 0),
                    "media": self.metrics.get("messages_media", 0)
                }
            },
            "conversions": {
                "missions_created": self.metrics.get("conversion_mission_created", 0),
                "missions_completed": self.metrics.get("conversion_mission_completed", 0),
                "orders_created": self.metrics.get("conversion_order_created", 0),
                "orders_completed": self.metrics.get("conversion_order_completed", 0)
            },
            "revenue": {
                "missions": self.metrics.get("revenue_mission_completed", 0),
                "orders": self.metrics.get("revenue_order_completed", 0),
                "total": (self.metrics.get("revenue_mission_completed", 0) + 
                         self.metrics.get("revenue_order_completed", 0))
            },
            "performance": {
                "avg_response_time_ms": round(avg_response_time, 2),
                "errors_total": self.metrics["errors_total"],
                "error_rate": round(
                    self.metrics["errors_total"] / self.metrics["messages_total"] * 100, 2
                ) if self.metrics["messages_total"] > 0 else 0
            }
        }
    
    def get_funnel_stats(self, flow: str = "coursier") -> Dict[str, Any]:
        """Analyse du funnel de conversion pour un flow"""
        steps_count = Counter()
        
        for event in self.events:
            if event.get("flow") == flow and event.get("step"):
                steps_count[event["step"]] += 1
        
        # Définir les étapes du funnel selon le flow
        if flow == "coursier":
            funnel_steps = [
                "COURIER_POSITION_TYPE",
                "COURIER_DEPART_GPS",
                "COURIER_DEST_TEXT",
                "COURIER_VALUE",
                "COURIER_DESC",
                "COURIER_CONFIRM"
            ]
        elif flow == "marketplace":
            funnel_steps = [
                "MARKET_CATEGORY",
                "MARKET_MERCHANT",
                "MARKET_PRODUCTS",
                "MARKET_QUANTITY",
                "MARKET_DESTINATION",
                "MARKET_PAY",
                "MARKET_CONFIRM"
            ]
        else:
            funnel_steps = []
        
        funnel_data = {}
        for step in funnel_steps:
            count = steps_count.get(step, 0)
            funnel_data[step] = {
                "count": count,
                "drop_rate": 0  # Calculer le taux d'abandon
            }
        
        # Calculer les taux de conversion
        if funnel_steps:
            first_step_count = steps_count.get(funnel_steps[0], 0)
            for i, step in enumerate(funnel_steps):
                if i > 0 and first_step_count > 0:
                    current_count = steps_count.get(step, 0)
                    prev_count = steps_count.get(funnel_steps[i-1], 0)
                    if prev_count > 0:
                        drop_rate = round((1 - current_count / prev_count) * 100, 2)
                        funnel_data[step]["drop_rate"] = drop_rate
        
        return {
            "flow": flow,
            "funnel": funnel_data,
            "total_started": steps_count.get(funnel_steps[0], 0) if funnel_steps else 0,
            "total_completed": steps_count.get(funnel_steps[-1], 0) if funnel_steps else 0,
            "completion_rate": round(
                steps_count.get(funnel_steps[-1], 0) / steps_count.get(funnel_steps[0], 1) * 100, 2
            ) if funnel_steps and steps_count.get(funnel_steps[0], 0) > 0 else 0
        }
    
    def get_top_errors(self, limit: int = 10) -> List[Dict]:
        """Retourne les erreurs les plus fréquentes"""
        error_counts = Counter()
        for error in self.errors:
            key = f"{error['type']}: {error['message'][:50]}"
            error_counts[key] += 1
        
        return [
            {"error": error, "count": count}
            for error, count in error_counts.most_common(limit)
        ]
    
    def get_active_users(self, minutes: int = 30) -> List[Dict]:
        """Retourne les utilisateurs actifs dans les N dernières minutes"""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        active = []
        
        for phone, session in self.sessions.items():
            last_activity = datetime.fromisoformat(session["last_activity"])
            if last_activity > cutoff_time:
                active.append({
                    "phone": phone,
                    "role": session.get("role"),
                    "flow": session.get("flow"),
                    "step": session.get("step"),
                    "messages": session.get("messages_count"),
                    "duration_min": round(
                        (datetime.now() - datetime.fromisoformat(session["start_time"])).seconds / 60, 1
                    )
                })
        
        return active
    
    def _is_session_active(self, session: Dict, timeout_minutes: int = 30) -> bool:
        """Vérifie si une session est encore active"""
        last_activity = datetime.fromisoformat(session["last_activity"])
        return datetime.now() - last_activity < timedelta(minutes=timeout_minutes)
    
    def export_to_json(self, filepath: str = None) -> str:
        """Exporte les analytics en JSON"""
        data = {
            "export_time": datetime.now().isoformat(),
            "summary": self.get_metrics_summary(),
            "funnel_coursier": self.get_funnel_stats("coursier"),
            "funnel_marketplace": self.get_funnel_stats("marketplace"),
            "top_errors": self.get_top_errors(),
            "active_users": self.get_active_users()
        }
        
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(json_str)
            logger.info(f"[ANALYTICS] Exported to {filepath}")
        
        return json_str
    
    def reset_metrics(self):
        """Reset toutes les métriques (pour tests ou nouvelle période)"""
        self.sessions.clear()
        self.events.clear()
        self.metrics.clear()
        self.conversions.clear()
        self.response_times.clear()
        self.errors.clear()
        logger.info("[ANALYTICS] Metrics reset")


# Instance globale (en prod, utiliser Redis ou DB)
analytics = AnalyticsTracker()


# === Décorateurs pour tracking automatique ===

def track_flow_execution(flow_name: str):
    """Décorateur pour tracker l'exécution d'un flow"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.time() - start_time) * 1000)
                analytics.track_response_time(duration_ms, flow_name)
                return result
            except Exception as e:
                analytics.track_error(
                    error_type="flow_execution_error",
                    error_msg=str(e),
                    context={"flow": flow_name}
                )
                raise
        return wrapper
    return decorator


# === Fonctions utilitaires ===

def print_dashboard():
    """Affiche un dashboard texte des métriques"""
    summary = analytics.get_metrics_summary()
    
    dashboard = f"""
╔══════════════════════════════════════════════════════════════╗
║             TOKTOK DELIVERY - ANALYTICS DASHBOARD             ║
╚══════════════════════════════════════════════════════════════╝

📊 SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total:    {summary['sessions']['total']:>6}
  Active:   {summary['sessions']['active']:>6}
  
  Par rôle:
    • Client:      {summary['sessions']['by_role']['client']:>6}
    • Livreur:     {summary['sessions']['by_role']['livreur']:>6}
    • Entreprise:  {summary['sessions']['by_role']['entreprise']:>6}

💬 MESSAGES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Total:        {summary['messages']['total']:>6}
  
  Par type:
    • Text:        {summary['messages']['by_type']['text']:>6}
    • Interactive: {summary['messages']['by_type']['interactive']:>6}
    • Location:    {summary['messages']['by_type']['location']:>6}
    • Media:       {summary['messages']['by_type']['media']:>6}

🎯 CONVERSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Missions créées:     {summary['conversions']['missions_created']:>6}
  Missions terminées:  {summary['conversions']['missions_completed']:>6}
  Commandes créées:    {summary['conversions']['orders_created']:>6}
  Commandes terminées: {summary['conversions']['orders_completed']:>6}

💰 REVENUS (FCFA)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Missions:   {summary['revenue']['missions']:>10,.0f}
  Commandes:  {summary['revenue']['orders']:>10,.0f}
  ─────────────────────
  TOTAL:      {summary['revenue']['total']:>10,.0f}

⚡ PERFORMANCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Temps réponse moyen: {summary['performance']['avg_response_time_ms']:>6.0f} ms
  Erreurs totales:     {summary['performance']['errors_total']:>6}
  Taux d'erreur:       {summary['performance']['error_rate']:>6.2f} %

╚══════════════════════════════════════════════════════════════╝
"""
    print(dashboard)
    return dashboard

