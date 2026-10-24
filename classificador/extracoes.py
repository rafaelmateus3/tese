"""As extrações que o ERP deixa na pasta ERP_PASTA.

A exportação do Metabase corre todos os dias à mesma hora do ciclo e deixa um
ficheiro de cada tipo: visitas_*, linhas_faturas_*, equipamentos_* e dossiers_*.
Usa-se sempre o mais recente de cada.
"""

import time
from datetime import date, datetime
from pathlib import Path

from config import ERP_PASTA

VISITAS = "visitas_*.xlsx"
FATURAS = "linhas[_-]faturas_*.xlsx"
EQUIPAMENTOS = "equipamentos_*.xlsx"
DOSSIERS = "dossiers_*.xlsx"


def mais_recente(pasta: Path, padrao: str) -> Path:
    """O ficheiro de `pasta` mais recente que cumpre `padrao`."""
    ficheiros = sorted(Path(pasta).glob(padrao), key=lambda p: p.stat().st_mtime)
    if not ficheiros:
        raise FileNotFoundError(f"nenhum {padrao} em {pasta}")
    return ficheiros[-1]


def idade_dias(ficheiro: Path) -> int:
    return (datetime.now() - datetime.fromtimestamp(ficheiro.stat().st_mtime)).days


def esperar_exportacao(falar, pasta: Path = ERP_PASTA, minutos: int = 20) -> None:
    """A exportação do ERP e o ciclo podem arrancar à mesma hora: espera que ela acabe."""
    pasta = Path(pasta)
    fim = time.time() + minutos * 60
    while time.time() < fim:
        a_meio = list(pasta.glob("*.xlsx.tmp"))
        vis = sorted(pasta.glob(VISITAS), key=lambda p: p.stat().st_mtime)
        de_hoje = bool(vis) and date.fromtimestamp(vis[-1].stat().st_mtime) == date.today()
        if de_hoje and not a_meio:
            return
        falar("à espera da exportação do ERP" + (" (ficheiros a meio)" if a_meio else " de hoje"))
        time.sleep(60)
    falar(f"AVISO: a exportação de hoje não apareceu em {minutos} min; segue com a mais recente")


def do_dia(falar, pasta: Path = ERP_PASTA, esperar: bool = True) -> tuple[Path, Path, Path]:
    """Passo 1 do ciclo: as extrações de visitas, faturas e equipamentos a usar."""
    if esperar:
        esperar_exportacao(falar, pasta)
    visitas = mais_recente(pasta, VISITAS)
    faturas = mais_recente(pasta, FATURAS)
    equipamentos = mais_recente(pasta, EQUIPAMENTOS)
    falar(f"extrações: {visitas.name} · {faturas.name} · {equipamentos.name}")
    idade = idade_dias(visitas)
    if idade > 2:
        falar(f"AVISO: a extração de visitas tem {idade} dias; o ERP deixou de exportar?")
    return visitas, faturas, equipamentos
