
from pathlib import Path
from datetime import datetime, timedelta
from itertools import groupby
import logging
import time
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from modules.gerador import format_cve
from modules.date_utils import format_date_br
from config import Config


AZUL = colors.HexColor("#0B5ED7")
AZUL_ESCURO = colors.HexColor("#073B82")
AZUL_CLARO = colors.HexColor("#EAF3FF")
CINZA = colors.HexColor("#64748B")
LINHA = colors.HexColor("#D9E2F2")
VERDE = colors.HexColor("#0F8A5F")
_LOGGER = logging.getLogger(__name__)
_EXTENSOES_EXPORT = {".pdf", ".xlsx", ".xls"}
_PREFIXOS_FORMULA_EXCEL = ("=", "+", "-", "@")


def _neutralizar_formula_excel(valor):
    """Mantém texto livre como texto literal ao abrir a exportação no Excel."""
    if isinstance(valor, str) and valor.startswith(_PREFIXOS_FORMULA_EXCEL):
        return "'" + valor
    return valor


def limpar_exports(pasta, dias=None, max_ficheiros=None, agora=None):
    """Aplica a política de retenção a uma pasta de PDF ou Excel.

    Os limites são inclusivos e independentes: ficheiros fora do prazo são
    removidos primeiro e, depois, ficam apenas os mais recentes até ao limite
    máximo. O valor zero desativa cada limite. `.gitkeep` e outras extensões
    não são tocados.
    """
    raiz = Path(pasta)
    raiz.mkdir(parents=True, exist_ok=True)
    dias = Config.EXPORT_RETENTION_DAYS if dias is None else max(0, int(dias))
    max_ficheiros = (Config.EXPORT_RETENTION_MAX_FILES
                     if max_ficheiros is None else max(0, int(max_ficheiros)))
    agora_ts = time.time() if agora is None else float(agora)
    candidatos = [p for p in raiz.iterdir() if p.is_file() and p.suffix.lower() in _EXTENSOES_EXPORT]
    removidos = 0
    if dias:
        limite = agora_ts - timedelta(days=dias).total_seconds()
        for ficheiro in list(candidatos):
            try:
                if ficheiro.stat().st_mtime < limite:
                    ficheiro.unlink()
                    candidatos.remove(ficheiro)
                    removidos += 1
            except OSError:
                _LOGGER.warning("Não foi possível remover exportação antiga: %s", ficheiro, exc_info=True)
    if max_ficheiros and len(candidatos) > max_ficheiros:
        candidatos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for ficheiro in candidatos[max_ficheiros:]:
            try:
                ficheiro.unlink()
                removidos += 1
            except OSError:
                _LOGGER.warning("Não foi possível aplicar limite de exports: %s", ficheiro, exc_info=True)
    return removidos


def exportar_excel_jogos(jogos, pasta="exports/excel"):
    Path(pasta).mkdir(parents=True, exist_ok=True)
    nome = Path(pasta) / f"historico_apostas_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df = pd.DataFrame(jogos)
    if not df.empty:
        for col in ["created_at"]:
            if col in df.columns:
                df[col] = df[col].apply(format_date_br)
        for col in df.columns:
            df[col] = df[col].map(_neutralizar_formula_excel)
    df.to_excel(nome, index=False)
    limpar_exports(pasta)
    return str(nome)


def _safe(valor, padrao="-"):
    return padrao if valor in (None, "") else str(valor)


def _numeros_formatados(valor):
    if isinstance(valor, (list, tuple)):
        nums = [str(v).strip() for v in valor]
    else:
        nums = [v.strip() for v in str(valor or "").replace(";", ",").split(",") if v.strip()]
    return "  ".join(nums) if nums else "-"


def _header_footer(canvas, doc):
    canvas.saveState()
    largura, altura = landscape(A4)
    canvas.setFillColor(AZUL_ESCURO)
    canvas.rect(0, altura - 1.15 * cm, largura, 1.15 * cm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 12)
    canvas.drawString(1.1 * cm, altura - 0.72 * cm, "Totoloto Analyzer Offline")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(largura - 1.1 * cm, altura - 0.72 * cm, f"Página {doc.page}")
    canvas.setFillColor(CINZA)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(1.1 * cm, 0.65 * cm, "Geração estatística semanal - score técnico, não é probabilidade de ganhar.")
    canvas.drawRightString(largura - 1.1 * cm, 0.65 * cm, "Moeda: CVE")
    canvas.restoreState()


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="TituloAzul", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22,
        textColor=AZUL_ESCURO, leading=26, spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="Subtitulo", parent=styles["Normal"], fontSize=10, textColor=CINZA, leading=14, spaceAfter=12
    ))
    styles.add(ParagraphStyle(
        name="Secao", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13,
        textColor=AZUL_ESCURO, leading=16, spaceBefore=12, spaceAfter=8
    ))
    styles.add(ParagraphStyle(
        name="Aviso", parent=styles["Normal"], fontSize=9, textColor=AZUL_ESCURO,
        backColor=AZUL_CLARO, borderColor=LINHA, borderWidth=0.5, borderPadding=8, leading=13, spaceAfter=12
    ))
    styles.add(ParagraphStyle(
        name="Centro", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9
    ))
    styles.add(ParagraphStyle(
        name="Direita", parent=styles["Normal"], alignment=TA_RIGHT, fontSize=9
    ))
    return styles


def _resumo_table(jogos):
    total_jogos = len(jogos)
    custo_total = sum(float(j.get("custo_final", 0) or 0) for j in jogos)
    estrategias = len(set(str(j.get("estrategia") or "-") for j in jogos))
    simples = sum(1 for j in jogos if str(j.get("tipo_aposta") or "").lower().startswith("simples"))
    multiplas = total_jogos - simples
    dados = [
        ["Apostas", str(total_jogos), "Custo total", format_cve(custo_total)],
        ["Estratégias", str(estrategias), "Simples / Múltiplas", f"{simples} / {multiplas}"],
    ]
    tabela = Table(dados, colWidths=[3.8 * cm, 2.6 * cm, 4.2 * cm, 3.2 * cm])
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), AZUL_CLARO),
        ("TEXTCOLOR", (0, 0), (-1, -1), AZUL_ESCURO),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.6, LINHA),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, LINHA),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    return tabela


def exportar_pdf_jogos(jogos, pasta="exports/pdf"):
    Path(pasta).mkdir(parents=True, exist_ok=True)
    nome = Path(pasta) / f"relatorio_geracao_estatistica_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    doc = SimpleDocTemplate(
        str(nome), pagesize=landscape(A4), rightMargin=1.1 * cm, leftMargin=1.1 * cm,
        topMargin=1.65 * cm, bottomMargin=1.2 * cm
    )
    styles = _styles()
    story = []

    story.append(Paragraph("Relatório - Geração Estatística Semanal", styles["TituloAzul"]))
    story.append(Paragraph(
        f"Gerado em {datetime.now().strftime('%d/%m/%Y às %H:%M')} • Sistema offline • Valores em CVE",
        styles["Subtitulo"]
    ))
    story.append(Paragraph(
        "Aviso: o score é uma nota estatística baseada em filtros, histórico, equilíbrio e estratégia. "
        "Não representa probabilidade de ganho, nem garantia de prémio.", styles["Aviso"]
    ))

    if not jogos:
        story.append(Paragraph("Ainda não existem apostas geradas para exportar.", styles["Secao"]))
        doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        limpar_exports(pasta)
        return str(nome)

    story.append(_resumo_table(jogos))
    story.append(Spacer(1, 0.35 * cm))

    jogos_ordenados = sorted(jogos, key=lambda j: (str(j.get("estrategia") or "Sem estratégia"), str(j.get("created_at") or ""), int(j.get("id") or 0)))
    for estrategia, grupo in groupby(jogos_ordenados, key=lambda j: str(j.get("estrategia") or "Sem estratégia")):
        grupo = list(grupo)
        story.append(Paragraph(f"Estratégia usada: {estrategia}", styles["Secao"]))
        data = [[
        "N.º", "Concurso", "Tipo", "Números", "Apostas", "Score técnico (%)", "Custo", "Joker", "Custo final", "Data"
        ]]
        for idx, jogo in enumerate(grupo, start=1):
            data.append([
                str(idx),
                _safe(jogo.get("concurso")),
                _safe(jogo.get("tipo_aposta")),
                _numeros_formatados(jogo.get("numeros")),
                str(jogo.get("apostas_simples") or 0),
        f"{float(jogo.get('score', 0) or 0):.2f}%".replace(".", ","),
                format_cve(jogo.get("custo_total", 0)),
                format_cve(jogo.get("custo_joker", 0)),
                format_cve(jogo.get("custo_final", 0)),
                format_date_br(jogo.get("created_at")),
            ])
        tabela = Table(data, repeatRows=1, colWidths=[1.0*cm, 1.8*cm, 2.1*cm, 4.5*cm, 1.7*cm, 1.5*cm, 2.2*cm, 2.0*cm, 2.3*cm, 2.8*cm])
        tabela.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL_ESCURO),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("BACKGROUND", (0, 1), (-1, -1), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FBFF")]),
            ("GRID", (0, 0), (-1, -1), 0.35, LINHA),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (2, -1), "CENTER"),
            ("ALIGN", (4, 1), (8, -1), "RIGHT"),
            ("TEXTCOLOR", (5, 1), (5, -1), VERDE),
            ("FONTNAME", (3, 1), (3, -1), "Helvetica-Bold"),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tabela)
        story.append(Spacer(1, 0.25 * cm))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    limpar_exports(pasta)
    return str(nome)
