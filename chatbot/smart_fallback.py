# chatbot/smart_fallback.py
"""
Smart AI Fallback System - Comprend l'intention et extrait les informations
même si l'utilisateur ne suit pas exactement le flow prévu
"""

import os
import json
import logging
import re
from typing import Dict, Any, Optional, List
from openai import OpenAI

logger = logging.getLogger(__name__)

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def extract_structured_data(user_input: str, current_step: str, current_flow: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Utilise l'IA pour extraire des données structurées depuis un input utilisateur libre
    
    Args:
        user_input: Ce que l'utilisateur a tapé
        current_step: L'étape actuelle du flow (ex: COURIER_DEPART_TEXT)
        current_flow: Le flow actuel (ex: coursier, marketplace)
        context: Contexte de la session
    
    Returns:
        Dict avec:
        - extracted_value: La valeur extraite pour l'étape actuelle
        - confidence: Niveau de confiance (0-1)
        - intent_change: Changement d'intention détecté (nouveau flow)
        - extracted_fields: Autres champs détectés
    """
    
    if not openai_client:
        return {
            "extracted_value": None,
            "confidence": 0,
            "intent_change": None,
            "extracted_fields": {}
        }
    
    # Définir ce qu'on cherche selon l'étape
    expected_info = _get_expected_info(current_step, current_flow)
    
    system_prompt = f"""Tu es un assistant intelligent pour TokTok Delivery.

CONTEXTE:
- Flow actuel: {current_flow}
- Étape actuelle: {current_step}
- On attend: {expected_info}

TÂCHE:
Analyse ce que l'utilisateur a dit et extrait les informations pertinentes.

RÈGLES IMPORTANTES:
1. Si l'utilisateur donne une information qui correspond à l'étape, extrais-la
2. Si l'utilisateur donne plusieurs infos d'un coup, extrais toutes
3. Si l'utilisateur change d'intention (veut faire autre chose), détecte-le
4. Sois flexible: accepte différentes formulations
5. Pour les adresses: accepte n'importe quel format

EXEMPLES:
- Input: "10 rue de la paix poto poto" → Adresse valide
- Input: "envoyez à moungali chez marie" → Adresse: "Moungali chez Marie"
- Input: "5000 francs" → Montant: 5000
- Input: "Jean MALONGA" → Nom: Jean Malonga
- Input: "je veux suivre ma commande" → Changement intention: follow
- Input: "non je préfère marketplace" → Changement intention: marketplace

CONTEXTE ADDITIONNEL:
{json.dumps(context, indent=2, ensure_ascii=False)}

Réponds STRICTEMENT en JSON:
{{
    "extracted_value": "valeur principale pour l'étape actuelle ou null",
    "confidence": 0.0 à 1.0,
    "intent_change": "coursier|marketplace|follow|null",
    "extracted_fields": {{
        "adresse_depart": "si trouvée",
        "adresse_destination": "si trouvée",
        "nom_expediteur": "si trouvé",
        "telephone": "si trouvé",
        "montant": "si trouvé",
        "description": "si trouvée"
    }},
    "reasoning": "pourquoi tu as extrait ça"
}}
"""
    
    try:
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Input utilisateur: {user_input}"}
            ],
            temperature=0.1,  # Faible pour être plus déterministe
            max_tokens=500,
            response_format={"type": "json_object"}
        )
        
        ai_response = completion.choices[0].message.content
        result = json.loads(ai_response)
        
        logger.info(f"[SMART_FALLBACK] Extracted from '{user_input}': {result.get('extracted_value')} (confidence: {result.get('confidence')})")
        if result.get('reasoning'):
            logger.debug(f"[SMART_FALLBACK] Reasoning: {result['reasoning']}")
        
        return {
            "extracted_value": result.get("extracted_value"),
            "confidence": float(result.get("confidence", 0)),
            "intent_change": result.get("intent_change"),
            "extracted_fields": result.get("extracted_fields", {}),
            "reasoning": result.get("reasoning", "")
        }
        
    except Exception as e:
        logger.exception(f"[SMART_FALLBACK] Error: {e}")
        return {
            "extracted_value": None,
            "confidence": 0,
            "intent_change": None,
            "extracted_fields": {}
        }


def _get_expected_info(step: str, flow: str) -> str:
    """Retourne une description de ce qu'on attend à cette étape"""
    
    expectations = {
        # Flow Coursier
        "COURIER_POSITION_TYPE": "Où se trouve le client: 'départ' ou 'arrivée'",
        "COURIER_DEPART": "Adresse de départ (texte ou GPS)",
        "COURIER_DEPART_TEXT": "Adresse de départ en texte",
        "COURIER_DEPART_GPS": "Position GPS de départ",
        "COURIER_DEST": "Adresse de destination (texte ou GPS)",
        "COURIER_DEST_TEXT": "Adresse de destination en texte",
        "COURIER_DEST_GPS": "Position GPS de destination",
        "EXPEDITEUR_NOM": "Nom de l'expéditeur",
        "EXPEDITEUR_TEL": "Téléphone de l'expéditeur",
        "DEST_NOM": "Nom du destinataire",
        "DEST_TEL": "Téléphone du destinataire",
        "COURIER_VALUE": "Valeur estimée du colis (montant en FCFA)",
        "COURIER_DESC": "Description du colis",
        
        # Flow Marketplace
        "MARKET_CATEGORY": "Catégorie de produit (Restaurant, Épicerie, etc.)",
        "MARKET_MERCHANT": "Nom du marchand/restaurant",
        "MARKET_PRODUCTS": "Nom du produit souhaité",
        "MARKET_QUANTITY": "Quantité (nombre entre 1 et 99)",
        "MARKET_DESTINATION": "Adresse de livraison",
        "MARKET_PAY": "Mode de paiement (Espèces, Mobile Money, Virement)",
        
        # Follow
        "FOLLOW_WAIT": "Référence de la mission (ex: M-61, COUR-123)",
    }
    
    return expectations.get(step, "Information générale")


def smart_validate(user_input: str, expected_type: str, current_step: str) -> tuple[bool, Any, str]:
    """
    Validation intelligente avec IA
    
    Args:
        user_input: Input utilisateur
        expected_type: Type attendu (address, amount, phone, name, quantity)
        current_step: Étape actuelle
    
    Returns:
        (is_valid, extracted_value, error_message)
    """
    
    if not openai_client:
        # Fallback sans IA: validation basique
        return _basic_validate(user_input, expected_type)
    
    validation_prompts = {
        "address": "C'est une adresse valide au Congo (rue, quartier, ville) ?",
        "amount": "C'est un montant valide en FCFA ? Extrais juste le nombre.",
        "phone": "C'est un numéro de téléphone congolais valide ? Format: 06/05/07 + 7 chiffres",
        "name": "C'est un nom de personne valide ?",
        "quantity": "C'est une quantité valide (nombre entre 1 et 99) ?",
        "reference": "C'est une référence de mission valide (format: M-XX, COUR-XXX, etc.) ?",
    }
    
    system_prompt = f"""Tu es un validateur intelligent.

Question: {validation_prompts.get(expected_type, "C'est valide ?")}

Input: "{user_input}"

Réponds en JSON:
{{
    "is_valid": true/false,
    "extracted_value": "valeur extraite et nettoyée ou null",
    "error_message": "message d'erreur si invalide ou null"
}}

Exemples:
- "10 rue de la paix" → {{"is_valid": true, "extracted_value": "10 rue de la paix", "error_message": null}}
- "5000 francs" → {{"is_valid": true, "extracted_value": "5000", "error_message": null}}
- "abc" pour un montant → {{"is_valid": false, "extracted_value": null, "error_message": "Montant invalide"}}
- "06 123 4567" → {{"is_valid": true, "extracted_value": "06 123 4567", "error_message": null}}
"""
    
    try:
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.0,
            max_tokens=200,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(completion.choices[0].message.content)
        
        is_valid = result.get("is_valid", False)
        extracted_value = result.get("extracted_value")
        error_message = result.get("error_message", "Format invalide")
        
        logger.info(f"[SMART_VALIDATE] '{user_input}' → Valid: {is_valid}, Value: {extracted_value}")
        
        return (is_valid, extracted_value, error_message)
        
    except Exception as e:
        logger.exception(f"[SMART_VALIDATE] Error: {e}")
        return _basic_validate(user_input, expected_type)


def _basic_validate(user_input: str, expected_type: str) -> tuple[bool, Any, str]:
    """Validation basique sans IA (fallback)"""
    
    if expected_type == "amount":
        # Extraire les chiffres
        numbers = re.findall(r'\d+', user_input)
        if numbers:
            amount = int(''.join(numbers))
            if amount > 0:
                return (True, amount, "")
        return (False, None, "Montant invalide")
    
    elif expected_type == "quantity":
        try:
            qty = int(user_input.strip())
            if 1 <= qty <= 99:
                return (True, qty, "")
            return (False, None, "Quantité doit être entre 1 et 99")
        except:
            return (False, None, "Quantité invalide")
    
    elif expected_type == "phone":
        # Numéro congolais: 06/05/07 + 7 chiffres
        clean = re.sub(r'[^\d]', '', user_input)
        if len(clean) >= 9 and clean[:2] in ['06', '05', '07']:
            return (True, user_input.strip(), "")
        return (False, None, "Numéro de téléphone invalide")
    
    elif expected_type == "address":
        # Adresse: au moins 3 caractères
        if len(user_input.strip()) >= 3:
            return (True, user_input.strip(), "")
        return (False, None, "Adresse trop courte")
    
    elif expected_type == "name":
        # Nom: au moins 2 caractères
        if len(user_input.strip()) >= 2:
            return (True, user_input.strip(), "")
        return (False, None, "Nom invalide")
    
    # Par défaut: accepter
    return (True, user_input.strip(), "")


def detect_intent_change(user_input: str, current_flow: str) -> Optional[str]:
    """
    Détecte si l'utilisateur veut changer de flow
    
    Returns:
        Nouveau flow souhaité ou None
    """
    
    user_lower = user_input.lower()
    
    # Mots-clés évidents
    if any(word in user_lower for word in ["marketplace", "commander", "restaurant", "manger", "plat", "menu"]):
        if current_flow != "marketplace":
            return "marketplace"
    
    if any(word in user_lower for word in ["suivre", "suivi", "track", "où est", "statut"]):
        if current_flow != "follow":
            return "follow"
    
    # Détecter "nouvelle demande" SEULEMENT si pas déjà dans un flow actif
    # Éviter de détecter "Nouvelle demande" qui peut être un bouton dans marketplace
    if current_flow == "coursier":
        # Dans coursier, on garde les redirections
        pass
    elif any(word in user_lower for word in ["livraison", "envoyer colis", "coursier"]):
        return "coursier"
    
    # NE PAS intercepter "retour" - laissons les flows gérer ça eux-mêmes
    # On détecte seulement "menu" et "accueil" explicitement
    if any(word in user_lower for word in ["menu principal", "accueil"]):
        return "menu"
    
    # Utiliser l'IA si disponible pour les cas ambigus
    if openai_client and len(user_input) > 15:
        try:
            system_prompt = """Tu détectes si l'utilisateur veut changer d'intention.

Flows possibles: coursier (livraison), marketplace (commande), follow (suivi), menu (retour menu)

Réponds en JSON:
{
    "intent_change": "coursier|marketplace|follow|menu|null"
}
"""
            
            completion = openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Flow actuel: {current_flow}\nInput: {user_input}"}
                ],
                temperature=0.0,
                max_tokens=50,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(completion.choices[0].message.content)
            intent_change = result.get("intent_change")
            
            if intent_change and intent_change != "null":
                logger.info(f"[INTENT_CHANGE] Detected: {current_flow} → {intent_change}")
                return intent_change
                
        except Exception as e:
            logger.debug(f"[INTENT_CHANGE] IA unavailable: {e}")
    
    return None


def generate_smart_error_message(user_input: str, expected_type: str, current_step: str) -> str:
    """Génère un message d'erreur intelligent et personnalisé"""
    
    if not openai_client:
        return _basic_error_message(expected_type)
    
    try:
        system_prompt = f"""Tu génères un message d'erreur court, amical et helpful en français.

Contexte:
- On attend: {_get_expected_info(current_step, "")}
- Type: {expected_type}
- L'utilisateur a tapé: "{user_input}"

Génère un message qui:
1. Explique gentiment le problème
2. Donne un exemple concret
3. Reste court (max 2 lignes)

Réponds en JSON:
{{
    "error_message": "ton message d'erreur ici"
}}
"""
        
        completion = openai_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ],
            temperature=0.5,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(completion.choices[0].message.content)
        return result.get("error_message", _basic_error_message(expected_type))
        
    except:
        return _basic_error_message(expected_type)


def _basic_error_message(expected_type: str) -> str:
    """Messages d'erreur basiques"""
    messages = {
        "address": "⚠️ Adresse invalide.\n_Exemple :_ `10 Avenue de la Paix, Poto-Poto`",
        "amount": "⚠️ Montant invalide.\n_Exemple :_ `5000` (en FCFA)",
        "phone": "⚠️ Numéro invalide.\n_Exemple :_ `06 123 45 67`",
        "name": "⚠️ Nom invalide.\n_Exemple :_ `Jean Malonga`",
        "quantity": "⚠️ Quantité invalide.\n_Entrez un nombre entre 1 et 99",
    }
    return messages.get(expected_type, "⚠️ Format invalide. Réessayez.")

