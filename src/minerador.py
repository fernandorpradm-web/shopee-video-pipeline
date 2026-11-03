#!/usr/bin/env python3
"""
Minerador Shopee Affiliate (GraphQL) — nicho Casa & Construção.

Uso:
  python src/minerador.py --testar          # valida credencial, busca e link
  python src/minerador.py --stats           # grade de calibração (não grava nada)
  python src/minerador.py --seco            # mostra o JSON, não grava
  python src/minerador.py --qtd 5           # grava produtos.json
  python src/minerador.py --nicho "tapete"  # keyword única
"""

import argparse
import hashlib
import json
import os
import sys
import time

import requests

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
APP_ID = os.environ.get("SHOPEE_APP_ID", "").strip()
SECRET = os.environ.get("SHOPEE_APP_SECRET", "").strip()

KEYWORDS_CASA = [
    "organizador cozinha",
    "aspirador portátil",
    "passadeira a vapor",
    "kit facas cozinha",
    "varal de chão",
    "tapete sala",
    "jogo de lençol",
    "panela de pressão elétrica",
    "impermeabilizante spray",
    "percarbonato",
]

MIN_COMISSAO = 6.0
MIN_VENDAS = 250
MIN_RATING = 4.4
QTD_DEFAULT = 5
HIST = "historico.json"
SAIDA = "produtos.json"
SUBIDS = ["telegram", "video"]

ERROS = {
    10000: "Erro interno da Shopee ou campo inexistente na query.",
    10010: "Query GraphQL com sintaxe inválida.",
    10020: "Assinatura inválida — confira AppId e Secret.",
    10030: "Rate limit — aguarde e reduza a frequência.",
    10035: "Sem acesso à API — habilite no painel de afiliados.",
    11001: "Parâmetros inválidos na query.",
}


def _payload(query):
    return json.dumps({"query": query}, separators=(",", ":"))


def _headers(payload):
    ts = str(int(time.time()))
    sig = hashlib.sha256((APP_ID + ts + payload + SECRET).encode()).hexdigest()
    return {
        "Content-Type": "application/json",
        "Authorization": "SHA256 Credential=%s, Timestamp=%s, Signature=%s"
        % (APP_ID, ts, sig),
    }


def gql(query, tentativas=3):
    payload = _payload(query)
    ultimo = None
    for i in range(tentativas):
        r = requests.post(ENDPOINT, data=payload.encode(),
                          headers=_headers(payload), timeout=60)
        try:
            body = r.json()
        except ValueError:
            raise RuntimeError("Resposta nao-JSON (HTTP %s): %s"
                               % (r.status_code, r.text[:300]))

        err = None
        if isinstance(body.get("errors"), list) and body["errors"]:
            err = body["errors"][0]
        elif body.get("error"):
            err = body["error"]

        if err:
            code = int(err.get("code") or (err.get("extensions") or {}).get("code") or 0)
            msg = err.get("message") or ERROS.get(code, "erro desconhecido")
            ultimo = RuntimeError("[%s] %s" % (code, msg))
            if code in (10000, 10001, 10030) and i < tentativas - 1:
                time.sleep(5 * (i + 1))
                continue
            raise ultimo

        if not isinstance(body.get("data"), dict):
            raise RuntimeError("Resposta sem data (HTTP %s): %s"
                               % (r.status_code, str(body)[:300]))
        return body["data"]
    raise ultimo or RuntimeError("Falha desconhecida")


def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


CAMPOS_MAX = ("itemId productName productLink offerLink imageUrl priceMin priceMax "
              "priceDiscountRate sales ratingStar commissionRate commission shopId shopName")
CAMPOS_MEDIO = "itemId productName productLink offerLink imageUrl priceMin sales ratingStar commission"
CAMPOS_MINIMO = "itemId productName"


def _q(campos, keyword, page, limit, extra=""):
    return ('{ productOfferV2(keyword: "%s", page: %d, limit: %d%s) '
            '{ nodes { %s } } }' % (esc(keyword), page, limit, extra, campos))


def buscar(keyword, page=1, limit=50):
    variantes = [
        ("completa", _q(CAMPOS_MAX, keyword, page, limit, ", listType: 1, sortType: 5")),
        ("sem-enums", _q(CAMPOS_MAX, keyword, page, limit, "")),
        ("media", _q(CAMPOS_MEDIO, keyword, page, limit, "")),
        ("minima", _q(CAMPOS_MINIMO, keyword, page, limit, "")),
    ]
    ultimo = None
    for nome, q in variantes:
        try:
            d = gql(q)
        except RuntimeError as e:
            ultimo = e
            continue
        bloco = d.get("productOfferV2")
        if isinstance(bloco, dict) and bloco.get("nodes") is not None:
            return bloco["nodes"]
    raise ultimo or RuntimeError("Todas as variantes de query falharam")


def shortlink(origin):
    q = ('mutation { generateShortLink(input: {originUrl: "%s", subIds: %s}) '
         '{ shortLink } }' % (esc(origin), json.dumps(SUBIDS)))
    bloco = gql(q).get("generateShortLink") or {}
    return bloco.get("shortLink") or ""


def score(p):
    try:
        c = float(p.get("commission") or 0)
        v = int(p.get("sales") or 0)
        r = float(p.get("ratingStar") or 0)
    except (TypeError, ValueError):
        return 0.0
    if c < MIN_COMISSAO or v < MIN_VENDAS or r < MIN_RATING:
        return 0.0
    return round(c * 3 + min(v, 20000) / 1000 + (r - 4.5) * 10, 2)


GANCHOS = [
    "Todo mundo tem esse problema em casa — e esse produto resolve em segundos.",
    "Se voce ja perdeu tempo tentando resolver do jeito dificil, olha isso.",
    "Nao precisa ser pratico pra usar. Olha como funciona.",
    "Eu testei e nao esperava esse resultado.",
    "Isso voce compra uma vez e usa todo dia.",
]
CTAS = [
    "Toque no card e veja o preco.",
    "Toca no card antes que acabe o estoque.",
    "Confere o preco no card.",
]


def roteiro(p):
    key = int(p.get("itemId") or 0)
    g = GANCHOS[key % len(GANCHOS)]
    c = CTAS[key % len(CTAS)]
    preco = p.get("priceMin")
    p_txt = " por R$ %s" % preco if preco else ""
    return "%s %s%s. %s" % (g, p.get("productName", ""), p_txt, c)


def ler_historico():
    if not os.path.exists(HIST):
        return []
    try:
        with open(HIST, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def stats(candidatos):
    """Grade de simulacao: quantos produtos passam por cada combinacao de cortes."""
    vendas_opts = [100, 250, 500, 1000, 2000]
    com_opts = [3, 5, 6, 8, 10]
    print("")
    print("Simulacao de cortes — %d candidatos unicos" % len(candidatos))
    print("Nota minima fixa em 4.4")
    print("")
    print("vendas \\ comissao".ljust(20) + "".join("%7d" % c for c in com_opts))
    for v in vendas_opts:
        linha = ("%18d" % v)
        for c in com_opts:
            n = 0
            for p in candidatos.values():
                try:
                    if (float(p.get("commission") or 0) >= c
                            and int(p.get("sales") or 0) >= v
                            and float(p.get("ratingStar") or 0) >= 4.4):
                        n += 1
                except (TypeError, ValueError):
                    pass
            linha += "%7d" % n
        print(linha)
    print("")
    print("Escolha a celula entre 5 e 15 produtos.")
    print("Abaixo de 5 trava o pipeline. Acima de 20 traz produto sem prova social.")


def main():
    ap = argparse.ArgumentParser(description="Minerador Shopee Affiliate")
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--qtd", type=int, default=QTD_DEFAULT)
    ap.add_argument("--nicho", default="")
    a = ap.parse_args()

    if not APP_ID or not SECRET:
        sys.exit("Faltam SHOPEE_APP_ID / SHOPEE_APP_SECRET no ambiente.")

    kw = a.nicho or KEYWORDS_CASA[0]

    if a.testar:
        print("1) Auth + busca: '%s'" % kw)
        nodes = buscar(kw, limit=5)
        if not nodes:
            sys.exit("Busca OK, mas zero resultados. Reveja a keyword.")
        print("   OK — %d ofertas" % len(nodes))
        for n in nodes[:3]:
            print("   · %s | R$ %s | vendas %s | nota %s"
                  % (str(n.get("productName"))[:55], n.get("commission"),
                     n.get("sales"), n.get("ratingStar")))
        print("2) generateShortLink com subIds")
        origem = nodes[0].get("productLink") or nodes[0].get("offerLink")
        link = shortlink(origem)
        if not link:
            sys.exit("Falhou a geracao de shortlink.")
        print("   OK — %s" % link)
        print("")
        print("Credencial valida e API liberada.")
        return

    qtd = max(3, min(a.qtd, 5))
    kws = [a.nicho] if a.nicho else KEYWORDS_CASA

    candidatos = {}
    for k in kws:
        total_k = 0
        for pagina in (1, 2):
            try:
                ns = buscar(k, page=pagina, limit=50)
            except RuntimeError as e:
                print("  '%s' p%d: %s" % (k, pagina, e))
                break
            if not ns:
                break
            total_k += len(ns)
            for n in ns:
                candidatos[str(n.get("itemId"))] = n
            if len(ns) < 50:
                break
        print("  '%s': %d" % (k, total_k))

    if not candidatos:
        sys.exit("Nenhum produto retornado. Verifique credencial e keywords.")

    print("")
    print("Total unico minerado: %d" % len(candidatos))

    if a.stats:
        stats(candidatos)
        return

    usados = set(map(str, ler_historico()))
    bons = []
    barrados = {"comissao": 0, "vendas": 0, "nota": 0, "repetido": 0}

    for iid, p in candidatos.items():
        if iid in usados:
            barrados["repetido"] += 1
            continue
        s = score(p)
        if s <= 0:
            try:
                if float(p.get("commission") or 0) < MIN_COMISSAO:
                    barrados["comissao"] += 1
                elif int(p.get("sales") or 0) < MIN_VENDAS:
                    barrados["vendas"] += 1
                else:
                    barrados["nota"] += 1
            except (TypeError, ValueError):
                barrados["comissao"] += 1
            continue
        p["_score"] = s
        bons.append(p)

    bons.sort(key=lambda x: x["_score"], reverse=True)
    escolhidos = bons[:qtd]

    print("Filtro: %d candidatos | %s" % (len(candidatos), dict(barrados)))

    if not escolhidos:
        sys.exit("Nenhum produto passou. O nicho esta sem oferta boa hoje.")

    produtos = []
    for p in escolhidos:
        origem = p.get("productLink") or p.get("offerLink")
        link = ""
        try:
            link = shortlink(origem)
        except RuntimeError as e:
            print("  shortlink falhou (%s); usando offerLink" % e)
        produtos.append({
            "id": str(p.get("itemId")),
            "titulo": p.get("productName", ""),
            "script": roteiro(p),
            "link": link or p.get("offerLink") or origem or "",
            "hashtags": "#casa #construção #shopee #oferta",
            "preco": p.get("priceMin"),
            "comissao_reais": p.get("commission"),
            "score": p.get("_score"),
            "imagem": p.get("imageUrl"),
        })

    if a.seco:
        print(json.dumps(produtos, ensure_ascii=False, indent=2))
        return

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(produtos, f, ensure_ascii=False, indent=2)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(sorted(usados | set(x["id"] for x in produtos)), f,
                  ensure_ascii=False, indent=2)

    print("")
    print("%d produtos em %s" % (len(produtos), SAIDA))
    for x in produtos:
        print("  · %s | R$ %s | score %s"
              % (x["titulo"][:55], x["comissao_reais"], x["score"]))


if __name__ == "__main__":
    main()
