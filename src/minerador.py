#!/usr/bin/env python3
"""
Minerador Shopee Affiliate (GraphQL) — nicho Casa & Construção.

Uso:
  python src/minerador.py --testar          # valida credencial, busca e link
  python src/minerador.py --stats           # calibra cortes + diagnostico (nao grava)
  python src/minerador.py --seco            # mostra o JSON, nao grava
  python src/minerador.py --qtd 5           # grava produtos.json
  python src/minerador.py --nicho "tapete"  # keyword unica
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, timedelta

import requests

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
APP_ID = os.environ.get("SHOPEE_APP_ID", "").strip()
SECRET = os.environ.get("SHOPEE_APP_SECRET", "").strip()

# ---------------------------------------------------------------------------
# CATALOGO DE BUSCA — 30 keywords, todas dentro de Casa & Construcao
# ---------------------------------------------------------------------------
KEYWORDS_CASA = [
    "organizador cozinha",
    "kit facas cozinha",
    "panela de pressão elétrica",
    "air fryer",
    "liquidificador",
    "batedeira",
    "jogo de panelas",
    "potes herméticos",
    "escorredor de louça",
    "torneira cozinha",
    "aspirador portátil",
    "robô aspirador",
    "passadeira a vapor",
    "impermeabilizante spray",
    "percarbonato",
    "ferro de passar roupa",
    "mop giratório",
    "varal de chão",
    "organizador geladeira",
    "cabideiro",
    "sapateira",
    "prateleira organizadora",
    "cesto organizador",
    "jogo de lençol",
    "colchão",
    "travesseiro",
    "cortina blackout",
    "tapete sala",
    "rack para tv",
    "kit ferramentas",
]

# ---------------------------------------------------------------------------
# CORTES
# ---------------------------------------------------------------------------
MIN_COMISSAO = 6.0
MIN_VENDAS = 100
MIN_RATING = 4.4

PAGINAS_POR_KEYWORD = 3
LIMITE_POR_PAGINA = 50
QTD_DEFAULT = 5
DIAS_HISTORICO = 30          # produto pode voltar depois de 30 dias, com angulo novo

HIST = "historico.json"
SAIDA = "produtos.json"
SUBIDS = ["telegram", "video"]

ERROS = {
    10000: "Erro interno da Shopee ou campo inexistente na query.",
    10010: "Query GraphQL com sintaxe invalida.",
    10020: "Assinatura invalida — confira AppId e Secret.",
    10030: "Rate limit — aguarde e reduza a frequencia.",
    10035: "Sem acesso a API — habilite no painel de afiliados.",
    11001: "Parametros invalidos na query.",
}


# ---------------------------------------------------------------------------
# HTTP / GRAPHQL
# ---------------------------------------------------------------------------
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
            code = int(err.get("code")
                       or (err.get("extensions") or {}).get("code") or 0)
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
              "priceDiscountRate sales ratingStar commissionRate commission "
              "shopId shopName")
CAMPOS_MEDIO = ("itemId productName productLink offerLink imageUrl priceMin "
                "sales ratingStar commission")
CAMPOS_MINIMO = "itemId productName sales ratingStar commission"


def _q(campos, keyword, page, limit, extra=""):
    return ('{ productOfferV2(keyword: "%s", page: %d, limit: %d%s) '
            '{ nodes { %s } } }' % (esc(keyword), page, limit, extra, campos))


def buscar(keyword, page=1, limit=LIMITE_POR_PAGINA):
    variantes = [
        ("completa", _q(CAMPOS_MAX, keyword, page, limit,
                        ", listType: 1, sortType: 5")),
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


# ---------------------------------------------------------------------------
# SCORE E ROTEIRO
# ---------------------------------------------------------------------------
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
    "Todo mundo tem esse problema em casa — e isso resolve em segundos.",
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


# ---------------------------------------------------------------------------
# HISTORICO COM PRAZO DE VALIDADE
# ---------------------------------------------------------------------------
def ler_historico():
    """Retorna {item_id: 'YYYY-MM-DD'}. Aceita o formato antigo (lista)."""
    if not os.path.exists(HIST):
        return {}
    try:
        with open(HIST, encoding="utf-8") as f:
            d = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

    hoje = date.today().isoformat()
    if isinstance(d, list):
        return dict((str(x), hoje) for x in d)
    if isinstance(d, dict):
        prods = d.get("produtos")
        if isinstance(prods, dict):
            return dict((str(k), str(v)) for k, v in prods.items())
        return dict((str(k), str(v)) for k, v in d.items()
                    if not str(k).startswith("_"))
    return {}


def _data(txt):
    try:
        return date.fromisoformat(str(txt)[:10])
    except (ValueError, TypeError):
        return date(1970, 1, 1)


def historico_ativos(hist):
    """IDs bloqueados: usados dentro da janela de DIAS_HISTORICO."""
    limite = date.today() - timedelta(days=DIAS_HISTORICO)
    return set([iid for iid, dt in hist.items() if _data(dt) > limite])


def salvar_historico(hist, novos_ids):
    hoje = date.today().isoformat()
    limite = date.today() - timedelta(days=DIAS_HISTORICO)
    registro = {}
    for iid, dt in hist.items():
        if _data(dt) > limite:
            registro[iid] = str(dt)
    for iid in novos_ids:
        registro[str(iid)] = hoje

    payload = {"version": 2, "atualizado": hoje, "produtos": registro}
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return registro


# ---------------------------------------------------------------------------
# DIAGNOSTICO E CALIBRACAO
# ---------------------------------------------------------------------------
def _grade(candidatos, nota_min, vazio_aprova, rotulo):
    vendas_opts = [100, 250, 500, 1000, 2000]
    com_opts = [3, 5, 6, 8, 10]
    print("")
    print(rotulo)
    print("vendas \\ comissao".ljust(20) + "".join("%7d" % c for c in com_opts))
    for v in vendas_opts:
        linha = "%18d" % v
        for c in com_opts:
            n = 0
            for p in candidatos.values():
                try:
                    com = float(p.get("commission") or 0)
                    ven = int(p.get("sales") or 0)
                    bruto = p.get("ratingStar")
                    if bruto in (None, "", 0):
                        if not vazio_aprova:
                            continue
                        nota = nota_min
                    else:
                        nota = float(bruto)
                    if com >= c and ven >= v and nota >= nota_min:
                        n += 1
                except (TypeError, ValueError):
                    pass
            linha += "%7d" % n
        print(linha)


def stats(candidatos):
    total = len(candidatos)
    sem_nota = 0
    sem_comissao = 0
    for p in candidatos.values():
        try:
            if not p.get("ratingStar"):
                sem_nota += 1
            if not p.get("commission"):
                sem_comissao += 1
        except (TypeError, ValueError):
            pass

    print("")
    print("=" * 62)
    print("DIAGNOSTICO DO CATALOGO")
    print("=" * 62)
    print("  candidatos unicos:        %d" % total)
    print("  sem ratingStar:           %d (%.1f%% do total)"
          % (sem_nota, 100.0 * sem_nota / max(total, 1)))
    print("  sem commission:           %d (%.1f%% do total)"
          % (sem_comissao, 100.0 * sem_comissao / max(total, 1)))
    print("")
    if sem_nota > 0:
        print("  ATENCAO: produtos sem nota estao sendo reprovados no corte atual.")
        print("  Compare as duas grades abaixo e decida se vale trata-los como neutros.")
    else:
        print("  Nenhum produto sem nota — o corte de rating nao esta escondendo nada.")

    _grade(candidatos, MIN_RATING, False,
           "GRADE A — nota minima %.1f (produto sem nota REPROVA)" % MIN_RATING)
    _grade(candidatos, MIN_RATING, True,
           "GRADE B — nota minima %.1f (produto sem nota = neutro, APROVA)" % MIN_RATING)

    print("")
    print("Escolha a celula entre 5 e 15 produtos na grade que voce usar.")
    print("Abaixo de 5 trava o pipeline. Acima de 20 traz produto sem prova social.")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
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

    # ---------------- modo teste ----------------
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

    # ---------------- mineracao ----------------
    qtd = max(3, min(a.qtd, 5))
    kws = [a.nicho] if a.nicho else KEYWORDS_CASA
    print("Minerando %d keywords x %d paginas" % (len(kws), PAGINAS_POR_KEYWORD))

    candidatos = {}
    for k in kws:
        acumulado_antes = len(candidatos)
        for pagina in range(1, PAGINAS_POR_KEYWORD + 1):
            try:
                ns = buscar(k, page=pagina)
            except RuntimeError as e:
                print("  '%s' p%d: %s" % (k, pagina, e))
                break
            if not ns:
                break
            for n in ns:
                candidatos[str(n.get("itemId"))] = n
            if len(ns) < LIMITE_POR_PAGINA:
                break
        print("  '%s': +%d" % (k, len(candidatos) - acumulado_antes))

    if not candidatos:
        sys.exit("Nenhum produto retornado. Verifique credencial e keywords.")

    print("")
    print("Total unico minerado: %d" % len(candidatos))

    if a.stats:
        stats(candidatos)
        return

    # ---------------- filtro ----------------
    hist = ler_historico()
    bloqueados = historico_ativos(hist)
    bons = []
    barrados = {"comissao": 0, "vendas": 0, "nota": 0, "repetido": 0}

    for iid, p in candidatos.items():
        if iid in bloqueados:
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

    print("Historico: %d ativos de %d registrados (validade %d dias)"
          % (len(bloqueados), len(hist), DIAS_HISTORICO))
    print("Filtro: %d candidatos | %s" % (len(candidatos), dict(barrados)))
    print("Elegiveis apos filtro: %d | escolhidos: %d" % (len(bons), len(escolhidos)))

    if not escolhidos:
        sys.exit("Nenhum produto passou. Catálogo sem oferta boa hoje — "
                 "rode --stats para recalibrar.")

    # ---------------- saida ----------------
    produtos = []
    for p in escolhidos:
        origem = p.get("productLink") or p.get("offerLink")
        link = ""
        try:
            link = shortlink(origem)
        except RuntimeError as e:
            print("  shortlink falhou (%s); usando offerLink" % e)
        link_final = link or p.get("offerLink") or origem or ""
        titulo = p.get("productName", "")
        texto = roteiro(p)

        # Chaves duplicadas de proposito: qualquer variante de main.py encontra a sua.
        produtos.append({
            "id": str(p.get("itemId")),
            "titulo": titulo,
            "title": titulo,
            "script": texto,
            "narration": texto,
            "texto": texto,
            "link": link_final,
            "url": link_final,
            "hashtags": "#casa #construção #shopee #oferta",
            "preco": p.get("priceMin"),
            "price": p.get("priceMin"),
            "comissao_reais": p.get("commission"),
            "score": p.get("_score"),
            "imagem": p.get("imageUrl"),
            "image": p.get("imageUrl"),
        })

    if a.seco:
        print(json.dumps(produtos, ensure_ascii=False, indent=2))
        return

    with open(SAIDA, "w", encoding="utf-8") as f:
        json.dump(produtos, f, ensure_ascii=False, indent=2)
    salvar_historico(hist, [x["id"] for x in produtos])

    print("")
    print("%d produtos em %s" % (len(produtos), SAIDA))
    for x in produtos:
        print("  · %s | R$ %s | score %s"
              % (x["titulo"][:55], x["comissao_reais"], x["score"]))


if __name__ == "__main__":
    main()
