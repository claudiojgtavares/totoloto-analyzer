import math
import time
from collections import Counter
from datetime import date, datetime

from modules.estatistica import calcular_estatisticas_de_sorteios
from modules.gerador import gerar_jogos_estatisticos
from modules.totoloto import APOSTAS_SIMPLES_POR_QTD, avaliar_carteira, gerar_pools_uniformes, metricas_cobertura
from modules.analise_rigor import controlo_sintetico

BASELINE_REPETICOES = 20
MAX_LINHAS_POR_CONCURSO = 420


def max_bilhetes_backtesting(qtd_numeros):
    linhas = APOSTAS_SIMPLES_POR_QTD[int(qtd_numeros)]
    return min(20, max(1, MAX_LINHAS_POR_CONCURSO // linhas))


def _numeros(sorteio):
    return {int(sorteio[f"n{i}"]) for i in range(1, 7)}


def _ordem_sorteio(sorteio):
    """Prioriza a data e aceita identificadores como 49/2025."""
    data = sorteio.get("data_sorteio")
    if data:
        if isinstance(data, (date, datetime)):
            data_ordenavel = data.strftime("%Y-%m-%d")
        else:
            texto = str(data).strip()
            data_ordenavel = texto
            for formato in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    data_ordenavel = datetime.strptime(texto[:10], formato).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    pass
        return (data_ordenavel, str(sorteio.get("concurso") or ""))
    concurso = str(sorteio.get("concurso") or "")
    digitos = "".join(c for c in concurso if c.isdigit())
    return ("", digitos.zfill(12), concurso)


def _intervalo_amostra(valores, nivel_z=1.96, minimo=None, maximo=None):
    """IC da média; as observações independentes são concursos, não linhas."""
    valores = list(valores)
    total = len(valores)
    if not total:
        return [0, 0]
    media = sum(valores) / total
    if total == 1:
        return [round(media, 4), round(media, 4)]
    variancia = sum((valor - media) ** 2 for valor in valores) / (total - 1)
    margem = nivel_z * math.sqrt(variancia / total)
    inferior = media - margem if minimo is None else max(minimo, media - margem)
    superior = media + margem if maximo is None else min(maximo, media + margem)
    return [round(inferior, 4), round(superior, 4)]


def _resumir(distribuicao, premios, medias_concurso=None, taxas_concurso=None):
    total = sum(distribuicao.values())
    soma = sum(acertos * qtd for acertos, qtd in distribuicao.items())
    tres_mais = sum(distribuicao.get(acertos, 0) for acertos in range(3, 7))
    return {
        "linhas": round(total),
        "media_acertos": round(soma / total, 4) if total else 0,
        "media_acertos_ic_95": _intervalo_amostra(medias_concurso or [], minimo=0, maximo=6),
        "maior_acerto": max((a for a, qtd in distribuicao.items() if qtd), default=0),
        "linhas_3_mais": round(tres_mais, 2),
        "taxa_3_mais": round(tres_mais / total, 6) if total else 0,
        "taxa_3_mais_ic_95": _intervalo_amostra(taxas_concurso or [], minimo=0, maximo=1),
        "premios": {chave: round(valor, 2) for chave, valor in premios.items()},
        "distribuicao_acertos": {a: round(distribuicao.get(a, 0), 2) for a in range(7)},
    }


def resumo_backtesting_demo():
    categorias = Counter({"primeiro": 0, "segundo": 0, "terceiro": 0, "quarto": 0})
    vazio = _resumir(Counter(), categorias, [], [])
    return {
        "media_acertos": 0, "media_acertos_ic_95": [0, 0], "maior_acerto": 0,
        "jogos_3_mais": 0, "taxa_3_mais": 0, "taxa_3_mais_ic_95": [0, 0],
        "linhas_testadas": 0, "bilhetes_testados": 0, "concursos_testados": 0,
        "concursos_ignorados": 0, "premios_por_categoria": dict(categorias),
        "baseline": vazio, "diferenca_baseline": 0, "diferenca_baseline_ic_95": [0, 0],
        "baseline_repeticoes": BASELINE_REPETICOES, "cobertura_media": {},
        "custo_simulado": 0, "retorno_simulado": None, "lucro_prejuizo": None,
        "observacao": "Cadastre sorteios suficientes para rodar backtesting real.",
        "erros": {}, "detalhes": [], "incompleto": False, "limite_concursos": None,
        "rotulo": "PADRÃO HISTÓRICO", "diferencas_emparelhadas": [],
    }


def executar_backtesting(sorteios, estrategia="Equilibrada", quantidade_jogos=5,
                         qtd_numeros=6, incluir_joker=False, min_historico=10,
                         preco_aposta=30, preco_joker=70, limite_concursos=None,
                         timeout_segundos=None, progresso=None, cancelar=None):
    """Walk-forward, expansão oficial e baseline Monte Carlo de mesmo custo."""
    qtd_numeros, quantidade_jogos = int(qtd_numeros), int(quantidade_jogos)
    maximo = max_bilhetes_backtesting(qtd_numeros)
    if not 1 <= quantidade_jogos <= maximo:
        raise ValueError(
            f"Para {qtd_numeros} números, use no máximo {maximo} bilhete(s) por teste "
            f"({MAX_LINHAS_POR_CONCURSO} linhas por concurso)."
        )
    sorteios = sorted(sorteios or [], key=_ordem_sorteio)
    if len(sorteios) <= min_historico:
        return resumo_backtesting_demo()

    detalhes, coberturas = [], []
    estrategia_dist, baseline_dist = Counter(), Counter()
    premios = Counter({"primeiro": 0, "segundo": 0, "terceiro": 0, "quarto": 0})
    baseline_premios = Counter({"primeiro": 0, "segundo": 0, "terceiro": 0, "quarto": 0})
    erros = Counter()
    medias, taxas, base_medias, base_taxas, diferencas = [], [], [], [], []
    custo_total, bilhetes_testados = 0.0, 0

    if limite_concursos is not None:
        limite_concursos = int(limite_concursos)
        if limite_concursos <= 0:
            raise ValueError("O limite de concursos deve ser positivo.")
    inicio_alvos = max(min_historico, len(sorteios) - limite_concursos) if limite_concursos else min_historico
    inicio_tempo = time.monotonic()
    interrompido = False
    def deve_parar():
        return ((cancelar is not None and cancelar()) or
                (timeout_segundos is not None and time.monotonic() - inicio_tempo >= float(timeout_segundos)))

    for idx in range(inicio_alvos, len(sorteios)):
        if deve_parar():
            interrompido = True
            break
        historico, alvo = sorteios[:idx], sorteios[idx]
        estat = calcular_estatisticas_de_sorteios(historico)
        jogos_ja_sorteados = {tuple(sorted(_numeros(s))) for s in historico}
        recentes = set().union(*(_numeros(s) for s in historico[-3:]))
        seed_base = f"{alvo.get('concurso')}-{idx}"
        try:
            gerados = gerar_jogos_estatisticos(
                estat, quantidade_jogos, qtd_numeros, estrategia, incluir_joker,
                jogos_ja_sorteados, recentes, preco_aposta, preco_joker,
                seed=f"estrategia-{estrategia}-{seed_base}",
            )
            sorteado = _numeros(alvo)
            avaliacao = avaliar_carteira(gerados, sorteado)
            bd, bp, bm, bmelhores = Counter(), Counter(), [], []
            for repeticao in range(BASELINE_REPETICOES):
                if deve_parar():
                    interrompido = True
                    break
                pools = gerar_pools_uniformes(
                    quantidade_jogos, qtd_numeros, seed=f"baseline-{repeticao}-{seed_base}"
                )
                av = avaliar_carteira(pools, sorteado)
                bd.update(av["distribuicao_acertos"])
                bp.update(av["premios"])
                bm.append(av["media_acertos"])
                bmelhores.append(av["melhor_acerto"])
            if interrompido:
                break
            cobertura = metricas_cobertura(gerados)
        except Exception as exc:
            erros[type(exc).__name__] += 1
            continue

        estrategia_dist.update(avaliacao["distribuicao_acertos"])
        premios.update(avaliacao["premios"])
        for acertos, total in bd.items():
            baseline_dist[acertos] += total / BASELINE_REPETICOES
        for categoria, total in bp.items():
            baseline_premios[categoria] += total / BASELINE_REPETICOES
        custo_total += sum(float(j["custo_final"]) for j in gerados)
        bilhetes_testados += len(gerados)
        coberturas.append(cobertura)

        taxa = avaliacao["linhas_3_mais"] / avaliacao["linhas"]
        base_media = sum(bm) / BASELINE_REPETICOES
        base_taxa = sum(bd.get(a, 0) for a in range(3, 7)) / (BASELINE_REPETICOES * avaliacao["linhas"])
        medias.append(avaliacao["media_acertos"])
        taxas.append(taxa)
        base_medias.append(base_media)
        base_taxas.append(base_taxa)
        diferencas.append(avaliacao["media_acertos"] - base_media)
        detalhes.append({
            "concurso": alvo.get("concurso"), "data_sorteio": alvo.get("data_sorteio"),
            "resultado": sorted(sorteado), "melhor_acerto": avaliacao["melhor_acerto"],
            "media_acertos": round(avaliacao["media_acertos"], 3),
            "jogos_testados": len(gerados), "linhas_testadas": avaliacao["linhas"],
            "premios": avaliacao["premios"], "baseline_media": round(base_media, 3),
            "baseline_melhor": round(sum(bmelhores) / BASELINE_REPETICOES, 2),
        })
        if progresso is not None:
            progresso(len(detalhes), len(sorteios) - inicio_alvos)

    if not estrategia_dist:
        demo = resumo_backtesting_demo()
        demo.update({"concursos_ignorados": sum(erros.values()), "erros": dict(erros),
                     "incompleto": True, "limite_concursos": limite_concursos,
                     "observacao": "Nenhum concurso pôde ser testado; reveja os filtros e os dados históricos."})
        return demo

    resumo = _resumir(estrategia_dist, premios, medias, taxas)
    baseline = _resumir(baseline_dist, baseline_premios, base_medias, base_taxas)
    campos = ("numeros_unicos", "pares_unicos", "trincas_unicas", "linhas_unicas",
              "linhas_duplicadas", "sobreposicao_media")
    cobertura_media = {c: round(sum(item[c] for item in coberturas) / len(coberturas), 3) for c in campos}
    joker_aviso = " O custo do Joker foi incluído, mas o resultado Joker não é avaliado." if incluir_joker else ""
    return {
        "media_acertos": resumo["media_acertos"], "media_acertos_ic_95": resumo["media_acertos_ic_95"],
        "maior_acerto": resumo["maior_acerto"], "jogos_3_mais": resumo["linhas_3_mais"],
        "taxa_3_mais": resumo["taxa_3_mais"], "taxa_3_mais_ic_95": resumo["taxa_3_mais_ic_95"],
        "linhas_testadas": resumo["linhas"], "bilhetes_testados": bilhetes_testados,
        "concursos_testados": len(detalhes), "concursos_ignorados": sum(erros.values()),
        "premios_por_categoria": resumo["premios"], "baseline": baseline,
        "diferenca_baseline": round(resumo["media_acertos"] - baseline["media_acertos"], 4),
        "diferenca_baseline_ic_95": _intervalo_amostra(diferencas, minimo=-6, maximo=6),
        "baseline_repeticoes": BASELINE_REPETICOES, "cobertura_media": cobertura_media,
        "custo_simulado": custo_total, "retorno_simulado": None, "lucro_prejuizo": None,
        "observacao": (
            "Walk-forward sem vazamento, com múltiplas expandidas em linhas simples e comparação "
            f"contra a média de {BASELINE_REPETICOES} seleções uniformes de mesmo volume por concurso. "
            "Os intervalos usam o concurso como unidade independente. Retorno e ROI ficam indisponíveis "
            "até serem carregados os quinhões oficiais por concurso." + joker_aviso
        ),
        "erros": dict(erros), "detalhes": detalhes[-30:],
        "incompleto": interrompido or bool(erros), "limite_concursos": limite_concursos,
        "rotulo": "PADRÃO HISTÓRICO", "diferencas_emparelhadas": diferencas,
    }


def comparar_historicos_nulos(diferencas_observadas, diferencas_nulas):
    """FATO MATEMÁTICO: cauda superior Monte Carlo, não previsão nem garantia."""
    if not diferencas_observadas or not diferencas_nulas:
        raise ValueError("O controlo exige a avaliação real e todos os históricos nulos completos.")
    valores = list(diferencas_observadas) + list(diferencas_nulas)
    if not all(math.isfinite(v) for v in valores):
        raise ValueError("O controlo exige diferenças finitas.")
    resultado = controlo_sintetico(diferencas_observadas, diferencas_nulas)
    ordenadas = sorted(diferencas_nulas)
    def percentil(p):
        pos = (len(ordenadas) - 1) * p
        baixo, alto = math.floor(pos), math.ceil(pos)
        return ordenadas[baixo] + (ordenadas[alto] - ordenadas[baixo]) * (pos - baixo)
    resultado.update(intervalo_nulo=[percentil(.025), percentil(.975)],
                     intervalo_descricao="Percentis 2,5–97,5 da distribuição nula; não é IC de desempenho futuro.",
                     alternativa="superior", resolucao_p=1 / (len(ordenadas) + 1))
    return resultado
