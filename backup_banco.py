"""Cria e retém backups SQL da base MySQL local.

Uso manual: python backup_banco.py
"""

import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from config import Config


class ErroBackup(RuntimeError):
    """Erro operacional ao criar ou validar um backup."""


def localizar_mysqldump():
    """Resolve MYSQLDUMP_PATH ou procura mysqldump no PATH."""
    configurado = str(Config.MYSQLDUMP_PATH or os.environ.get("MYSQLDUMP_PATH", "")).strip()
    if configurado:
        caminho = shutil.which(configurado)
        if caminho:
            return caminho
        if Path(configurado).is_file():
            return str(Path(configurado))
        raise ErroBackup(f"O executável indicado em MYSQLDUMP_PATH não foi encontrado: {configurado}")
    caminho = shutil.which("mysqldump")
    if not caminho:
        raise ErroBackup("mysqldump não foi encontrado. Instale o XAMPP ou configure MYSQLDUMP_PATH.")
    return caminho


def limpar_backups(pasta=None, dias=None, max_ficheiros=None, agora=None):
    """Aplica a retenção própria dos backups; só é chamada pelo script."""
    raiz = Path(pasta or Config.BACKUP_FOLDER)
    raiz.mkdir(parents=True, exist_ok=True)
    dias = Config.BACKUP_RETENTION_DAYS if dias is None else max(0, int(dias))
    max_ficheiros = Config.BACKUP_RETENTION_MAX_FILES if max_ficheiros is None else max(0, int(max_ficheiros))
    agora_ts = time.time() if agora is None else float(agora)
    ficheiros = [p for p in raiz.iterdir() if p.is_file() and p.suffix.lower() == ".sql"]
    removidos = 0
    if dias:
        limite = agora_ts - timedelta(days=dias).total_seconds()
        for ficheiro in list(ficheiros):
            if ficheiro.stat().st_mtime < limite:
                ficheiro.unlink()
                ficheiros.remove(ficheiro)
                removidos += 1
    if max_ficheiros and len(ficheiros) > max_ficheiros:
        ficheiros.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for ficheiro in ficheiros[max_ficheiros:]:
            ficheiro.unlink()
            removidos += 1
    return removidos


def criar_backup(pasta=None, agora=None):
    """Executa mysqldump e devolve o caminho do dump validado."""
    executavel = localizar_mysqldump()
    raiz = Path(pasta or Config.BACKUP_FOLDER)
    raiz.mkdir(parents=True, exist_ok=True)
    instante = datetime.now() if agora is None else agora
    nome = f"totoloto_analyzer_{instante.strftime('%Y%m%d_%H%M%S_%f')}.sql"
    destino = raiz / nome
    temporario = destino.with_suffix(".sql.part")
    ambiente = os.environ.copy()
    ambiente["MYSQL_PWD"] = str(Config.MYSQL_PASSWORD or "")
    comando = [
        executavel,
        f"--host={Config.MYSQL_HOST}",
        f"--port={Config.MYSQL_PORT}",
        f"--user={Config.MYSQL_USER}",
        f"--result-file={temporario}",
        Config.MYSQL_DATABASE,
    ]
    try:
        processo = subprocess.run(comando, env=ambiente, capture_output=True, text=True, check=False)
        if processo.returncode != 0:
            detalhe = (processo.stderr or "").strip()
            raise ErroBackup(f"mysqldump terminou com código {processo.returncode}. {detalhe}".strip())
        if not temporario.exists() or temporario.stat().st_size <= 0:
            raise ErroBackup("mysqldump terminou sem produzir um ficheiro SQL válido.")
        temporario.replace(destino)
        limpar_backups(raiz, agora=agora.timestamp() if agora is not None else None)
        return str(destino)
    except (OSError, ErroBackup) as exc:
        for ficheiro in (temporario, destino):
            try:
                ficheiro.unlink()
            except FileNotFoundError:
                pass
        if isinstance(exc, ErroBackup):
            raise
        raise ErroBackup(f"Não foi possível executar mysqldump: {exc}") from exc


def main():
    try:
        caminho = criar_backup()
    except ErroBackup as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    print(f"Backup criado com sucesso: {caminho}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
