"""F-04: FATO MATEMÁTICO (protocolo); PADRÃO HISTÓRICO (desempenho).

Configuração imutável antes de avaliar; nenhum destes resultados prevê sorteios.
"""
from dataclasses import asdict, dataclass
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
from random import Random

from modules.backtesting import (
    BASELINE_REPETICOES, MAX_LINHAS_POR_CONCURSO, _ordem_sorteio,
    executar_backtesting, max_bilhetes_backtesting,
)
from modules.gerador import ESTRATEGIAS_VALIDAS

RAIZ = Path(__file__).resolve().parents[1]
PASTA_RESULTADOS = RAIZ / "exports" / "backtesting"
VERSAO_PROTOCOLO = 1


class ErroProtocolo(ValueError):
    """Mensagem de domínio controlada, segura para a interface (não erro técnico)."""


def json_canonico(valor):
    return json.dumps(valor, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False)


def digest(valor):
    return hashlib.sha256(json_canonico(valor).encode("utf-8")).hexdigest()


def normalizar_historico(sorteios):
    resultado, vistos = [], set()
    for s in sorted(sorteios, key=_ordem_sorteio):
        try:
            numeros = [int(s[f"n{i}"]) for i in range(1, 7)]
        except (KeyError, TypeError, ValueError):
            raise ErroProtocolo("Cada sorteio deve conter seis números inteiros de 1 a 45.") from None
        if len(set(numeros)) != 6 or not all(1 <= n <= 45 for n in numeros):
            raise ErroProtocolo("Cada sorteio deve conter seis números distintos de 1 a 45.")
        data = s.get("data_sorteio")
        if isinstance(data, (date, datetime)):
            data = data.strftime("%Y-%m-%d")
        elif data:
            data = _ordem_sorteio(s)[0]
        concurso = str(s.get("concurso", "")).strip()
        chave = (concurso, data)
        if not concurso or chave in vistos:
            raise ErroProtocolo("O histórico contém concursos em falta ou duplicados.")
        vistos.add(chave)
        resultado.append({"concurso": concurso, "data_sorteio": data,
                          **{f"n{i}": n for i, n in enumerate(sorted(numeros), 1)}})
    return resultado


def corte_holdout(total):
    """Últimos ceil(20% N); calculado ANTES de escolher/avaliar parâmetros."""
    return total - (total + 4) // 5


def gerar_historico_sintetico(historico, seed):
    """FATO MATEMÁTICO: concursos independentes, uniformes 6/45 sem reposição."""
    rng = Random(seed)
    return [{"concurso": s["concurso"], "data_sorteio": s.get("data_sorteio"),
             **{f"n{i}": n for i, n in enumerate(sorted(rng.sample(range(1, 46), 6)), 1)}}
            for s in historico]


def seed_simulacao(seed, indice):
    return int.from_bytes(hashlib.sha256(f"F04:{seed}:{indice}".encode()).digest()[:8], "big")


def estimar_duracao(total, alvos, n_sinteticos, workers, qtd_numeros, bilhetes):
    """Estimativa conservadora, não benchmark; referência AUDITORIA.md (300 concursos).

    Não desconta bilhetes abaixo da referência. Escala histórico acima de 300,
    trabalho avaliado, número de réplicas e paralelismo efetivo (não ideal).
    """
    referencia = max(62.8, 30.9 * bilhetes / 2) if qtd_numeros > 6 else 62.8
    base = referencia * alvos / 290 * max(1, total / 300)
    efetivos = 1 + .6 * (workers - 1)
    nominal = base * (1 + n_sinteticos / efetivos)
    inferior = math.ceil(nominal * 1.15 + 10)
    superior = math.ceil(nominal * 2.05 + 30)
    return {"inferior_segundos": inferior, "superior_segundos": superior,
            "base": "Auditoria: 62,8 s (6/20) e 30,9 s (10/2), 300 concursos; extrapolação conservadora.",
            "medido": False, "alvos": alvos, "workers": workers,
            "aviso": "A duração real pode exceder a estimativa; timeout implica resultado incompleto sem p-valor."}


@dataclass(frozen=True)
class PlanoProtocolo:
    historico_json: str
    configuracao_json: str
    seed: int
    n_sinteticos: int
    workers: int
    ambito: str
    corte: int
    inicio_alvos: int
    timeout_global: int
    timeout_simulacao: int
    estimativa_json: str
    codigo_hash: str

    @property
    def historico(self):
        return json.loads(self.historico_json)

    @property
    def configuracao(self):
        return json.loads(self.configuracao_json)

    @property
    def alvos(self):
        return len(self.historico) - self.inicio_alvos

    def registo(self):
        return asdict(self)


def hash_codigo():
    nomes = ("backtesting.py", "protocolo_backtesting.py", "gerador.py", "estatistica.py",
             "score.py", "filtros.py", "totoloto.py", "analise_rigor.py")
    return digest({n: hashlib.sha256((RAIZ / "modules" / n).read_bytes()).hexdigest() for n in nomes})


def preparar_protocolo(sorteios, *, estrategia="Equilibrada", quantidade_jogos=5,
                       qtd_numeros=6, incluir_joker=False, preco_aposta=30, preco_joker=70,
                       min_historico=10, limite_concursos=50, seed=2026, n_sinteticos=199,
                       workers=4, ambito="holdout", timeout_global=None, timeout_simulacao=300,
                       holdout_inedito=False):
    historico = normalizar_historico(sorteios)
    try:
        quantidade_jogos, qtd_numeros = int(quantidade_jogos), int(qtd_numeros)
        min_historico, limite_concursos = int(min_historico), int(limite_concursos)
        seed, n_sinteticos, workers = int(seed), int(n_sinteticos), int(workers)
        timeout_simulacao = int(timeout_simulacao)
        preco_aposta, preco_joker = float(preco_aposta), float(preco_joker)
    except (TypeError, ValueError, OverflowError):
        raise ErroProtocolo("Verifique os parâmetros numéricos do protocolo.") from None
    if estrategia not in ESTRATEGIAS_VALIDAS or qtd_numeros not in range(6, 11):
        raise ErroProtocolo("Escolha uma estratégia válida e entre 6 e 10 números.")
    if not 1 <= quantidade_jogos <= max_bilhetes_backtesting(qtd_numeros):
        raise ErroProtocolo("A carteira excede os limites de bilhetes ou de 420 linhas por concurso.")
    if (not 1 <= n_sinteticos <= 999 or not 1 <= workers <= 4 or not 0 <= seed < 2**63
            or min_historico < 10 or limite_concursos < 1 or timeout_simulacao < 1):
        raise ErroProtocolo("Use B entre 1 e 999, 1–4 workers, seed não negativa e limites positivos (histórico mínimo 10).")
    if any(not math.isfinite(p) or p < 0 for p in (preco_aposta, preco_joker)):
        raise ErroProtocolo("Os custos em CVE devem ser finitos e não negativos.")
    corte = corte_holdout(len(historico))
    if corte < min_historico or len(historico) <= min_historico:
        raise ErroProtocolo("Histórico bruto insuficiente: são necessários pelo menos 10 concursos antes do holdout.")
    if ambito not in ("holdout", "exploratorio"):
        raise ErroProtocolo("Âmbito inválido: escolha holdout ou exploratório.")
    if ambito == "holdout" and not holdout_inedito:
        raise ErroProtocolo("Confirme que o holdout foi reservado antes de escolher parâmetros e não foi usado em ajustes.")
    if ambito == "holdout":
        inicio = corte
        if limite_concursos < len(historico) - corte:
            raise ErroProtocolo(f"O holdout exige {len(historico) - corte} concursos completos; aumente o limite de {limite_concursos} antes de iniciar.")
    else:
        inicio = max(min_historico, len(historico) - limite_concursos)
    if timeout_global in (None, ""):
        if ambito == "exploratorio":
            raise ErroProtocolo("O âmbito exploratório exige um prazo explícito; as 2 horas predefinidas aplicam-se apenas ao holdout.")
        timeout_global = 7200
    try:
        timeout_global = int(timeout_global)
    except (TypeError, ValueError):
        raise ErroProtocolo("Indique o prazo global em segundos inteiros.") from None
    if timeout_global < 1:
        raise ErroProtocolo("O prazo global deve ser positivo.")
    estimativa = estimar_duracao(len(historico), len(historico) - inicio, n_sinteticos,
                               workers, qtd_numeros, quantidade_jogos)
    config = {"estrategia": estrategia, "quantidade_jogos": quantidade_jogos,
              "qtd_numeros": qtd_numeros, "incluir_joker": bool(incluir_joker),
              "min_historico": min_historico, "preco_aposta": preco_aposta, "preco_joker": preco_joker,
              "limite_concursos": len(historico) - inicio, "timeout_segundos": timeout_simulacao}
    return PlanoProtocolo(json_canonico(historico), json_canonico(config), seed, n_sinteticos,
                          workers, ambito, corte, inicio, timeout_global, timeout_simulacao,
                          json_canonico(estimativa), hash_codigo())


def validar_prazo(plano):
    estimativa = json.loads(plano.estimativa_json)
    if estimativa["superior_segundos"] > plano.timeout_global:
        raise ErroProtocolo(
            f"Duração estimada: {estimativa['inferior_segundos']}–{estimativa['superior_segundos']} segundos. "
            f"Prazo configurado: {plano.timeout_global} segundos. "
            f"Aumente o prazo para pelo menos {estimativa['superior_segundos']} segundos ou reveja a configuração antes de iniciar.")


def executar_avaliacao(plano, indice=None, progresso=None, cancelar=None):
    """ÚNICO núcleo para real e nulos; sem simplificar estratégia nem baselines."""
    historico = plano.historico
    if indice is not None:
        historico = gerar_historico_sintetico(historico, seed_simulacao(plano.seed, indice))
    return executar_backtesting(historico, **plano.configuracao, progresso=progresso, cancelar=cancelar)


def resultado_completo(resultado, plano):
    return (not resultado.get("incompleto", True) and not resultado.get("concursos_ignorados", 0)
            and resultado.get("concursos_testados") == plano.alvos
            and len(resultado.get("diferencas_emparelhadas", [])) == plano.alvos)


def novo_registo(plano, job_id):
    return {"id": job_id, "versao_protocolo": VERSAO_PROTOCOLO, "estado": "pendente",
            "rotulo": "FATO MATEMÁTICO", "rotulo_desempenho": "PADRÃO HISTÓRICO",
            "aviso": "Desempenho passado e controlo nulo não garantem desempenho futuro. Sem ROI sem quinhões oficiais.",
            "plano": plano.registo(), "configuracao_usada": plano.configuracao,
            "hash_historico": digest(plano.historico), "hash_configuracao": digest(plano.registo()),
            "seed": plano.seed, "n_sinteticos": plano.n_sinteticos,
            "seeds_sinteticas": [seed_simulacao(plano.seed, i) for i in range(plano.n_sinteticos)],
            "baseline_repeticoes": BASELINE_REPETICOES, "max_linhas": MAX_LINHAS_POR_CONCURSO,
            "metrica": "Média por concurso da diferença emparelhada: acertos por linha da estratégia menos baseline.",
            "metrica_observada": None, "p_valor_empirico": None, "intervalo_nulo": None,
            "simulacoes_concluidas": 0, "tempo_decorrido": 0, "motivo": None,
            "estimativa": json.loads(plano.estimativa_json), "timeout_global": plano.timeout_global,
            "ambito": plano.ambito, "corte": plano.corte, "inicio_alvos": plano.inicio_alvos,
            "alvos": plano.alvos, "avaliacao_iniciada": False, "nulos": {}, "resultado_real": None,
            "confirmacao": "Configuração congelada e estimativa aceite antes de avaliar; holdout declarado inédito." if plano.ambito == "holdout" else "Exploratório: não é confirmação independente."}
