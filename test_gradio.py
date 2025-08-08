import gradio as gr
import os

# ⚠️ Adapte l'import si ton app Django n'est pas importable direct.
# Si besoin, ajoute le répertoire du projet au PYTHONPATH :
# import sys
# sys.path.append(os.path.abspath("."))

try:
    # Import direct si tu as un package "chatbot" avec conversation_flow.py
    from chatbot.conversation_flow import handle_message
except Exception as e:
    # Fallback : si tu as mis conversation_flow.py à côté de ce fichier
    print(f"[WARN] Import chatbot.conversation_flow failed: {e}")
    from conversation_flow import handle_message  # type: ignore


APP_TITLE = "TokTok Delivery Bot (Demo)"
APP_SUBTITLE = "Simulation locale sans WhatsApp. Saisis ton numéro pour isoler ta session."


def chat_backend(message: str, history: list, phone: str):
    """
    - history est au format type='messages' : liste de dicts {"role": "...", "content": "..."}
    - phone sert d'ID de session côté flow
    - on renvoie l'historique mis à jour et on vide la textbox
    """
    if not phone:
        phone = "242000000000"

    try:
        result = handle_message(phone, message)

        if isinstance(result, dict):
            text = result.get("response", "")
            buttons = result.get("buttons") or []
            if buttons:
                # Affichage simple des choix : tu pourras raffiner en UI plus tard
                text += "\n\n**Options :** " + " | ".join([f"[{b}]" for b in buttons])
        else:
            text = str(result)

    except Exception as e:
        text = f"Erreur côté bot : {e}"

    # On pousse les 2 messages (user puis assistant) dans l'historique
    updated = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": text},
    ]
    return updated, gr.update(value="")  # vide la textbox


def send_quick(phone: str, button_label: str, history: list):
    """
    Déclenche un 'clic bouton' comme si l'utilisateur avait envoyé le texte du bouton.
    """
    if not button_label:
        return history
    # Simule un tour complet via chat_backend
    updated, _ = chat_backend(button_label, history, phone)
    return updated


with gr.Blocks(theme="soft") as demo:
    gr.Markdown(f"# {APP_TITLE}\n{APP_SUBTITLE}")

    with gr.Row():
        phone_box = gr.Textbox(label="Téléphone (ID session)", value="242000111222")
        start_btn = gr.Button("Démarrer", variant="primary")

    chatbot = gr.Chatbot(type="messages", height=450, label="Conversation")
    msg = gr.Textbox(
        label="Votre message",
        placeholder="Tapez votre message ici… (Entrée pour envoyer)",
        autofocus=True,
    )
    send = gr.Button("Envoyer")
    clear = gr.ClearButton([msg, chatbot], value="Effacer")

    with gr.Accordion("Raccourcis (simulateurs de boutons)", open=False):
        with gr.Row():
            btn1 = gr.Button("Nouvelle demande")
            btn2 = gr.Button("Suivre ma course")
            btn3 = gr.Button("Historique")

    # — Interactions —
    # Démarrage = envoi automatique de "Bonjour"
    start_btn.click(
        fn=lambda h, p: chat_backend("Bonjour", h, p),
        inputs=[chatbot, phone_box],
        outputs=[chatbot, msg],
    )

    send.click(
        fn=chat_backend,
        inputs=[msg, chatbot, phone_box],
        outputs=[chatbot, msg],
    )
    msg.submit(
        fn=chat_backend,
        inputs=[msg, chatbot, phone_box],
        outputs=[chatbot, msg],
    )

    # Raccourcis pour cliquer des "boutons"
    btn1.click(lambda p, h: send_quick(p, "Nouvelle demande", h), [phone_box, chatbot], [chatbot])
    btn2.click(lambda p, h: send_quick(p, "Suivre ma course", h), [phone_box, chatbot], [chatbot])
    btn3.click(lambda p, h: send_quick(p, "Historique", h), [phone_box, chatbot], [chatbot])

if __name__ == "__main__":
    # Mets share=True si tu veux un lien public temporaire
    demo.launch(server_name="127.0.0.1", server_port=7860)
