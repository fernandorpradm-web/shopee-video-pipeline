#!/usr/bin/env python3
"""Gera e envia os videos a partir de produtos.json."""

import argparse
import asyncio
import json
import os
import sys
import urllib.request
from datetime import datetime

from tts import gerar_audio
from video import montar_video
from telegram import enviar_video

PASTA_SAIDA = "saida"
PASTA_IMAGENS = "imagens"
VOZ_PADRAO = "pt-BR-FranciscaNeural"

ARQ_PRODUTOS = "produtos.json"
ARQ_PUBLICACOES = "publicacoes.json"

LEGENDA_USAR = "texto_tela"    # "texto_tela" (curto) ou "titulo" (completo)
INCLUIR_HASHTAGS = False       # True adiciona uma terceira linha
TAMANHO_MAX_LEGENDA = 90


def carregar_json(caminho, padrao):
    if not os.path.exists(caminho):
        return padrao
    try:
        with open(caminho, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return padrao


def carregar_produtos(caminho=ARQ_PRODUTOS):
    dados = carregar_json(caminho, [])
    if isinstance(dados, dict):
        return dados.get("produtos") or dados.get("itens") or []
    return dados if isinstance(dados, list) else []


def campo(produto, *nomes, **kw):
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
    os.makedirs(PASTA_IMAGENS, exist_ok=True)
    pid = str(campo(produto, "id")).strip()
    ref = str(campo(produto, "imagem", "image")).strip()

    if ref.startswith("http"):
        local = os.path.join(PASTA_IMAGENS, "%s.jpg" % pid)
        if not os.path.exists(local) or os.path.getsize(local) < 1024:
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
        "legenda igual ao id, ou use --sem-envio." % pid
    )


def montar_legenda(produto):
    base = campo(produto, LEGENDA_USAR, "texto_tela", "titulo", "title")
    base = str(base).strip()
    if len(base) > TAMANHO_MAX_LEGENDA:
        base = base[:TAMANHO_MAX_LEGENDA].rsplit(" ", 1)[0]
    link = str(campo(produto, "link_afiliado", "link", "url")).strip()
    linhas = [base, link]
    if INCLUIR_HASHTAGS:
        tags = str(campo(produto, "hashtags")).strip()
        if tags:
            linhas.append(tags)
    return "\n".join(l for l in linhas if l)


def carregar_publicacoes():
    dados = carregar_json(ARQ_PUBLICACOES, [])
    if isinstance(dados, dict):
        dados = dados.get("publicacoes") or []
    return dados if isinstance(dados, list) else []


def ja_publicado(pid, publicacoes):
    return any(str(p.get("id")) == str(pid) for p in publicacoes)


def registrar_publicacao(produto, publicacoes):
    publicacoes.append({
        "id": str(campo(produto, "id")),
        "data": datetime.now().strftime("%Y-%m-%d"),
        "hora": datetime.now().strftime("%H:%M"),
        "nicho": campo(produto, "nicho", default="?"),
        "gancho_id": campo(produto, "gancho_id"),
        "texto_tela": campo(produto, "texto_tela", "titulo"),
        "titulo": campo(produto, "titulo", "title"),
        "link": campo(produto, "link", "url"),
        "script": campo(produto, "script", "narration", "texto"),
        "score": campo(produto, "score"),
    })
    with open(ARQ_PUBLICACOES, "w", encoding="utf-8") as f:
        json.dump(publicacoes, f, ensure_ascii=False, indent=2)


def processar(produtos, voz=VOZ_PADRAO, enviar=True, limite=0):
    os.makedirs(PASTA_SAIDA, exist_ok=True)
    if limite > 0:
        produtos = produtos[:limite]

    publicacoes = carregar_publicacoes()
    ok, pulados, falhas = 0, 0, 0

    for i, produto in enumerate(produtos, 1):
        nome = str(campo(produto, "id")) or "produto_%d" % i
        print("[%d/%d] %s" % (i, len(produtos), nome))

        if enviar and ja_publicado(nome, publicacoes):
            print("   ja publicado — pulando")
            pulados += 1
            continue

        try:
            roteiro = campo(produto, "script", "narration", "texto")
            if not roteiro:
                raise ValueError("Sem roteiro (script/narration/texto)")

            imagem = resolver_imagem(produto)

            audio = os.path.join(PASTA_SAIDA, "%s.mp3" % nome)
            asyncio.run(gerar_audio(roteiro, audio, voz))

            texto_tela = campo(produto, "texto_tela",
                               default=campo(produto, "titulo", "title"))
            video = os.path.join(PASTA_SAIDA, "%s.mp4" % nome)
            montar_video(imagem, audio, texto_tela, video)

            if enviar:
                enviar_video(video, montar_legenda(produto))
                registrar_publicacao(produto, publicacoes)

            ok += 1
            print("   OK")
        except Exception as erro:
            falhas += 1
            print("   FALHA: %s" % erro)

    print("Resumo: %d ok, %d pulados, %d falhas" % (ok, pulados, falhas))
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
