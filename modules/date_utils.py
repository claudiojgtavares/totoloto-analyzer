from datetime import datetime, date
from decimal import Decimal, InvalidOperation
import re

_FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d-%m-%y")
_MESES_PT = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3, "março": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}


def _normalizar_texto_data(texto):
    texto = str(texto or "").strip()
    texto = texto.replace(".", " ").replace(",", " ").replace("-", " ")
    texto = re.sub(r"\s+", " ", texto)
    return texto


def parse_date_br(valor):
    """Aceita dd/mm/aaaa, aaaa-mm-dd e datas PT-PT como 06 DEZ 2025."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    for fmt in _FORMATOS_DATA:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            pass

    # Formatos vindos do site: Sábado, 06 DEZ 2025 | 23-mai-26 | 06 DEZ 2025
    limpo = _normalizar_texto_data(texto).lower()
    partes = limpo.split()
    for i in range(len(partes) - 2):
        dia_txt, mes_txt, ano_txt = partes[i], partes[i + 1], partes[i + 2]
        if not dia_txt.isdigit():
            continue
        mes = _MESES_PT.get(mes_txt)
        if not mes or not ano_txt.isdigit():
            continue
        dia = int(dia_txt)
        ano = int(ano_txt)
        if ano < 100:
            ano += 2000
        try:
            return date(ano, mes, dia)
        except ValueError:
            continue

    raise ValueError("Data inválida. Use o formato dd/mm/aaaa ou uma data PT-PT, por exemplo 06 DEZ 2025.")


def format_date_br(valor):
    if valor in (None, ""):
        return "-"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    if isinstance(valor, date):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            dt = datetime.strptime(texto[:19] if fmt.endswith("%S") else texto[:10], fmt)
            return dt.strftime("%d/%m/%Y" if not fmt.endswith("%S") else "%d/%m/%Y %H:%M")
        except ValueError:
            pass
    try:
        return parse_date_br(texto).strftime("%d/%m/%Y")
    except Exception:
        return texto


def parse_decimal_br(valor, padrao=0):
    if valor in (None, ""):
        return float(padrao)
    if isinstance(valor, (int, float, Decimal)):
        return float(valor)
    texto = str(valor).strip().replace(" ", "")
    if not texto:
        return float(padrao)

    sinal = ""
    if texto[0] in "+-":
        sinal, texto = texto[0], texto[1:]
    if not texto:
        raise ValueError(f"Valor numérico inválido: {valor}")

    # Em formato PT-PT, a vírgula é o separador decimal. Quando não existe
    # vírgula, um ponto seguido de três dígitos é interpretado como milhares;
    # um ou dois dígitos depois do ponto continuam a ser casas decimais.
    if "," in texto:
        if texto.count(",") != 1:
            raise ValueError(f"Valor numérico inválido: {valor}")
        inteiro, fracao = texto.split(",")
        grupos = inteiro.split(".")
        if not inteiro or not fracao or not all(grupo.isdigit() for grupo in grupos) or not fracao.isdigit():
            raise ValueError(f"Valor numérico inválido: {valor}")
        if len(grupos) > 1 and (len(grupos[0]) < 1 or any(len(grupo) != 3 for grupo in grupos[1:])):
            raise ValueError(f"Valor numérico inválido: {valor}")
        texto = "".join(grupos) + "." + fracao
    elif "." in texto:
        grupos = texto.split(".")
        if not all(grupo.isdigit() for grupo in grupos) or not grupos[0]:
            raise ValueError(f"Valor numérico inválido: {valor}")
        if len(grupos) == 1:
            texto = grupos[0]
        elif len(grupos) == 2 and len(grupos[1]) in (1, 2):
            texto = ".".join(grupos)
        elif all(len(grupo) == 3 for grupo in grupos[1:]):
            texto = "".join(grupos)
        else:
            raise ValueError(f"Valor numérico inválido: {valor}")
    elif not texto.isdigit():
        raise ValueError(f"Valor numérico inválido: {valor}")

    try:
        numero = Decimal(f"{sinal}{texto}")
        if not numero.is_finite():
            raise ValueError(f"Valor numérico inválido: {valor}")
        return float(numero)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Valor numérico inválido: {valor}")
