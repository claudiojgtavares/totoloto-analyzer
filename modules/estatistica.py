
from statistics import mean


def _numeros_do_sorteio(sorteio):
    return [int(sorteio[f"n{i}"]) for i in range(1, 7)]


def calcular_estatisticas_de_sorteios(sorteios, total_numeros=45, numeros_por_sorteio=6):
    """Calcula estatísticas usando distância real entre sorteios carregados.

    Ausência = quantidade de sorteios cadastrados desde a última saída do número.
    Isso é mais fiel do que subtrair número do concurso, porque concursos podem faltar no cadastro.
    """
    sorteios = sorted(sorteios or [], key=lambda s: int(s.get("concurso") or 0))
    total_sorteios = len(sorteios)
    esperado_saidas = (total_sorteios * numeros_por_sorteio / total_numeros) if total_sorteios else 0
    prob_teorica = round((numeros_por_sorteio / total_numeros) * 100, 2)

    ocorrencias = {n: [] for n in range(1, total_numeros + 1)}
    datas = {n: None for n in range(1, total_numeros + 1)}
    concursos = {n: None for n in range(1, total_numeros + 1)}

    for idx, sorteio in enumerate(sorteios):
        nums = _numeros_do_sorteio(sorteio)
        for n in nums:
            ocorrencias[n].append(idx)
            datas[n] = sorteio.get("data_sorteio")
            concursos[n] = sorteio.get("concurso")

    ultimos_5 = sorteios[-5:]
    ultimos_10 = sorteios[-10:]
    set_5 = []
    set_10 = []
    for s in ultimos_5:
        set_5.extend(_numeros_do_sorteio(s))
    for s in ultimos_10:
        set_10.extend(_numeros_do_sorteio(s))

    resultado = []
    for n in range(1, total_numeros + 1):
        idxs = ocorrencias[n]
        saidas = len(idxs)
        percentual = round((saidas / total_sorteios) * 100, 2) if total_sorteios else 0
        if idxs:
            ausencias = total_sorteios - idxs[-1] - 1
            intervalos = [idxs[i] - idxs[i-1] for i in range(1, len(idxs))]
            media_intervalo = round(mean(intervalos), 2) if intervalos else None
        else:
            ausencias = total_sorteios
            media_intervalo = None

        # Índices de apoio ao score; não são probabilidade de acerto.
        desvio = round(saidas - esperado_saidas, 2)
        freq5 = set_5.count(n)
        freq10 = set_10.count(n)
        indice_quente = round((percentual - prob_teorica) + (freq5 * 1.5) + (freq10 * 0.7), 2)
        indice_atraso = round(ausencias - (media_intervalo or 0), 2) if idxs else round(float(ausencias), 2)

        resultado.append({
            "numero": n,
            "numero_saidas": saidas,
            "percentual_saidas": percentual,
            "probabilidade_teorica": prob_teorica,
            "desvio_frequencia": desvio,
            "ultimo_sorteio": concursos[n],
            "data_ultimo_sorteio": datas[n],
            "ausencias": ausencias,
            "frequencia_ultimos_5": freq5,
            "frequencia_ultimos_10": freq10,
            "media_intervalo": media_intervalo,
            "indice_quente": indice_quente,
            "indice_atraso": indice_atraso,
        })
    return resultado


def recalcular_estatisticas(conexao):
    """Recalcula frequência, percentual, últimos sorteios, janelas recentes e ausências dos números 1 a 45."""
    cursor = conexao.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM sorteios ORDER BY concurso ASC")
        sorteios = cursor.fetchall()
        resumo = calcular_estatisticas_de_sorteios(sorteios)

        upsert = """
    INSERT INTO estatisticas_numeros
    (numero, numero_saidas, percentual_saidas, probabilidade_teorica, desvio_frequencia,
     ultimo_sorteio, data_ultimo_sorteio, ausencias, frequencia_ultimos_5, frequencia_ultimos_10,
     media_intervalo, indice_quente, indice_atraso)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
        numero_saidas = VALUES(numero_saidas),
        percentual_saidas = VALUES(percentual_saidas),
        probabilidade_teorica = VALUES(probabilidade_teorica),
        desvio_frequencia = VALUES(desvio_frequencia),
        ultimo_sorteio = VALUES(ultimo_sorteio),
        data_ultimo_sorteio = VALUES(data_ultimo_sorteio),
        ausencias = VALUES(ausencias),
        frequencia_ultimos_5 = VALUES(frequencia_ultimos_5),
        frequencia_ultimos_10 = VALUES(frequencia_ultimos_10),
        media_intervalo = VALUES(media_intervalo),
        indice_quente = VALUES(indice_quente),
        indice_atraso = VALUES(indice_atraso)
    """
        for item in resumo:
            cursor.execute(upsert, (
                item["numero"], item["numero_saidas"], item["percentual_saidas"], item["probabilidade_teorica"],
                item["desvio_frequencia"], item["ultimo_sorteio"], item["data_ultimo_sorteio"], item["ausencias"],
                item["frequencia_ultimos_5"], item["frequencia_ultimos_10"], item["media_intervalo"],
                item["indice_quente"], item["indice_atraso"]
            ))
        return resumo
    finally:
        cursor.close()
