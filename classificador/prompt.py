"""Acesso aos prompts disponíveis em `prompts/`.

Cada módulo de prompt define VERSION e SYSTEM_PROMPT. Pedir uma versão que não
existe é erro, não motivo para recorrer a outra: uma corrida tem de saber com
que prompt foi produzida.
"""

import importlib
import pkgutil
from pathlib import Path

_DIR = Path(__file__).parent / "prompts"


def _carregar() -> dict[str, str]:
    """Os prompts disponíveis, indexados pela versão que declaram.

    A pasta tem também módulos de apoio, como a lista de marcas e o script que
    a gera. Só entram os que declaram VERSION e SYSTEM_PROMPT; os nomes que
    começam por underscore nem chegam a ser importados.
    """
    out = {}
    for info in pkgutil.iter_modules([str(_DIR)]):
        if info.name.startswith("_"):
            continue
        mod = importlib.import_module(f"prompts.{info.name}")
        if hasattr(mod, "VERSION") and hasattr(mod, "SYSTEM_PROMPT"):
            out[mod.VERSION] = mod.SYSTEM_PROMPT
    return out


PROMPTS = _carregar()


def get(versao: str) -> str:
    if versao not in PROMPTS:
        raise KeyError(f"prompt '{versao}' não existe. Disponíveis: {sorted(PROMPTS)}")
    return PROMPTS[versao]
