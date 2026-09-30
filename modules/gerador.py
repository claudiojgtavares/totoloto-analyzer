
import random
import math
from itertools import combinations
from modules.filtros import passa_filtros, normalizar_tuple
from modules.score import calcular_score
from modules.totoloto import APOSTAS_SIMPLES_POR_QTD, expandir_aposta

ESTRATEGIAS_VALIDAS = [
    "Equilibrada", "Frequentes", "Atrasados", "Mista", "Conservadora", "Agressiva", "Aleatória Inteligente"
]


def format_cve(valor):
    inteiro = int(round(float(valor or 0)))
    sinal = "-" if inteiro < 0 else ""
    inteiro = abs(inteiro)
    return sinal + f"{inteiro:,}".replace(",", ".") + " CVE"


def calcular_custo(qtd_numeros, incluir_joker=False, preco_aposta=30, preco_joker=70):
    qtd = int(qtd_numeros)
    if qtd not in APOSTAS_SIMPLES_POR_QTD:
        raise ValueError("Quantidade inválida. Use 5, 6, 7, 8, 9 ou 10 números.")
    apostas = APOSTAS_SIMPLES_POR_QTD[qtd]
    custo_total = apostas * float(preco_aposta)
    custo_joker = float(preco_joker) if incluir_joker else 0
    return {
        "apostas_simples": apostas,
        "custo_total": custo_total,
        "custo_joker": custo_joker,
        "custo_final": custo_total + custo_joker,
    }


def _norm(mapa, chave, numero, padrao=0):
    valores = [float(v.get(chave, 0) or 0) for v in mapa.values()]
    if not valores:
        return 0.5
    mn, mx = min(valores), max(valores)
    if mx == mn:
        return 0.5
    return (float(mapa.get(numero, {}).get(chave, padrao) or 0) - mn) / (mx - mn)


def _peso_numero(numero, mapa, estrategia, rng):
    freq = _norm(mapa, "numero_saidas", numero)
    atraso = _norm(mapa, "ausencias", numero)
    recente5 = _norm(mapa, "frequencia_ultimos_5", numero)
    quente = _norm(mapa, "indice_quente", numero)
    atraso_indice = _norm(mapa, "indice_atraso", numero)

    # Popularidade aparente: números 1-31 tendem a ser mais usados por datas.
    # Não muda probabilidade de sorteio, só ajuda a evitar combinações muito óbvias.
    baixa_popularidade = 1.0 if numero > 31 else 0.45
    centro = 1.0 - abs(numero - 23) / 22
    extremo = 1.0 - centro

    perfis = {
        "Equilibrada": (0.95, 0.85, 0.35, 0.50, 0.30, 0.35, 0.15),
        "Frequentes": (1.90, 0.20, 0.75, 0.85, 0.15, 0.20, 0.10),
        "Atrasados": (0.20, 1.90, 0.05, 0.15, 0.85, 0.25, 0.10),
        "Mista": (1.05, 1.05, 0.45, 0.55, 0.45, 0.30, 0.12),
        "Conservadora": (0.65, 0.65, 0.25, 0.35, 0.25, 0.75, 0.05),
        "Agressiva": (1.35, 1.35, 0.55, 0.35, 0.65, 0.05, 0.40),
        "Aleatória Inteligente": (0.45, 0.45, 0.20, 0.20, 0.20, 0.25, 0.20),
    }
    pf, pa, pr, pq, pia, pc, pe = perfis.get(estrategia, perfis["Equilibrada"])

    peso = 1.0
    peso += freq * pf
    peso += atraso * pa
    peso += recente5 * pr
    peso += quente * pq
    peso += atraso_indice * pia
    peso += baixa_popularidade * 0.25
    peso += centro * pc
    peso += extremo * pe

    # Ruído controlado para não gerar sempre o mesmo jogo.
    peso += rng.random() * (0.25 if estrategia != "Aleatória Inteligente" else 1.25)
    return max(0.05, peso)


def _amostra_ponderada(numeros, pesos, quantidade, rng):
    disponiveis = list(numeros)
    pesos_disp = list(pesos)
    escolhidos = []
    for _ in range(quantidade):
        total = sum(max(0.01, p) for p in pesos_disp)
        alvo = rng.random() * total
        acumulado = 0
        idx = 0
        for i, peso in enumerate(pesos_disp):
            acumulado += max(0.01, peso)
            if acumulado >= alvo:
                idx = i
                break
        escolhidos.append(disponiveis.pop(idx))
        pesos_disp.pop(idx)
    return sorted(escolhidos)


def _selecionar_carteira_diversificada(candidatos, quantidade, rng):
    """Seleciona pools equilibrando score estrutural e cobertura nova.

    A diversidade não aumenta a probabilidade de uma linha individual. Ela reduz
    redundância entre bilhetes e aumenta números, pares e trincas cobertos pelo
    conjunto comprado sob o mesmo orçamento.
    """
    restantes = []
    for candidato in candidatos:
        nums = tuple(candidato["numeros"])
        restantes.append({
            **candidato,
            "_conjunto": set(nums),
            "_pares": set(combinations(nums, 2)),
            "_trincas": set(combinations(nums, 3)),
            "_sobreposicao_total": 0,
        })
    selecionados = []
    numeros_cobertos = set()
    pares_cobertos = set()
    trincas_cobertas = set()

    while restantes and len(selecionados) < quantidade:
        melhor_idx = None
        melhor_objetivo = float("-inf")
        melhor_cobertura = 0.0

        for idx, candidato in enumerate(restantes):
            conjunto = candidato["_conjunto"]
            pares = candidato["_pares"]
            trincas = candidato["_trincas"]
            novo_num = len(conjunto - numeros_cobertos) / len(conjunto)
            novos_pares = len(pares - pares_cobertos) / max(1, len(pares))
            novas_trincas = len(trincas - trincas_cobertas) / max(1, len(trincas))
            if selecionados:
                sobreposicao = candidato["_sobreposicao_total"] / (len(conjunto) * len(selecionados))
            else:
                sobreposicao = 0.0

            cobertura = 100 * (
                0.20 * novo_num
                + 0.35 * novos_pares
                + 0.30 * novas_trincas
                + 0.15 * (1 - sobreposicao)
            )
            objetivo = candidato["score"] * 0.60 + cobertura * 0.40 + rng.random() * 0.0001
            if objetivo > melhor_objetivo:
                melhor_idx = idx
                melhor_objetivo = objetivo
                melhor_cobertura = cobertura

        melhor = restantes.pop(melhor_idx)
        melhor["score_cobertura"] = round(melhor_cobertura, 2)
        selecionados.append({k: v for k, v in melhor.items() if not k.startswith("_")})
        for candidato in restantes:
            candidato["_sobreposicao_total"] += len(candidato["_conjunto"] & melhor["_conjunto"])
        numeros_cobertos.update(melhor["numeros"])
        pares_cobertos.update(combinations(melhor["numeros"], 2))
        trincas_cobertas.update(combinations(melhor["numeros"], 3))

    return selecionados


def gerar_jogos_estatisticos(
    estatisticas,
    quantidade_jogos=5,
    qtd_numeros=6,
    estrategia="Equilibrada",
    incluir_joker=False,
    jogos_ja_sorteados=None,
    recentes=None,
    preco_aposta=30,
    preco_joker=70,
    seed=None,
):
    qtd_numeros = int(qtd_numeros)
    quantidade_jogos = int(quantidade_jogos)
    if qtd_numeros not in APOSTAS_SIMPLES_POR_QTD:
        raise ValueError("Quantidade inválida para aposta. Use 5, 6, 7, 8, 9 ou 10 números.")
    if estrategia not in ESTRATEGIAS_VALIDAS:
        estrategia = "Equilibrada"

    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    mapa = {int(e.get("numero", 0)): e for e in (estatisticas or [])}
    numeros = list(range(1, 46))
    pesos = [_peso_numero(n, mapa, estrategia, rng) for n in numeros]

    candidatos = []
    vistos = set()
    tentativas = 0
    alvo_candidatos = min(5000, max(200, quantidade_jogos * 40))
    limite = max(2000, alvo_candidatos * 12)
    while len(candidatos) < alvo_candidatos and tentativas < limite:
        tentativas += 1
        jogo = _amostra_ponderada(numeros, pesos, qtd_numeros, rng)
        chave = normalizar_tuple(jogo)
        if chave in vistos:
            continue
        if not passa_filtros(jogo, jogos_ja_sorteados=jogos_ja_sorteados, recentes=recentes):
            continue
        vistos.add(chave)
        candidatos.append({
            "numeros": jogo,
            "score": calcular_score(jogo, estatisticas, estrategia=estrategia),
        })

    if len(candidatos) < quantidade_jogos:
        raise ValueError("Não foi possível gerar a quantidade solicitada com os filtros atuais. Reduza a quantidade ou tente outra estratégia.")

    escolhidos = _selecionar_carteira_diversificada(candidatos, quantidade_jogos, rng)
    custos = calcular_custo(qtd_numeros, incluir_joker=incluir_joker, preco_aposta=preco_aposta, preco_joker=preco_joker)
    gerados = []
    for escolhido in escolhidos:
        linhas = expandir_aposta(escolhido["numeros"])
        linhas_aprovadas = sum(
            passa_filtros(linha, jogos_ja_sorteados=jogos_ja_sorteados, recentes=recentes)
            for linha in linhas
        )
        gerados.append({
            "numeros": escolhido["numeros"],
            "tipo_aposta": "Simples" if qtd_numeros == 6 else "Múltipla",
            "estrategia": estrategia,
            "apostas_simples": custos["apostas_simples"],
            "score": escolhido["score"],
            "score_cobertura": escolhido["score_cobertura"],
            "linhas_aprovadas_filtros": linhas_aprovadas,
            "percentual_linhas_aprovadas": round(100 * linhas_aprovadas / len(linhas), 1),
            "custo_total": custos["custo_total"],
            "custo_joker": custos["custo_joker"],
            "custo_final": custos["custo_final"],
            "incluir_joker": incluir_joker,
        })

    return gerados
