
import itertools
import math
from collections import Counter
from modules.score import sequencia_maxima, media_soma_lotto, desvio_soma_lotto, zona


def normalizar_tuple(numeros):
    return tuple(sorted(int(n) for n in numeros))


def soma_intervalo_aceitavel(qtd, total_numeros=45, desvios=1.8):
    media = media_soma_lotto(qtd, total_numeros)
    sd = desvio_soma_lotto(qtd, total_numeros)
    return int(math.floor(media - desvios * sd)), int(math.ceil(media + desvios * sd))


def _contem_sorteio_historico(nums, jogos_ja_sorteados):
    if not jogos_ja_sorteados or len(nums) < 6:
        return False
    if len(nums) == 6:
        return normalizar_tuple(nums) in jogos_ja_sorteados
    for comb in itertools.combinations(nums, 6):
        if normalizar_tuple(comb) in jogos_ja_sorteados:
            return True
    return False


def passa_filtros(numeros, jogos_ja_sorteados=None, recentes=None, total_numeros=45):
    nums = sorted(int(n) for n in numeros)
    qtd = len(nums)
    jogos_ja_sorteados = jogos_ja_sorteados or set()
    recentes = recentes or set()

    if len(nums) != len(set(nums)):
        return False
    if any(n < 1 or n > total_numeros for n in nums):
        return False

    pares = sum(1 for n in nums if n % 2 == 0)
    if pares == 0 or pares == qtd:
        return False
    if abs(pares - (qtd - pares)) > max(3, math.ceil(qtd * 0.55)):
        return False

    if sequencia_maxima(nums) > 3:
        return False

    if _contem_sorteio_historico(nums, jogos_ja_sorteados):
        return False

    qtd_recentes = sum(1 for n in nums if n in recentes)
    if qtd_recentes > max(2, math.ceil(qtd * 0.55)):
        return False

    baixos = sum(1 for n in nums if n <= 22)
    altos = qtd - baixos
    if abs(baixos - altos) > max(3, math.ceil(qtd * 0.55)):
        return False

    soma = sum(nums)
    min_soma, max_soma = soma_intervalo_aceitavel(qtd, total_numeros)
    if not (min_soma <= soma <= max_soma):
        return False

    zonas = Counter(zona(n) for n in nums)
    if qtd >= 6 and any(zonas.get(z, 0) == 0 for z in (1, 2, 3)):
        return False
    if max(zonas.values() or [0]) > max(3, math.ceil(qtd * 0.65)):
        return False

    ultimos_digitos = Counter(n % 10 for n in nums)
    if max(ultimos_digitos.values() or [0]) > max(2, math.ceil(qtd / 3)):
        return False

    return True
