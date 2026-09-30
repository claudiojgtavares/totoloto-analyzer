
import math
from collections import Counter


# FATO MATEMÁTICO: esta é uma escala técnica normalizada dos critérios do
# sistema. Não é a probabilidade de acertar nem uma estimativa do próximo
# sorteio. O teto cobre o máximo teórico dos bónus estruturais e estatísticos.
SCORE_TECNICO_TETO = 135.0


def normalizar_score_tecnico(valor, teto=SCORE_TECNICO_TETO):
    """Converte o índice bruto numa escala 0-100 para apresentação como %."""
    bruto = float(valor or 0)
    return round(max(0.0, min(100.0, bruto / float(teto) * 100.0)), 2)


def sequencia_maxima(numeros):
    nums = sorted(int(n) for n in numeros)
    if not nums:
        return 0
    maior = atual = 1
    for i in range(1, len(nums)):
        if nums[i] == nums[i - 1] + 1:
            atual += 1
            maior = max(maior, atual)
        else:
            atual = 1
    return maior


def adjacencias(numeros):
    nums = sorted(int(n) for n in numeros)
    return sum(1 for i in range(1, len(nums)) if nums[i] == nums[i - 1] + 1)


def media_soma_lotto(qtd, total_numeros=45):
    return qtd * (total_numeros + 1) / 2


def desvio_soma_lotto(qtd, total_numeros=45):
    # Variância da soma de amostra sem reposição de 1..N.
    var_pop = (total_numeros ** 2 - 1) / 12
    return math.sqrt(qtd * var_pop * (total_numeros - qtd) / (total_numeros - 1))


def zona(n):
    if n <= 15:
        return 1
    if n <= 30:
        return 2
    return 3


def _norm_lista(valores, valor):
    valores = [float(v or 0) for v in valores]
    if not valores:
        return 0.5
    mn, mx = min(valores), max(valores)
    if mx == mn:
        return 0.5
    return (float(valor or 0) - mn) / (mx - mn)


def _popularidade_aparente(nums):
    """Apenas reduz padrões populares; não altera chance matemática de saída."""
    qtd = len(nums)
    ate_31 = sum(1 for n in nums if n <= 31)
    multiplos_5 = sum(1 for n in nums if n % 5 == 0)
    penalidade = 0
    if ate_31 >= max(4, math.ceil(qtd * 0.75)):
        penalidade += 4
    if multiplos_5 >= max(3, math.ceil(qtd * 0.45)):
        penalidade += 3
    return penalidade


def calcular_score(numeros, estatisticas=None, estrategia="Equilibrada"):
    """Score de 0 a 100. É uma nota técnica dos filtros, não probabilidade de ganhar."""
    nums = sorted(int(n) for n in numeros)
    qtd = len(nums)
    if qtd == 0 or len(set(nums)) != qtd or any(n < 1 or n > 45 for n in nums):
        return 0

    score = 50.0
    pares = sum(1 for n in nums if n % 2 == 0)
    baixos = sum(1 for n in nums if n <= 22)
    soma = sum(nums)
    seq = sequencia_maxima(nums)
    adj = adjacencias(nums)
    zonas = Counter(zona(n) for n in nums)
    ultimos_digitos = Counter(n % 10 for n in nums)

    # Paridade: para 6 números, 3/3 é ótimo; 2/4 ou 4/2 é aceitável.
    diferenca_pares = abs(pares - (qtd - pares))
    score += max(0, 14 - diferenca_pares * 5)

    # Baixos/altos.
    diferenca_baixos = abs(baixos - (qtd - baixos))
    score += max(0, 12 - diferenca_baixos * 4)

    # Zonas 1-15, 16-30, 31-45.
    if all(zonas.get(z, 0) > 0 for z in (1, 2, 3)):
        score += 10
    if max(zonas.values() or [0]) > math.ceil(qtd * 0.65):
        score -= 8

    # Soma total comparada à distribuição teórica de uma amostra 6/45.
    media = media_soma_lotto(qtd)
    sd = desvio_soma_lotto(qtd) or 1
    z_soma = abs((soma - media) / sd)
    if z_soma <= 0.75:
        score += 12
    elif z_soma <= 1.35:
        score += 7
    elif z_soma <= 1.8:
        score += 2
    else:
        score -= 10

    # Sequências: aceitar vizinhos, evitar blocos grandes.
    if seq <= 2:
        score += 8
    elif seq == 3:
        score += 2
    else:
        score -= 15
    if 0 <= adj <= max(2, qtd // 3):
        score += 4
    else:
        score -= 6

    # Evitar repetição visual/popular em excesso.
    if max(ultimos_digitos.values() or [0]) <= max(2, math.ceil(qtd / 3)):
        score += 4
    else:
        score -= 5
    score -= _popularidade_aparente(nums)

    if estatisticas:
        mapa = {int(e.get("numero", 0)): e for e in estatisticas}
        saidas_all = [float(e.get("numero_saidas", 0) or 0) for e in estatisticas]
        aus_all = [float(e.get("ausencias", 0) or 0) for e in estatisticas]
        quente_all = [float(e.get("indice_quente", 0) or 0) for e in estatisticas]
        atraso_all = [float(e.get("indice_atraso", 0) or 0) for e in estatisticas]

        freq_norm = [_norm_lista(saidas_all, mapa.get(n, {}).get("numero_saidas", 0)) for n in nums]
        aus_norm = [_norm_lista(aus_all, mapa.get(n, {}).get("ausencias", 0)) for n in nums]
        quente_norm = [_norm_lista(quente_all, mapa.get(n, {}).get("indice_quente", 0)) for n in nums]
        atraso_norm = [_norm_lista(atraso_all, mapa.get(n, {}).get("indice_atraso", 0)) for n in nums]

        media_freq = sum(freq_norm) / qtd
        media_aus = sum(aus_norm) / qtd
        media_quente = sum(quente_norm) / qtd
        media_atraso = sum(atraso_norm) / qtd

        if estrategia == "Frequentes":
            score += media_freq * 12 + media_quente * 8
        elif estrategia == "Atrasados":
            score += media_aus * 12 + media_atraso * 8
        elif estrategia == "Mista":
            score += (1 - abs(media_freq - media_aus)) * 12 + media_quente * 5
        elif estrategia == "Aleatória Inteligente":
            score += (1 - abs(media_freq - 0.5)) * 8 + (1 - abs(media_aus - 0.5)) * 8
        else:
            score += (1 - abs(media_freq - 0.55)) * 7 + (1 - abs(media_aus - 0.50)) * 7 + media_quente * 3

        # Penaliza jogos formados só por extremos estatísticos.
        extremos_freq = sum(1 for v in freq_norm if v >= 0.85 or v <= 0.15)
        if extremos_freq >= max(4, math.ceil(qtd * 0.75)):
            score -= 8

    return normalizar_score_tecnico(score)
