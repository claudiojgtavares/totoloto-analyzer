"""Coordenador F-04 independente do Flask/reloader. Autoridade única: GET_LOCK.

FATO MATEMÁTICO: protocolo nulo. PADRÃO HISTÓRICO: desempenho, nunca previsão.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
import json
import logging
import multiprocessing
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import time
import uuid

from database.protocolo_lock import LockProtocolo
from modules.backtesting import comparar_historicos_nulos
from modules.processos_backtesting import GrupoProcessos, associar_worker
from modules.protocolo_backtesting import (
    ErroProtocolo, PASTA_RESULTADOS, RAIZ, PlanoProtocolo, digest, executar_avaliacao,
    hash_codigo, novo_registo, resultado_completo, validar_prazo,
)

ATIVOS = {"pendente", "em_execucao"}


def agora():
    return datetime.now(timezone.utc).isoformat()


def caminho_registo(job_id, pasta=PASTA_RESULTADOS):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ErroProtocolo("Identificador de protocolo inválido.")
    return Path(pasta) / f"{job_id}.json"


def guardar(registo, pasta=PASTA_RESULTADOS):
    destino = caminho_registo(registo["id"], pasta)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(f".{uuid.uuid4().hex}.tmp")
    try:
        with temporario.open("x", encoding="utf-8") as f:
            json.dump(registo, f, ensure_ascii=False, sort_keys=True, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)


def ler(job_id, pasta=PASTA_RESULTADOS):
    return json.loads(caminho_registo(job_id, pasta).read_text(encoding="utf-8"))


def interromper(registo, motivo, decorrido=None):
    registo.update(estado="incompleto", motivo=motivo, p_valor_empirico=None, intervalo_nulo=None,
                   terminado_em=agora())
    if decorrido is not None:
        registo["tempo_decorrido"] = round(decorrido, 3)
    return registo


def reconciliar(lock, pasta=PASTA_RESULTADOS, ignorar=None):
    """Só quem ADQUIRIU o lock pode reconciliar. Uma flag/ficheiro nunca dá posse."""
    lock.verificar()
    for caminho in Path(pasta).glob("*.json"):
        reg = json.loads(caminho.read_text(encoding="utf-8"))
        # Pendente ainda não tem proprietário: só uma execução iniciada pode ficar órfã.
        if reg["id"] == ignorar or reg["estado"] != "em_execucao":
            continue
        interromper(reg, "interrompido_sem_proprietario_ativo")
        if reg.get("inicio_epoch"):
            reg["tempo_decorrido"] = round(max(reg.get("tempo_decorrido", 0), time.time() - reg["inicio_epoch"]), 3)
        guardar(reg, pasta)


def chaves_alvos(plano):
    return {digest([s["concurso"], s["data_sorteio"]]) for s in plano.historico[plano.inicio_alvos:]}


def verificar_holdout_inedito(plano, job_id, pasta):
    if plano.ambito != "holdout":
        return
    alvos = chaves_alvos(plano)
    for ficheiro in Path(pasta).glob("*.json"):
        anterior = json.loads(ficheiro.read_text(encoding="utf-8"))
        if anterior["id"] != job_id and anterior.get("avaliacao_iniciada"):
            outro = PlanoProtocolo(**anterior["plano"])
            if alvos & chaves_alvos(outro):
                raise ErroProtocolo(f"Holdout já usado ou exposto no protocolo {anterior['id']}. Consulte esse resultado; não é permitida nova avaliação confirmatória sobre esses concursos.")


def iniciar(plano, pasta=PASTA_RESULTADOS):
    validar_prazo(plano)  # antes de criar processo ou consumir o holdout
    if sys.version_info < (3, 14):
        raise ErroProtocolo("O controlo sintético requer Python 3.14 ou superior para terminar o pool com segurança.")
    reg = novo_registo(plano, uuid.uuid4().hex)
    reg.update(criado_em=agora(), criado_epoch=time.time())
    guardar(reg, pasta)
    flags = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
    env = dict(os.environ)
    env.pop("WERKZEUG_RUN_MAIN", None)
    try:
        subprocess.Popen([sys.executable, "-m", "modules.coordenador_backtesting", "--job", reg["id"],
                          "--pasta", str(Path(pasta).resolve())], cwd=RAIZ, env=env,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, creationflags=flags, start_new_session=os.name != "nt")
    except Exception:
        guardar(interromper(reg, "falha_no_arranque"), pasta)
        raise
    return reg["id"]


def estado_publico(reg):
    campos = ("id", "estado", "motivo", "tempo_decorrido", "simulacoes_concluidas", "n_sinteticos",
              "seed", "ambito", "corte", "inicio_alvos", "alvos", "estimativa", "timeout_global",
              "rotulo", "rotulo_desempenho", "aviso", "progresso", "erro_id", "mensagem",
              "metrica", "confirmacao", "configuracao_usada")
    publico = {k: reg[k] for k in campos if k in reg}
    publico.update(p_valor_empirico=None, intervalo_nulo=None, metrica_observada=None)
    if reg["estado"] == "completo":
        publico.update({k: reg[k] for k in ("p_valor_empirico", "intervalo_nulo", "metrica_observada", "comparacao")})
    return publico


def consultar(job_id, pasta=PASTA_RESULTADOS):
    reg = ler(job_id, pasta)
    if reg["estado"] in ATIVOS:
        with LockProtocolo() as lock:
            if lock.obtido:
                reconciliar(lock, pasta)
        reg = ler(job_id, pasta)
    return estado_publico(reg)


def _initializer(nome_grupo, parent_pid, fila, cancelar):
    associar_worker(nome_grupo, parent_pid)
    global _FILA, _CANCELAR
    _FILA, _CANCELAR = fila, cancelar


def _worker(plano, indice):
    _FILA.put(("inicio", indice, time.monotonic()))
    def progresso(n, total):
        _FILA.put(("progresso", indice, n, total))
    return executar_avaliacao(plano, None if indice == -1 else indice,
                             progresso=progresso, cancelar=_CANCELAR.is_set)


def executar_pool(plano, reg, lock, pasta, clock=time.monotonic, pool_factory=ProcessPoolExecutor):
    inicio = clock()
    contexto = multiprocessing.get_context("spawn")
    fila, cancelar = contexto.Queue(), contexto.Event()
    grupo = GrupoProcessos()
    pool = None
    futuros, inicios = {}, {}
    proximo, total = -1, plano.n_sinteticos
    motivo = None
    try:
        pool = pool_factory(max_workers=plano.workers, mp_context=contexto,
                            initializer=_initializer, initargs=(grupo.nome, os.getpid(), fila, cancelar))
        while proximo < total or futuros:
            decorrido = clock() - inicio
            reg["tempo_decorrido"] = round(decorrido, 3)
            if decorrido >= plano.timeout_global:
                motivo = "timeout_global"
                break
            try:
                lock.verificar()
            except Exception:
                motivo = "perda_do_lock_mysql"
                raise
            while True:
                try:
                    evento = fila.get_nowait()
                except queue.Empty:
                    break
                if evento[0] == "inicio":
                    inicios[evento[1]] = evento[2]
                else:
                    reg.setdefault("progresso", {})[str(evento[1])] = {"concursos": evento[2], "total": evento[3]}
            if any(clock() - t >= plano.timeout_simulacao for i, t in inicios.items() if i in futuros.values()):
                motivo = "timeout_avaliacao"
                break
            while proximo < total and len(futuros) < plano.workers:
                futuros[pool.submit(_worker, plano, proximo)] = proximo
                proximo += 1
            concluidos, _ = wait(futuros, timeout=min(1, max(0, plano.timeout_global - decorrido)),
                                 return_when=FIRST_COMPLETED)
            for futuro in concluidos:
                indice = futuros.pop(futuro)
                resultado = futuro.result()
                if not resultado_completo(resultado, plano):
                    reg.setdefault("avaliacoes_incompletas", {})[str(indice)] = resultado
                    motivo = "avaliacao_incompleta"
                    break
                if indice == -1:
                    reg["resultado_real"] = resultado
                else:
                    diferencas = resultado["diferencas_emparelhadas"]
                    reg["nulos"][str(indice)] = {"media": sum(diferencas) / len(diferencas),
                                                "diferencas_emparelhadas": diferencas,
                                                "concursos_testados": resultado["concursos_testados"],
                                                "baseline_repeticoes": resultado["baseline_repeticoes"]}
                    reg["simulacoes_concluidas"] = len(reg["nulos"])
            guardar(reg, pasta)
            if motivo:
                break
        # Verificar o prazo e a posse também após o último futuro: nunca publicar fora deles.
        if clock() - inicio >= plano.timeout_global:
            motivo = "timeout_global"
        lock.verificar()
        if motivo:
            interromper(reg, motivo, clock() - inicio)
        elif reg["resultado_real"] is not None and len(reg["nulos"]) == plano.n_sinteticos:
            comparacao = comparar_historicos_nulos(
                reg["resultado_real"]["diferencas_emparelhadas"],
                [reg["nulos"][str(i)]["media"] for i in range(plano.n_sinteticos)])
            reg.update(estado="completo", comparacao=comparacao,
                       metrica_observada=comparacao["media_observada"],
                       p_valor_empirico=comparacao["p_valor_empirico"],
                       intervalo_nulo=comparacao["intervalo_nulo"], terminado_em=agora(),
                       tempo_decorrido=round(clock() - inicio, 3))
        else:
            interromper(reg, "avaliacoes_em_falta", clock() - inicio)
    except BaseException:
        interromper(reg, motivo or "erro_na_avaliacao", clock() - inicio)
        raise
    finally:
        # Persistir antes do encerramento de até 30 s; não esconder timeout ao utilizador.
        try:
            guardar(reg, pasta)
        finally:
            cancelar.set()
            try:
                if pool is not None:
                    if reg["estado"] != "completo":
                        for futuro in futuros:
                            futuro.cancel()
                        wait(futuros, timeout=30)
                        pool.terminate_workers()
                    else:
                        pool.shutdown(wait=True)
            finally:
                grupo.close()
                fila.close()


def coordenar(job_id, pasta=PASTA_RESULTADOS, lock_factory=LockProtocolo, runner=executar_pool):
    reg = ler(job_id, pasta)
    # Nunca repetir um comando com o mesmo ficheiro após crash/conclusão.
    if reg["estado"] != "pendente":
        return
    plano = PlanoProtocolo(**reg["plano"])
    try:
        validar_prazo(plano)
        if plano.codigo_hash != hash_codigo():
            raise ErroProtocolo("O código mudou desde a preparação; prepare novamente antes de avaliar.")
        with lock_factory() as lock:
            if not lock.obtido:
                reg.update(estado="recusado", motivo="protocolo_ativo",
                           mensagem="Já existe um protocolo sintético ativo; aguarde a sua conclusão.")
                guardar(reg, pasta)
                return
            # Reler sob lock: dois coordenadores podem ter lido o mesmo pendente.
            reg = ler(job_id, pasta)
            if reg["estado"] != "pendente":
                return
            reconciliar(lock, pasta, ignorar=job_id)
            verificar_holdout_inedito(plano, job_id, pasta)
            reg.update(estado="em_execucao", avaliacao_iniciada=True, proprietario_mysql=lock.owner,
                       inicio_em=agora(), inicio_epoch=time.time())
            guardar(reg, pasta)  # reserva durável antes de qualquer avaliação
            runner(plano, reg, lock, pasta)
    except ErroProtocolo as exc:
        reg.update(estado="recusado", motivo="validacao", mensagem=str(exc))
        guardar(reg, pasta)
    except BaseException:
        erro_id = uuid.uuid4().hex[:8]
        logging.exception("Erro F-04 [%s] protocolo %s", erro_id, job_id)
        interromper(reg, reg.get("motivo") or "erro_coordenador")
        reg["erro_id"] = erro_id
        guardar(reg, pasta)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--pasta", default=str(PASTA_RESULTADOS))
    args = parser.parse_args()
    (RAIZ / "logs").mkdir(exist_ok=True)
    logging.basicConfig(filename=RAIZ / "logs" / "backtesting.log", encoding="utf-8", level=logging.ERROR)
    coordenar(args.job, args.pasta)


if __name__ == "__main__":
    main()
