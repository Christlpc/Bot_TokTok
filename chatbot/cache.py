# chatbot/cache.py
"""
Système de cache simple pour optimiser les performances
En production, remplacer par Redis
"""

import logging
import time
from typing import Dict, Any, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)


class SimpleCache:
    """Cache en mémoire simple avec TTL"""
    
    def __init__(self, default_ttl: int = 300):
        """
        Args:
            default_ttl: Durée de vie par défaut en secondes (5 min)
        """
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.default_ttl = default_ttl
    
    def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache"""
        if key not in self.cache:
            return None
        
        entry = self.cache[key]
        if time.time() > entry["expires_at"]:
            # Expiré
            del self.cache[key]
            logger.debug(f"[CACHE] Expired: {key}")
            return None
        
        logger.debug(f"[CACHE] HIT: {key}")
        return entry["value"]
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """Stocke une valeur dans le cache"""
        ttl = ttl or self.default_ttl
        self.cache[key] = {
            "value": value,
            "expires_at": time.time() + ttl,
            "created_at": time.time()
        }
        logger.debug(f"[CACHE] SET: {key} (TTL={ttl}s)")
    
    def delete(self, key: str):
        """Supprime une clé du cache"""
        if key in self.cache:
            del self.cache[key]
            logger.debug(f"[CACHE] DELETED: {key}")
    
    def clear(self):
        """Vide tout le cache"""
        count = len(self.cache)
        self.cache.clear()
        logger.info(f"[CACHE] Cleared {count} entries")
    
    def cleanup_expired(self):
        """Nettoie les entrées expirées"""
        now = time.time()
        expired_keys = [
            key for key, entry in self.cache.items()
            if now > entry["expires_at"]
        ]
        for key in expired_keys:
            del self.cache[key]
        
        if expired_keys:
            logger.info(f"[CACHE] Cleaned {len(expired_keys)} expired entries")
    
    def get_stats(self) -> Dict[str, Any]:
        """Statistiques du cache"""
        now = time.time()
        valid = sum(1 for e in self.cache.values() if now <= e["expires_at"])
        expired = len(self.cache) - valid
        
        return {
            "total_keys": len(self.cache),
            "valid_keys": valid,
            "expired_keys": expired,
            "memory_estimate_kb": len(str(self.cache)) // 1024
        }


# Instance globale
cache = SimpleCache(default_ttl=300)  # 5 minutes par défaut


# === Décorateurs pour caching automatique ===

def cached(ttl: int = 300, key_prefix: str = ""):
    """
    Décorateur pour mettre en cache le résultat d'une fonction
    
    Usage:
        @cached(ttl=600, key_prefix="categories")
        def get_categories(session):
            # API call...
            return result
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Générer une clé de cache
            cache_key = f"{key_prefix}:{func.__name__}:{str(args)}:{str(kwargs)}"
            
            # Essayer de récupérer du cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"[CACHE] Using cached result for {func.__name__}")
                return cached_value
            
            # Exécuter la fonction
            result = func(*args, **kwargs)
            
            # Mettre en cache
            cache.set(cache_key, result, ttl)
            logger.debug(f"[CACHE] Cached result for {func.__name__}")
            
            return result
        return wrapper
    return decorator


# === Cache spécifiques pour TokTok Delivery ===

CACHE_TTL_CATEGORIES = 600  # 10 minutes
CACHE_TTL_MERCHANTS = 300   # 5 minutes
CACHE_TTL_PRODUCTS = 180    # 3 minutes
CACHE_TTL_USER_PROFILE = 120  # 2 minutes


def cache_categories(categories: list, category_id: Optional[str] = None):
    """Cache la liste des catégories"""
    key = f"categories:{category_id}" if category_id else "categories:all"
    cache.set(key, categories, CACHE_TTL_CATEGORIES)


def get_cached_categories(category_id: Optional[str] = None) -> Optional[list]:
    """Récupère les catégories du cache"""
    key = f"categories:{category_id}" if category_id else "categories:all"
    return cache.get(key)


def cache_merchants(merchant_id: str, merchants: list):
    """Cache la liste des marchands d'une catégorie"""
    key = f"merchants:category_{merchant_id}"
    cache.set(key, merchants, CACHE_TTL_MERCHANTS)


def get_cached_merchants(merchant_id: str) -> Optional[list]:
    """Récupère les marchands du cache"""
    key = f"merchants:category_{merchant_id}"
    return cache.get(key)


def cache_products(merchant_id: str, products: list):
    """Cache les produits d'un marchand"""
    key = f"products:merchant_{merchant_id}"
    cache.set(key, products, CACHE_TTL_PRODUCTS)


def get_cached_products(merchant_id: str) -> Optional[list]:
    """Récupère les produits du cache"""
    key = f"products:merchant_{merchant_id}"
    return cache.get(key)


def cache_user_profile(phone: str, profile: Dict):
    """Cache le profil utilisateur"""
    key = f"profile:{phone}"
    cache.set(key, profile, CACHE_TTL_USER_PROFILE)


def get_cached_user_profile(phone: str) -> Optional[Dict]:
    """Récupère le profil du cache"""
    key = f"profile:{phone}"
    return cache.get(key)


def invalidate_user_cache(phone: str):
    """Invalide tout le cache d'un utilisateur"""
    cache.delete(f"profile:{phone}")
    logger.info(f"[CACHE] Invalidated cache for user {phone}")


# === Rate Limiting ===

class RateLimiter:
    """Rate limiter simple basé sur le cache"""
    
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        """
        Args:
            max_requests: Nombre max de requêtes
            window_seconds: Fenêtre de temps en secondes
        """
        self.max_requests = max_requests
        self.window = window_seconds
    
    def is_allowed(self, identifier: str) -> bool:
        """Vérifie si une requête est autorisée"""
        key = f"ratelimit:{identifier}"
        
        # Récupérer le compteur
        counter = cache.get(key)
        if counter is None:
            # Première requête dans la fenêtre
            cache.set(key, 1, self.window)
            return True
        
        if counter >= self.max_requests:
            logger.warning(f"[RATELIMIT] Exceeded for {identifier}: {counter}/{self.max_requests}")
            return False
        
        # Incrémenter
        cache.set(key, counter + 1, self.window)
        return True
    
    def get_remaining(self, identifier: str) -> int:
        """Retourne le nombre de requêtes restantes"""
        key = f"ratelimit:{identifier}"
        counter = cache.get(key) or 0
        return max(0, self.max_requests - counter)


# Rate limiters par défaut
api_rate_limiter = RateLimiter(max_requests=30, window_seconds=60)  # 30 req/min
whatsapp_rate_limiter = RateLimiter(max_requests=80, window_seconds=60)  # 80 req/min


# === Background Cleanup ===

def start_cache_cleanup_worker(interval: int = 300):
    """
    Démarre un worker background pour nettoyer le cache
    En production, utiliser Celery ou similaire
    
    Args:
        interval: Intervalle de nettoyage en secondes
    """
    import threading
    
    def cleanup_loop():
        while True:
            time.sleep(interval)
            try:
                cache.cleanup_expired()
                logger.info("[CACHE] Cleanup completed")
            except Exception as e:
                logger.exception(f"[CACHE] Cleanup error: {e}")
    
    thread = threading.Thread(target=cleanup_loop, daemon=True)
    thread.start()
    logger.info(f"[CACHE] Cleanup worker started (interval={interval}s)")


# === Monitoring ===

def print_cache_stats():
    """Affiche les statistiques du cache"""
    stats = cache.get_stats()
    print(f"""
╔════════════════════════════════════╗
║       CACHE STATISTICS             ║
╚════════════════════════════════════╝

Total keys:    {stats['total_keys']:>6}
Valid keys:    {stats['valid_keys']:>6}
Expired keys:  {stats['expired_keys']:>6}
Memory (KB):   {stats['memory_estimate_kb']:>6}
""")
    return stats

