"""Verifica a ligação ao ollama antes de correr um lote.

    python diagnostico.py gemma4:e4b

Faz três perguntas por ordem, e pára na primeira que falhar: o servidor
responde, o modelo existe, e o modelo aguenta o prompt de produção inteiro com
o contexto configurado.
"""

import json
import sys
import urllib.error
import urllib.request

from config import MAX_TOKENS, OLLAMA_CONTEXTO, OLLAMA_URL, TEMPERATURA
from prompt import get


def _pedir(caminho: str, corpo: dict | None = None, timeout: int = 300):
    dados = json.dumps(corpo).encode() if corpo else None
    pedido = urllib.request.Request(
        OLLAMA_URL + caminho, data=dados,
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"  FALHOU  {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")
    except OSError as e:
        sys.exit(f"  FALHOU  {e}")


def main() -> None:
    modelo = sys.argv[1] if len(sys.argv) > 1 else "gemma4:e4b"
    print(f"servidor : {OLLAMA_URL}")
    print(f"modelo   : {modelo}")
    print(f"contexto : {OLLAMA_CONTEXTO}\n")

    instalados = [m["name"] for m in _pedir("/api/tags", timeout=30).get("models", [])]
    print("1. servidor responde, %d modelos instalados" % len(instalados))
    if modelo not in instalados:
        sys.exit(f"  FALHOU  '{modelo}' não está instalado. Instalados:\n   "
                 + "\n   ".join(instalados))
    print("2. modelo instalado")

    sistema = get("c01")
    print(f"3. prompt de produção: {len(sistema)} caracteres, "
          f"~{len(sistema)//4} tokens")

    r = _pedir("/api/chat", {
        "model": modelo, "format": "json", "stream": False,
        "options": {"temperature": TEMPERATURA, "num_predict": MAX_TOKENS,
                    "num_ctx": OLLAMA_CONTEXTO},
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content":
                      "<report>\n  rel  Falei com o cliente, sem necessidade "
                      "de material de momento.\n</report>"}],
    })
    print("4. resposta obtida, %d tokens de entrada, %d de saída"
          % (r.get("prompt_eval_count") or 0, r.get("eval_count") or 0))
    print("\n" + r["message"]["content"].strip()[:400])
    print("\nTudo bem. Podes correr o run.py.")


if __name__ == "__main__":
    main()
