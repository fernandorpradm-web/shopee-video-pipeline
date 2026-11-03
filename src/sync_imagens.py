#!/usr/bin/env python3
"""Sincroniza imagens enviadas ao bot do Telegram (override manual)."""

import json
import os
import re
import urllib.request

import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API = "https://api.telegram.org/bot%s" % TOKEN
PASTA = "imagens"


def api(metodo, **params):
    r = requests.get("%s/%s" % (API, metodo), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def baixar(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(destino, "wb") as f:
        f.write(resp.read())


def baixar_do_telegram(file_id, destino):
    info = api("getFile", file_id=file_id)["result"]
    baixar("https://api.telegram.org/file/bot%s/%s" % (TOKEN, info["file_path"]),
           destino)


def ids_conhecidos():
    """Aceita lista direta (minerador) ou dict com 'produtos'."""
    with open("produtos.json", encoding="utf-8-sig") as f:
        dados = json.load(f)
    if isinstance(dados, dict):
        dados = dados.get("produtos") or dados.get("itens") or []
    return set(str(p.get("id")) for p in dados if isinstance(p, dict))


def processar():
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN ausente — sync ignorado.")
        return

    os.makedirs(PASTA, exist_ok=True)
    ids = ids_conhecidos()
    if not ids:
        print("produtos.json sem ids — nada a sincronizar.")
        return

    updates = api("getUpdates", timeout=0).get("result") or []
    if not updates:
        print("Nenhuma mensagem nova no bot.")
        return

    ultimo, salvos = 0, 0
    for u in updates:
        ultimo = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = msg.get("chat", {}).get("id")
        legenda = (msg.get("caption") or msg.get("text") or "").strip()
        foto = msg.get("photo")
        doc = msg.get("document")

        if (foto or doc) and legenda in ids:
            file_id = foto[-1]["file_id"] if foto else doc["file_id"]
            info = api("getFile", file_id=file_id)["result"]
            ext = os.path.splitext(info["file_path"])[1] or ".jpg"
            destino = os.path.join(PASTA, "%s%s" % (legenda, ext))
            baixar_do_telegram(file_id, destino)
            api("sendMessage", chat_id=chat, text="Imagem salva: %s" % legenda)
            salvos += 1
        elif (foto or doc) and legenda:
            api("sendMessage", chat_id=chat,
                text="ID '%s' nao existe no produtos.json" % legenda)
        elif (foto or doc):
            api("sendMessage", chat_id=chat,
                text="Envie a foto com legenda igual ao id do produto.")
        elif legenda:
            m = re.match(r"(\S+)\s+(https?://\S+)", legenda)
            if m and m.group(1) in ids:
                baixar(m.group(2), os.path.join(PASTA, "%s.jpg" % m.group(1)))
                api("sendMessage", chat_id=chat,
                    text="Imagem baixada: %s" % m.group(1))
                salvos += 1

    if ultimo:
        api("getUpdates", offset=ultimo)
    print("Resumo do sync: %d imagens novas." % salvos)


if __name__ == "__main__":
    processar()
