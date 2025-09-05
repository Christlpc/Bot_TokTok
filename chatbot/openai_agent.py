# openai_agent.py
from __future__ import annotations
import os
import json
import re
from typing import List, Dict
from urllib.parse import quote_plus

import requests

# -----------------------------
# Config API : OpenRouter OU OpenAI
# -----------------------------
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")  # ex: "openai/gpt-4o-mini"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

SYSTEM_PROMPT_PRO = """\
Tu es l’agent IA de TokTok Delivery (Congo-Brazzaville).
Objectif : comprendre l’intention utilisateur et extraire les informations manquantes pour :
- Livraison (coursier) : nom, adresse départ, adresse destination, photo (optionnel), valeur colis.
- Marketplace (restaurants/boutiques) : détecter le besoin (ex: “poulet mayo”), proposer redirection vers la marketplace avec un lien de filtre, puis finaliser commande quand le plat est choisi.
- Suivi de course (follow) et Historique (history) : guider l’utilisateur.

Règles :
- Réponds TOUJOURS en français, de façon concise, polie et professionnelle.
- Ne demande jamais le rôle utilisateur.
- Si l’intention est ambiguë, propose le menu principal.
"""

def _call_openrouter(messages: List[Dict]) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"}  # utile si on demande du JSON
    }
    r = requests.post(url, headers=headers, json=data, timeout=30)
    r.raise_for_status()
    out = r.json()
    return out["choices"][0]["message"]["content"]

def _call_openai(messages: List[Dict]) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "model": OPENAI_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }
    r = requests.post(url, headers=headers, json=data, timeout=30)
    r.raise_for_status()
    out = r.json()
    return out["choices"][0]["message"]["content"]

def ask_gpt(user_message: str, system_prompt: str = SYSTEM_PROMPT_PRO) -> str:
    """
    Appel générique pour produire une réponse textuelle (non strict JSON).
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ]
    try:
        if OPENROUTER_API_KEY:
            # Pour les réponses texte simples, on n'impose pas JSON
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            }
            data = {
                "model": OPENROUTER_MODEL,
                "messages": messages,
                "temperature": 0.5
            }
            r = requests.post(url, headers=headers, json=data, timeout=30)
            r.raise_for_status()
            out = r.json()
            return out["choices"][0]["message"]["content"]
        elif OPENAI_API_KEY:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }
            data = {
                "model": OPENAI_MODEL,
                "messages": messages,
                "temperature": 0.5
            }
            r = requests.post(url, headers=headers, json=data, timeout=30)
            r.raise_for_status()
            out = r.json()
            return out["choices"][0]["message"]["content"]
        else:
            # Fallback offline
            return "Je suis disponible. Dites-moi votre besoin (livraison, suivi, historique ou commande restaurant)."
    except Exception:
        return "Je n’ai pas pu générer de réponse pour l’instant."

def classify_intent(text: str) -> str:
    """
    Retourne l’intention: 'courier' | 'marketplace' | 'follow' | 'history'
    Utilise heuristiques + (optionnel) modèle, au format JSON.
    """
    t = text.lower()
    # Heuristique rapide
    if any(k in t for k in ["manger", "commander", "restaurant", "poulet", "pizza", "burger", "plats", "menu"]):
        return "marketplace"
    if "suivre" in t:
        return "follow"
    if "historique" in t:
        return "history"
    if any(k in t for k in ["envoyer", "colis", "livrer", "livraison", "coursier"]):
        return "courier"

    if not (OPENROUTER_API_KEY or OPENAI_API_KEY):
        return "courier"  # fallback

    sys = "Tu retournes strictement un JSON: {\"intent\":\"courier|marketplace|follow|history\"}."
    messages = [
        {"role": "system", "content": sys},
        {"role": "user", "content": f"Texte: {text}\nDonne uniquement le JSON."}
    ]
    try:
        raw = _call_openrouter(messages) if OPENROUTER_API_KEY else _call_openai(messages)
        data = json.loads(raw)
        intent = data.get("intent", "").lower()
        if intent in ["courier", "marketplace", "follow", "history"]:
            return intent
    except Exception:
        pass
    return "courier"

def suggest_restaurants(query: str) -> List[Dict[str, str]]:
    """
    MVP : suggestions mockées. À remplacer par DB/algorithme réel.
    """
    base = [
        {
            "name": "Savana Grill",
            "address": "Centre-ville",
            "image_url": "https://picsum.photos/seed/savana/400/220",
            "wa_url": "https://wa.me/242061234567?text=" + quote_plus(f"Bonjour, je veux {query}")
        },
        {
            "name": "Chez Mama Poulet",
            "address": "Poto-Poto",
            "image_url": "https://picsum.photos/seed/mama/400/220",
            "wa_url": "https://wa.me/242069876543?text=" + quote_plus(f"Bonjour, je veux {query}")
        },
        {
            "name": "La Braise",
            "address": "Moungali",
            "image_url": "https://picsum.photos/seed/braise/400/220",
            "wa_url": "https://wa.me/242055551111?text=" + quote_plus(f"Bonjour, je veux {query}")
        },
    ]
    return base
