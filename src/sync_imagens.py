import glob
import json
import os
import re
import urllib.request

import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}"
PASTA = "imagens"


def api(metodo, **params):
    r = requests.get(f"{API}/{metodo}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def baixar(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(destino, "wb") as f:
        f.write(resp.read())


def baixar_do_telegram(file_id, destino):
    info = api("getFile", file_id=file_id)["result"]
    baixar(f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}", destino)


def ids_conhecidos():
    with open("produtos.json", encoding="utf-8-sig") as f:
        config = json.load(f)
    return {p["id"] for p in config["produtos"]}


def processar():
    os.makedirs(PASTA, exist_ok=True)
    ids = ids_conhecidos()
    updates = api("getUpdates", timeout=0)["result"]
    if not updates:
        print("Nenhuma mensagem nova no bot.")
        return

    ultimo = 0
    salvos = 0
    for u in updates:
        ultimo = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = msg.get("chat", {}).get("id")
        legenda = (msg.get("caption") or msg.get("text") or "").strip()
        foto = msg.get("photo")          # foto comprimida pelo Telegram
        doc = msg.get("document")        # arquivo (resolução original)

        if (foto or doc) and legenda in ids:
            file_id = foto[-1]["file_id"] if foto else doc["file_id"]
            info = api("getFile", file_id=file_id)["result"]
            ext = os.path.splitext(info["file_path"])[1] or ".jpg"
            destino = os.path.join(PASTA, f"{legenda}{ext}")
            baixar_do_telegram(file_id, destino)
            api("sendMessage", chat_id=chat, text=f"✅ Imagem salva: {legenda}")
            salvos += 1
            print(f"Salvo: {destino}")
        elif (foto or doc) and legenda:
            api("sendMessage", chat_id=chat, text=f"❌ ID '{legenda}' não existe no produtos.json")
        elif (foto or doc):
            api("sendMessage", chat_id=chat, text="⚠️ Envie a foto com legenda = id do produto (ex.: varal-3-andares)")
        elif legenda:
            m = re.match(r"(\S+)\s+(https?://\S+)", legenda)
            if m and m.group(1) in ids:
                baixar(m.group(2), os.path.join(PASTA, f"{m.group(1)}.jpg"))
                api("sendMessage", chat_id=chat, text=f"✅ Imagem baixada de URL: {m.group(1)}")
                salvos += 1

    if ultimo:
        api("getUpdates", offset=ultimo)  # confirma o processamento
    print(f"Resumo do sync: {salvos} imagens novas.")


if __name__ == "__main__":
    processar()
