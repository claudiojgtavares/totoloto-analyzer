from pathlib import Path
from datetime import datetime, date, timedelta
import math
import re
import unicodedata

import pandas as pd
from modules.date_utils import parse_date_br

COLUNAS_ESPERADAS = {
    "numero": ["número", "numero", "numeros", "números", "num", "bola", "dezena"],
    "numero_saidas": [
        "número de saídas", "numero de saidas", "numeros de saidas", "números de saídas",
        "saidas", "saídas", "qtd saidas", "quantidade de saidas"
    ],
    "percentual_saidas": ["% de saídas", "% de saidas", "percentual", "percentual de saidas", "%"],
    "ultimo_sorteio": ["último sorteio", "ultimo sorteio", "concurso", "ultimo concurso"],
    "data_ultimo_sorteio": ["data do sorteio", "data ultimo sorteio", "data", "data do último sorteio"],
    "ausencias": ["ausências", "ausencias", "atraso", "atrasos"],
}

MESES_PT = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3, "março": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "sep": 9, "setembro": 9,
    "out": 10, "oct": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dec": 12, "dezembro": 12,
}


def _sem_acentos(texto):
    texto = str(texto)
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _normalizar_nome(nome):
    texto = _sem_acentos(nome).strip().lower().replace("_", " ")
    texto = re.sub(r"[^a-z0-9% ]+", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _mapear_colunas(df):
    mapa = {}
    nomes = {_normalizar_nome(c): c for c in df.columns}
    for destino, possibilidades in COLUNAS_ESPERADAS.items():
        for p in possibilidades:
            p_norm = _normalizar_nome(p)
            if p_norm in nomes:
                mapa[nomes[p_norm]] = destino
                break
    return df.rename(columns=mapa)


def _normalizar_dataframe(df):
    """Remove linhas vazias, detecta cabeçalho e padroniza nomes."""
    df = df.dropna(how="all").copy()
    df = _mapear_colunas(df)
    obrigatorias = set(COLUNAS_ESPERADAS.keys())
    if obrigatorias.issubset(set(df.columns)):
        return df

    # Caso o Excel venha com linhas acima do cabeçalho, procura a linha que contém "Número".
    for idx, row in df.iterrows():
        valores = [_normalizar_nome(v) for v in row.tolist()]
        texto = " ".join(valores)
        if "numero" in texto and ("saida" in texto or "%" in texto) and "ausencia" in texto:
            novos_headers = [str(v).strip() for v in row.tolist()]
            df2 = df.loc[idx + 1:].copy()
            df2.columns = novos_headers
            return _mapear_colunas(df2)
    return df


def _valor_vazio(valor):
    if valor is None:
        return True
    if isinstance(valor, float) and math.isnan(valor):
        return True
    texto = str(valor).strip()
    return texto == "" or texto.lower() in {"nan", "none", "nat"}


def _parse_int(valor, campo="valor"):
    if _valor_vazio(valor):
        return 0
    if isinstance(valor, (int,)):
        return int(valor)
    if isinstance(valor, float):
        return int(round(valor))
    texto = str(valor).strip().replace("%", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        return int(float(texto))
    except Exception as exc:
        raise ValueError(f"Campo {campo} inválido: {valor}") from exc


def _parse_percentual(valor):
    if _valor_vazio(valor):
        return 0.0
    if isinstance(valor, (int, float)):
        return round(float(valor), 2)
    texto = str(valor).strip().replace("%", "").replace(" ", "")
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        texto = texto.replace(",", ".")
    return round(float(texto or 0), 2)


def _excel_serial_para_data(valor):
    try:
        numero = float(valor)
    except Exception:
        return None
    if not 20000 <= numero <= 80000:
        return None
    # Excel/Windows: dia 1 = 1900-01-01. Usar 1899-12-30 corrige o bug histórico de 1900.
    return (datetime(1899, 12, 30) + timedelta(days=int(numero))).date()


def _ano_completo(ano):
    ano = int(ano)
    return 2000 + ano if ano < 100 else ano


def parse_data_estatistica(valor):
    """Converte datas brasileiras, meses abreviados e serial Excel para date."""
    if _valor_vazio(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.date()
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if isinstance(valor, (int, float)):
        dt = _excel_serial_para_data(valor)
        if dt:
            return dt

    texto = str(valor).strip().lower().replace(".", "")
    texto_sem = _sem_acentos(texto)

    if re.fullmatch(r"\d+(?:\.0)?", texto_sem):
        dt = _excel_serial_para_data(float(texto_sem))
        if dt:
            return dt

    # Ex.: 23-mai-26, 23/mai/2026, 23 mai 2026
    m = re.fullmatch(r"(\d{1,2})[\-/\s]+([a-zç]{3,9})[\-/\s]+(\d{2,4})", texto_sem)
    if m:
        dia = int(m.group(1))
        mes = MESES_PT.get(m.group(2))
        ano = _ano_completo(m.group(3))
        if not mes:
            raise ValueError(f"Mês inválido na data: {valor}")
        return date(ano, mes, dia)

    # Ex.: 23/05/2026, 23-05-26, 2026-05-23
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(texto_sem, fmt).date()
        except ValueError:
            pass

    try:
        return parse_date_br(valor)
    except Exception as exc:
        raise ValueError(f"Data inválida: {valor}. Use dd/mm/aaaa ou datas como 23-mai-26.") from exc


def parse_ultimo_sorteio(valor):
    """Normaliza o campo Último Sorteio.

    O ficheiro oficial pode vir como 21/2026. Em Excel/PDF alguns concursos como
    9/2026 podem ser convertidos para 'set-26' ou serial Excel; nesses casos,
    voltamos para 9/2026.
    """
    if _valor_vazio(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return f"{valor.month}/{valor.year}"
    if isinstance(valor, datetime):
        return f"{valor.month}/{valor.year}"
    if isinstance(valor, date):
        return f"{valor.month}/{valor.year}"
    if isinstance(valor, (int, float)):
        dt = _excel_serial_para_data(valor)
        if dt:
            return f"{dt.month}/{dt.year}"
        return str(int(valor))

    texto = str(valor).strip().lower().replace(".", "")
    texto_sem = _sem_acentos(texto)

    # Ex.: 21/2026, 21-2026, 21/26
    m = re.fullmatch(r"(\d{1,2})\s*[/-]\s*(\d{2,4})", texto_sem)
    if m:
        concurso = int(m.group(1))
        ano = _ano_completo(m.group(2))
        return f"{concurso}/{ano}"

    # Ex.: set-26, mar-26, out-26. São conversões automáticas do Excel de 9/2026 etc.
    m = re.fullmatch(r"([a-zç]{3,9})\s*[/-]\s*(\d{2,4})", texto_sem)
    if m:
        mes = MESES_PT.get(m.group(1))
        ano = _ano_completo(m.group(2))
        if mes:
            return f"{mes}/{ano}"

    # Ex.: serial Excel em texto.
    if re.fullmatch(r"\d+(?:\.0)?", texto_sem):
        numero = float(texto_sem)
        dt = _excel_serial_para_data(numero)
        if dt:
            return f"{dt.month}/{dt.year}"
        return str(int(numero))

    return str(valor).strip()


def _ler_csv(caminho):
    return pd.read_csv(caminho, sep=None, engine="python")


def _ler_excel(caminho):
    try:
        return pd.read_excel(caminho)
    except ImportError as exc:
        if Path(caminho).suffix.lower() == ".xls":
            raise ValueError("Para importar .xls, instale a dependência xlrd: python -m pip install xlrd") from exc
        raise


def _linha_pdf_para_registro(linha):
    limpa = re.sub(r"\s+", " ", linha.strip())
    if not limpa:
        return None
    padrao_data = r"(?:\d{1,2}[/-][A-Za-zÀ-ÿçÇ]{3,9}[/-]\d{2,4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{1,2}-\d{1,2})"
    padrao = re.compile(
        rf"^\s*(?P<numero>\d{{1,2}})\s+"
        rf"(?P<saidas>\d+)\s+"
        rf"(?P<percentual>\d+(?:[,.]\d+)?)\s+"
        rf"(?P<ultimo>\S+)\s+"
        rf"(?P<data>{padrao_data})\s+"
        rf"(?P<ausencias>\d+)\s*$",
        re.IGNORECASE,
    )
    m = padrao.match(limpa)
    if not m:
        return None
    numero = _parse_int(m.group("numero"), "Número")
    if not 1 <= numero <= 45:
        return None
    return {
        "numero": numero,
        "numero_saidas": _parse_int(m.group("saidas"), "Número de Saídas"),
        "percentual_saidas": _parse_percentual(m.group("percentual")),
        "ultimo_sorteio": parse_ultimo_sorteio(m.group("ultimo")),
        "data_ultimo_sorteio": parse_data_estatistica(m.group("data")),
        "ausencias": _parse_int(m.group("ausencias"), "Ausências"),
    }


def _ler_pdf_tabela_simples(caminho):
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise ValueError("Para importar PDF, instale também: python -m pip install pypdf") from exc

    reader = PdfReader(str(caminho))
    texto = "\n".join(page.extract_text() or "" for page in reader.pages)
    linhas = texto.splitlines()

    registros = []
    for linha in linhas:
        registro = _linha_pdf_para_registro(linha)
        if registro:
            registros.append(registro)

    # Proteção: espera-se 45 números no Totoloto.
    registros_unicos = {}
    for r in registros:
        registros_unicos[r["numero"]] = r
    registros = [registros_unicos[n] for n in sorted(registros_unicos)]

    if not registros:
        raise ValueError("Não consegui identificar uma tabela estatística no PDF. Use Excel/CSV ou envie um PDF com tabela legível.")
    if len(registros) < 45:
        raise ValueError(f"A tabela do PDF foi lida, mas só encontrei {len(registros)} número(s). Verifique se o PDF tem os 45 números.")
    return pd.DataFrame(registros)


def _preparar_registros(df):
    df = _normalizar_dataframe(df)
    obrigatorias = ["numero", "numero_saidas", "percentual_saidas", "ultimo_sorteio", "data_ultimo_sorteio", "ausencias"]
    faltando = [c for c in obrigatorias if c not in df.columns]
    if faltando:
        raise ValueError("Colunas ausentes: " + ", ".join(faltando))

    registros = []
    for _, row in df.iterrows():
        if _valor_vazio(row.get("numero")):
            continue
        try:
            numero = _parse_int(row.get("numero"), "Número")
        except ValueError:
            # Ignora rodapés/observações do ficheiro, como as notas de Ausências e % de Saídas.
            continue
        if not 1 <= numero <= 45:
            continue
        registros.append({
            "numero": numero,
            "numero_saidas": _parse_int(row.get("numero_saidas"), "Número de Saídas"),
            "percentual_saidas": _parse_percentual(row.get("percentual_saidas")),
            "ultimo_sorteio": parse_ultimo_sorteio(row.get("ultimo_sorteio")),
            "data_ultimo_sorteio": parse_data_estatistica(row.get("data_ultimo_sorteio")),
            "ausencias": _parse_int(row.get("ausencias"), "Ausências"),
        })

    # Mantém a última ocorrência se houver duplicados.
    unicos = {r["numero"]: r for r in registros}
    registros = [unicos[n] for n in sorted(unicos)]
    if not registros:
        raise ValueError("Nenhuma linha estatística válida foi encontrada no ficheiro.")
    if len(registros) != 45:
        raise ValueError(
            f"A importação estatística exige os 45 números únicos do Totoloto; foram encontrados {len(registros)}."
        )
    return registros


def carregar_registros_estatistica(caminho):
    """Lê CSV/Excel/PDF e retorna lista de dicionários normalizada. Útil para testes."""
    caminho = Path(caminho)
    ext = caminho.suffix.lower()
    if ext == ".csv":
        df = _ler_csv(caminho)
    elif ext in [".xlsx", ".xls"]:
        df = _ler_excel(caminho)
    elif ext == ".pdf":
        df = _ler_pdf_tabela_simples(caminho)
    else:
        raise ValueError("Formato inválido. Use CSV, Excel ou PDF.")
    return _preparar_registros(df)


def importar_arquivo_estatistica(caminho, conexao):
    registros = carregar_registros_estatistica(caminho)

    cursor = conexao.cursor()
    sql = """
    INSERT INTO estatisticas_numeros
    (numero, numero_saidas, percentual_saidas, ultimo_sorteio, data_ultimo_sorteio, ausencias,
     probabilidade_teorica, desvio_frequencia, frequencia_ultimos_5, frequencia_ultimos_10)
    VALUES (%s, %s, %s, %s, %s, %s, 13.33, %s, 0, 0)
    ON DUPLICATE KEY UPDATE
        numero_saidas = VALUES(numero_saidas),
        percentual_saidas = VALUES(percentual_saidas),
        ultimo_sorteio = VALUES(ultimo_sorteio),
        data_ultimo_sorteio = VALUES(data_ultimo_sorteio),
        ausencias = VALUES(ausencias),
        desvio_frequencia = VALUES(desvio_frequencia)
    """
    total = 0
    for row in registros:
        desvio = round(float(row["percentual_saidas"] or 0) - 13.33, 2)
        cursor.execute(sql, (
            row["numero"],
            row["numero_saidas"],
            row["percentual_saidas"],
            row["ultimo_sorteio"],
            row["data_ultimo_sorteio"],
            row["ausencias"],
            desvio,
        ))
        total += 1
    cursor.close()
    return total
