#!/usr/bin/env python3
"""
Minerador Shopee Affiliate (GraphQL) — nicho Casa & Construção.
Gera produtos.json + historico.json e links com subIds para atribuição.

Uso:
  python src/minerador.py --testar          # valida credencial, busca e link
  python src/minerador.py --qtd 5           # gera produtos.json
  python src/minerador.py --nicho "tapete"  # keyword única
  python src/minerador.py --seco            # não grava arquivos
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

MIN_COMISSAO = 6.0     # era 8.0 — o pago está pausado, orgânico não tem custo por clique
MIN_VENDAS = 250       # era 500 — libera a faixa de bestseller intermediário
MIN_RATING = 4.4       # era 4.5 — o corte de 4.5 nunca barrou nada
QTD_DEFAULT = 5
HIST = "historico.json"
SAIDA = "produtos.json"
SUBIDS = ["telegram", "video"]

ERROS = {
    10010: "Query GraphQL com sintaxe inválida.",
    10020: "Assinatura inválida — confira AppId, Secret e a origem do AppId.",
    10030: "Rate limit — aguarde e reduza a frequência.",
    10035: "Sem acesso à API — solicite habilitação no painel de afiliados.",
    11001: "Parâmetros inválidos na query.",
}


def _payload(query: str) -> str:
    # ensure_ascii=True garante corpo ASCII puro: elimina ambiguidade de encoding na assinatura
    return json.dumps({"query": query}, separators=(",", ":"))


def _headers(payload: str) -> dict:
    ts = str(int(time.time()))
    sig = hashlib.sha256((APP_ID + ts + payload + SECRET).encode()).hexdigest()
    return {
        "Content-Type": "application/json",
        "Authorization": f"SHA256 Credential={APP_ID}, Timestamp={ts}, Signature={sig}",
    }


def gql(query: str, tentativas: int = 3) -> dict:
    payload = _payload(query)
    for i in range(tentativas):
        r = requests.post(ENDPOINT, data=payload.encode(), headers=_headers(payload), timeout=60)
        try:
            body = r.json()
        except ValueError:
            raise RuntimeError(f"Resposta não-JSON (HTTP {r.status_code}): {r.text[:300]}")

        err = None
        if isinstance(body.get("errors"), list) and body["errors"]:
            err = body["errors"][0]
        elif body.get("error"):
            err = body["error"]

        if err:
            code = int(err.get("code") or (err.get("extensions") or {}).get("code") or 0)
            msg = err.get("message") or ERROS.get(code, "erro desconhecido")
            if code == 10030 and i < tentativas - 1:
                time.sleep(5 * (i + 1))
                continue
            raise RuntimeError(f"[{code}] {msg}")

        if not isinstance(body.get("data"), dict):
            raise RuntimeError(f"Resposta sem data (HTTP {r.status_code}): {str(body)[:300]}")
        return body["data"]


def esc(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace('"', '\\"')


def buscar(keyword: str, page: int = 1, limit: int = 50) -> list:
    q = f"""{{ productOfferV2(keyword: "{esc(keyword)}", listType: 1, sortType: 5, page: {page}, limit: {limit}) {{
      nodes {{ itemId productName productLink offerLink imageUrl priceMin priceMax
               priceDiscountRate sales ratingStar commissionRate commission shopId shopName }}
      pageInfo {{ page limit hasNextPage }} }} }}"""
    return (gql(q).get("productOfferV2") or {}).get("nodes") or []


def shortlink(origin: str) -> str:
    q = f"""mutation {{ generateShortLink(input: {{originUrl: "{esc(origin)}", subIds: {json.dumps(SUBIDS)}}}) {{ shortLink }} }}"""
    return ((gql(q).get("generateShortLink") or {}).get("shortLink")) or ""


def score(p: dict) -> float:
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
    "Se você já perdeu tempo tentando resolver do jeito difícil, olha isso.",
    "Não precisa ser prático pra usar. Olha como funciona.",
    "Eu testei e não esperava esse resultado.",
    "Isso você compra uma vez e usa todo dia.",
]
CTAS = [
    "Toque no card e veja o preço.",
    "Toca no card antes que acabe o estoque.",
    "Confere o preço no card — tá barato.",
]


def roteiro(p: dict) -> str:
    key = int(p.get("itemId") or 0)
    g = GANCHOS[key % len(GANCHOS)]
    c = CTAS[key % len(CTAS)]
    preco = p.get("priceMin")
    p_txt = f" por R$ {preco}" if preco else ""
    return f"{g} {p.get('productName','')}{p_txt}. {c}"


def ler_historico() -> list:
    if not os.path.exists(HIST):
        return []
    try:
        with open(HIST, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (json.JSONDecodeError, OSError):
        return []

def stats(candidatos: dict) -> None:
    """Grade de simulação: quantos produtos passariam por cada combinação de cortes."""
    vos = [100, 250, 500, 1000, 2000]
    coms = [3, 5, 6, 8, 10]
    print(f"\nSimulacao de cortes — {len(candidatos)} candidatos")
    print("vendas \\ comissao".ljust(20) + "".join(f"{c:>7}" for c in coms))
    for v in vos:
        linha = f"{v:>18}"
        for c in coms:
            n = 0
            for p in candidatos.values():
                try:
                    if (float(p.get("commission") or 0) >= c
                            and int(p.get("sales") or 0) >= v
                            and float(p.get("ratingStar") or 0) >= 4.4):
                        n += 1
                except (TypeError, ValueError):
                    pass
            linha += f"{n:>7}"
        print(linha)
    print("\nEscolha a celula entre 5 e 15 produtos.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--stats", action="store_true", help="grade de calibração de cortes")
    ap.add_argument("--qtd", type=int, default=QTD_DEFAULT)
    ap.add_argument("--nicho", default="")
    a = ap.parse_args()

    if not APP_ID or not SECRET:
        sys.exit("Faltam SHOPEE_APP_ID / SHOPEE_APP_SECRET no ambiente.")

    kw = a.nicho or KEYWORDS_CASA[0]

    if a.testar:
        print(f"1) Auth + busca: '{kw}'")
        nodes = buscar(kw, limit=5)
        if not nodes:
            sys.exit("Busca OK, mas zero resultados. Reveja a keyword.")
        print(f"   OK — {len(nodes)} ofertas.")
        for n in nodes[:3]:
            print(f"   · {str(n.get('productName'))[:60]} | R$ {n.get('commission')} | vendas {n.get('sales')} | nota {n.get('ratingStar')}")

        print("2) generateShortLink com subIds")
        link = shortlink(nodes[0].get("productLink") or nodes[0].get("offerLink"))
        if not link:
            sys.exit("Falhou a geração de shortlink.")
        print(f"   OK — {link}")
        print("\nCredencial válida e API liberada.")
        return

    qtd = max(3, min(a.qtd, 5))
    kws = [a.nicho] if a.nicho else KEYWORDS_CASA

     candidatos = {}
     for k in kws:
        for pagina in (1, 2):
            try:
                ns = buscar(k, page=pagina, limit=50)
            except Exception as e:
                print(f"  '{k}' p{pagina}: {e}")
                break
            if not ns:
                break
            for n in ns:
                candidatos[str(n.get("itemId"))] = n
            if len(ns) < 50:
                break
        print(f"  '{k}': {len(candidatos)} acumulados")

    if not candidatos:
        sys.exit("Nenhum produto retornado. Verifique credencial e keywords.")

    usados = set(map(str, ler_historico()))
    bons, barrados = [], {"comissao": 0, "vendas": 0, "nota": 0, "repetido": 0}

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

    if a.stats:
        stats(candidatos)
        return
    print(f"\nFiltro: {len(candidatos)} candidatos | {dict(barrados)}")

    if not escolhidos:
        sys.exit("Nenhum produto passou. O nicho está sem oferta boa hoje — mantenha o histórico e tente amanhã.")

    produtos = []
    for p in escolhidos:
        origem = p.get("productLink") or p.get("offerLink")
        link = ""
        try:
            link = shortlink(origem)
        except Exception as e:
            print(f"  shortlink falhou ({e}); usando offerLink")
        produtos.append({
            "id": str(p.get("itemId")),
            "titulo": p.get("productName", ""),
            "script": roteiro(p),
            "link": link or p.get("offerLink") or origem,
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
        json.dump(sorted(usados | {x["id"] for x in produtos}), f, ensure_ascii=False, indent=2)

    print(f"\n{len(produtos)} produtos em {SAIDA}")
    for x in produtos:
        print(f"  · {x['titulo'][:55]} | R$ {x['comissao_reais']} | score {x['score']}")


if __name__ == "__main__":
    main()
