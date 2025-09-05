import traceback
from typing import List, Dict, Any, Optional
import gradio as gr

try:
    from chatbot.conversation_flow import (
        handle_message,
        get_session,
        start_session,
        MAIN_MENU_BTNS,
    )
except Exception as e:
    print("❌ Import error:", e)
    raise

APP_TITLE = "TokTok Delivery Bot"

def format_bot_output(resp: Dict[str, Any]) -> str:
    text = resp.get("response", "")
    buttons = resp.get("buttons", [])
    if buttons:
        text += "\n\n**Options :** " + " | ".join(f"[{b}]" for b in buttons)
    return text

def on_send(
    message: str,
    chat_history: List[Dict[str, str]],
    phone: str,
    image_path: Optional[str],
    value_fcfa: Optional[float],
) -> tuple[str, List[Dict[str, str]]]:
    try:
        msg = (message or "").strip()
        img = image_path if image_path else None
        val = int(value_fcfa) if value_fcfa is not None and str(value_fcfa).strip() != "" else None

        resp = handle_message(
            phone=phone.strip() or "demo",
            text=msg,
            photo_present=bool(img),
            photo_url=img,
            price_value=val,
        )
        bot_text = format_bot_output(resp)
        new_history = chat_history + [
            {"role": "user", "content": msg if msg else "(entrée vide)"},
            {"role": "assistant", "content": bot_text},
        ]
        return "", new_history

    except Exception as e:
        print("⚠️ Exception dans on_send():", e)
        traceback.print_exc()
        new_history = chat_history + [{"role": "assistant", "content": f"⚠️ Erreur : {e}"}]
        return message, new_history

def quick_action(
    label: str,
    chat_history: List[Dict[str, str]],
    phone: str,
    image_path: Optional[str],
    value_fcfa: Optional[float],
):
    return on_send(label, chat_history, phone, image_path, value_fcfa)

def do_reset_session(phone: str) -> None:
    try:
        start_session(phone.strip() or "demo")
    except Exception as e:
        print("⚠️ reset_session a échoué :", e)

with gr.Blocks(theme=gr.themes.Soft(primary_hue="orange", neutral_hue="slate")) as demo:
    gr.Markdown(f"## {APP_TITLE}\nSimulation locale (sans WhatsApp)")

    with gr.Row():
        phone_box = gr.Textbox(label="Téléphone (ID session)", value="242000111222")
        reset_btn = gr.Button("🧹 Réinitialiser la session")

    with gr.Row():
        image_in = gr.Image(label="Photo du colis (optionnel)", type="filepath", interactive=True)
        value_in = gr.Number(label="Valeur du colis (FCFA) (optionnel)", value=None, precision=0)

    chatbot = gr.Chatbot(label="TokTok Assistant", type="messages", height=440)

    with gr.Row():
        user_msg = gr.Textbox(label="Votre message", placeholder="Tapez ici... (Entrée pour envoyer)")
    with gr.Row():
        send_btn = gr.Button("Envoyer", variant="primary")
        clear_btn = gr.Button("Effacer")

    gr.Markdown("### Actions rapides :")
    with gr.Row():
        btn_new = gr.Button("Nouvelle demande")
        btn_track = gr.Button("Suivre ma course")
        btn_hist = gr.Button("Historique")
        btn_market = gr.Button("Marketplace")

    send_btn.click(fn=on_send, inputs=[user_msg, chatbot, phone_box, image_in, value_in], outputs=[user_msg, chatbot])
    user_msg.submit(fn=on_send, inputs=[user_msg, chatbot, phone_box, image_in, value_in], outputs=[user_msg, chatbot])

    clear_btn.click(lambda: ([], ""), None, [chatbot, user_msg])

    btn_new.click(quick_action, [gr.State("Nouvelle demande"), chatbot, phone_box, image_in, value_in], [user_msg, chatbot])
    btn_track.click(quick_action, [gr.State("Suivre ma course"), chatbot, phone_box, image_in, value_in], [user_msg, chatbot])
    btn_hist.click(quick_action, [gr.State("Historique"), chatbot, phone_box, image_in, value_in], [user_msg, chatbot])
    btn_market.click(quick_action, [gr.State("Marketplace"), chatbot, phone_box, image_in, value_in], [user_msg, chatbot])

    reset_btn.click(lambda p: do_reset_session(p), [phone_box], None)

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=17860, debug=True)
