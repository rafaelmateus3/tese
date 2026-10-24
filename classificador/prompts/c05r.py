"""Prompt c05r: o c05 com duas linhas corrigidas (11-Out-2026).

Correção de uma inconsistência entre o prompt e o guia de anotação, detetada na
quarta etapa (e4):
  - <nivel_1>: a frase que vinha da v2 («Não recebes o estado actual de nenhum
    deles») deixou de ser verdade com o bloco v3, que mostra o último estado;
  - <glossary>: «fica para mais tarde → 1 ou 10» contrariava a regra do guia
    («adiar ou não ter verba de momento não muda a fase»).

O texto constrói-se a partir do c05 em vez de o copiar, para que o resto seja
garantidamente igual. Resumo SHA-256 esperado do texto: 10607aa64bb0 (com os nomes de clientes
anonimizados; ver README).
"""

import hashlib

from .c05 import SYSTEM_PROMPT as _C05

VERSION = "c05r"

_TROCAS = [
    ("   Não recebes o estado actual de nenhum deles: decides-o pelo relatório.",
     "   Nos de equipamento e produção recebes também o último estado conhecido e a data em que foi "
     "registado. É contexto: o estado que atribuis é o que ESTE relatório mostra."),
    ('"fica para mais tarde / não é prioridade agora" → estado 1 ou 10.',
     '"fica para mais tarde / não é prioridade agora / para já" → adiar ou não ter verba de momento '
     'não muda a fase: mantém o último estado. Só um sinal definitivo de perda é "9".'),
]

SYSTEM_PROMPT = _C05
for _velho, _novo in _TROCAS:
    assert SYSTEM_PROMPT.count(_velho) == 1, _velho
    SYSTEM_PROMPT = SYSTEM_PROMPT.replace(_velho, _novo)

assert hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12] == "10607aa64bb0", \
    "o texto do c05r não é o avaliado: o c05 mudou?"
