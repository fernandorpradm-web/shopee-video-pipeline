#!/usr/bin/env python3
"""Diagnóstico do schema da Shopee Affiliate API."""
import hashlib, json, os, sys, time
import requests

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
APP_ID = os.environ.get("SHOPEE_APP_ID", "").strip()
SECRET = os.environ.get("SHOPEE_APP_SECRET", "").strip()


def post(query):
    payload = json.dumps({"query": query}, separators=(",", ":"))
    ts = str(int(time.time()))
    sig = hashlib.sha256((APP_ID + ts + payload + SECRET).encode()).hexdigest()
    r = requests.post(
        ENDPOINT, data=payload.encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"SHA256 Credential={APP_ID}, Timestamp={ts}, Signature={sig}"},
        timeout=60,
    )
    try:
        return r.json()
    except ValueError:
        print(f"HTTP {r.status_code} | corpo não-JSON: {r.text[:400]}")
        sys.exit(1)


def main():
    if not APP_ID or not SECRET:
        sys.exit("Faltam SHOPEE_APP_ID / SHOPEE_APP_SECRET")

    # 1) introspecção está habilitada?
    d = post("{ __schema { queryType { name } mutationType { name } } }")
    if "errors" in d:
        print("INTRESPECÇÃO BLOQUEADA:")
        print(json.dumps(d["errors"], ensure_ascii=False, indent=2)[:800])
        print("\n-> O schema é fechado. Use o Passo 2 (query mínima) para isolar o campo.")
        return
    print("OK: introspecção habilitada.")

    # 2) queries e mutations
    d = post("{ __schema { queryType { fields { name } } mutationType { fields { name } } } }")
    q = [f["name"] for f in d["data"]["__schema"]["queryType"]["fields"]]
    m = [f["name"] for f in (d["data"]["__schema"]["mutationType"] or {}).get("fields", [])]
    print("\nQUERIES:", ", ".join(sorted(q)))
    print("\nMUTATIONS:", ", ".join(sorted(m)) if m else "(nenhuma)")

    # 3) argumentos da operação de produto
    alvo = next((x for x in q if "roduct" in x or "ffer" in x), None)
    if not alvo:
        print("\nNenhuma query de produto encontrada no schema.")
        return
    print(f"\nAnalisando: {alvo}")

    d = post('{ __schema { queryType { fields { name args { name } type { name kind ofType { name } } } } } }')
    campos = d["data"]["__schema"]["queryType"]["fields"]
    f = next((x for x in campos if x["name"] == alvo), None)
    if f:
        print("  argumentos:", ", ".join(a["name"] for a in f["args"]) or "(nenhum)")
        tipo = (f["type"].get("name") or (f["type"].get("ofType") or {}).get("name"))
        print("  tipo de retorno:", tipo)

        # 4) campos do tipo de retorno e do node
        if tipo:
            d2 = post('{{ __type(name: "{}") {{ fields {{ name type {{ name kind ofType {{ name }} }} }} }} }}'.format(tipo))
            tt = d2.get("data", {}).get("__type")
            if tt and tt.get("fields"):
                print(f"\n  campos de {tipo}:")
                for c in tt["fields"]:
                    n = c["type"].get("name") or (c["type"].get("ofType") or {}).get("name")
                    print(f"    - {c['name']}: {n}")


if __name__ == "__main__":
    main()
