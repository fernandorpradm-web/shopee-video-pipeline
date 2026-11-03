#!/usr/bin/env python3
"""Gera e envia os videos a partir de produtos.json."""

import argparse
import asyncio
import json
import os
import sys
import urllib.request

from tts import gerar_audio
from video import montar_video
from telegram import enviar_video

PASTA_SAIDA = "saida"
PASTA_IMAGENS = "imagens"
VOZ_PADRAO = "pt-BR-FranciscaNeural"


def carregar_produtos(caminho="produtos.json"):
    """Aceita lista direta (minerador) ou dict com 'produtos' (formato antigo)."""
    with open(caminho, encoding="utf-8-sig") as f:
        dados = json.load(f)
    if isinstance(dados, dict):
        return dados.get("produtos") or dados.get("itens") or []
    return dados if isinstance(dados, list) else []


def campo(produto, *nomes, **kw):
    """Retorna o primeiro valor nao vazio entre as variantes de chave."""
    for n in nomes:
        v = produto.get(n)
        if v not in (None, "", []):
            return v
    return kw.get("default", "")


def baixar_imagem(url, destino):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as r, open(destino, "wb") as f:
        f.write(r.read())


def resolver_imagem(produto):
    """URL baixa; arquivo local informado; ou imagens/{id}.* automatico."""
    os.makedirs(PASTA_IMAGENS, exist_ok=True)
    pid = str(campo(produto, "id")).strip()
    ref = str(campo(produto, "imagem", "image")).strip()

    if ref.startswith("http"):
        local = os.path.join(PASTA_IMAGENS, "%s.jpg" % pid)
        baixar_imagem(ref, local)
        return local

    if ref and os.path.exists(ref):
        return ref

    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        cand = os.path.join(PASTA_IMAGENS, pid + ext)
        if os.path.exists(cand):
            return cand

    raise FileNotFoundError(
        "Imagem nao encontrada para '%s'. Envie ao bot do Telegram com "
        "legenda igual ao id, ou use --sem-envio para so gerar o video." % pid
    )


def processar(produtos, voz=VOZ_PADRAO, enviar=True, limite=0):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    if limite > 0:
        produtos = produtos[:limite]

    ok, falhas = 0, 0

    for i, produto in enumerate(produtos, 1):
        nome = str(campo(produto, "id")) or "produto_%d" % i
        print("[%d/%d] %s" % (i, len(produtos), nome))
        try:
            roteiro = campo(produto, "script", "narration", "texto")
            if not roteiro:
                raise ValueError("Sem roteiro (script/narration/texto)")

            imagem = resolver_imagem(produto)

            audio = os.path.join(PASTA_SAIDA, "%s.mp3" % nome)
            asyncio.run(gerar_audio(roteiro, audio, voz))

            titulo = campo(produto, "titulo", "title")
            texto_tela = campo(produto, "texto_tela", default=titulo)
            video = os.path.join(PASTA_SAIDA, "%s.mp4" % nome)
            montar_video(imagem, audio, texto_tela, video)

            if enviar:
                link = campo(produto, "link_afiliado", "link", "url")
                hashtags = campo(produto, "hashtags")
                legenda = "%s\n%s\n\n%s" % (titulo, link, hashtags)
                enviar_video(video, legenda.strip())

            ok += 1
            print("   OK")
        except Exception as erro:
            falhas += 1
            print("   FALHA: %s" % erro)

    print("Resumo: %d ok, %d falhas" % (ok, falhas))
    if falhas and ok == 0:
        sys.exit(1)


def main():
    ap = argparse.ArgumentParser(description="Gerador de videos de afiliado")
    ap.add_argument("--limite", type=int, default=0, help="maximo de produtos")
    ap.add_argument("--voz", default=VOZ_PADRAO)
    ap.add_argument("--sem-envio", action="store_true", help="gera sem enviar")
    ap.add_argument("--enviar", action="store_true",
                    help="compatibilidade: envio ja e o padrao")
    a = ap.parse_args()

    produtos = carregar_produtos()
    if not produtos:
        sys.exit("produtos.json vazio ou em formato inesperado.")

    print("Carregados %d produtos." % len(produtos))
    processar(produtos, voz=a.voz, enviar=not a.sem_envio, limite=a.limite)


if __name__ == "__main__":
    main()
