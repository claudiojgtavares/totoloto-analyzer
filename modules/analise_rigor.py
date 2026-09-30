"""Métricas opt-in de rigor; não são previsões de concursos aleatórios."""

from random import Random

FATO_MATEMATICO = "FATO MATEMÁTICO"
PADRAO_HISTORICO = "PADRÃO HISTÓRICO"
HEURISTICA = "HEURÍSTICA"


def suavizar_frequencias(contagens, kappa=45.0, p0=6 / 45):
    """Posterior Beta centrado em p0=6/45 (PADRÃO HISTÓRICO; não previsão)."""
    valores = {int(k): float(v) for k, v in contagens.items()}
    universo = max(valores, default=0)
    if universo <= 0 or kappa <= 0 or not 0 < p0 < 1:
        return {}
    total = sum(valores.get(n, 0.0) for n in range(1, universo + 1))
    concursos = total / 6
    alpha = kappa * p0
    beta = kappa * (1 - p0)
    denominador = concursos + alpha + beta
    return {n: (valores.get(n, 0.0) + alpha) / denominador for n in range(1, universo + 1)}


def teste_ajuste_uniforme(contagens, simulacoes=1000, seed=0):
    """Qui-quadrado com p empírico nulo (FATO MATEMÁTICO; não prova viés mecânico)."""
    valores = [int(contagens.get(n, 0)) for n in sorted(contagens)]
    total = sum(valores)
    universo = len(valores)
    if universo == 0 or total == 0 or total % 6:
        raise ValueError("São necessárias contagens de 1..N e um total múltiplo de 6.")
    esperado = total / universo
    observado = sum((v - esperado) ** 2 / esperado for v in valores)
    rng = Random(seed)
    concursos = total // 6
    extremos = 0
    for _ in range(simulacoes):
        sim = [0] * universo
        for _ in range(concursos):
            for numero in rng.sample(range(universo), 6):
                sim[numero] += 1
        qui = sum((v - esperado) ** 2 / esperado for v in sim)
        extremos += qui >= observado
    return {"rotulo": FATO_MATEMATICO, "qui_quadrado": observado,
            "p_valor_empirico": (extremos + 1) / (simulacoes + 1),
            "simulacoes": simulacoes}


def corrigir_bh(p_valores, q=0.05):
    """Benjamini-Hochberg para descobertas entre muitos números (FATO MATEMÁTICO)."""
    ordenados = sorted((float(p), i) for i, p in enumerate(p_valores))
    m = len(ordenados)
    ajustados = [1.0] * m
    minimo = 1.0
    for pos in range(m - 1, -1, -1):
        p, indice = ordenados[pos]
        minimo = min(minimo, p * m / (pos + 1))
        ajustados[indice] = min(1.0, minimo)
    return {"rotulo": FATO_MATEMATICO, "metodo": "Benjamini-Hochberg",
            "p_valores_ajustados": ajustados,
            "significativos": [i for i, p in enumerate(ajustados) if p <= q]}


def corrigir_holm(p_valores, alpha=0.05):
    """Holm-Bonferroni step-down para testes múltiplos (FATO MATEMÁTICO)."""
    valores = [float(p) for p in p_valores]
    if any(p < 0 or p > 1 for p in valores) or alpha <= 0 or alpha > 1:
        raise ValueError("p-valores e alpha devem estar entre 0 e 1.")
    m = len(valores)
    ajustados = [1.0] * m
    anterior = 0.0
    for pos, (p, indice) in enumerate(sorted((p, i) for i, p in enumerate(valores))):
        ajustado = max(anterior, min(1.0, (m - pos) * p))
        ajustados[indice] = ajustado
        anterior = ajustado
    significativos = []
    for pos, (p, indice) in enumerate(sorted((p, i) for i, p in enumerate(valores))):
        if p <= alpha / (m - pos):
            significativos.append(indice)
        else:
            break
    return {"rotulo": FATO_MATEMATICO, "metodo": "Holm-Bonferroni",
            "p_valores_ajustados": ajustados, "significativos": significativos}


def controlo_sintetico(diferencas_observadas, diferencas_nulas):
    """Compara estratégia-baseline com históricos nulos (FATO MATEMÁTICO)."""
    obs = sum(diferencas_observadas) / len(diferencas_observadas)
    nulas = [float(valor) for valor in diferencas_nulas]
    extremos = sum(valor >= obs for valor in nulas)
    p = (extremos + 1) / (len(nulas) + 1) if nulas else None
    return {"rotulo": FATO_MATEMATICO, "media_observada": obs, "p_valor_empirico": p}
