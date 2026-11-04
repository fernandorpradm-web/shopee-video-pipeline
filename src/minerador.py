#!/usr/bin/env python3
"""
Minerador Shopee Affiliate (GraphQL) — multi-nicho.

Nichos ativos por padrao: casa + beleza (60 keywords).
Pet disponivel via --nicho pet ou --nicho todos (90 keywords).

Uso:
  python src/minerador.py --testar
  python src/minerador.py --stats
  python src/minerador.py --seco
  python src/minerador.py --qtd 3
  python src/minerador.py --nicho todos
  python src/minerador.py --keyword "tapete sala"
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import date, timedelta

import requests

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
APP_ID = os.environ.get("SHOPEE_APP_ID", "").strip()
SECRET = os.environ.get("SHOPEE_APP_SECRET", "").strip()

# ---------------------------------------------------------------------------
# KEYWORDS POR NICHO
# ---------------------------------------------------------------------------
NICHOS = {
    "casa": [
        "organizador cozinha", "kit facas cozinha", "panela de pressão elétrica",
        "air fryer", "liquidificador", "batedeira", "jogo de panelas",
        "potes herméticos", "escorredor de louça", "torneira cozinha",
        "aspirador portátil", "robô aspirador", "passadeira a vapor",
        "impermeabilizante spray", "percarbonato", "ferro de passar roupa",
        "mop giratório", "varal de chão", "organizador geladeira",
        "cabideiro", "sapateira", "prateleira organizadora",
        "cesto organizador", "jogo de lençol", "colchão", "travesseiro",
        "cortina blackout", "tapete sala", "rack para tv", "kit ferramentas",
    ],
    "beleza": [
        "creme anti-idade facial", "sérum vitamina c", "protetor solar facial",
        "creme para rugas", "hidratante corporal", "óleo capilar",
        "máscara capilar", "escova secadora", "prancha alisadora",
        "secador de cabelo", "kit escova alisadora", "base facial",
        "corretivo de olheiras", "batom matte", "paleta de sombras",
        "rímel alongador", "esmalte gel", "kit unhas de gel",
        "creme para mãos", "creme para pés", "esfoliante facial",
        "ácido hialurônico", "colágeno em pó", "biotina cabelo unhas",
        "óleo de argan", "modelador de cachos", "chapinha profissional",
        "kit pincéis maquiagem", "depilador elétrico", "massageador facial",
    ],
    "pet": [
        "ração para cães", "ração para gatos", "areia para gato",
        "arranhador para gato", "caminha para cachorro", "coleira antipulgas",
        "brinquedo para cachorro", "comedouro automático", "bebedouro para gatos",
        "tapete higiênico", "escova para pets", "cortador de unha pet",
        "shampoo para cachorro", "peitoral para cães", "caixa de transporte pet",
        "cama para gato", "arranhador torre", "kit brinquedos gato",
        "suplemento para cães", "petisco natural para cães",
        "escova removedora de pelos", "aspirador de pelos pet",
        "fonte de água para gatos", "mochila transportar pet",
        "cama iglu para gato", "comedouro lento", "tapete de alimentação pet",
        "antipulgas spray", "vermífugo para cães", "kit higiene para gatos",
    ],
}

NICHOS_ATIVOS = ["casa", "beleza"]

# ---------------------------------------------------------------------------
# CORTES
# ---------------------------------------------------------------------------
MIN_COMISSAO = 6.0
MIN_VENDAS = 100
MIN_RATING = 4.4

MIN_TICKET = 25.0
MAX_TICKET = 200.0

PAGINAS_POR_KEYWORD = 3
LIMITE_POR_PAGINA = 50
PAUSA_ENTRE_KEYWORDS = 0.4

QTD_DEFAULT = 3
DIAS_HISTORICO_MAX = 30
MARGEM_CICLO = 0.8

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
# TEXTO PARA O TTS
# ---------------------------------------------------------------------------
TRADUZIR = {
    "oil control": "controle de oleosidade",
    "mattifying": "matificante",
    "matte finish": "acabamento seco",
    "sun stick": "bastão protetor solar",
    "sun screen": "protetor solar",
    "sunscreen": "protetor solar",
    "long lasting": "longa duração",
    "waterproof": "à prova d'água",
    "semi permanent": "semipermanente",
    "hair dryer": "secador de cabelo",
    "hair mask": "máscara capilar",
    "hair oil": "óleo capilar",
    "face wash": "sabonete facial",
    "cleanser": "sabonete facial",
    "makeup": "maquiagem",
    "shampoo": "shampoo",
    "serum": "sérum",
    "cream": "creme",
    "lotion": "loção",
    "spray": "spray",
    "mask": "máscara",
    "brush": "escova",
    "comb": "pente",
    "set": "kit",
    "kit": "kit",
    "gift": "presente",
    "oil": "óleo",
    "hair": "cabelo",
    "skin": "pele",
    "gel": "gel",
}

LIXO_TITULO = {
    "premium", "profissional", "multiuso", "moderna", "moderno", "decoracao",
    "decoração", "livros", "banheiro", "cozinha", "sala", "bivolt", "original",
    "novo", "nova", "importado", "com", "de", "da", "do", "das", "dos",
    "para", "pra", "e", "em", "a", "o", "os", "as", "por", "aco", "aço",
    "inox", "f", "unidade", "un", "pcs", "kit", "dry", "felpudo",
}


def traduzir(titulo):
    """Troca termos em ingles por portugues antes de falar."""
    t = str(titulo)
    for en in sorted(TRADUZIR, key=len, reverse=True):
        if en in t.lower():
            t = re.sub(re.escape(en), TRADUZIR[en], t, flags=re.I)
    return t


def falar_preco(valor):
    """349.9 -> '349 reais e 90 centavos'. O TTS le corretamente."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return ""
    if v <= 0:
        return ""
    reais = int(v)
    cents = int(round((v - reais) * 100))
    if cents == 0:
        return "%d reais" % reais
    if cents < 10:
        return "%d reais e 0%d centavos" % (reais, cents)
    return "%d reais e %d centavos" % (reais, cents)


def nome_curto(titulo, limite=42):
    """Reduz o titulo do marketplace a algo falavel em 2 segundos."""
    palavras = []
    for p in traduzir(titulo).split():
        limpo = p.strip(",.;:-–—()º°")
        if not limpo:
            continue
        baixo = limpo.lower()
        if baixo in LIXO_TITULO:
            continue
        if any(ch.isdigit() for ch in limpo) and len(limpo) > 4:
            continue
        if len(limpo) == 1:
            continue
        palavras.append(limpo)
        if len(" ".join(palavras)) >= limite:
            break

    curto = " ".join(palavras).strip()
    if len(curto) > limite:
        curto = curto[:limite].rsplit(" ", 1)[0]
    return curto or traduzir(titulo)[:limite].strip()


# ---------------------------------------------------------------------------
# GANCHOS POR NICHO
# ---------------------------------------------------------------------------
GANCHOS_CASA = [
    "Todo mundo tem esse problema em casa — e isso resolve em segundos.",
    "Olha o antes e depois. Não precisa fazer força.",
    "Isso você compra uma vez e usa todo dia.",
    "Eu testei e não esperava esse resultado.",
    "Se você já perdeu tempo tentando do jeito difícil, olha isso.",
    "Não precisa ser prático pra usar. Olha como funciona.",
    "Repara como resolve em um movimento só.",
    "Isso caberia na sua casa hoje mesmo.",
    "Quem tem esse problema vai entender na hora.",
    "Simples, barato e resolve o que ninguém resolve.",
]

GANCHOS_BELEZA = [
    "Olha a textura. Não pesa e não deixa brilho.",
    "Eu uso isso todo dia antes de sair de casa.",
    "Olha como espalha rápido e não fica pegajoso.",
    "Isso resolve o que maquiagem sozinha não cobre.",
    "A diferença aparece já na primeira semana.",
    "Não precisa de sete produtos. Um resolve.",
    "Olha o resultado depois de aplicar.",
    "Rende muito mais do que parece.",
    "Pra quem tem pele oleosa, presta atenção nisso.",
    "Simples de usar, e o resultado aparece.",
]

GANCHOS_PET = [
    "Quem tem pet em casa sabe o quanto isso ajuda.",
    "Olha como ele usa na hora.",
    "Isso resolve aquela bagunça que ninguém aguenta.",
    "Testei com o meu e funcionou.",
    "Se você tem pet, vai querer isso.",
]

CTAS = [
    "Toque no card e veja o preço.",
    "Toca no card antes que acabe o estoque.",
    "Confere o preço no card.",
    "O link está no card.",
    "Toca no card e aproveita.",
    "Preço no card, enquanto durar.",
]


def _ganchos(nicho):
    if nicho == "beleza":
        return GANCHOS_BELEZA
    if nicho == "pet":
        return GANCHOS_PET
    return GANCHOS_CASA


def roteiro(p, janela):
    """Gancho coerente com o nicho e rotacionado por data."""
    nicho = p.get("_nicho", "casa")
    ganchos = _ganchos(nicho)
    rotacao = date.today().toordinal() // max(janela, 1)
    base = int(p.get("itemId") or 0)
    key = base + rotacao * 7
    gancho = ganchos[key % len(ganchos)]
    cta = CTAS[(key // 3) % len(CTAS)]
    item = nome_curto(p.get("productName", ""))
    preco = falar_preco(p.get("priceMin"))
    p_txt = " por %s" % preco if preco else ""
    texto = "%s %s%s. %s" % (gancho, item, p_txt, cta)
    return texto, key % len(ganchos)


# ---------------------------------------------------------------------------
# SCORE
# ---------------------------------------------------------------------------
def score(p):
    """Comissao pesa 1.5x, vendas pesam forte. Teto de ticket aplicado."""
    try:
        c = float(p.get("commission") or 0)
        v = int(p.get("sales") or 0)
        r = float(p.get("ratingStar") or 0)
        preco = float(p.get("priceMin") or 0)
    except (TypeError, ValueError):
        return 0.0

    if c < MIN_COMISSAO or v < MIN_VENDAS or r < MIN_RATING:
        return 0.0
    if preco < MIN_TICKET:
        return 0.0
    if MAX_TICKET > 0 and preco > MAX_TICKET:
        return 0.0

    return round(c * 1.5 + min(v, 20000) / 200.0 + (r - 4.5) * 10, 2)


# ---------------------------------------------------------------------------
# HISTORICO COM JANELA DINAMICA
# ---------------------------------------------------------------------------
def _data(txt):
    try:
        return date.fromisoformat(str(txt)[:10])
    except (ValueError, TypeError):
        return date(1970, 1, 1)


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


def janela_ideal(pool, qtd):
    """Dias que o ciclo sustenta com 20% de margem. Nunca trava o pipeline."""
    if pool <= 0 or qtd <= 0:
        return 7
    return max(7, int(pool / qtd * MARGEM_CICLO))


def historico_ativos(hist, janela):
    limite = date.today() - timedelta(days=janela)
    return set(iid for iid, dt in hist.items() if _data(dt) > limite)


def salvar_historico(hist, novos_ids, janela):
    hoje = date.today().isoformat()
    limite = date.today() - timedelta(days=janela)
    registro = dict((iid, str(dt)) for iid, dt in hist.items()
                    if _data(dt) > limite)
    for iid in novos_ids:
        registro[str(iid)] = hoje

    payload = {"version": 2, "atualizado": hoje, "janela_dias": janela,
               "produtos": registro}
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return registro


# ---------------------------------------------------------------------------
# DIAGNOSTICO
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


def _contar_elegiveis(candidatos, aplicar_teto):
    n = 0
    for p in candidatos.values():
        try:
            com = float(p.get("commission") or 0)
            ven = int(p.get("sales") or 0)
            nota = float(p.get("ratingStar") or 0)
            preco = float(p.get("priceMin") or 0)
        except (TypeError, ValueError):
            continue
        if com < MIN_COMISSAO or ven < MIN_VENDAS or nota < MIN_RATING:
            continue
        if preco < MIN_TICKET:
            continue
        if aplicar_teto and MAX_TICKET > 0 and preco > MAX_TICKET:
            continue
        n += 1
    return n


def _elegiveis_por_nicho(candidatos):
    out = {}
    for p in candidatos.values():
        try:
            com = float(p.get("commission") or 0)
            ven = int(p.get("sales") or 0)
            nota = float(p.get("ratingStar") or 0)
            preco = float(p.get("priceMin") or 0)
        except (TypeError, ValueError):
            continue
        if com < MIN_COMISSAO or ven < MIN_VENDAS or nota < MIN_RATING:
            continue
        if preco < MIN_TICKET:
            continue
        if MAX_TICKET > 0 and preco > MAX_TICKET:
            continue
        n = p.get("_nicho", "?")
        out[n] = out.get(n, 0) + 1
    return out


def stats(candidatos):
    total = len(candidatos)
    sem_nota = sum(1 for p in candidatos.values() if not p.get("ratingStar"))
    sem_com = sum(1 for p in candidatos.values() if not p.get("commission"))

    por_nicho = {}
    for p in candidatos.values():
        n = p.get("_nicho", "?")
        por_nicho[n] = por_nicho.get(n, 0) + 1

    sem_teto = _contar_elegiveis(candidatos, False)
    com_teto = _contar_elegiveis(candidatos, True)
    por_nicho_ok = _elegiveis_por_nicho(candidatos)

    print("")
    print("=" * 62)
    print("DIAGNOSTICO DO CATALOGO")
    print("=" * 62)
    print("  candidatos unicos:    %d" % total)
    print("  por nicho:            %s" % por_nicho)
    print("  sem ratingStar:       %d (%.1f%%)"
          % (sem_nota, 100.0 * sem_nota / max(total, 1)))
    print("  sem commission:       %d (%.1f%%)"
          % (sem_com, 100.0 * sem_com / max(total, 1)))
    print("")
    print("  corte atual:          comissao >= R$ %.0f | vendas >= %d | nota >= %.1f"
          % (MIN_COMISSAO, MIN_VENDAS, MIN_RATING))
    print("  ticket:               R$ %.0f a R$ %.0f"
          % (MIN_TICKET, MAX_TICKET if MAX_TICKET > 0 else 999999))
    print("  elegiveis sem teto:   %d" % sem_teto)
    print("  elegiveis com teto:   %d  (barrados por ticket: %d)"
          % (com_teto, sem_teto - com_teto))
    print("  elegiveis por nicho:  %s" % por_nicho_ok)
    print("")
    if com_teto > 0:
        j = janela_ideal(com_teto, QTD_DEFAULT)
        print("  janela calculada:     %d dias a %d videos/dia"
              % (min(DIAS_HISTORICO_MAX, j), QTD_DEFAULT))
        dias = com_teto / float(QTD_DEFAULT)
        print("  folego total:         %.1f dias sem repetir" % dias)
    if sem_nota > 0:
        print("")
        print("  ATENCAO: produtos sem nota estao sendo reprovados.")

    _grade(candidatos, MIN_RATING, False,
           "GRADE A — nota %.1f (sem nota REPROVA)" % MIN_RATING)
    _grade(candidatos, MIN_RATING, True,
           "GRADE B — nota %.1f (sem nota = neutro, APROVA)" % MIN_RATING)

    print("")
    print("As grades NAO aplicam o teto de ticket. Use 'elegiveis com teto'")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def _resolver_keywords(a):
    if a.keyword:
        return [a.keyword], "keyword unica"
    if a.nicho == "todos":
        kws = []
        for nome in NICHOS:
            kws.extend(NICHOS[nome])
        return kws, "todos os nichos"
    if a.nicho in NICHOS:
        return NICHOS[a.nicho], "nicho %s" % a.nicho
    kws = []
    for nome in NICHOS_ATIVOS:
        kws.extend(NICHOS[nome])
    return kws, "nichos ativos: %s" % ", ".join(NICHOS_ATIVOS)


def _nicho_de(keyword, a):
    if a.keyword:
        return "avulso"
    for nome, lista in NICHOS.items():
        if keyword in lista:
            return nome
    return "?"


def main():
    ap = argparse.ArgumentParser(description="Minerador Shopee Affiliate")
    ap.add_argument("--testar", action="store_true")
    ap.add_argument("--seco", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--qtd", type=int, default=QTD_DEFAULT)
    ap.add_argument("--nicho", default="",
                    choices=["", "casa", "beleza", "pet", "todos"])
    ap.add_argument("--keyword", default="")
    a = ap.parse_args()

    if not APP_ID or not SECRET:
        sys.exit("Faltam SHOPEE_APP_ID / SHOPEE_APP_SECRET no ambiente.")

    kws, rotulo = _resolver_keywords(a)

    # ---------------- modo teste ----------------
    if a.testar:
        print("1) Auth + busca: '%s'" % kws[0])
        nodes = buscar(kws[0], limit=5)
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
    print("Minerando %d keywords x %d paginas (%s)"
          % (len(kws), PAGINAS_POR_KEYWORD, rotulo))

    candidatos = {}
    for k in kws:
        antes = len(candidatos)
        for pagina in range(1, PAGINAS_POR_KEYWORD + 1):
            try:
                ns = buscar(k, page=pagina)
            except RuntimeError as e:
                print("  '%s' p%d: %s" % (k, pagina, e))
                break
            if not ns:
                break
            for n in ns:
                n["_nicho"] = _nicho_de(k, a)
                candidatos[str(n.get("itemId"))] = n
            if len(ns) < LIMITE_POR_PAGINA:
                break
        print("  '%s': +%d" % (k, len(candidatos) - antes))
        time.sleep(PAUSA_ENTRE_KEYWORDS)

    if not candidatos:
        sys.exit("Nenhum produto retornado. Verifique credencial e keywords.")

    print("")
    print("Total unico minerado: %d" % len(candidatos))

    if a.stats:
        stats(candidatos)
        return

    # 1) elegibilidade
    elegiveis = []
    barrados = {"comissao": 0, "vendas": 0, "nota": 0, "ticket": 0}
    for iid, p in candidatos.items():
        s = score(p)
        if s <= 0:
            try:
                preco = float(p.get("priceMin") or 0)
                if float(p.get("commission") or 0) < MIN_COMISSAO:
                    barrados["comissao"] += 1
                elif int(p.get("sales") or 0) < MIN_VENDAS:
                    barrados["vendas"] += 1
                elif float(p.get("ratingStar") or 0) < MIN_RATING:
                    barrados["nota"] += 1
                elif preco < MIN_TICKET or (MAX_TICKET > 0 and preco > MAX_TICKET):
                    barrados["ticket"] += 1
                else:
                    barrados["comissao"] += 1
            except (TypeError, ValueError):
                barrados["comissao"] += 1
            continue
        p["_score"] = s
        elegiveis.append(p)

    # 2) janela calculada do pool real
    janela = min(DIAS_HISTORICO_MAX, janela_ideal(len(elegiveis), qtd))

    # 3) historico com a janela calculada
    hist = ler_historico()
    bloqueados = historico_ativos(hist, janela)
    livres = [p for p in elegiveis if str(p.get("itemId")) not in bloqueados]

    livres.sort(key=lambda x: x["_score"], reverse=True)
    escolhidos = livres[:qtd]

    print("Filtro: %d candidatos | %s" % (len(candidatos), barrados))
    print("Historico: %d registros | janela: %d dias | bloqueados: %d"
          % (len(hist), janela, len(bloqueados)))
    print("Elegiveis: %d | livres: %d" % (len(elegiveis), len(livres)))
    if not hist:
        print("")
        print("AVISO: historico.json vazio ou inexistente.")
        print("Todos os produtos estao livres — o controle de repeticao")
        print("so passa a valer depois do primeiro run real (sem --seco).")
    if len(livres) < qtd:
        print("AVISO: pool livre menor que a quantidade pedida (%d)." % qtd)

    if not escolhidos:
        sys.exit("Nenhum produto livre. Catalogo esgotado — rode --stats "
                 "para recalibrar ou amplie as keywords.")

    # 4) saida
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
        texto, gancho_id = roteiro(p, janela)

        produtos.append({
            "id": str(p.get("itemId")),
            "titulo": titulo,
            "title": titulo,
            "texto_tela": nome_curto(titulo, 40),
            "script": texto,
            "narration": texto,
            "texto": texto,
            "link": link_final,
            "url": link_final,
            "hashtags": "#casa #beleza #shopee #oferta",
            "nicho": p.get("_nicho", "?"),
            "gancho_id": gancho_id,
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
    salvar_historico(hist, [x["id"] for x in produtos], janela)

    print("")
    print("%d produtos em %s (janela %d dias)"
          % (len(produtos), SAIDA, janela))
    for x in produtos:
        print("  · [%s] %s | R$ %s | gancho %d"
              % (x["nicho"], x["titulo"][:44],
                 x["comissao_reais"], x["gancho_id"]))
        print("    script: %s" % x["script"][:120])
        print("    tela:   %s" % x["texto_tela"])


if __name__ == "__main__":
    main()
