import os
import requests

SYSTEM_PROMPT = (
    "Tu es un agent conversationnel professionnel pour une plateforme de livraison (style TokTok Delivery), "
    "dont la mission principale est d'accompagner l'utilisateur dans :\n"
    "- La prise de commande de livraison (coursier)\n"
    "- Le suivi des courses\n"
    "- La consultation de l'historique des courses\n"
    "Tu es courtois, clair, efficace. Si l'utilisateur choisit 'Nouvelle demande de coursier', tu dois collecter : "
    "nom, adresse de départ, adresse de destination, photo du colis (ou lien/photo), valeur du colis. "
    "Ne propose pas d'autres options tant que la commande n'est pas finalisée."
)

def ask_gpt(prompt):
    api_key = os.getenv("OPENROUTER_API_KEY")
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "mistralai/mistral-7b-instruct:free",   # ou "meta-llama/llama-3-8b-instruct:free", etc.
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 256,
        "temperature": 0.6
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"❌ OpenRouter error: {e}")
        return "Je n'ai pas pu répondre pour le moment."
