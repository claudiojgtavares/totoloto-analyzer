"""Regras matemáticas do Totoloto CVCV.

Este módulo separa três conceitos que antes estavam misturados:

* pool: números marcados num bilhete simples ou múltiplo;
* linha: combinação efetiva de seis números que participa no sorteio;
* carteira: conjunto de pools gerados para o mesmo concurso.

As rotinas daqui calculam cobertura e prémios por categoria. Não tentam prever
um sorteio aleatório.
"""

from collections import Counter
from itertools import combinations
from math import comb
import random


TOTAL_NUMEROS = 45
NUMEROS_POR_LINHA = 6
PRECO_APOSTA_SIMPLES = 30
PRECO_JOKER = 70

# A modalidade de cinco fixos consta do regulamento, mas não aparece no fluxo
# operacional atual da CVCV. Mantém-se no motor para avaliar registos antigos;
# a interface oferece somente 6-10.
APOSTAS_SIMPLES_POR_QTD = {
    5: 40,
    6: 1,
    7: 7,
    8: 28,
    9: 84,
    10: 210,
}
QTD_NUMEROS_ATUAIS = (6, 7, 8, 9, 10)

CATEGORIA_POR_ACERTOS = {
    6: "primeiro",
    5: "segundo",
    4: "terceiro",
    3: "quarto",
}


def normalizar_numeros(numeros, tamanhos_permitidos=None):
    nums = tuple(sorted(int(n) for n in numeros))
    if len(nums) != len(set(nums)):
        raise ValueError("Os números de uma aposta devem ser únicos.")
    if any(n < 1 or n > TOTAL_NUMEROS for n in nums):
        raise ValueError("Os números devem estar entre 1 e 45.")
    permitidos = tuple(tamanhos_permitidos or APOSTAS_SIMPLES_POR_QTD)
    if len(nums) not in permitidos:
        esperado = ", ".join(str(n) for n in permitidos)
        raise ValueError(f"Quantidade inválida. Use {esperado} números.")
    return nums


def expandir_aposta(numeros):
    """Expande um pool nas linhas simples de seis números que ele representa.

    Cinco fixos representam 40 linhas: os fixos combinados uma vez com cada
    número restante do universo. Pools de 6-10 seguem C(n, 6).
    """
    nums = normalizar_numeros(numeros)
    if len(nums) == 5:
        fixos = set(nums)
        return [tuple(sorted((*nums, extra))) for extra in range(1, 46) if extra not in fixos]
    return [tuple(linha) for linha in combinations(nums, NUMEROS_POR_LINHA)]


def avaliar_aposta(numeros, resultado):
    """Conta acertos e prémios de todas as linhas representadas por um pool."""
    resultado_set = set(normalizar_numeros(resultado, tamanhos_permitidos=(6,)))
    linhas = expandir_aposta(numeros)
    distribuicao = Counter(len(set(linha) & resultado_set) for linha in linhas)
    premios = {
        categoria: distribuicao.get(acertos, 0)
        for acertos, categoria in CATEGORIA_POR_ACERTOS.items()
    }
    return {
        "linhas": linhas,
        "total_linhas": len(linhas),
        "distribuicao_acertos": {acertos: distribuicao.get(acertos, 0) for acertos in range(7)},
        "premios": premios,
        "melhor_acerto": max(distribuicao, default=0),
        "media_acertos": (
            sum(acertos * quantidade for acertos, quantidade in distribuicao.items()) / len(linhas)
            if linhas else 0
        ),
    }


def avaliar_carteira(apostas, resultado):
    """Avalia todos os pools como linhas simples, sem misturar as unidades."""
    distribuicao = Counter()
    premios = Counter({categoria: 0 for categoria in CATEGORIA_POR_ACERTOS.values()})
    total_linhas = 0
    melhor = 0
    for aposta in apostas:
        numeros = aposta.get("numeros", aposta) if isinstance(aposta, dict) else aposta
        avaliacao = avaliar_aposta(numeros, resultado)
        distribuicao.update(avaliacao["distribuicao_acertos"])
        premios.update(avaliacao["premios"])
        total_linhas += avaliacao["total_linhas"]
        melhor = max(melhor, avaliacao["melhor_acerto"])

    soma_acertos = sum(acertos * quantidade for acertos, quantidade in distribuicao.items())
    return {
        "bilhetes": len(apostas),
        "linhas": total_linhas,
        "distribuicao_acertos": {acertos: distribuicao.get(acertos, 0) for acertos in range(7)},
        "premios": dict(premios),
        "linhas_3_mais": sum(distribuicao.get(acertos, 0) for acertos in range(3, 7)),
        "melhor_acerto": melhor,
        "media_acertos": soma_acertos / total_linhas if total_linhas else 0,
    }


def metricas_cobertura(apostas):
    """Mede diversidade estrutural da carteira de pools e linhas."""
    pools = []
    linhas = []
    for aposta in apostas:
        numeros = aposta.get("numeros", aposta) if isinstance(aposta, dict) else aposta
        pool = normalizar_numeros(numeros)
        pools.append(set(pool))
        linhas.extend(expandir_aposta(pool))

    linhas_unicas = set(linhas)
    numeros_unicos = set().union(*pools) if pools else set()
    pares = set()
    trincas = set()
    for linha in linhas_unicas:
        pares.update(combinations(linha, 2))
        trincas.update(combinations(linha, 3))

    sobreposicoes = [len(a & b) for a, b in combinations(pools, 2)]
    total_linhas = len(linhas)
    return {
        "numeros_unicos": len(numeros_unicos),
        "pares_unicos": len(pares),
        "trincas_unicas": len(trincas),
        "linhas": total_linhas,
        "linhas_unicas": len(linhas_unicas),
        "linhas_duplicadas": total_linhas - len(linhas_unicas),
        "sobreposicao_media": (
            round(sum(sobreposicoes) / len(sobreposicoes), 3) if sobreposicoes else 0
        ),
    }


def probabilidade_acertos(acertos, universo=45, sorteados=6, escolhidos=6):
    """Probabilidade hipergeométrica exata de k acertos numa linha."""
    acertos = int(acertos)
    if acertos < 0 or acertos > min(sorteados, escolhidos):
        return 0.0
    erros = escolhidos - acertos
    if erros > universo - sorteados:
        return 0.0
    return comb(sorteados, acertos) * comb(universo - sorteados, erros) / comb(universo, escolhidos)


def gerar_pools_uniformes(quantidade, qtd_numeros=6, seed=None):
    """Baseline uniforme com a mesma estrutura e o mesmo número de bilhetes."""
    quantidade = int(quantidade)
    qtd_numeros = int(qtd_numeros)
    if qtd_numeros not in APOSTAS_SIMPLES_POR_QTD:
        raise ValueError("Quantidade inválida para o baseline uniforme.")
    rng = random.Random(seed)
    pools = []
    vistos = set()
    while len(pools) < quantidade:
        pool = tuple(sorted(rng.sample(range(1, TOTAL_NUMEROS + 1), qtd_numeros)))
        if pool in vistos:
            continue
        vistos.add(pool)
        pools.append({"numeros": list(pool)})
    return pools
