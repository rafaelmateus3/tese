"""Configuração do classificador."""

import os
from pathlib import Path

from dotenv import load_dotenv

# O .env está na raiz do projeto, para que todos os módulos partilhem as mesmas
# credenciais seja de onde for que se corram.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Por omissão, a tarefa e o modelo avaliados e em uso (Cap. 6): prompt c05r,
# esquema e05 (esquema.py), entrada v3 e gemma4:26b no servidor local.
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "c05r")
ENTRADA_VERSION = os.getenv("ENTRADA_VERSION", "v3")

MODELO = os.getenv("MODELO", "gemma4:26b")
BACKEND = os.getenv("BACKEND", "ollama")   # ollama | anthropic | openai

# Pasta onde o ERP deixa as extrações (visitas_*, linhas_faturas_*, equipamentos_*).
ERP_PASTA = Path(os.getenv("ERP_PASTA", str(Path(__file__).resolve().parents[1] / "extracoes")))
# Faturação usada pelo sistema a partir desta data: a mesma janela das extrações com que a
# tarefa foi avaliada (a exportação do Metabase passou a trazer o histórico desde 2006).
FATURAS_DESDE = os.getenv("FATURAS_DESDE", "2024-01-01")
# Arranque do uso pelos comerciais: a revisão do dia só pede dias a partir desta data.
# O histórico anterior corrige-se na carteira, negócio a negócio (decisão de 15-Out-2026).
REVISAO_DESDE = os.getenv("REVISAO_DESDE", "2026-10-12")
TEMPERATURA = 0.0          # RF1.5: a mesma entrada produz sempre a mesma saída

# A saída válida tem cerca de 100 tokens, mas modelos que emitem raciocínio
# antes da resposta gastam o orçamento e terminam por limite de comprimento,
# devolvendo JSON incompleto.
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
PAUSA_SEG = 0.4            # entre chamadas, para não saturar a API

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# O prompt de sistema ocupa cerca de 4.000 tokens. O contexto por omissão do
# ollama é menor do que isso em vários modelos e truncaria o prompt em silêncio.
OLLAMA_CONTEXTO = int(os.getenv("OLLAMA_CONTEXTO", "16384"))
# O raciocínio explícito foi rejeitado por avaliação e só gasta orçamento de
# geração. Desliga-se onde o modelo o suporte; onde não suporte, o pedido é
# repetido sem o campo.
OLLAMA_PENSAR = os.getenv("OLLAMA_PENSAR", "0") == "1"
# Quanto tempo o servidor mantém os pesos em memória depois de uma resposta. Por
# omissão descarrega-os ao fim de poucos minutos, e uma corrida longa pagaria o
# carregamento várias vezes, o que falsearia a medição de débito.
OLLAMA_MANTER = os.getenv("OLLAMA_MANTER", "30m")

API_KEY = os.getenv("ANTHROPIC_API_KEY", "")   # só é preciso no caminho anthropic
OPENAI_URL = os.getenv("OPENAI_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")   # só no caminho openai
DB_URL = os.getenv("NEON_DATABASE_URL", "")   # só é preciso para ler ou gravar na base


def hoje():
    """A data de hoje. DATA_DEMO fixa outra (só para demonstrações com dados
    antigos: o dashboard e os alertas passam a ver o mundo nessa data)."""
    from datetime import date
    d = os.getenv("DATA_DEMO")
    return date.fromisoformat(d) if d else date.today()
