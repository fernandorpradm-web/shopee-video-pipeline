import sys
import asyncio
import json
import os
import urllib.request

from tts import gerar_audio
from video import montar_video
from telegram import enviar_video

PASTA_SAIDA = "saida"

def baixar_imagem(url: str, destino: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r, open(destino, "wb") as f:
        f.write(r.read())

def processar(config: dict):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    voz = config.get("voz", "pt-BR-FranciscaNeural")
    enviados, falhas = 0, 0

    for i, produto in enumerate(config["produtos"], 1):
        nome = produto["id"]
        print(f"[{i}] Gerando: {nome}")
        try:
            # 1. Imagem (URL da Shopee ou arquivo local)
            imagem = produto["imagem"]
            if imagem.startswith("http"):
                local = os.path.join(PASTA_SAIDA, f"{nome}.jpg")
                baixar_imagem(imagem, local)
                imagem = local

            # 2. Narração (edge-tts)
            audio = os.path.join(PASTA_SAIDA, f"{nome}.mp3")
            asyncio.run(gerar_audio(produto["script"], audio, voz))

            # 3. Vídeo (ffmpeg)
            video = os.path.join(PASTA_SAIDA, f"{nome}.mp4")
            montar_video(imagem, audio, produto.get("texto_tela", produto["titulo"]), video)

            # 4. Envio ao Telegram
            legenda = f"{produto['titulo']}\n{produto['link_afiliado']}"
            enviar_video(video, legenda)
            enviados += 1
            print(f"[{i}] Enviado ao Telegram: {nome}")
        except Exception as erro:
            falhas += 1
            print(f"[{i}] FALHA em {nome}: {erro}")

    print(f"Resumo: {enviados} enviados, {falhas} falhas.")
    if falhas and not enviados:
        sys.exit(1)

if __name__ == "__main__":
    with open("produtos.json", encoding="utf-8") as f:
        processar(json.load(f))
