"""Esquema da saída do classificador.

Serve dois fins: restringe a descodificação, nos motores que aceitam um esquema,
e valida a resposta antes de ela entrar no sistema.

O esquema é construído para cada relatório, porque os identificadores de negócio
válidos dependem do relatório: são os que constam do seu bloco de negócios
abertos, mais "NOVO". Assim, cinco erros deixam de ser possíveis por construção
em vez de desaconselhados por instrução:

  - um estado inventado;
  - a cadeia "null" escrita como texto, em vez do valor nulo;
  - um estado atribuído a consumíveis, que não percorrem o ciclo comercial;
  - um identificador de negócio inventado, que apontaria o par a um destino
    inexistente;
  - um tipo incompatível com o negócio apontado, por exemplo um par de produção,
    com estado do ciclo, a apontar para um negócio de consumíveis. Seria a mesma
    violação do terceiro ponto, entrando pela porta do identificador.

Os três primeiros vêm dos enumerados de estado e das duas formas de par. Os dois
últimos vêm de haver uma forma de par por negócio conhecido, com o identificador
e o tipo fixos ao que o registo diz, mais a forma de negócio novo. Só se sabem
no momento da chamada, pelo que o esquema é construído por relatório.

As duas últimas foram observadas em corrida, não antecipadas.
"""

# Versão do esquema, registada com cada corrida. O prompt e o esquema são as
# duas metades da tarefa dada ao modelo e mudam por razões diferentes, pelo que
# se versionam em separado. Uma corrida só é reproduzível com as duas fixadas.
#
#   e01  esquema fixo, igual para todos os relatórios
#   e02  identificadores restritos aos do relatório, mais NOVO
#   e03  e ainda o tipo preso ao tipo do negócio apontado
#   e04  acrescenta o tipo `lead`, para o negócio ainda não tipificado
#   e05  retira `conteudo_comercial` da saída: passa a ser derivado de haver
#        pares. Com o tipo `lead`, todo o conteúdo comercial tem um negócio, e
#        o campo tornou-se redundante. Um campo redundante numa saída
#        restringida é onde a incoerência entra (conteúdo comercial sem par,
#        #191), e a única forma portável de a impedir nos três motores é não
#        haver os dois campos. A raiz com `anyOf` resolveria o mesmo, mas a
#        OpenAI em modo estrito não aceita `anyOf` na raiz.
VERSAO = "e05"

import hashlib
import json

ESTADOS = [
    "1. Lead / Prospeção",
    "2. Qualificação",
    "3. Proposta / Orçamento",
    "4. Negociação",
    "5. Aprovação Interna",
    "6. Encomenda Confirmada",
    "7. Em Produção / Entrega",
    "8. Fechado",
    "9. Perdido / Cancelado",
    "10. Indeterminado",
]

# `lead` é o negócio cujo tipo ainda não é determinável: há contacto comercial
# e prospecção, mas o texto não nomeia produto, necessidade, pedido nem acção.
# Percorre o ciclo como os outros dois e é re-tipificado quando o assunto ganha
# forma. Existe para que o topo do funil não se perca, que era o que acontecia
# quando esse caso devolvia uma lista de pares vazia.
TIPOS = ["equipamento", "producao", "consumiveis", "lead"]

# Identificador de um negócio que ainda não existe no registo.
NOVO = "NOVO"


def _par(ids: list[str], tipos: list[str], estado: dict) -> dict:
    """Uma das duas formas de par: a do ciclo comercial ou a de consumíveis."""
    return {
        "type": "object",
        "properties": {
            "negocio_id": {"type": "string", "enum": ids},
            "excerto": {"type": "string"},
            "tipo": {"type": "string", "enum": tipos},
            "estado": estado,
        },
        "required": ["negocio_id", "tipo", "estado", "excerto"],
        "additionalProperties": False,
    }


# As duas formas que o campo `estado` pode tomar: do ciclo comercial, ou nulo.
_CICLO = {"type": "string", "enum": ESTADOS}
_NULO = {"type": "null"}

# Os tipos que percorrem o ciclo comercial. Consumíveis não percorrem.
_DO_CICLO = ["equipamento", "producao", "lead"]


def permitidos(negocios) -> dict[str, list[str]]:
    """Que tipos cada identificador aceita neste relatório.

    `negocios` são os pares (identificador, tipo) do bloco de negócios abertos.
    Um negócio novo aceita qualquer tipo, porque ainda não está tipificado.
    """
    out = {NOVO: list(TIPOS)}
    for nid, tipo in negocios:
        out[nid] = [tipo] if tipo in TIPOS else list(TIPOS)
    return out


def _formas(negocios):
    """Uma forma de par por negócio conhecido, mais as duas de negócio novo."""
    for nid, tipo in sorted(set(negocios)):
        if tipo == "consumiveis":
            yield _par([nid], ["consumiveis"], _NULO)
        elif tipo in TIPOS:
            yield _par([nid], [tipo], _CICLO)
        else:
            # Tipo desconhecido no registo: não há base para o restringir.
            yield _par([nid], _DO_CICLO, _CICLO)
            yield _par([nid], ["consumiveis"], _NULO)
    yield _par([NOVO], _DO_CICLO, _CICLO)
    yield _par([NOVO], ["consumiveis"], _NULO)


def saida_para(negocios) -> dict:
    """O esquema de saída de um relatório, dados os seus negócios abertos."""
    return {
        "type": "object",
        "properties": {
            "pares": {"type": "array", "items": {"anyOf": list(_formas(negocios))}},
        },
        "required": ["pares"],
        "additionalProperties": False,
    }


# Entrada fixa usada só para resumir o esquema. Como o esquema muda de relatório
# para relatório, o resumo tem de ser tirado sempre da mesma entrada, senão não
# compara nada. Cobre as duas formas que existem: um negócio do ciclo e um de
# consumíveis.
_REFERENCIA = [("NG-E0000", "equipamento"), ("NG-C00000", "consumiveis")]


def impressao() -> str:
    """Resumo do esquema que este código produz, e não só da sua etiqueta.

    A VERSAO acima é escrita à mão e pode ficar para trás de uma alteração ao
    código. O resumo não: muda com o que o código faz. Gravado com cada corrida,
    torna visível um esquema alterado sob uma etiqueta que não mudou.
    """
    canonico = json.dumps(saida_para(_REFERENCIA), sort_keys=True,
                          ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonico.encode("utf-8")).hexdigest()[:12]
