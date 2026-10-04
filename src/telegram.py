import os
import requests

def enviar_video(caminho: str, legenda: str = ""):
    """Envia o vídeo pronto para o seu Telegram via Bot API."""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendVideo"
    with open(caminho, "rb") as f:
        resposta = requests.post(
            url,
            data={"chat_id": chat_id, "caption": legenda[:1024], "supports_streaming": "true"},
            files={"video": f},
            timeout=600,
        )
    resposta.raise_for_status()
    return resposta.json()
