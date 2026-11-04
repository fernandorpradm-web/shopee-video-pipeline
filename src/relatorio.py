#!/usr/bin/env python3
"""
Cruza gancho_id com views para descobrir quais ganchos convertem.

Fontes:
  publicacoes.json  -> gerado pelo main.py a cada envio
  views.csv         -> voce preenche: id,views,cliques,vendas

Uso:
  python src/relatorio.py                 # relatorio no terminal
  python src/relatorio.py --template      # cria/atualiza views.csv
"""

import argparse
import csv
import json
import os
import statistics
from collections import defaultdict

ARQ_PUBLICACOES = "publicacoes.json"
ARQ_VIEWS = "views.csv"
ARQ_SAIDA = "relatorio_ganchos.csv"
MIN_AMOSTRA = 3


def carregar_publicacoes():
    if not os.path.exists(ARQ_PUBLICACOES):
        return []
    try:
        with open(ARQ_PUBLICACOES, encoding="utf-8-sig") as f:
            dados = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(dados, dict):
        dados = dados.get("publicacoes") or []
    return dados if isinstance(dados, list) else []


def carregar_views():
    """{id: {'views': int, 'cliques': int, 'vendas': int}}"""
    if not os.path.exists(ARQ_VIEWS):
        return {}
    out = {}
    with open(ARQ_VIEWS, encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f):
            pid = str(linha.get("id") or "").strip()
            if not pid:
                continue
            out[pid] = {
                "views": _int(linha.get("views")),
                "cliques": _int(linha.get("cliques")),
                "vendas": _int(linha.get("vendas")),
            }
    return out


def _int(v):
    try:
        return int(float(str(v).replace(",", ".")))
    except (TypeError, ValueError):
        return 0


def gravar_template(publicacoes, views):
    novos = 0
    existe = os.path.exists(ARQ_VIEWS)
    with open(ARQ_VIEWS, "a" if existe else "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if not existe:
            w.writerow(["id", "views", "cliques", "vendas"])
        for p in publicacoes:
            pid = str(p.get("id"))
            if pid in views:
                continue
            w.writerow([pid, "", "", ""])
            novos += 1
    print("Template: %d linhas novas em %s" % (novos, ARQ_VIEWS))


def agrupar(publicacoes, views):
    grupos = defaultdict(lambda: {"views": [], "cliques": [], "vendas": []})
    sem_views = 0
    for p in publicacoes:
        pid = str(p.get("id"))
        d = views.get(pid)
        if not d or not d.get("views"):
            sem_views += 1
            continue
        chave = (p.get("nicho", "?"), p.get("gancho_id"))
        grupos[chave]["views"].append(d["views"])
        grupos[chave]["cliques"].append(d.get("cliques", 0))
        grupos[chave]["vendas"].append(d.get("vendas", 0))
    return grupos, sem_views


def linha_tabela(nicho, gancho, dados):
    vs = dados["views"]
    media = statistics.mean(vs)
    mediana = statistics.median(vs)
    return {
        "nicho": nicho,
        "gancho_id": gancho,
        "amostra": len(vs),
        "media_views": round(media, 1),
        "mediana_views": round(mediana, 1),
        "total_views": sum(vs),
        "media_cliques": round(statistics.mean(dados["cliques"]), 1),
        "conversoes": sum(dados["vendas"]),
    }


def relatorio(publicacoes, views):
    grupos, sem_views = agrupar(publicacoes, views)

    print("")
    print("=" * 68)
    print("RELATORIO DE GANCHOS")
    print("=" * 68)
    print("  publicacoes registradas: %d" % len(publicacoes))
    print("  com views preenchidas:   %d" % (len(publicacoes) - sem_views))
    print("  pendentes de views:      %d" % sem_views)

    if not grupos:
        print("")
        print("Nenhum dado de views. Rode --template e preencha o %s." % ARQ_VIEWS)
        return

    linhas = [linha_tabela(n, g, d) for (n, g), d in grupos.items()]
    linhas.sort(key=lambda x: (-x["nicho"], -x["media_views"]))

    for nicho in sorted(set(l["nicho"] for l in linhas)):
        bloco = [l for l in linhas if l["nicho"] == nicho]
        print("")
        print("--- NICHO %s ---" % str(nicho).upper())
        print("%6s %6s %9s %9s %8s %9s %8s"
              % ("gancho", "n", "media", "mediana", "total", "cliques", "vendas"))
        for l in bloco:
            print("%6d %6d %9.1f %9.1f %8d %9.1f %8d"
                  % (l["gancho_id"] if l["gancho_id"] is not None else -1,
                     l["amostra"], l["media_views"], l["mediana_views"],
                     l["total_views"], l["media_cliques"], l["conversoes"]))

        melhor = bloco[0]
        pior = bloco[-1]
        maior_n = max(l["amostra"] for l in bloco)

        if maior_n < MIN_AMOSTRA:
            print("")
            print("  Amostra insuficiente (maximo %d por gancho, minimo %d)."
                  % (maior_n, MIN_AMOSTRA))
            print("  Nao corte ganchos ainda: com 3 videos/dia e 10 ganchos,")
            print("  sao ~4 semanas para cada gancho ter amostra confiavel.")
        else:
            print("")
            print("  Melhor: gancho %s (media %.1f views, n=%d)"
                  % (melhor["gancho_id"], melhor["media_views"], melhor["amostra"]))
            print("  Pior:   gancho %s (media %.1f views, n=%d)"
                  % (pior["gancho_id"], pior["media_views"], pior["amostra"]))

    with open(ARQ_SAIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)
    print("")
    print("Detalhe por gancho em %s" % ARQ_SAIDA)


def main():
    ap = argparse.ArgumentParser(description="Relatorio de ganchos por views")
    ap.add_argument("--template", action="store_true",
                    help="cria/atualiza views.csv com os ids pendentes")
    a = ap.parse_args()

    publicacoes = carregar_publicacoes()
    views = carregar_views()

    if a.template:
        if not publicacoes:
            print("publicacoes.json vazio — rode o main.py com envio primeiro.")
            return
        gravar_template(publicacoes, views)
        return

    relatorio(publicacoes, views)


if __name__ == "__main__":
    main()
