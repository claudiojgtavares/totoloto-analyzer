import os
import secrets


def _inteiro_ambiental(nome, padrao):
    try:
        valor = int(os.environ.get(nome, str(padrao)))
    except (TypeError, ValueError):
        return padrao
    return max(0, valor)

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"

    MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
    MYSQL_USER = os.environ.get("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
    MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
    MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "totoloto_analyzer")

    TOTAL_NUMEROS = 45
    NUMEROS_POR_JOGO = 6
    PRECO_APOSTA_SIMPLES = 30
    PRECO_JOKER = 70
    MOEDA = "CVE"

    UPLOAD_FOLDER = "uploads"
    EXPORT_PDF_FOLDER = os.path.join("exports", "pdf")
    EXPORT_EXCEL_FOLDER = os.path.join("exports", "excel")
    # Retenção automática: zero desativa o limite correspondente.
    EXPORT_RETENTION_DAYS = _inteiro_ambiental("EXPORT_RETENTION_DAYS", 30)
    EXPORT_RETENTION_MAX_FILES = _inteiro_ambiental("EXPORT_RETENTION_MAX_FILES", 100)
    BACKUP_FOLDER = os.path.join("exports", "backup")
    MYSQLDUMP_PATH = os.environ.get("MYSQLDUMP_PATH", "")
    BACKUP_RETENTION_DAYS = _inteiro_ambiental("BACKUP_RETENTION_DAYS", 180)
    BACKUP_RETENTION_MAX_FILES = _inteiro_ambiental("BACKUP_RETENTION_MAX_FILES", 30)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
