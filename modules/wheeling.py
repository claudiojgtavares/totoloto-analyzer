"""FATO MATEMÁTICO: cobertura verificada. HEURÍSTICA: construção gulosa.

Os limites permitem enumeração exata local; não se promete uma carteira mínima
nem se atribui maior probabilidade aos números escolhidos.
"""

from decimal import Decimal, InvalidOperation
from hashlib import sha256
from itertools import combinations
import json
import re
from math import isfinite
from time import monotonic

from modules.totoloto import metricas_cobertura

FATO_MATEMATICO = "FATO MATEMÁTICO"
HEURISTICA = "HEURÍSTICA"
MAX_POOL = 12
MAX_LINHAS = 420
TIMEOUT_SEGUNDOS = 10.0
MAX_VALOR_CVE = Decimal("999999999.99")


class ErroWheel(ValueError):
    """Validação com mensagens públicas, sem dados internos ou SQL."""


def _valor_cve(valor):
    """Valor monetário canónico, sem conversão intermédia para float."""
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        raise ErroWheel("Indique um valor CVE positivo com até duas casas decimais.") from None
    if (not numero.is_finite() or not 0 < numero <= MAX_VALOR_CVE
            or numero != numero.quantize(Decimal("0.01"))):
        raise ErroWheel("Indique um valor CVE entre 0,01 e 999.999.999,99, com até duas casas decimais.")
    return numero


def interpretar_orcamento_cve(valor):
    """Orçamento PT-PT: 1.000 é mil; 1.000,50 é mil e cinquenta centavos.

    O parser é restrito a dinheiro (duas casas), sem alterar a API de datas
    e decimais existente, que devolve float para outros consumidores.
    """
    if not isinstance(valor, str):
        return _valor_cve(valor)
    texto = valor.strip()
    if len(texto) > 32:
        raise ErroWheel("O orçamento indicado é demasiado longo.")
    if re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:\.[0-9]{3})+)(?:,[0-9]{1,2})?", texto):
        texto = texto.replace(".", "").replace(",", ".")
    elif not re.fullmatch(r"[0-9]+\.[0-9]{1,2}", texto):
        raise ErroWheel("Orçamento inválido. Use, por exemplo, 1.000 ou 1.000,50 CVE.")
    return _valor_cve(texto)


def formatar_cve_exato(valor):
    """Apresentação PT-PT, preservando centavos sem arredondar para inteiros."""
    numero = Decimal(str(valor))
    casas = 0 if numero == numero.to_integral_value() else 2
    return format(numero, f",.{casas}f").translate(str.maketrans({",": ".", ".": ","})) + " CVE"


def _inteiro(valor, minimo, maximo, campo):
    if type(valor) is not int or not minimo <= valor <= maximo:
        raise ErroWheel(f"{campo}: indique um inteiro entre {minimo} e {maximo}.")
    return valor


def _pool_valido(pool):
    pool = tuple(pool)
    if not 1 <= len(pool) <= MAX_POOL:
        raise ErroWheel(f"Escolha entre 1 e {MAX_POOL} números para o conjunto.")
    for n in pool:
        _inteiro(n, 1, 45, "Número do conjunto")
    if len(set(pool)) != len(pool):
        raise ErroWheel("O conjunto não pode conter números repetidos.")
    return tuple(sorted(pool))


def verificar_cobertura(linhas, pool, t=2, tamanho_linha=None):
    """Enumeração independente da seleção: FATO MATEMÁTICO.

Aceita blocos pequenos para verificar exemplos combinatórios. No relatório
Totoloto, tamanho_linha=6 é obrigatório. Duplicados não aumentam a cobertura.
"""
    pool = _pool_valido(pool)
    _inteiro(t, 1, len(pool), "Nível de cobertura")
    linhas = list(linhas)
    if len(linhas) > MAX_LINHAS:
        raise ErroWheel(f"O certificado aceita até {MAX_LINHAS} linhas.")
    if tamanho_linha is None:
        tamanho_linha = len(linhas[0]) if linhas else min(6, len(pool))
    _inteiro(tamanho_linha, t, len(pool), "Tamanho de linha")
    normalizadas = []
    for linha in linhas:
        linha = tuple(linha)
        if len(linha) != tamanho_linha:
            raise ErroWheel("Todas as linhas devem ter o tamanho indicado.")
        for n in linha:
            _inteiro(n, 1, 45, "Número da linha")
        if len(set(linha)) != len(linha):
            raise ErroWheel("Uma linha não pode repetir números.")
        if not set(linha) <= set(pool):
            raise ErroWheel("Todas as linhas devem usar apenas números do conjunto escolhido.")
        normalizadas.append(tuple(sorted(linha)))
    alvo = set(combinations(pool, t))
    cobertos = set()
    for linha in normalizadas:
        cobertos.update(combinations(linha, t))
    descobertos = sorted(alvo - cobertos)
    conteudo = {"versao": 1, "numeros_pool": pool, "nivel": t,
                "tamanho_linha": tamanho_linha, "linhas": sorted(normalizadas)}
    return {
        "rotulo": FATO_MATEMATICO,
        **conteudo, "pool": len(pool),
        "subconjuntos_totais": len(alvo), "cobertos": len(cobertos),
        "descobertos": len(descobertos), "subconjuntos_descobertos": descobertos,
        "cobertura": len(cobertos) / len(alvo),
        "cobertura_completa": not descobertos,
        "linhas_duplicadas": len(normalizadas) - len(set(normalizadas)),
        "hash_sha256": sha256(json.dumps(conteudo, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest(),
    }


def _construir(pool, quantidade_linhas, tamanho_linha, t, timeout_segundos):
    pool = _pool_valido(pool)
    _inteiro(quantidade_linhas, 1, MAX_LINHAS, "Máximo de linhas")
    _inteiro(tamanho_linha, 1, len(pool), "Tamanho de linha")
    _inteiro(t, 1, tamanho_linha, "Nível de cobertura")
    if (isinstance(timeout_segundos, bool) or not isinstance(timeout_segundos, (int, float))
            or not isfinite(timeout_segundos) or not 0 < timeout_segundos <= TIMEOUT_SEGUNDOS):
        raise ErroWheel(f"O prazo deve ser positivo e não exceder {TIMEOUT_SEGUNDOS:g} segundos.")
    inicio = monotonic()
    prazo = inicio + timeout_segundos
    # Máscaras aceleram a seleção. O certificado usa enumeração independente.
    indices = {s: i for i, s in enumerate(combinations(pool, t))}
    restantes = (1 << len(indices)) - 1
    candidatos = []
    linhas = []
    motivo = "limite_linhas"
    for linha in combinations(pool, tamanho_linha):
        if monotonic() >= prazo:
            return linhas, "timeout", monotonic() - inicio
        mascara = sum(1 << indices[s] for s in combinations(linha, t))
        candidatos.append((linha, mascara))
    while restantes and len(linhas) < quantidade_linhas:
        melhor = None
        ganho = 0
        for i, (_, mascara) in enumerate(candidatos):
            if monotonic() >= prazo:
                return linhas, "timeout", monotonic() - inicio
            novo = (mascara & restantes).bit_count()
            # Desempate lexicográfico: mesma entrada, mesmas linhas.
            if novo > ganho:
                melhor, ganho = i, novo
        if melhor is None:
            break
        linha, mascara = candidatos.pop(melhor)
        linhas.append(linha)
        restantes &= ~mascara
    if not restantes:
        motivo = "cobertura_completa"
    return linhas, motivo, monotonic() - inicio


def construir_wheel(pool, quantidade_linhas, tamanho_linha=6, t=2):
    """HEURÍSTICA determinística; conserva a API original que devolve linhas."""
    linhas, motivo, _ = _construir(pool, quantidade_linhas, tamanho_linha, t, TIMEOUT_SEGUNDOS)
    if motivo == "timeout":
        raise TimeoutError("Construção interrompida pelo prazo; use o relatório para obter o parcial.")
    return linhas


def planear_wheel(pool, quantidade_linhas, t=3, preco_aposta=30,
                  timeout_segundos=TIMEOUT_SEGUNDOS):
    """Carteira de análise 6/45, custo simulado e certificado; sem compras."""
    pool = _pool_valido(pool)
    if len(pool) < 6:
        raise ErroWheel(f"Escolha entre 6 e {MAX_POOL} números distintos de 1 a 45.")
    _inteiro(t, 2, 3, "Nível de cobertura")
    try:
        preco = Decimal(str(preco_aposta))
    except (InvalidOperation, ValueError):
        raise ErroWheel("O preço por linha deve ser um valor CVE positivo e finito.") from None
    if not preco.is_finite() or preco <= 0:
        raise ErroWheel("O preço por linha deve ser um valor CVE positivo e finito.")
    linhas, motivo, tempo = _construir(pool, quantidade_linhas, 6, t, timeout_segundos)
    certificado = verificar_cobertura(linhas, pool, t, tamanho_linha=6)
    garantia = None
    if certificado["cobertura_completa"]:
        garantia = (
            f"Se pelo menos {t} números sorteados pertencerem ao conjunto escolhido, "
            f"existe uma linha desta carteira com pelo menos {t} acertos. "
            "Esta garantia é condicional e pressupõe jogar todas as linhas apresentadas."
        )
    return {
        "linhas": linhas, "certificado": certificado, "garantia": garantia,
        "rotulo_construcao": HEURISTICA, "metodo": "Seleção gulosa determinística",
        "motivo": motivo, "incompleto": motivo == "timeout",
        "tempo_segundos": round(tempo, 3), "prazo_segundos": timeout_segundos,
        "max_linhas": quantidade_linhas, "preco_linha": preco,
        "custo_simulado": preco * len(linhas),
        "metricas": metricas_cobertura(linhas),
    }


def planear_wheel_orcamento(pool, orcamento, t=3, preco_aposta=30,
                            timeout_segundos=TIMEOUT_SEGUNDOS):
    """HEURÍSTICA de cobertura sob orçamento; certificado = FATO MATEMÁTICO.

    Todas as linhas custam o mesmo: o orçamento define o limite de linhas.
    Não constitui reserva de dinheiro nem movimento na banca.
    """
    montante = interpretar_orcamento_cve(orcamento)
    preco = _valor_cve(preco_aposta)
    linhas_financiaveis = int(montante // preco)
    if not linhas_financiaveis:
        raise ErroWheel(f"O orçamento de {formatar_cve_exato(montante)} não permite uma linha "
                        f"de {formatar_cve_exato(preco)}. Aumente o orçamento desta simulação.")
    limite = min(MAX_LINHAS, linhas_financiaveis)
    r = planear_wheel(pool, limite, t=t, preco_aposta=preco, timeout_segundos=timeout_segundos)
    if r["motivo"] == "limite_linhas":
        r["motivo"] = "limite_tecnico" if linhas_financiaveis > MAX_LINHAS else "limite_orcamento"
    custo = r["custo_simulado"]
    r.update(
        orcamento=montante, saldo_nao_utilizado=montante - custo,
        linhas_financiaveis=linhas_financiaveis,
        limitado_por_teto=linhas_financiaveis > MAX_LINHAS,
        cobertura_por_cve=(Decimal(r["certificado"]["cobertos"]) / custo if custo else None),
    )
    return r
