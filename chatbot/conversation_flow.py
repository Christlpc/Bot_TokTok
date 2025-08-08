import re
from .openai_agent import ask_gpt

user_sessions = {}

ACCUEIL_MSG = (
    "🚚 *Bienvenue sur TokTok Delivery* !\n"
    "Que souhaitez-vous faire aujourd'hui ?\n"
    "1️⃣ Nouvelle demande de coursier\n"
    "2️⃣ Suivre ma course\n"
    "3️⃣ Historique des courses\n\n"
    "✉️ *Vous pouvez à tout moment taper « menu » ou « retour » pour revenir à l'accueil.*"
)
ACCUEIL_BTNS = ["Nouvelle demande", "Suivre ma course", "Historique"]

SALUTATIONS = ["bonjour", "salut", "hello", "coucou", "bonsoir", "yo", "hey", "salutation"]

INTENT_PATTERNS = [
    (r"(1|nouvelle|demande|commander|envoyer|livraison|colis|coursier)", "nouvelle demande"),
    (r"(2|suivre|suivi|tracking|track|statut|où est mon colis|où est ma livraison)", "suivre"),
    (r"(3|historique|courses précédentes|liste|récapitulatif)", "historique"),
]

def reset_session(phone):
    user_sessions[phone] = {"step": 0, "data": {}, "last_confirm": None}

def detect_menu_choice(msg):
    msg = msg.lower()
    for pattern, intent in INTENT_PATTERNS:
        if re.search(pattern, msg):
            return intent
    return None

def is_salutation(msg):
    return msg.strip().lower() in SALUTATIONS

def is_retour(msg):
    return msg.strip().lower() in ["menu", "retour", "accueil", "recommencer", "restart"]

def is_oui(msg):
    return msg.strip().lower() in ["oui", "yes", "yep", "ok", "d'accord", "certainement", "bien sûr"]

def is_non(msg):
    return msg.strip().lower() in ["non", "no", "pas du tout", "jamais", "annuler"]

def handle_message(phone, message):
    if phone not in user_sessions:
        reset_session(phone)

    session = user_sessions[phone]
    step = session["step"]
    data = session["data"]
    msg = message.strip()

    try:
        # Commande de retour ou menu à tout moment
        if is_retour(msg):
            reset_session(phone)
            return {"response": ACCUEIL_MSG, "buttons": ACCUEIL_BTNS}

        # Étape 0 : accueil/salutation/entrée
        if step == 0:
            if is_salutation(msg) or msg == "" or "livraison" in msg.lower() or "colis" in msg.lower() or "envoyer" in msg.lower():
                session["step"] = 1
                return {"response": ACCUEIL_MSG, "buttons": ACCUEIL_BTNS}
            session["step"] = 1
            return {"response": ACCUEIL_MSG, "buttons": ACCUEIL_BTNS}

        # Étape 1 : choix du menu (tolérance)
        if step == 1:
            choix = detect_menu_choice(msg)
            if choix == "nouvelle demande":
                session["step"] = 10
                session["last_confirm"] = None
                return {"response": "📝 *Nouvelle demande*.\nQuel est votre nom complet ?"}
            elif choix == "suivre":
                session["step"] = 20
                return {"response": "🔎 Merci d'indiquer le numéro ou l'identifiant de la course à suivre."}
            elif choix == "historique":
                session["step"] = 30
                return {"response": "🗒️ *Historique* — cette fonctionnalité arrive bientôt !"}
            # Reconnaissance d'un mot clé prix/tarif même hors menu
            if "tarif" in msg.lower() or "prix" in msg.lower() or "coût" in msg.lower():
                return {"response": "💰 Nos tarifs varient selon la ville, la distance et le poids du colis. Souhaitez-vous faire une simulation ?", "buttons": ["Nouvelle demande", "Retour menu"]}
            return {"response": ACCUEIL_MSG, "buttons": ACCUEIL_BTNS}

        # Nouvelle demande de livraison (étapes 10+)
        if step == 10:
            # Vérif simple sur nom
            if len(msg) < 2:
                return {"response": "Merci de préciser votre nom complet."}
            data["nom"] = msg
            session["step"] = 11
            return {"response": "📍 *Adresse de départ* : où le coursier doit-il récupérer le colis ?"}

        if step == 11:
            if len(msg) < 3:
                return {"response": "Merci de préciser l'adresse complète de départ."}
            data["adresse_depart"] = msg
            session["step"] = 12
            return {"response": "🚩 *Adresse de destination* : où doit-on livrer le colis ?"}

        if step == 12:
            if len(msg) < 3:
                return {"response": "Merci de préciser l'adresse complète de destination."}
            data["adresse_destination"] = msg
            session["step"] = 13
            return {"response": "📷 *Photo du colis* : envoyez une photo (ou tapez 'skip' pour passer)."}

        if step == 13:
            if msg.lower() not in ["skip", "sauter", "non", "pas de photo", "aucune"]:
                data["photo"] = msg
            else:
                data["photo"] = None
            session["step"] = 14
            return {"response": "💵 *Valeur estimée du colis* (en FCFA) ?"}

        if step == 14:
            try:
                valeur = int(re.sub(r"[^\d]", "", msg))
                if valeur < 1:
                    raise ValueError()
                data["valeur"] = valeur
            except Exception:
                return {"response": "Merci d'indiquer la valeur du colis (un nombre entier en FCFA)."}
            session["step"] = 15
            recap = (
                f"📝 *Récapitulatif de la demande* :\n"
                f"• Nom : {data.get('nom')}\n"
                f"• Départ : {data.get('adresse_depart')}\n"
                f"• Destination : {data.get('adresse_destination')}\n"
                f"• Photo : {'Oui' if data.get('photo') else 'Non'}\n"
                f"• Valeur : {data.get('valeur')} FCFA\n"
                "✅ Confirmez-vous cette commande ?"
            )
            session["last_confirm"] = "commande"
            return {"response": recap, "buttons": ["Oui", "Non", "Menu"]}

        if step == 15:
            if is_oui(msg):
                # Ici : sauvegarder en base, envoyer notif, etc.
                reset_session(phone)
                return {"response": "👍 Votre demande a bien été prise en compte ! Un coursier vous contactera très vite.\nMerci pour votre confiance. 😊", "buttons": ACCUEIL_BTNS}
            elif is_non(msg):
                reset_session(phone)
                return {"response": "🚫 Demande annulée. Vous êtes de retour au menu principal.", "buttons": ACCUEIL_BTNS}
            else:
                # Si la personne écrit autre chose
                return {"response": "Merci de répondre par Oui ou Non pour confirmer la commande.", "buttons": ["Oui", "Non", "Menu"]}

        # Suivi de course (étape 20)
        if step == 20:
            # Ici tu peux brancher la vraie recherche avec la base
            reset_session(phone)
            return {"response": "⏳ Le suivi de course sera disponible très bientôt. Merci pour votre patience !"}

        # Historique (étape 30)
        if step == 30:
            reset_session(phone)
            return {"response": "🗒️ L'historique de vos courses arrive prochainement. Restez connectés !"}

    except Exception as e:
        print(f"❌ Erreur dans le flow : {e}")

    # Fallback IA avec prompt professionnel
    try:
        gpt_reply = ask_gpt(message)
        return {"response": gpt_reply}
    except Exception as e:
        print(f"❌ GPT Error: {e}")
        return {"response": "Je n'ai pas pu répondre pour le moment."}
