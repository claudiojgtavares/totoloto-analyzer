from pathlib import Path
from math import floor, comb, isfinite
from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import uuid
import re
import hashlib
import hmac
import secrets
import logging
from logging.handlers import RotatingFileHandler
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, session, abort
from werkzeug.utils import secure_filename
from config import Config
from database.connection import connection_scope, get_connection, transaction_scope
from modules.estatistica import recalcular_estatisticas
from modules.importador import importar_arquivo_estatistica
from modules.gerador import gerar_jogos_estatisticos, format_cve, calcular_custo, ESTRATEGIAS_VALIDAS
from modules.backtesting import executar_backtesting, max_bilhetes_backtesting, resumo_backtesting_demo
from modules.relatorios import exportar_excel_jogos, exportar_pdf_jogos
from modules.date_utils import parse_date_br, format_date_br, parse_decimal_br
from modules.joker import (
    normalizar_numero_joker, recalcular_estatisticas_joker, gerar_combinacoes_joker,
    importar_historico_joker, ESTRATEGIAS_JOKER,
)
from modules.analise_rigor import suavizar_frequencias, teste_ajuste_uniforme
from modules.conferencia import conferir_jogos, ROTULOS_PREMIO
from modules.wheeling import (
    ErroWheel, planear_wheel, planear_wheel_orcamento,
    interpretar_orcamento_cve, formatar_cve_exato,
)
from modules.totoloto import QTD_NUMEROS_ATUAIS
from modules.protocolo_backtesting import (
    ErroProtocolo, PlanoProtocolo, preparar_protocolo, corte_holdout, validar_prazo,
    digest, PASTA_RESULTADOS,
)
from modules.coordenador_backtesting import iniciar as iniciar_protocolo, consultar as consultar_protocolo

app = Flask(__name__)
app.config.from_object(Config)

Path("logs").mkdir(exist_ok=True)
_log_handler = RotatingFileHandler("logs/app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
_log_handler.setLevel(logging.ERROR)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
app.logger.addHandler(_log_handler)
app.logger.setLevel(logging.ERROR)

_BACKTEST_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_BACKTEST_JOBS = {}
_BACKTEST_JOBS_LOCK = threading.Lock()


def _mensagem_erro(exc, contexto="operação"):
    erro_id = uuid.uuid4().hex[:8]
    app.logger.error("Erro interno [%s] durante %s", erro_id, contexto,
                     exc_info=(type(exc), exc, exc.__traceback__))
    orientacao = ""
    if isinstance(exc, ValueError):
        texto = str(exc)
        if "Concurso Joker" in texto:
            orientacao = " Verifique o Concurso Joker indicado."
        elif "inteiro" in texto:
            orientacao = " Verifique o número inteiro indicado."
    return f"Ocorreu um erro interno durante {contexto}.{orientacao} Consulte o registo com o ID {erro_id}."


def _csrf_token():
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


@app.before_request
def _proteger_csrf():
    if request.method != "POST" or app.config.get("TESTING"):
        return None
    esperado = session.get("_csrf_token")
    recebido = request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    origem = request.headers.get("Origin") or request.headers.get("Referer", "")
    origem_valida = origem.startswith(request.host_url.rstrip("/")) if origem else False
    token_valido = esperado and recebido and hmac.compare_digest(str(esperado), str(recebido))
    if not token_valido and not origem_valida:
        abort(400, description="Token CSRF ausente ou inválido.")


@app.context_processor
def inject_csrf():
    return {"csrf_token": _csrf_token}

Path(app.config["UPLOAD_FOLDER"]).mkdir(exist_ok=True)
Path(app.config["EXPORT_PDF_FOLDER"]).mkdir(parents=True, exist_ok=True)
Path(app.config["EXPORT_EXCEL_FOLDER"]).mkdir(parents=True, exist_ok=True)


NAV_ITEMS = [
    {"key": "dashboard", "label": "Painel", "icon": "📊", "url": "/dashboard"},
    {"key": "estatisticas", "label": "Estatísticas", "icon": "🔢", "url": "/estatisticas"},
    {"key": "importar", "label": "Importar Estatísticas", "icon": "⬆️", "url": "/importar-estatistica"},
    {"key": "sorteios", "label": "Registar Sorteio", "icon": "🗓️", "url": "/cadastrar-sorteio"},
    {"key": "gerar", "label": "Gerar Apostas", "icon": "⚙️", "url": "/gerar-jogos"},
    {"key": "wheeling", "label": "Wheeling e cobertura", "icon": "▦", "url": "/wheeling"},
    {"key": "joker", "label": "Joker", "icon": "🎯", "url": "/joker"},
    {"key": "estrategias", "label": "Estratégias", "icon": "🧠", "url": "/estrategias"},
    {"key": "backtesting", "label": "Teste Histórico", "icon": "📈", "url": "/backtesting"},
    {"key": "banca", "label": "Gestão de Banca", "icon": "💼", "url": "/controle-banca"},
    {"key": "relatorios", "label": "Relatórios", "icon": "📄", "url": "/relatorios"},
    {"key": "configuracoes", "label": "Definições", "icon": "🔧", "url": "/configuracoes"},
]



@app.context_processor
def inject_globals():
    return {
        "nav_items": NAV_ITEMS,
        "format_cve": format_cve,
        "total_combinacoes_simples": comb(45, 6),
    }


@app.template_filter("date_br")
def date_br_filter(valor):
    return format_date_br(valor)


@app.template_filter("pct_br")
def pct_br_filter(valor):
    try:
        numero = round(float(valor), 2)
        if numero == 0:
            numero = 0.0
        texto = f"{numero:.2f}".rstrip("0").rstrip(".")
        return texto.replace(".", ",") + "%"
    except Exception:
        return "0%"


def fetch_all(sql, params=None):
    with connection_scope() as con:
        cur = con.cursor(dictionary=True)
        try:
            cur.execute(sql, params or ())
            return cur.fetchall()
        finally:
            cur.close()


def fetch_one(sql, params=None):
    rows = fetch_all(sql, params)
    return rows[0] if rows else None


def get_configuracao():
    return fetch_one("SELECT * FROM configuracoes WHERE id=1") or {
        "preco_aposta_simples": 30,
        "preco_joker": 70,
        "orcamento_semanal": 1000,
        "moeda": "CVE",
    }


def _inteiro_positivo(valor, campo, opcional=False):
    if valor in (None, ""):
        if opcional:
            return None
        raise ValueError(f"Informe {campo}.")
    texto = str(valor).strip()
    if not re.fullmatch(r"\d+", texto):
        raise ValueError(f"{campo} deve ser um nÃºmero inteiro positivo.")
    numero = int(texto)
    if numero <= 0:
        raise ValueError(f"{campo} deve ser um nÃºmero inteiro positivo.")
    return numero


def _valor_financeiro(valor, campo):
    numero = parse_decimal_br(valor)
    if not isfinite(numero) or numero < 0:
        raise ValueError(f"{campo} deve ser um valor CVE finito e nÃ£o negativo.")
    return numero


def _validar_estrategia(valor, permitidas):
    estrategia = str(valor or "").strip()
    if estrategia not in permitidas:
        opcoes = ", ".join(permitidas)
        raise ValueError(f"EstratÃ©gia invÃ¡lida. Escolha uma destas: {opcoes}.")
    return estrategia


def _validar_concurso_joker(valor):
    concurso = str(valor or "").strip()
    if not re.fullmatch(r"(?:\d+|\d{1,2}/20\d{2})", concurso):
        raise ValueError("Concurso Joker invÃ¡lido. Use um nÃºmero ou o formato NN/AAAA.")
    if concurso.isdigit() and int(concurso) <= 0:
        raise ValueError("O concurso Joker deve ser positivo.")
    return concurso


def _limites_semana_iso(data_atual=None):
    """Devolve segunda-feira 00:00 e a segunda-feira seguinte (intervalo semiaberto)."""
    data_atual = data_atual or date.today()
    inicio = data_atual - timedelta(days=data_atual.weekday())
    fim = inicio + timedelta(days=7)
    return datetime.combine(inicio, datetime.min.time()), datetime.combine(fim, datetime.min.time())


def _guardar_geracao_com_orcamento(jogos, concurso, estrategia, orcamento, inicio_semana, fim_semana, consumir_orcamento=True):
    """Guarda uma geração e valida o orçamento acumulado sob lock MySQL."""
    total = sum(float(jogo["custo_final"]) for jogo in jogos)
    chave_lock = "totoloto:orcamento-semanal"
    with transaction_scope() as con:
        cur = con.cursor()
        lock_obtido = False
        try:
            if consumir_orcamento:
                cur.execute("SELECT GET_LOCK(%s, 5)", (chave_lock,))
            lock_obtido = bool((cur.fetchone() or (0,))[0]) if consumir_orcamento else False
            if consumir_orcamento and not lock_obtido:
                raise RuntimeError("Não foi possível reservar o orçamento semanal; tente novamente.")
            if consumir_orcamento and orcamento > 0:
                cur.execute(
                    """SELECT COALESCE(SUM(custo_total), 0)
                       FROM geracoes_semanais
                       WHERE data_geracao >= %s AND data_geracao < %s""",
                    (inicio_semana, fim_semana),
                )
                gasto_atual = float((cur.fetchone() or (0,))[0] or 0)
                if gasto_atual + total > orcamento + 1e-9:
                    disponivel = max(0.0, orcamento - gasto_atual)
                    raise ValueError(
                        f"O orçamento semanal disponível ({format_cve(disponivel)}) "
                        f"não cobre esta geração ({format_cve(total)})."
                    )
            for jogo in jogos:
                cur.execute("""
                    INSERT INTO jogos_gerados
                    (concurso, tipo_aposta, estrategia, numeros, apostas_simples, score, custo_total, incluir_joker, custo_joker, custo_final, observacao)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (
                    concurso, jogo["tipo_aposta"], jogo["estrategia"],
                    ",".join(str(n) for n in jogo["numeros"]), jogo["apostas_simples"],
                    jogo["score"], jogo["custo_total"], jogo["incluir_joker"],
                    jogo["custo_joker"], jogo["custo_final"], "geração estatística semanal"
                ))
            if consumir_orcamento and jogos:
                cur.execute("""
                    INSERT INTO geracoes_semanais (concurso, estrategia, tipo_aposta, quantidade_jogos, custo_total, observacao)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (concurso, estrategia, jogos[0]["tipo_aposta"], len(jogos), total, "geração estatística semanal"))
        finally:
            try:
                if lock_obtido:
                    cur.execute("SELECT RELEASE_LOCK(%s)", (chave_lock,))
            finally:
                cur.close()


@app.route("/")
def home():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
def dashboard():
    try:
        resumo = {
            "sorteios": fetch_one("SELECT COUNT(*) total FROM sorteios")["total"],
            "joker": fetch_one("SELECT COUNT(*) total FROM joker_resultados")["total"],
            "numeros": fetch_one("SELECT COUNT(*) total FROM estatisticas_numeros")["total"],
            "jogos": fetch_one("SELECT COUNT(*) total FROM jogos_gerados")["total"],
            "gasto": fetch_one("SELECT COALESCE(SUM(valor_gasto), 0) total FROM controle_banca")["total"],
        }
        inicio_semana, fim_semana = _limites_semana_iso()
        comprometido = fetch_one(
            "SELECT COALESCE(SUM(custo_total), 0) total FROM geracoes_semanais "
            "WHERE data_geracao >= %s AND data_geracao < %s",
            (inicio_semana, fim_semana),
        ) or {"total": 0}
        comprado = fetch_one(
            "SELECT COALESCE(SUM(custo_final), 0) total FROM jogos_gerados WHERE comprado = TRUE"
        ) or {"total": 0}
        resumo["orcamento_comprometido"] = float(comprometido["total"] or 0)
        resumo["gasto_real_comprado"] = float(comprado["total"] or 0)
        destaques = fetch_all("""
            SELECT numero, numero_saidas, ausencias, indice_quente
            FROM estatisticas_numeros
            ORDER BY indice_quente DESC, numero_saidas DESC, ausencias DESC, numero ASC
            LIMIT 8
        """)
        ultimos_jogos = fetch_all("""
            SELECT * FROM jogos_gerados
            ORDER BY id DESC
            LIMIT 8
        """)
        ultimo_sorteio = fetch_one("SELECT * FROM sorteios ORDER BY concurso DESC LIMIT 1")
        jogos_ultimo_sorteio = fetch_all(
            "SELECT id, concurso, numeros FROM jogos_gerados WHERE concurso = %s ORDER BY id ASC",
            (ultimo_sorteio["concurso"],),
        ) if ultimo_sorteio else []
        conferencia_ultimo = conferir_jogos(
            jogos_ultimo_sorteio,
            [ultimo_sorteio[f"n{i}"] for i in range(1, 7)],
        ) if ultimo_sorteio else None
    except Exception as exc:
        flash(_mensagem_erro(exc, "carregar o painel"), "error")
        resumo = {"sorteios": 0, "joker": 0, "numeros": 0, "jogos": 0, "gasto": 0,
                  "orcamento_comprometido": 0, "gasto_real_comprado": 0}
        destaques = []
        ultimos_jogos = []
        conferencia_ultimo = None
    return render_template("dashboard.html", active="dashboard", resumo=resumo, destaques=destaques,
                           ultimos_jogos=ultimos_jogos, conferencia_ultimo=conferencia_ultimo)


@app.route("/estatisticas")
def estatisticas():
    rows = fetch_all("SELECT * FROM estatisticas_numeros ORDER BY numero ASC")
    contagens = {int(row["numero"]): int(row.get("numero_saidas") or 0) for row in rows}
    suavizadas = suavizar_frequencias(contagens) if contagens and sum(contagens.values()) else {}
    ajuste = None
    if contagens and sum(contagens.values()) % 6 == 0 and sum(contagens.values()) > 0:
        ajuste = teste_ajuste_uniforme(contagens, simulacoes=1000, seed=20260917)
    return render_template("estatisticas.html", active="estatisticas", estatisticas=rows,
                           frequencias_suavizadas=suavizadas, ajuste_uniforme=ajuste)


@app.route("/importar-estatistica", methods=["GET", "POST"])
def importar_estatistica():
    if request.method == "POST":
        arquivo = request.files.get("arquivo")
        if not arquivo or arquivo.filename == "":
            flash("Seleccione um ficheiro.", "error")
            return redirect(url_for("importar_estatistica"))
        nome_seguro = secure_filename(arquivo.filename)
        if Path(nome_seguro).suffix.lower() not in {".csv", ".xlsx", ".pdf"}:
            flash("Formato de estatística inválido. Use CSV, XLSX ou PDF.", "error")
            return redirect(url_for("importar_estatistica"))
        destino = Path(app.config["UPLOAD_FOLDER"]) / nome_seguro
        arquivo.save(destino)
        try:
            with transaction_scope() as con:
                total = importar_arquivo_estatistica(destino, con)
                digest = hashlib.sha256(destino.read_bytes()).hexdigest()
                cur = con.cursor()
                try:
                    cur.execute(
                        """INSERT INTO importacoes_estatistica
                           (nome_ficheiro, sha256, registos_aceites)
                           VALUES (%s, %s, %s)""",
                        (nome_seguro, digest, total),
                    )
                finally:
                    cur.close()
            flash(f"Estatística importada com sucesso: {total} linhas.", "success")
            return redirect(url_for("estatisticas"))
        except Exception as exc:
            flash(_mensagem_erro(exc), "error")
    return render_template("importar_estatistica.html", active="importar")


@app.route("/sorteios")
@app.route("/cadastrar-sorteio", methods=["GET", "POST"])
def cadastrar_sorteio():
    if request.method == "POST":
        try:
            concurso = _inteiro_positivo(request.form.get("concurso"), "O concurso")
            data_sorteio = parse_date_br(request.form["data_sorteio"])
            numeros = [int(request.form[f"n{i}"]) for i in range(1, 7)]
            if len(set(numeros)) != 6 or any(n < 1 or n > 45 for n in numeros):
                raise ValueError("Informe exactamente 6 números únicos entre 1 e 45.")
            numeros = sorted(numeros)
            with transaction_scope() as con:
                cur = con.cursor()
                try:
                    cur.execute("""
                        INSERT INTO sorteios (concurso, data_sorteio, n1, n2, n3, n4, n5, n6)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (concurso, data_sorteio, *numeros))
                finally:
                    cur.close()
                recalcular_estatisticas(con)
            flash("Sorteio registado e estatística actualizada automaticamente.", "success")
            try:
                jogos_do_concurso = fetch_all(
                    "SELECT id, concurso, numeros, tipo_aposta, estrategia, apostas_simples, custo_final, observacao "
                    "FROM jogos_gerados WHERE concurso = %s ORDER BY id ASC",
                    (concurso,),
                )
                conferencia = conferir_jogos(jogos_do_concurso, numeros)
                total_premios = sum(conferencia["premios_por_categoria"].values())
                flash(
                    f"Conferência: {conferencia['jogos_conferidos']} jogo(s), {total_premios} prémio(s).",
                    "success",
                )
                for erro in conferencia["erros"]:
                    flash(f"Não foi possível conferir o jogo {erro['id']}: {erro['mensagem']}", "warning")
            except Exception as exc:
                app.logger.warning("Conferência do concurso %s indisponível: %s", concurso, exc, exc_info=True)
                flash("O sorteio foi guardado, mas não foi possível concluir a conferência.", "warning")
            return redirect(url_for("cadastrar_sorteio"))
        except Exception as exc:
            flash(_mensagem_erro(exc), "error")
    sorteios = fetch_all("SELECT * FROM sorteios ORDER BY concurso DESC LIMIT 20")
    jogos = fetch_all(
        "SELECT id, concurso, numeros FROM jogos_gerados WHERE concurso IS NOT NULL ORDER BY id ASC"
    )
    por_concurso = {}
    for jogo in jogos:
        por_concurso.setdefault(jogo.get("concurso"), []).append(jogo)
    conferencias = {
        sorteio.get("concurso"): conferir_jogos(
            por_concurso.get(sorteio.get("concurso"), []),
            [sorteio[f"n{i}"] for i in range(1, 7)],
        )
        for sorteio in sorteios
    }
    return render_template("cadastrar_sorteio.html", active="sorteios", sorteios=sorteios,
                           conferencias=conferencias, rotulos_premio=ROTULOS_PREMIO)


@app.route("/gerar-jogos", methods=["GET", "POST"])
def gerar_jogos():
    jogos = []
    estrategias = fetch_all("SELECT * FROM estrategias WHERE ativa = TRUE ORDER BY id ASC")
    config = get_configuracao()
    aviso_orcamento = None
    if request.method == "POST":
        try:
            qtd_numeros = int(request.form.get("qtd_numeros", 6))
            quantidade_jogos = int(request.form.get("quantidade_jogos", 5))
            if qtd_numeros not in QTD_NUMEROS_ATUAIS:
                raise ValueError("A modalidade atual aceita 6, 7, 8, 9 ou 10 números.")
            if not 1 <= quantidade_jogos <= 50:
                raise ValueError("A quantidade de bilhetes deve estar entre 1 e 50.")
            estrategia = _validar_estrategia(request.form.get("estrategia", "Equilibrada"), ESTRATEGIAS_VALIDAS)
            incluir_joker = request.form.get("incluir_joker") == "1"
            consumir_orcamento = request.form.get("consumir_orcamento") == "1"
            concurso = _inteiro_positivo(request.form.get("concurso"), "O concurso", opcional=True)

            preco_aposta = float(config.get("preco_aposta_simples") or 30)
            preco_joker = float(config.get("preco_joker") or 70)
            orcamento = float(config.get("orcamento_semanal") or 0)
            custo_unitario = calcular_custo(qtd_numeros, incluir_joker, preco_aposta, preco_joker)["custo_final"]
            inicio_semana, fim_semana = _limites_semana_iso()
            gasto_semana = 0.0
            if consumir_orcamento and orcamento > 0:
                gasto_row = fetch_one(
                    """SELECT COALESCE(SUM(custo_total), 0) AS gasto
                       FROM geracoes_semanais
                       WHERE data_geracao >= %s AND data_geracao < %s""",
                    (inicio_semana, fim_semana),
                )
                gasto_semana = float((gasto_row or {}).get("gasto") or 0)
            disponivel = max(0.0, orcamento - gasto_semana) if orcamento > 0 else 0.0
            if consumir_orcamento and orcamento > 0 and custo_unitario * quantidade_jogos > disponivel:
                maximo = int(floor(disponivel / custo_unitario))
                if maximo <= 0:
                    raise ValueError(
                        f"O orçamento semanal disponível é {format_cve(disponivel)}; "
                        f"o bilhete custa {format_cve(custo_unitario)}. "
                        "Aumente o orçamento em Definições ou aguarde a próxima semana ISO."
                    )
                    raise ValueError(f"O custo por bilhete ({format_cve(custo_unitario)}) ultrapassa o orçamento semanal configurado ({format_cve(orcamento)}).")
                aviso_orcamento = f"Quantidade ajustada de {quantidade_jogos} para {maximo} bilhete(s), respeitando o orçamento semanal."
                quantidade_jogos = maximo

            estat = fetch_all("SELECT * FROM estatisticas_numeros ORDER BY numero ASC")
            sorteados = fetch_all("SELECT n1,n2,n3,n4,n5,n6 FROM sorteios")
            jogos_ja_sorteados = {tuple(sorted([r[f"n{i}"] for i in range(1, 7)])) for r in sorteados}
            recentes_rows = fetch_all("SELECT n1,n2,n3,n4,n5,n6 FROM sorteios ORDER BY concurso DESC LIMIT 3")
            recentes = set()
            for r in recentes_rows:
                recentes.update([r[f"n{i}"] for i in range(1, 7)])

            jogos = gerar_jogos_estatisticos(
                estat,
                quantidade_jogos,
                qtd_numeros,
                estrategia,
                incluir_joker,
                jogos_ja_sorteados,
                recentes,
                preco_aposta=preco_aposta,
                preco_joker=preco_joker,
            )
            _guardar_geracao_com_orcamento(
                jogos, concurso, estrategia, orcamento, inicio_semana, fim_semana,
                consumir_orcamento=consumir_orcamento,
            )
            if aviso_orcamento:
                flash(aviso_orcamento, "success")
            flash(f"{len(jogos)} aposta(s) gerada(s) e guardada(s).", "success")
        except Exception as exc:
            flash(_mensagem_erro(exc), "error")
    return render_template("gerar_jogos.html", active="gerar", estrategias=estrategias, jogos=jogos, config=config)


@app.route("/wheeling", methods=["GET", "POST"])
def wheeling():
    selecionado = {"pool": "", "quantidade_linhas": "10", "nivel": "3",
                  "modo_limite": "linhas", "orcamento": ""}
    resultado, erro, status = None, None, 200
    if request.method == "POST":
        selecionado = {chave: request.form.get(chave, padrao) for chave, padrao in selecionado.items()}
        try:
            texto = selecionado["pool"].strip()
            if len(texto) > 200 or not re.fullmatch(r"[0-9,;\s]+", texto):
                raise ErroWheel("Indique os números separados por espaços, vírgulas ou ponto e vírgula.")
            partes = re.split(r"[,;\s]+", texto.strip(" ,;\t\r\n"))
            if not 6 <= len(partes) <= 12 or any(not p for p in partes):
                raise ErroWheel("Escolha entre 6 e 12 números distintos de 1 a 45.")
            modo = selecionado["modo_limite"]
            if modo not in ("linhas", "orcamento"):
                raise ErroWheel("Escolha o limite por linhas ou por orçamento.")
            campos_inteiros = ("quantidade_linhas", "nivel") if modo == "linhas" else ("nivel",)
            for chave in campos_inteiros:
                if not re.fullmatch(r"[0-9]{1,3}", selecionado[chave]):
                    raise ErroWheel("O máximo de linhas e o nível devem ser números inteiros.")
            quantidade = int(selecionado["quantidade_linhas"]) if modo == "linhas" else 1
            nivel = int(selecionado["nivel"])
            if not 1 <= quantidade <= 420 or nivel not in (2, 3):
                raise ErroWheel("Use entre 1 e 420 linhas e cobertura de pares (2) ou trincas (3).")
            pool = [int(p) for p in partes]
            if len(set(pool)) != len(pool) or any(n < 1 or n > 45 for n in pool):
                raise ErroWheel("Os números devem ser distintos e estar entre 1 e 45.")
            montante = interpretar_orcamento_cve(selecionado["orcamento"]) if modo == "orcamento" else None
            config = get_configuracao()
            if modo == "orcamento":
                resultado = planear_wheel_orcamento(pool, montante, t=nivel,
                                                   preco_aposta=config.get("preco_aposta_simples", 30))
            else:
                resultado = planear_wheel(pool, quantidade, t=nivel,
                                         preco_aposta=config.get("preco_aposta_simples", 30))
        except ErroWheel as exc:
            # Mensagens desta classe são validações públicas e controladas.
            erro, status = str(exc), 400
        except Exception as exc:
            erro, status = _mensagem_erro(exc, "planear a cobertura"), 500
    return render_template("wheeling.html", active="wheeling", selecionado=selecionado,
                           resultado=resultado, erro=erro, formatar_cve_exato=formatar_cve_exato), status


@app.route("/joker", methods=["GET", "POST"])
def joker():
    combinacoes = []
    selecionado = {"quantidade": 5, "estrategia": "Equilibrada"}
    try:
        if request.method == "POST":
            acao = request.form.get("acao")
            if acao == "registar":
                concurso = _validar_concurso_joker(request.form.get("concurso", ""))
                data_sorteio = parse_date_br(request.form.get("data_sorteio"))
                numero_joker = normalizar_numero_joker(request.form.get("numero_joker"))
                premio = request.form.get("premio") or "1.º Prémio"
                with transaction_scope() as con:
                    cur = con.cursor()
                    try:
                        cur.execute("""
                            INSERT INTO joker_resultados (concurso, data_sorteio, numero_joker, premio)
                            VALUES (%s,%s,%s,%s)
                            ON DUPLICATE KEY UPDATE
                                data_sorteio=VALUES(data_sorteio),
                                numero_joker=VALUES(numero_joker),
                                premio=VALUES(premio)
                        """, (concurso, data_sorteio, numero_joker, premio))
                    finally:
                        cur.close()
                    recalcular_estatisticas_joker(con)
                flash("Resultado Joker registado e estatística actualizada automaticamente.", "success")
                return redirect(url_for("joker"))
            elif acao == "importar_ficheiro":
                arquivo = request.files.get("arquivo_joker")
                if not arquivo or arquivo.filename == "":
                    raise ValueError("Seleccione um ficheiro Joker para importar.")
                nome_seguro = secure_filename(arquivo.filename)
                if Path(nome_seguro).suffix.lower() not in {".csv", ".xlsx", ".txt", ".pdf"}:
                    raise ValueError("Formato Joker inválido. Use CSV, XLSX, TXT ou PDF.")
                destino = Path(app.config["UPLOAD_FOLDER"]) / nome_seguro
                arquivo.save(destino)
                with transaction_scope() as con:
                    total = importar_historico_joker(con, caminho=destino)
                flash(f"Histórico Joker importado com sucesso: {total} concurso(s). Estatística actualizada.", "success")
                return redirect(url_for("joker"))
            elif acao == "importar_texto":
                texto = request.form.get("texto_joker", "")
                if not texto.strip():
                    raise ValueError("Cole o texto do histórico Joker antes de importar.")
                with transaction_scope() as con:
                    total = importar_historico_joker(con, texto=texto)
                flash(f"Histórico Joker importado com sucesso: {total} concurso(s). Estatística actualizada.", "success")
                return redirect(url_for("joker"))
            elif acao == "gerar":
                selecionado["quantidade"] = _inteiro_positivo(request.form.get("quantidade", 5), "A quantidade")
                if selecionado["quantidade"] > 30:
                    raise ValueError("A quantidade de combinaÃ§Ãµes Joker deve estar entre 1 e 30.")
                selecionado["estrategia"] = _validar_estrategia(request.form.get("estrategia", "Equilibrada"), ESTRATEGIAS_JOKER)
                estat = fetch_all("SELECT * FROM joker_estatisticas ORDER BY posicao ASC, digito ASC")
                combinacoes = gerar_combinacoes_joker(estat, selecionado["quantidade"], selecionado["estrategia"])
    except Exception as exc:
        flash(_mensagem_erro(exc), "error")

    resultados = fetch_all("SELECT * FROM joker_resultados ORDER BY data_sorteio DESC, id DESC LIMIT 30")
    estatisticas_joker = fetch_all("SELECT * FROM joker_estatisticas ORDER BY posicao ASC, digito ASC")
    total = fetch_one("SELECT COUNT(*) total FROM joker_resultados")["total"]
    ultimo = fetch_one("SELECT * FROM joker_resultados ORDER BY data_sorteio DESC, id DESC LIMIT 1")
    mais_quente = fetch_one("SELECT * FROM joker_estatisticas ORDER BY indice_quente DESC, total_saidas DESC LIMIT 1")
    mais_atrasado = fetch_one("SELECT * FROM joker_estatisticas ORDER BY indice_atraso DESC, ausencias DESC LIMIT 1")
    resumo = {"total": total, "ultimo": ultimo, "mais_quente": mais_quente, "mais_atrasado": mais_atrasado}
    return render_template(
        "joker.html", active="joker", resultados=resultados, estatisticas_joker=estatisticas_joker,
        resumo=resumo, combinacoes=combinacoes, selecionado=selecionado
    )


@app.route("/joker/modelo-importacao")
def modelo_importacao_joker():
    conteudo = "Concurso;Data;Joker;Categoria\n49/2025;06/12/2025;989682;1.º Prémio\n50/2025;13/12/2025;123456;1.º Prémio\n"
    return send_file(
        BytesIO(conteudo.encode("utf-8-sig")),
        mimetype="text/csv; charset=utf-8",
        as_attachment=True,
        download_name="modelo_importacao_joker.csv",
    )


@app.route("/estrategias")
def estrategias():
    rows = fetch_all("SELECT * FROM estrategias ORDER BY id ASC")
    return render_template("estrategias.html", active="estrategias", estrategias=rows)


@app.route("/backtesting", methods=["GET", "POST"])
def backtesting():
    estrategias = fetch_all("SELECT * FROM estrategias WHERE ativa = TRUE ORDER BY id ASC")
    config = get_configuracao()
    resumo = resumo_backtesting_demo()
    selecionado = {"estrategia": "Equilibrada", "quantidade_jogos": 5, "qtd_numeros": 6, "incluir_joker": False, "limite_concursos": 50}
    try:
        sorteios = fetch_all("SELECT * FROM sorteios ORDER BY data_sorteio ASC, id ASC")
        # PADRÃO HISTÓRICO: exploração apenas nos primeiros 80%; nunca abrir o holdout no GET.
        sorteios = sorteios[:corte_holdout(len(sorteios))]
        if request.method == "POST":
            selecionado["estrategia"] = _validar_estrategia(request.form.get("estrategia", "Equilibrada"), ESTRATEGIAS_VALIDAS)
            selecionado["quantidade_jogos"] = int(request.form.get("quantidade_jogos", 5))
            selecionado["qtd_numeros"] = int(request.form.get("qtd_numeros", 6))
            selecionado["incluir_joker"] = request.form.get("incluir_joker") == "1"
            selecionado["limite_concursos"] = _inteiro_positivo(request.form.get("limite_concursos", 50), "O limite de concursos")
            if selecionado["qtd_numeros"] not in QTD_NUMEROS_ATUAIS:
                raise ValueError("A modalidade atual aceita 6, 7, 8, 9 ou 10 números.")
            maximo = max_bilhetes_backtesting(selecionado["qtd_numeros"])
            if not 1 <= selecionado["quantidade_jogos"] <= maximo:
                raise ValueError(
                    f"Para {selecionado['qtd_numeros']} números, use entre 1 e {maximo} "
                    "bilhete(s) por concurso no backtesting."
                )
            if request.form.get("modo") == "assíncrono":
                job_id = uuid.uuid4().hex
                parametros = dict(selecionado)
                with _BACKTEST_JOBS_LOCK:
                    _BACKTEST_JOBS[job_id] = {"estado": "queued", "resultado": None, "erro": None}

                def executar_job():
                    with _BACKTEST_JOBS_LOCK:
                        _BACKTEST_JOBS[job_id]["estado"] = "running"
                    try:
                        resultado = executar_backtesting(
                            sorteios,
                            estrategia=parametros["estrategia"],
                            quantidade_jogos=parametros["quantidade_jogos"],
                            qtd_numeros=parametros["qtd_numeros"],
                            incluir_joker=parametros["incluir_joker"],
                            preco_aposta=float(config.get("preco_aposta_simples") or 30),
                            preco_joker=float(config.get("preco_joker") or 70),
                            limite_concursos=parametros["limite_concursos"],
                        )
                        with _BACKTEST_JOBS_LOCK:
                            _BACKTEST_JOBS[job_id].update(estado="completed", resultado=resultado)
                    except Exception as exc:
                        with _BACKTEST_JOBS_LOCK:
                            _BACKTEST_JOBS[job_id].update(estado="failed", erro=str(exc))

                _BACKTEST_EXECUTOR.submit(executar_job)
                return {"job_id": job_id, "estado": "queued", "poll": url_for("estado_backtesting", job_id=job_id)}, 202
        if request.method == "POST":
            resumo = executar_backtesting(
            sorteios,
            estrategia=selecionado["estrategia"],
            quantidade_jogos=selecionado["quantidade_jogos"],
            qtd_numeros=selecionado["qtd_numeros"],
            incluir_joker=selecionado["incluir_joker"],
            limite_concursos=selecionado["limite_concursos"],
            preco_aposta=float(config.get("preco_aposta_simples") or 30),
            preco_joker=float(config.get("preco_joker") or 70),
            )
    except Exception as exc:
        flash(_mensagem_erro(exc), "error")
    return render_template("backtesting.html", active="backtesting", resumo=resumo, estrategias=estrategias, selecionado=selecionado)


@app.route("/backtesting/jobs/<job_id>")
def estado_backtesting(job_id):
    with _BACKTEST_JOBS_LOCK:
        job = _BACKTEST_JOBS.get(job_id)
        if not job:
            return {"estado": "nao_encontrado"}, 404
        return dict(job)


@app.route("/backtesting/protocolo/preparar", methods=["POST"])
def preparar_protocolo_http():
    """Pré-validação sem avaliar concursos; token assinado congela dados/parâmetros."""
    from itsdangerous import URLSafeTimedSerializer
    try:
        dados = request.get_json(silent=True) or request.form
        config = get_configuracao()
        plano = preparar_protocolo(
            fetch_all("SELECT * FROM sorteios ORDER BY data_sorteio ASC, id ASC"),
            estrategia=dados.get("estrategia", "Equilibrada"),
            quantidade_jogos=dados.get("quantidade_jogos", 5), qtd_numeros=dados.get("qtd_numeros", 6),
            incluir_joker=dados.get("incluir_joker") in (True, "1"),
            preco_aposta=config.get("preco_aposta_simples", 30), preco_joker=config.get("preco_joker", 70),
            limite_concursos=dados.get("limite_concursos", 50), seed=dados.get("seed", 2026),
            n_sinteticos=dados.get("n_sinteticos", 199), workers=dados.get("workers", 4),
            ambito=dados.get("ambito", "holdout"), timeout_global=dados.get("timeout_global"),
            timeout_simulacao=dados.get("timeout_simulacao", 300),
            holdout_inedito=dados.get("holdout_inedito") in (True, "1"))
        import json
        estimativa = json.loads(plano.estimativa_json)
        try:
            validar_prazo(plano)
        except ErroProtocolo as exc:
            return {"estado": "bloqueado", "mensagem": str(exc), "estimativa": estimativa}, 422
        # Não confiar em parâmetros reenviados depois da confirmação: só este token é aceite.
        token = URLSafeTimedSerializer(app.secret_key, salt="F04").dumps(plano.registo())
        return {"token": token, "estimativa": estimativa, "corte": plano.corte,
                "alvos": plano.alvos, "ambito": plano.ambito, "timeout_global": plano.timeout_global,
                "mensagem": "Configuração preparada. Confirme a estimativa antes de iniciar; o holdout só pode ser avaliado uma vez."}
    except ErroProtocolo as exc:
        return {"estado": "recusado", "mensagem": str(exc)}, 422
    except Exception as exc:
        return {"estado": "erro", "mensagem": _mensagem_erro(exc, "preparar o protocolo")}, 500


@app.route("/backtesting/protocolo/iniciar", methods=["POST"])
def iniciar_protocolo_http():
    from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
    try:
        dados = request.get_json(silent=True) or request.form
        if dados.get("confirmar") not in (True, "1"):
            raise ErroProtocolo("Confirme a estimativa e a configuração antes de iniciar.")
        try:
            registo = URLSafeTimedSerializer(app.secret_key, salt="F04").loads(dados.get("token", ""), max_age=1800)
        except (BadSignature, SignatureExpired):
            raise ErroProtocolo("A preparação expirou ou é inválida; prepare novamente o protocolo.") from None
        plano = PlanoProtocolo(**registo)
        job_id = iniciar_protocolo(plano)
        return {"id": job_id, "estado": "pendente", "poll": url_for("estado_protocolo_http", job_id=job_id)}, 202
    except ErroProtocolo as exc:
        return {"estado": "recusado", "mensagem": str(exc)}, 422
    except Exception as exc:
        return {"estado": "erro", "mensagem": _mensagem_erro(exc, "iniciar o protocolo")}, 500


@app.route("/backtesting/protocolo/<job_id>")
def estado_protocolo_http(job_id):
    try:
        return consultar_protocolo(job_id)
    except (FileNotFoundError, ErroProtocolo):
        return {"estado": "nao_encontrado"}, 404
    except Exception as exc:
        # Falha de MySQL não significa lock livre nem execução completa.
        return {"estado": "indeterminado", "mensagem": _mensagem_erro(exc, "consultar o protocolo")}, 503


@app.route("/jogos/<int:jogo_id>/comprado", methods=["POST"])
def marcar_jogo_comprado(jogo_id):
    comprado = request.form.get("comprado") == "1"
    try:
        with transaction_scope() as con:
            cur = con.cursor(dictionary=True)
            try:
                cur.execute("SELECT id FROM jogos_gerados WHERE id = %s FOR UPDATE", (jogo_id,))
                if not cur.fetchone():
                    raise LookupError("jogo inexistente")
                cur.execute("UPDATE jogos_gerados SET comprado = %s WHERE id = %s", (comprado, jogo_id))
            finally:
                cur.close()
        estado = "comprado" if comprado else "apenas gerado"
        flash(f"Jogo {jogo_id} marcado como {estado}.", "success")
    except LookupError:
        return "Jogo não encontrado.", 404
    except Exception as exc:
        flash(_mensagem_erro(exc, "actualizar o estado do jogo"), "error")
    return redirect(url_for("dashboard"))


@app.route("/controle-banca", methods=["GET", "POST"])
def controle_banca():
    if request.method == "POST":
        try:
            concurso = _inteiro_positivo(request.form.get("concurso"), "O concurso", opcional=True)
            valor_gasto = _valor_financeiro(request.form.get("valor_gasto") or 0, "O valor gasto")
            valor_retorno = _valor_financeiro(request.form.get("valor_retorno") or 0, "O valor de retorno")
            lucro_prejuizo = valor_retorno - valor_gasto
            observacao = request.form.get("observacao") or None
            with transaction_scope() as con:
                cur = con.cursor()
                try:
                    cur.execute("""
                        INSERT INTO controle_banca (concurso, valor_gasto, valor_retorno, lucro_prejuizo, observacao)
                        VALUES (%s,%s,%s,%s,%s)
                    """, (concurso, valor_gasto, valor_retorno, lucro_prejuizo, observacao))
                finally:
                    cur.close()
            flash("Movimento guardado.", "success")
            return redirect(url_for("controle_banca"))
        except Exception as exc:
            flash(_mensagem_erro(exc), "error")
    lancamentos = fetch_all("SELECT * FROM controle_banca ORDER BY id DESC LIMIT 30")
    totais = fetch_one("SELECT COALESCE(SUM(valor_gasto),0) gasto, COALESCE(SUM(valor_retorno),0) retorno, COALESCE(SUM(lucro_prejuizo),0) saldo FROM controle_banca")
    inicio_semana, fim_semana = _limites_semana_iso()
    comprometido = fetch_one(
        "SELECT COALESCE(SUM(custo_total), 0) total FROM geracoes_semanais "
        "WHERE data_geracao >= %s AND data_geracao < %s",
        (inicio_semana, fim_semana),
    ) or {"total": 0}
    gasto_real = fetch_one(
        "SELECT COALESCE(SUM(custo_final), 0) total FROM jogos_gerados WHERE comprado = TRUE"
    ) or {"total": 0}
    gasto = float(gasto_real.get("total", 0) or 0)
    retorno = float(totais["retorno"] or 0)
    saldo = retorno - gasto
    roi = round((saldo / gasto) * 100, 2) if gasto else 0
    resumo = {"orcamento_comprometido": float(comprometido.get("total", 0) or 0),
              "gasto_real_comprado": gasto, "retorno": retorno, "saldo": saldo, "roi": roi}
    return render_template("controle_banca.html", active="banca", lancamentos=lancamentos, resumo=resumo)


@app.route("/relatorios")
def relatorios():
    return render_template("relatorios.html", active="relatorios")


@app.route("/relatorios/excel")
def exportar_excel():
    jogos = fetch_all("SELECT * FROM jogos_gerados ORDER BY id DESC")
    caminho = exportar_excel_jogos(jogos, app.config["EXPORT_EXCEL_FOLDER"])
    return send_file(caminho, as_attachment=True)


@app.route("/relatorios/pdf")
def exportar_pdf():
    jogos = fetch_all("SELECT * FROM jogos_gerados ORDER BY id DESC")
    caminho = exportar_pdf_jogos(jogos, app.config["EXPORT_PDF_FOLDER"])
    return send_file(caminho, as_attachment=True)


@app.route("/configuracoes", methods=["GET", "POST"])
def configuracoes():
    if request.method == "POST":
        try:
            with transaction_scope() as con:
                cur = con.cursor()
                try:
                    cur.execute("""
                UPDATE configuracoes
                SET preco_aposta_simples=%s, preco_joker=%s, orcamento_semanal=%s, moeda='CVE'
                WHERE id=1
                    """, (
                _valor_financeiro(request.form.get("preco_aposta_simples") or 30, "O preÃ§o da aposta simples"),
                _valor_financeiro(request.form.get("preco_joker") or 70, "O preÃ§o do Joker"),
                _valor_financeiro(request.form.get("orcamento_semanal") or 1000, "O orÃ§amento semanal"),
                    ))
                finally:
                    cur.close()
            flash("Definições guardadas.", "success")
            return redirect(url_for("configuracoes"))
        except Exception as exc:
            flash(_mensagem_erro(exc), "error")
    config = fetch_one("SELECT * FROM configuracoes WHERE id=1")
    return render_template("configuracoes.html", active="configuracoes", config=config)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=app.config["DEBUG"])
