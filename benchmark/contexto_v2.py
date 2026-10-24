"""O construtor do bloco de negócios passou para classificador/contexto.py,
onde a produção também o usa. Este módulo fica para os scripts do benchmark."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "classificador"))
from contexto import *            # noqa: E402,F401,F403
from contexto import Contexto, _tipo, _limpo, ABANDONO, TIPO_DE_CLASSIF  # noqa: E402,F401
