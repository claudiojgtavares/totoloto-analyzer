
import random
import re
from pathlib import Path
from statistics import mean
from collections import Counter

import pandas as pd

from modules.date_utils import parse_date_br
from modules.score import normalizar_score_tecnico


NUM_POSICOES_JOKER = 6
DIGITOS = list(range(10))
ESTRATEGIAS_JOKER = [
    "Equilibrada", "Frequentes", "Atrasados", "Mista", "Conservadora", "Agressiva", "Aleatória Inteligente"
]


def normalizar_numero_joker(valor):
    texto = "".join(ch for ch in str(valor or "").strip() if ch.isdigit())
    if len(texto) != NUM_POSICOES_JOKER:
        raise ValueError("O número Joker deve ter exactamente 6 dígitos. Exemplo: 056708.")
    return texto


def _chave_concurso(valor):
    texto = str(valor or "").strip()
    if "/" in texto:
        parte, ano = texto.split("/", 1)
        try:
            return (int(ano), int(parte))
        except Exception:
            pass
    try:
        return (0, int(texto))
    except Exception:
        return (0, 0)


def _ordenar_resultados(resultados):
    return sorted(resultados or [], key=lambda r: (_chave_concurso(r.get("concurso")), str(r.get("data_sorteio") or "")))


def calcular_estatisticas_joker(resultados):
    """Calcula estatísticas por posição e por dígito do Joker.

    O Joker é tratado como sequência de 6 dígitos. A estatística é por posição:
    posição 1, posição 2, ..., posição 6, sempre dígitos 0 a 9.
    """
    resultados = _ordenar_resultados(resultados)
    total = len(resultados)
    por_posicao = {(pos, dig): [] for pos in range(1, NUM_POSICOES_JOKER + 1) for dig in DIGITOS}
    datas = {(pos, dig): None for pos in range(1, NUM_POSICOES_JOKER + 1) for dig in DIGITOS}
    concursos = {(pos, dig): None for pos in range(1, NUM_POSICOES_JOKER + 1) for dig in DIGITOS}

    for idx, row in enumerate(resultados):
        numero = normalizar_numero_joker(row.get("numero_joker"))
        for pos, ch in enumerate(numero, start=1):
            dig = int(ch)
            por_posicao[(pos, dig)].append(idx)
            datas[(pos, dig)] = row.get("data_sorteio")
            concursos[(pos, dig)] = row.get("concurso")

    ultimos_5 = resultados[-5:]
    ultimos_10 = resultados[-10:]

    resumo = []
    for pos in range(1, NUM_POSICOES_JOKER + 1):
        for dig in DIGITOS:
            idxs = por_posicao[(pos, dig)]
            saidas = len(idxs)
            percentual = round((saidas / total) * 100, 2) if total else 0
            if idxs:
                ausencias = total - idxs[-1] - 1
                intervalos = [idxs[i] - idxs[i - 1] for i in range(1, len(idxs))]
                media_intervalo = round(mean(intervalos), 2) if intervalos else None
            else:
                ausencias = total
                media_intervalo = None

            freq5 = sum(1 for r in ultimos_5 if normalizar_numero_joker(r.get("numero_joker"))[pos - 1] == str(dig))
            freq10 = sum(1 for r in ultimos_10 if normalizar_numero_joker(r.get("numero_joker"))[pos - 1] == str(dig))
            indice_quente = round((percentual - 10) + (freq5 * 4) + (freq10 * 1.5), 2)
            indice_atraso = round(ausencias - (media_intervalo or 0), 2) if idxs else round(float(ausencias), 2)

            resumo.append({
                "posicao": pos,
                "digito": dig,
                "total_saidas": saidas,
                "percentual": percentual,
                "ultimo_concurso": concursos[(pos, dig)],
                "data_ultimo_sorteio": datas[(pos, dig)],
                "ausencias": ausencias,
                "frequencia_ultimos_5": freq5,
                "frequencia_ultimos_10": freq10,
                "media_intervalo": media_intervalo,
                "indice_quente": indice_quente,
                "indice_atraso": indice_atraso,
            })
    return resumo


def recalcular_estatisticas_joker(conexao):
    cursor = conexao.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM joker_resultados ORDER BY data_sorteio ASC, id ASC")
        resultados = cursor.fetchall()
        resumo = calcular_estatisticas_joker(resultados)

        upsert = """
    INSERT INTO joker_estatisticas
    (posicao, digito, total_saidas, percentual, ultimo_concurso, data_ultimo_sorteio, ausencias,
     frequencia_ultimos_5, frequencia_ultimos_10, media_intervalo, indice_quente, indice_atraso)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON DUPLICATE KEY UPDATE
        total_saidas=VALUES(total_saidas),
        percentual=VALUES(percentual),
        ultimo_concurso=VALUES(ultimo_concurso),
        data_ultimo_sorteio=VALUES(data_ultimo_sorteio),
        ausencias=VALUES(ausencias),
        frequencia_ultimos_5=VALUES(frequencia_ultimos_5),
        frequencia_ultimos_10=VALUES(frequencia_ultimos_10),
        media_intervalo=VALUES(media_intervalo),
        indice_quente=VALUES(indice_quente),
        indice_atraso=VALUES(indice_atraso)
    """
        cur = conexao.cursor()
        try:
            for item in resumo:
                cur.execute(upsert, (
                    item["posicao"], item["digito"], item["total_saidas"], item["percentual"],
                    item["ultimo_concurso"], item["data_ultimo_sorteio"], item["ausencias"],
                    item["frequencia_ultimos_5"], item["frequencia_ultimos_10"], item["media_intervalo"],
                    item["indice_quente"], item["indice_atraso"]
                ))
        finally:
            cur.close()
        return resumo
    finally:
        cursor.close()


def _norm(valores, valor):
    valores = [float(v or 0) for v in valores]
    if not valores:
        return 0.5
    mn, mx = min(valores), max(valores)
    if mn == mx:
        return 0.5
    return (float(valor or 0) - mn) / (mx - mn)


def calcular_score_joker(numero_joker, estatisticas=None, estrategia="Equilibrada"):
    numero = normalizar_numero_joker(numero_joker)
    score = 55.0
    digitos = [int(ch) for ch in numero]
    cont = Counter(digitos)

    # Evita combinações visualmente fracas ou demasiado repetidas.
    repeticoes = max(cont.values() or [1])
    if repeticoes <= 2:
        score += 12
    elif repeticoes == 3:
        score += 3
    else:
        score -= 18

    # Sequências crescentes/decrescentes longas tendem a ser padrões populares.
    pares_adjacentes = sum(1 for i in range(1, len(digitos)) if abs(digitos[i] - digitos[i - 1]) == 1)
    if pares_adjacentes <= 2:
        score += 8
    elif pares_adjacentes <= 3:
        score += 2
    else:
        score -= 8

    # Equilíbrio par/ímpar e baixos/altos.
    pares = sum(1 for d in digitos if d % 2 == 0)
    baixos = sum(1 for d in digitos if d <= 4)
    score += max(0, 10 - abs(pares - 3) * 4)
    score += max(0, 10 - abs(baixos - 3) * 4)

    if estatisticas:
        mapa = {(int(e.get("posicao")), int(e.get("digito"))): e for e in estatisticas}
        saidas_all = [float(e.get("total_saidas", 0) or 0) for e in estatisticas]
        aus_all = [float(e.get("ausencias", 0) or 0) for e in estatisticas]
        quente_all = [float(e.get("indice_quente", 0) or 0) for e in estatisticas]
        atraso_all = [float(e.get("indice_atraso", 0) or 0) for e in estatisticas]

        freq_vals, aus_vals, quente_vals, atraso_vals = [], [], [], []
        for pos, dig in enumerate(digitos, start=1):
            e = mapa.get((pos, dig), {})
            freq_vals.append(_norm(saidas_all, e.get("total_saidas", 0)))
            aus_vals.append(_norm(aus_all, e.get("ausencias", 0)))
            quente_vals.append(_norm(quente_all, e.get("indice_quente", 0)))
            atraso_vals.append(_norm(atraso_all, e.get("indice_atraso", 0)))

        mf = sum(freq_vals) / len(freq_vals)
        ma = sum(aus_vals) / len(aus_vals)
        mq = sum(quente_vals) / len(quente_vals)
        mi = sum(atraso_vals) / len(atraso_vals)

        if estrategia == "Frequentes":
            score += mf * 13 + mq * 9
        elif estrategia == "Atrasados":
            score += ma * 13 + mi * 9
        elif estrategia == "Mista":
            score += (1 - abs(mf - ma)) * 12 + mq * 5 + mi * 5
        elif estrategia == "Agressiva":
            score += (mf + ma + mq + mi) * 5
        elif estrategia == "Aleatória Inteligente":
            score += (1 - abs(mf - 0.5)) * 8 + (1 - abs(ma - 0.5)) * 8
        else:
            score += (1 - abs(mf - 0.55)) * 8 + (1 - abs(ma - 0.50)) * 8 + mq * 4

    return normalizar_score_tecnico(score)


def gerar_combinacoes_joker(estatisticas, quantidade=5, estrategia="Equilibrada", seed=None):
    quantidade = int(quantidade)
    if estrategia not in ESTRATEGIAS_JOKER:
        estrategia = "Equilibrada"
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    estatisticas = estatisticas or []
    mapa = {(int(e.get("posicao")), int(e.get("digito"))): e for e in estatisticas}

    def peso(pos, dig):
        e = mapa.get((pos, dig), {})
        freq = float(e.get("total_saidas", 0) or 0)
        aus = float(e.get("ausencias", 0) or 0)
        quente = float(e.get("indice_quente", 0) or 0)
        atraso = float(e.get("indice_atraso", 0) or 0)
        # Escalas simples, robustas mesmo com pouco histórico.
        base = 1.0
        if estrategia == "Frequentes":
            base += freq * 0.45 + max(0, quente) * 0.12
        elif estrategia == "Atrasados":
            base += aus * 0.35 + max(0, atraso) * 0.15
        elif estrategia == "Mista":
            base += freq * 0.25 + aus * 0.25 + max(0, quente) * 0.08 + max(0, atraso) * 0.08
        elif estrategia == "Agressiva":
            base += freq * 0.35 + aus * 0.35
        elif estrategia == "Conservadora":
            base += 0.35 if 2 <= dig <= 7 else 0.05
        elif estrategia == "Aleatória Inteligente":
            base += rng.random() * 1.8
        else:
            base += freq * 0.18 + aus * 0.18 + max(0, quente) * 0.06 + max(0, atraso) * 0.06
        return max(0.05, base + rng.random() * 0.35)

    geradas, vistos = [], set()
    tentativas = 0
    while len(geradas) < quantidade and tentativas < quantidade * 500:
        tentativas += 1
        chars = []
        for pos in range(1, NUM_POSICOES_JOKER + 1):
            pesos = [peso(pos, dig) for dig in DIGITOS]
            total = sum(pesos)
            alvo = rng.random() * total
            acum = 0
            escolhido = 0
            for dig, p in zip(DIGITOS, pesos):
                acum += p
                if acum >= alvo:
                    escolhido = dig
                    break
            chars.append(str(escolhido))
        numero = "".join(chars)
        if numero in vistos:
            continue
        vistos.add(numero)
        geradas.append({
            "numero_joker": numero,
            "digitos": list(numero),
            "estrategia": estrategia,
            "score": calcular_score_joker(numero, estatisticas, estrategia),
            "observacao": "score técnico; não representa probabilidade de ganho",
        })
    return geradas

# -----------------------------
# Importação em lote do Joker
# -----------------------------
_COLUNAS_CONCURSO = {"concurso", "conc", "numero concurso", "n concurso", "nº concurso", "n concurso joker"}
_COLUNAS_DATA = {"data", "data sorteio", "data do sorteio", "dia", "sorteio"}
_COLUNAS_JOKER = {"joker", "numero joker", "número joker", "n joker", "nº joker", "resultado joker", "1 premio", "1 premio joker", "1.º premio", "1.º prémio"}
_COLUNAS_PREMIO = {"categoria", "premio", "prémio", "tipo", "premio/categoria", "prémio/categoria"}


def _limpar_nome_coluna(nome):
    texto = str(nome or "").strip().lower()
    texto = texto.replace("á", "a").replace("à", "a").replace("ã", "a").replace("â", "a")
    texto = texto.replace("é", "e").replace("ê", "e")
    texto = texto.replace("í", "i")
    texto = texto.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    texto = texto.replace("ú", "u").replace("ç", "c")
    texto = re.sub(r"[^a-z0-9]+", " ", texto).strip()
    return texto


def _achar_coluna(colunas, opcoes):
    mapa = {_limpar_nome_coluna(c): c for c in colunas}
    opcoes_norm = {_limpar_nome_coluna(o) for o in opcoes}
    for chave, original in mapa.items():
        if chave in opcoes_norm:
            return original
    for chave, original in mapa.items():
        if any(op in chave for op in opcoes_norm if op):
            return original
    return None


def _normalizar_concurso(valor):
    texto = str(valor or "").strip()
    texto = texto.replace("\\", "/")
    texto = re.sub(r"\s+", "", texto)
    m = re.search(r"(\d{1,2})\s*/\s*(20\d{2})", texto)
    if m:
        return f"{int(m.group(1)):02d}/{m.group(2)}"
    # Excel às vezes traz 49.0
    try:
        n = int(float(texto.replace(",", ".")))
        if 1 <= n <= 999:
            return str(n)
    except Exception:
        pass
    return texto


def _extrair_joker(valor):
    texto = str(valor or "").strip()
    texto = texto.replace(".0", "") if re.fullmatch(r"\d+\.0", texto) else texto
    # 9 8 9 6 8 2 -> 989682
    m = re.search(r"(?<!\d)(\d(?:\s+\d){5})(?!\d)", texto)
    if m:
        return normalizar_numero_joker(m.group(1).replace(" ", ""))
    digitos = "".join(ch for ch in texto if ch.isdigit())
    if len(digitos) >= NUM_POSICOES_JOKER:
        # prefere os últimos 6 dígitos para textos do tipo "1.º Prémio 989682"
        return normalizar_numero_joker(digitos[-NUM_POSICOES_JOKER:])
    return normalizar_numero_joker(digitos)


def _linha_para_registo(concurso, data_sorteio, joker, premio=None):
    concurso = _normalizar_concurso(concurso)
    if not concurso:
        raise ValueError("Concurso em branco.")
    data = parse_date_br(data_sorteio)
    numero = _extrair_joker(joker)
    return {
        "concurso": concurso,
        "data_sorteio": data,
        "numero_joker": numero,
        "premio": str(premio or "1.º Prémio").strip() or "1.º Prémio",
    }


def _ler_dataframe_joker(caminho):
    caminho = Path(caminho)
    ext = caminho.suffix.lower()
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(caminho, dtype=str).fillna("")
    if ext in {".csv", ".txt"}:
        try:
            return pd.read_csv(caminho, dtype=str, sep=None, engine="python").fillna("")
        except Exception:
            return pd.read_csv(caminho, dtype=str, sep=";", engine="python").fillna("")
    return None


def _texto_de_pdf(caminho):
    from pypdf import PdfReader
    reader = PdfReader(str(caminho))
    partes = []
    for page in reader.pages:
        partes.append(page.extract_text() or "")
    return "\n".join(partes)


def _registos_de_dataframe(df):
    if df is None or df.empty:
        return []
    colunas = list(df.columns)
    col_concurso = _achar_coluna(colunas, _COLUNAS_CONCURSO)
    col_data = _achar_coluna(colunas, _COLUNAS_DATA)
    col_joker = _achar_coluna(colunas, _COLUNAS_JOKER)
    col_premio = _achar_coluna(colunas, _COLUNAS_PREMIO)

    if not (col_concurso and col_data and col_joker):
        # tenta ficheiro sem cabeçalho: 1ª coluna concurso, 2ª data, 3ª Joker
        if len(colunas) >= 3:
            col_concurso, col_data, col_joker = colunas[0], colunas[1], colunas[2]
        else:
            raise ValueError("A tabela Joker deve ter pelo menos as colunas Concurso, Data e Joker.")

    registos = []
    erros = []
    for idx, row in df.iterrows():
        try:
            concurso = row.get(col_concurso, "")
            data = row.get(col_data, "")
            joker = row.get(col_joker, "")
            premio = row.get(col_premio, "1.º Prémio") if col_premio else "1.º Prémio"
            if not str(concurso).strip() and not str(data).strip() and not str(joker).strip():
                continue
            registos.append(_linha_para_registo(concurso, data, joker, premio))
        except Exception as exc:
            erros.append(f"linha {idx + 2}: {exc}")
    if not registos:
        raise ValueError("Não foi possível importar o histórico Joker. " + "; ".join(erros[:5]))
    return registos


_RE_CONCURSO = re.compile(r"(?i)(?:concurso\s*)?(\d{1,2}\s*/\s*20\d{2})")
_RE_DATA_PT = re.compile(r"(?i)(\d{1,2}\s*(?:JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ)\s*20\d{2})")
_RE_DATA_NUM = re.compile(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})")
_RE_JOKER = re.compile(r"(?<!\d)(\d(?:\s+\d){5}|\d{6})(?!\d)")


def _registos_de_texto(texto):
    texto = str(texto or "")
    if not texto.strip():
        return []

    # Primeiro tenta blocos iniciados por "Concurso 49/2025".
    partes = re.split(r"(?=\bConcurso\s+\d{1,2}\s*/\s*20\d{2}\b)", texto, flags=re.I)
    candidatos = [p.strip() for p in partes if p.strip()]
    if len(candidatos) <= 1:
        candidatos = [ln.strip() for ln in texto.splitlines() if ln.strip()]

    registos = []
    for bloco in candidatos:
        m_concurso = _RE_CONCURSO.search(bloco)
        m_data = _RE_DATA_PT.search(bloco) or _RE_DATA_NUM.search(bloco)
        jokers = _RE_JOKER.findall(bloco)
        if not (m_concurso and m_data and jokers):
            continue
        joker = jokers[-1]
        # evita capturar 202506 como Joker quando a linha é muito incompleta
        try:
            registos.append(_linha_para_registo(m_concurso.group(1), m_data.group(1), joker, "1.º Prémio"))
        except Exception:
            continue

    # Segundo modo: linhas em tabela copiada, separadas por tab, ponto e vírgula ou vírgula.
    if not registos:
        for linha in texto.splitlines():
            cells = [c.strip() for c in re.split(r"\t|;|,", linha) if c.strip()]
            if len(cells) >= 3:
                try:
                    registos.append(_linha_para_registo(cells[0], cells[1], cells[2], cells[3] if len(cells) > 3 else "1.º Prémio"))
                except Exception:
                    pass

    # Remove duplicados dentro do ficheiro/texto, preservando o último.
    por_concurso = {r["concurso"]: r for r in registos}
    return list(por_concurso.values())


def importar_historico_joker(conexao, caminho=None, texto=None):
    """Importa histórico Joker por Excel/CSV/TXT/PDF ou texto colado.

    Formato recomendado: Concurso | Data | Joker | Categoria.
    Exemplos aceites: 49/2025 | 06/12/2025 | 989682 ou
    Concurso 49/2025 Sábado, 06 DEZ 2025 1.º Prémio 9 8 9 6 8 2.
    """
    registos = []
    if caminho:
        caminho = Path(caminho)
        if caminho.suffix.lower() == ".pdf":
            registos = _registos_de_texto(_texto_de_pdf(caminho))
        else:
            df = _ler_dataframe_joker(caminho)
            if df is not None:
                registos = _registos_de_dataframe(df)
            else:
                registos = _registos_de_texto(caminho.read_text(encoding="utf-8", errors="ignore"))
    if texto:
        registos.extend(_registos_de_texto(texto))

    por_concurso = {r["concurso"]: r for r in registos}
    registos = list(por_concurso.values())
    if not registos:
        raise ValueError("Não encontrei resultados Joker para importar. Use colunas Concurso, Data e Joker, ou cole texto do site contendo Concurso, data e número Joker.")

    cur = conexao.cursor()
    try:
        for r in registos:
            cur.execute("""
                INSERT INTO joker_resultados (concurso, data_sorteio, numero_joker, premio)
                VALUES (%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    data_sorteio=VALUES(data_sorteio),
                    numero_joker=VALUES(numero_joker),
                    premio=VALUES(premio)
            """, (r["concurso"], r["data_sorteio"], r["numero_joker"], r["premio"]))
    finally:
        cur.close()
    recalcular_estatisticas_joker(conexao)
    return len(registos)
