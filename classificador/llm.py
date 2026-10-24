"""Chamada ao modelo e leitura da resposta.

Três caminhos de execução, com a mesma interface e o mesmo contrato de saída:

    anthropic   API da Anthropic, com `output_config.format`
    openai      API da OpenAI, com `response_format` em modo estrito
    ollama      servidor local, com `format` a receber o mesmo esquema

Os três restringem a descodificação: em cada passo, os tokens que tornariam a
saída inválida face ao esquema são eliminados dos candidatos. A estrutura fica
garantida por construção e não por instrução.

Os controlos de variabilidade não são os mesmos nos dois caminhos, nem sequer
iguais entre modelos do mesmo fornecedor. O caminho local aceita sempre
temperatura zero e raciocínio desligado. No caminho em nuvem a temperatura foi
descontinuada modelo a modelo, e o raciocínio nem sempre se deixa desligar, sem
que nenhuma das duas coisas seja anunciada antes da chamada: a plataforma
responde 400 a nomear o que recusa. Pede-se por isso o máximo e retira-se o que
for recusado, guardando por modelo o que ficou em vigor, para que a corrida
possa declarar em que condições correu.

Nenhum dos caminhos em nuvem oferece semente, pelo que a reprodutibilidade
exacta que o RF1.5 pede só é alcançável localmente. Em nuvem fixa-se o
identificador do modelo e regista-se a resposta bruta.

O modelo devolve `conteudo_comercial` e uma lista de `pares`. Um relatório pode
produzir zero pares: é um resultado válido, não um erro.
"""

import json
import re
import subprocess
import time
import urllib.error
import urllib.request

import anthropic

from config import (API_KEY, MAX_TOKENS, MODELO, OLLAMA_CONTEXTO,
                    OLLAMA_MANTER, OLLAMA_PENSAR, OLLAMA_URL,
                    OPENAI_API_KEY, OPENAI_URL, TEMPERATURA)
from esquema import ESTADOS, TIPOS, permitidos, saida_para
from prompt import get

CAMPOS = ["vistamp", "data", "hora", "nome", "vendnm",
          "duracao", "ctipo", "u_anegocio", "u_classif", "resumo", "rel"]


# O bloco de negócios abertos, de onde saem os identificadores que o esquema vai
# aceitar. A procura é feita dentro do bloco e não na mensagem inteira, porque o
# bloco de relatórios anteriores tem o mesmo formato de linha e as suas datas
# seriam lidas como identificadores.
_BLOCO_NEGOCIOS = re.compile(r"<negocios_abertos>(.*?)</negocios_abertos>", re.S)
_LINHA_NEGOCIO = re.compile(r"^\s+(\S+)\s*\|\s*([^|]+?)\s*\|", re.M)


def negocios_abertos(mensagem: str) -> list[tuple[str, str]]:
    """Os pares (identificador, tipo) que a mensagem apresenta ao modelo."""
    bloco = _BLOCO_NEGOCIOS.search(mensagem)
    return _LINHA_NEGOCIO.findall(bloco.group(1)) if bloco else []


class RespostaInvalida(ValueError):
    """A resposta do modelo não cumpre o contrato de saída."""


def _mensagem(relatorio: dict, bloco_negocios: str,
              bloco_historico: str = "") -> str:
    """A mensagem dada ao modelo: o relatório, o histórico e os negócios vivos.

    O histórico são relatórios anteriores do mesmo cliente, em texto bruto. Sem
    ele, o estado de um negócio teria de sair de um relatório isolado, o que
    muitas vezes não é possível nem para um anotador humano. Com ele, modelo e
    anotador decidem sobre exactamente a mesma informação, que é a condição
    para o acerto medido dizer alguma coisa sobre o modelo.

    Não se injecta o estado anterior, apenas os relatórios. O estado anterior é
    o que se está a inferir, e dá-lo seria circular.
    """
    campos = "\n".join(
        f"  {c:<12} {str(relatorio.get(c) or '').strip()}" for c in CAMPOS
    )
    return f"<report>\n{campos}\n{bloco_historico}{bloco_negocios}</report>"


def _validar(dados: dict, aceites: dict[str, list[str]]) -> dict:
    """Verifica o contrato de saída antes de deixar os dados entrarem no sistema.

    Duplica o que o esquema já garante nos motores que o aceitam. Vale a pena:
    a validação é barata e é a única rede quando um motor ignora o esquema.
    """
    pares = dados.get("pares")
    if not isinstance(pares, list):
        raise RespostaInvalida("pares ausente ou não é lista")
    # A partir do e05 o conteúdo comercial deriva de haver pares. Os esquemas
    # anteriores pediam o campo ao modelo, e aí mantém-se o que ele disse.
    if "conteudo_comercial" not in dados:
        dados["conteudo_comercial"] = bool(pares)
    elif not isinstance(dados["conteudo_comercial"], bool):
        raise RespostaInvalida("conteudo_comercial não booleano")
    for p in pares:
        if p.get("negocio_id") not in aceites:
            raise RespostaInvalida(f"negocio_id inválido: {p.get('negocio_id')!r}")
        if p.get("tipo") not in TIPOS:
            raise RespostaInvalida(f"tipo inválido: {p.get('tipo')!r}")
        if p["tipo"] not in aceites[p["negocio_id"]]:
            raise RespostaInvalida(
                f"tipo {p['tipo']!r} não corresponde ao negócio {p['negocio_id']}")
        if p.get("estado") is not None and p["estado"] not in ESTADOS:
            raise RespostaInvalida(f"estado inválido: {p['estado']!r}")
        if not str(p.get("excerto") or "").strip():
            raise RespostaInvalida("par sem excerto")
        if p["tipo"] == "consumiveis" and p.get("estado") is not None:
            raise RespostaInvalida("consumíveis não recebem estado do ciclo")
        if p["tipo"] != "consumiveis" and not p.get("estado"):
            raise RespostaInvalida(f"par de {p['tipo']} sem estado")
    return dados


def juntar_repetidos(pares: list, nid=lambda p: p["negocio_id"],
                     tipo=lambda p: p["tipo"]) -> list:
    """Um negócio aparece uma só vez, e os consumíveis são uma só relação.

    O prompt pede as duas coisas, mas os modelos repetem às vezes o mesmo id, ou
    partem os consumíveis em dois pares (c06, #87, #193, #311). Fica o primeiro;
    nos consumíveis, o do bloco quando existe. É regra do sistema e não do
    prompt, pelo que se aplica a todas as versões (metricas.py aplica-a
    também às corridas antigas).
    """
    out, vistos = [], set()
    cons = [p for p in pares if tipo(p) == "consumiveis"]
    guardar = next((p for p in cons if nid(p) != "NOVO"), cons[0] if cons else None)
    for p in pares:
        if tipo(p) == "consumiveis":
            if p is guardar:
                out.append(p)
            continue
        if nid(p) != "NOVO":
            if nid(p) in vistos:
                continue
            vistos.add(nid(p))
        out.append(p)
    return out


def _extrair_json(texto: str) -> dict:
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio < 0 or fim < inicio:
        raise RespostaInvalida(f"sem JSON na resposta: {texto[:120]!r}")
    return json.loads(texto[inicio:fim + 1])


_cliente = None


# O que cada modelo em nuvem acabou por aceitar. Descobre-se à primeira chamada
# e fica guardado, para não repetir a tentativa recusada em cada relatório.
_CONTROLOS: dict[str, dict[str, bool]] = {}


def controlos_aplicados(modelo: str, backend: str) -> str:
    """Em que condições o modelo correu, para ficar registado com a corrida."""
    if backend == "ollama":
        return "temperatura=0, sem raciocínio"
    c = _CONTROLOS.get(f"{backend}|{modelo}")
    if c is None:
        return "por determinar"
    # "não ajustável" cobre as duas recusas observadas: o parâmetro ter sido
    # descontinuado, e ser aceite mas só no valor por omissão. Nos dois casos a
    # amostragem fica ligada e a corrida não é reproduzível à saída.
    partes = ["temperatura=0" if c["temperatura"] else "temperatura não ajustável"]
    if "sem_raciocinio" in c:
        partes.append("sem raciocínio" if c["sem_raciocinio"]
                      else "raciocínio não desligável")
    return ", ".join(partes)


def _anthropic(sistema: str, utilizador: str, modelo: str,
               esquema: dict) -> tuple[str, int, int]:
    global _cliente
    if _cliente is None:
        _cliente = anthropic.Anthropic(api_key=API_KEY)
    c = _CONTROLOS.setdefault(f"anthropic|{modelo}",
                              {"temperatura": True, "sem_raciocinio": True})
    # A decisão de repetir olha para o que ESTE pedido enviou, e não para o
    # estado partilhado. Com pedidos concorrentes, o primeiro a ser recusado já
    # desligou o controlo quando os outros são recusados pelo mesmo motivo, e
    # ler o estado partilhado faria esses tomar a recusa por alheia.
    for _ in range(len(c) + 1):
        enviou_temperatura = c["temperatura"]
        enviou_sem_raciocinio = c["sem_raciocinio"]
        pedido = dict(
            model=modelo,
            max_tokens=MAX_TOKENS,
            system=sistema,
            messages=[{"role": "user", "content": utilizador}],
            output_config={"format": {"type": "json_schema", "schema": esquema}},
        )
        # A temperatura não é um parâmetro nomeado desta versão do cliente e
        # segue no corpo do pedido; onde o modelo ainda a aceita, é o controlo
        # mais forte de que dispomos em nuvem.
        if enviou_temperatura:
            pedido["extra_body"] = {"temperature": TEMPERATURA}
        if enviou_sem_raciocinio:
            pedido["thinking"] = {"type": "disabled"}
        try:
            r = _cliente.messages.create(**pedido)
            break
        except anthropic.APIStatusError as e:
            recusa = str(e).lower()
            if enviou_temperatura and "temperature" in recusa:
                c["temperatura"] = False
            elif enviou_sem_raciocinio and "thinking" in recusa:
                c["sem_raciocinio"] = False
            else:
                raise
    else:
        raise RespostaInvalida(
            f"{modelo} recusou todos os controlos e continua a recusar o pedido")
    # A resposta pode trazer blocos de raciocínio antes do texto, consoante o
    # modelo. Só os blocos de texto contêm a saída pedida, e assumir que o
    # primeiro bloco é texto falha nos modelos que raciocinam.
    texto = "".join(b.text for b in r.content
                    if getattr(b, "type", None) == "text")
    if not texto.strip():
        tipos = ", ".join(getattr(b, "type", "?") for b in r.content) or "nenhum"
        raise RespostaInvalida(f"resposta sem bloco de texto (blocos: {tipos})")
    return texto.strip(), r.usage.input_tokens, r.usage.output_tokens


def _pedir_ollama(corpo: dict) -> dict:
    pedido = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat", data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido, timeout=900) as r:
        return json.loads(r.read())


def _ollama(sistema: str, utilizador: str, modelo: str,
            esquema: dict) -> tuple[str, int, int]:
    corpo = {
        "model": modelo,
        "format": esquema,
        "stream": False,
        "think": OLLAMA_PENSAR,
        "keep_alive": OLLAMA_MANTER,
        "options": {"temperature": TEMPERATURA, "num_predict": MAX_TOKENS,
                    "num_ctx": OLLAMA_CONTEXTO},
        "messages": [{"role": "system", "content": sistema},
                     {"role": "user", "content": utilizador}],
    }
    try:
        d = _pedir_ollama(corpo)
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:300]
        if "think" in detalhe.lower():
            # O modelo não suporta a opção; repete-se sem ela.
            corpo.pop("think")
            d = _pedir_ollama(corpo)
        else:
            # O ollama devolve a causa no corpo; sem ela um 500 não distingue
            # modelo inexistente de contexto grande de mais.
            raise OSError(f"ollama {e.code}: {detalhe}") from None
    conteudo = d["message"]["content"].strip()
    if not conteudo:
        motivo = d.get("done_reason", "desconhecido")
        pista = (" (esgotou o orçamento de geração: aumentar MAX_TOKENS ou "
                 "desligar o raciocínio)" if motivo == "length" else "")
        raise RespostaInvalida(f"resposta vazia, motivo {motivo}{pista}")
    return conteudo, d.get("prompt_eval_count"), d.get("eval_count")


def _pedir_openai(corpo: dict) -> dict:
    pedido = urllib.request.Request(
        f"{OPENAI_URL}/chat/completions", data=json.dumps(corpo).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {OPENAI_API_KEY}"})
    with urllib.request.urlopen(pedido, timeout=900) as r:
        return json.loads(r.read())


def _openai(sistema: str, utilizador: str, modelo: str,
            esquema: dict) -> tuple[str, int, int]:
    """O mesmo esquema, em modo estrito, pela interface da OpenAI.

    Negocia-se o que o modelo aceita, pela mesma razão que no caminho anterior:
    a temperatura deixou de existir nos modelos mais recentes, e o campo que
    limita a geração mudou de nome entre gerações sem que a recusa seja
    previsível a partir do nome do modelo.
    """
    if not OPENAI_API_KEY:
        raise OSError("OPENAI_API_KEY não está definida no .env")
    c = _CONTROLOS.setdefault(f"openai|{modelo}",
                              {"temperatura": True, "limite_actual": True})
    for _ in range(len(c) + 1):
        enviou_temperatura = c["temperatura"]
        enviou_limite_actual = c["limite_actual"]
        corpo = {
            "model": modelo,
            "messages": [{"role": "system", "content": sistema},
                         {"role": "user", "content": utilizador}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "classificacao", "strict": True, "schema": esquema}},
        }
        corpo["max_completion_tokens" if enviou_limite_actual
              else "max_tokens"] = MAX_TOKENS
        if enviou_temperatura:
            corpo["temperature"] = TEMPERATURA
        try:
            d = _pedir_openai(corpo)
            break
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode("utf-8", "replace")[:400]
            recusa = detalhe.lower()
            if enviou_temperatura and "temperature" in recusa:
                c["temperatura"] = False
            elif enviou_limite_actual and "max_completion_tokens" in recusa:
                c["limite_actual"] = False
            else:
                raise OSError(f"openai {e.code}: {detalhe}") from None
    else:
        raise OSError(f"{modelo} recusa o pedido com e sem os controlos")

    escolha = d["choices"][0]
    if escolha["message"].get("refusal"):
        raise RespostaInvalida(
            f"o modelo recusou responder: {escolha['message']['refusal'][:120]}")
    conteudo = (escolha["message"].get("content") or "").strip()
    if not conteudo:
        motivo = escolha.get("finish_reason", "desconhecido")
        pista = (" (esgotou o orçamento de geração: aumentar MAX_TOKENS)"
                 if motivo == "length" else "")
        raise RespostaInvalida(f"resposta vazia, motivo {motivo}{pista}")
    uso = d.get("usage") or {}
    return conteudo, uso.get("prompt_tokens"), uso.get("completion_tokens")


BACKENDS = {"anthropic": _anthropic, "openai": _openai, "ollama": _ollama}


def identificar(modelo: str, backend: str) -> str:
    """Identidade dos pesos que vão ser executados.

    A etiqueta não chega: o mesmo nome pode corresponder a pesos diferentes em
    máquinas diferentes. No caminho local devolve-se o resumo criptográfico que
    o servidor reporta; no caminho em nuvem, o identificador do modelo, que é o
    mais forte que essa plataforma oferece.
    """
    if backend != "ollama":
        return modelo
    # O resumo dos pesos está na lista de modelos (/api/tags), e não no /api/show, que só
    # traz o código do tipo de ficheiro (general.file_type: 15 = Q4_K_M, 2 = Q4_0), que
    # não identifica os pesos. Corrigido a 19-Out-2026.
    with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=60) as r:
        modelos = json.loads(r.read()).get("models", [])
    nomes = {modelo, modelo if ":" in modelo else modelo + ":latest"}
    for m in modelos:
        if m.get("name") in nomes or m.get("model") in nomes:
            if m.get("digest"):
                return m["digest"]
    raise RuntimeError(f"O Ollama não lista o modelo {modelo!r}: sem resumo dos pesos")


# Mensagem sintética, fora do conjunto de referência, usada só para aquecer.
_AQUECIMENTO = ("<report>\n  vistamp      aquecimento\n"
                "  nome         (aquecimento)\n  rel          Sem assunto.\n</report>")


def preparar(modelo: str, backend: str, versao: str = "c02") -> float:
    """Põe o modelo pronto a classificar e devolve quanto tempo isso demorou.

    Na primeira chamada um modelo local paga o carregamento dos pesos para
    memória e o processamento inicial do prompt de sistema. Medido junto com o
    resto, esse custo aparece como se fosse débito do modelo, e o débito é um
    dos critérios de decisão. Faz-se por isso uma classificação descartada,
    sobre uma mensagem sintética que não pertence ao conjunto de referência, e
    o tempo dela fica registado à parte.

    Serve também de teste de prontidão: se o modelo não carrega, não responde,
    ou não respeita o contrato de saída, sabe-se aqui e não a meio da corrida.
    Nos caminhos em nuvem não há nada a carregar e devolve zero.
    """
    if backend != "ollama":
        return 0.0
    inicio = time.perf_counter()
    r = classificar_mensagem(_AQUECIMENTO, versao, modelo, backend)
    if r["erro"]:
        raise OSError(f"aquecimento falhou: {r['erro']}")
    return time.perf_counter() - inicio


def garantir_modelo(modelo: str, backend: str, versao: str, falar=print) -> None:
    """O servidor Ollama tem de estar a correr."""
    if backend != "ollama":
        return
    try:
        preparar(modelo, backend, versao)
        return
    except OSError:
        falar("Ollama não responde; a arrancar 'ollama serve'")
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    time.sleep(15)
    preparar(modelo, backend, versao)


def classificar(relatorio: dict, bloco_negocios: str = "", versao: str = "c01",
                modelo: str = MODELO, backend: str = "anthropic") -> dict:
    """Classifica um relatório, montando a mensagem a partir dos seus campos."""
    return classificar_mensagem(
        _mensagem(relatorio, bloco_negocios), versao, modelo, backend)


def classificar_mensagem(mensagem: str, versao: str = "c01",
                         modelo: str = MODELO,
                         backend: str = "anthropic") -> dict:
    """Classifica uma mensagem já montada.

    É este o ponto de entrada do benchmark, que guarda a mensagem exacta dada a
    cada modelo para que todos respondam à mesma pergunta.

    Devolve sempre um dicionário com conteudo_comercial, pares, contagem de
    tokens e erro. Quando `erro` está preenchido, `pares` vem vazio.
    """
    saida = {"conteudo_comercial": None, "pares": [], "tokens_in": None,
             "tokens_out": None, "raw": None, "erro": None,
             "prompt_version": versao, "modelo": modelo}
    try:
        abertos = negocios_abertos(mensagem)
        bruto, t_in, t_out = BACKENDS[backend](
            get(versao), mensagem, modelo, saida_para(abertos))
        saida.update(raw=bruto, tokens_in=t_in, tokens_out=t_out)

        dados = _validar(_extrair_json(bruto), permitidos(abertos))
        saida["conteudo_comercial"] = dados["conteudo_comercial"]
        saida["pares"] = juntar_repetidos(dados["pares"])
    except (json.JSONDecodeError, ValueError) as e:
        saida["erro"] = f"Resposta inválida: {e}"
    except anthropic.APIError as e:
        saida["erro"] = f"API: {e}"
    except OSError as e:
        saida["erro"] = f"Ligação ao modelo: {e}"
    return saida
