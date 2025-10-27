# chatbot/geocoding_service.py
"""
Service de géolocalisation et calcul de distance
Convertit adresses → coordonnées et calcule les distances
"""
import os
import logging
import requests
from typing import Optional, Tuple, Dict, Any
from math import radians, cos, sin, asin, sqrt

logger = logging.getLogger(__name__)

# Configuration
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
USER_AGENT = "TokTokDelivery/1.0"


def geocode_address(address: str, city: str = "Brazzaville", country: str = "Congo") -> Optional[Tuple[float, float]]:
    """
    Convertit une adresse en coordonnées GPS (latitude, longitude)
    
    Args:
        address: Adresse à géocoder (ex: "25 Rue Malanda")
        city: Ville (par défaut "Brazzaville")
        country: Pays (par défaut "Congo")
    
    Returns:
        (latitude, longitude) ou None si non trouvé
    """
    try:
        # Construire la query pour Nominatim
        query = f"{address}, {city}, {country}"
        
        params = {
            "q": query,
            "format": "json",
            "limit": 1
        }
        
        headers = {
            "User-Agent": USER_AGENT
        }
        
        response = requests.get(
            f"{NOMINATIM_BASE_URL}/search",
            params=params,
            headers=headers,
            timeout=5
        )
        
        if response.status_code == 200:
            results = response.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                logger.info(f"[GEOCODE] '{address}' → ({lat}, {lon})")
                return (lat, lon)
        
        logger.warning(f"[GEOCODE] Impossible de géocoder '{address}'")
        return None
        
    except Exception as e:
        logger.error(f"[GEOCODE] Erreur: {e}")
        return None


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcule la distance entre deux points GPS en kilomètres
    Utilise la formule de Haversine
    
    Args:
        lat1, lon1: Coordonnées du point 1
        lat2, lon2: Coordonnées du point 2
    
    Returns:
        Distance en kilomètres
    """
    # Convertir en radians
    lon1, lat1, lon2, lat2 = map(radians, [lon1, lat1, lon2, lat2])
    
    # Formule de Haversine
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Rayon de la Terre en km
    r = 6371
    
    distance = c * r
    return round(distance, 2)


def estimate_distance_from_addresses(
    address1: str, 
    address2: str,
    coords1: Optional[str] = None,
    coords2: Optional[str] = None
) -> Dict[str, Any]:
    """
    Estime la distance entre deux adresses
    
    Args:
        address1: Première adresse (ou "Position actuelle")
        address2: Deuxième adresse
        coords1: Coordonnées optionnelles du point 1 (format: "lat,lng")
        coords2: Coordonnées optionnelles du point 2 (format: "lat,lng")
    
    Returns:
        {
            "distance_km": float,
            "distance_text": str,  # Ex: "5.2 km"
            "estimated_time": str,  # Ex: "15 min"
            "success": bool
        }
    """
    try:
        lat1, lon1, lat2, lon2 = None, None, None, None
        
        # Point 1 : Utiliser les coordonnées si disponibles, sinon géocoder
        if coords1:
            try:
                lat1, lon1 = map(float, coords1.split(","))
            except:
                pass
        
        if lat1 is None and address1 and address1 != "Position actuelle":
            result = geocode_address(address1)
            if result:
                lat1, lon1 = result
        
        # Point 2 : Utiliser les coordonnées si disponibles, sinon géocoder
        if coords2:
            try:
                lat2, lon2 = map(float, coords2.split(","))
            except:
                pass
        
        if lat2 is None and address2 and address2 != "Position actuelle":
            result = geocode_address(address2)
            if result:
                lat2, lon2 = result
        
        # Vérifier qu'on a les deux points
        if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
            return {
                "distance_km": 0,
                "distance_text": "—",
                "estimated_time": "—",
                "success": False
            }
        
        # Calculer la distance
        distance_km = haversine_distance(lat1, lon1, lat2, lon2)
        
        # Estimer le temps de trajet (vitesse moyenne 25 km/h en ville)
        average_speed = 25  # km/h
        time_minutes = int((distance_km / average_speed) * 60)
        
        # Formatter le temps
        if time_minutes < 60:
            time_text = f"{time_minutes} min"
        else:
            hours = time_minutes // 60
            mins = time_minutes % 60
            time_text = f"{hours}h{mins:02d}"
        
        return {
            "distance_km": distance_km,
            "distance_text": f"{distance_km} km",
            "estimated_time": time_text,
            "success": True
        }
        
    except Exception as e:
        logger.error(f"[DISTANCE] Erreur: {e}")
        return {
            "distance_km": 0,
            "distance_text": "—",
            "estimated_time": "—",
            "success": False
        }


def format_mission_with_distance(mission: Dict[str, Any]) -> str:
    """
    Formate une mission avec calcul de distance
    
    Args:
        mission: Dictionnaire mission avec adresses et coordonnées
    
    Returns:
        String formaté avec distance et temps estimé
    """
    depart = mission.get("adresse_recuperation", "—")
    dest = mission.get("adresse_livraison", "—")
    coords_depart = mission.get("coordonnees_recuperation")
    coords_dest = mission.get("coordonnees_livraison")
    
    # Calculer la distance
    dist_info = estimate_distance_from_addresses(
        depart, dest,
        coords_depart, coords_dest
    )
    
    # Formatter
    if dist_info["success"]:
        return (
            f"📍 *{depart}* → *{dest}*\n"
            f"📏 Distance : {dist_info['distance_text']}\n"
            f"⏱️ Temps estimé : {dist_info['estimated_time']}"
        )
    else:
        return f"📍 *{depart}* → *{dest}*"


# Fonction helper pour missions livreurs
def format_mission_for_livreur(mission: Dict[str, Any], livreur_position: Optional[Tuple[float, float]] = None) -> str:
    """
    Formate une mission pour un livreur avec toutes les infos utiles
    
    Args:
        mission: Dict de la mission
        livreur_position: Position actuelle du livreur (lat, lng) optionnel
    
    Returns:
        String formaté premium pour affichage
    """
    mid = mission.get("id", "—")
    depart = mission.get("adresse_recuperation", "—")
    dest = mission.get("adresse_livraison", "—")
    coords_depart = mission.get("coordonnees_recuperation")
    coords_dest = mission.get("coordonnees_livraison")
    valeur = mission.get("valeur_produit", 0)
    
    # Distance entre départ et destination
    dist_trajet = estimate_distance_from_addresses(depart, dest, coords_depart, coords_dest)
    
    # Distance du livreur au point de départ (si position fournie)
    dist_to_pickup = None
    if livreur_position and coords_depart:
        try:
            lat, lon = livreur_position
            depart_coords = coords_depart.split(",")
            if len(depart_coords) == 2:
                lat_depart, lon_depart = map(float, depart_coords)
                dist_km = haversine_distance(lat, lon, lat_depart, lon_depart)
                dist_to_pickup = {
                    "distance_km": dist_km,
                    "distance_text": f"{dist_km} km"
                }
        except:
            pass
    
    # Formatter le message
    lines = [
        f"*📦 Mission #{mid}*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"🚏 *Départ :* {depart}",
        f"🎯 *Arrivée :* {dest}",
    ]
    
    if dist_trajet["success"]:
        lines.append(f"📏 *Distance :* {dist_trajet['distance_text']}")
        lines.append(f"⏱️ *Temps estimé :* {dist_trajet['estimated_time']}")
    
    if dist_to_pickup:
        lines.append(f"🚴 *Vous êtes à :* {dist_to_pickup['distance_text']} du départ")
    
    lines.append(f"💰 *Valeur :* {int(float(valeur or 0)):,} FCFA".replace(",", " "))
    
    return "\n".join(lines)

