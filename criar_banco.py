from database.connection import get_connection
from config import Config
from mysql.connector import errors as mysql_errors


def executar(cursor, sql):
    cursor.execute(sql)


def coluna_existe(cursor, tabela, coluna):
    cursor.execute(f"SHOW COLUMNS FROM {tabela} LIKE %s", (coluna,))
    return cursor.fetchone() is not None


def garantir_coluna(cursor, tabela, coluna, definicao):
    if not coluna_existe(cursor, tabela, coluna):
        cursor.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")


def normalizar_coluna_ultimo_sorteio(cursor):
    """Altera o tipo; ignora apenas MySQL 1060 (coluna já existente)."""
    try:
        cursor.execute("ALTER TABLE estatisticas_numeros MODIFY COLUMN ultimo_sorteio VARCHAR(30) NULL")
    except mysql_errors.ProgrammingError as exc:
        if getattr(exc, "errno", None) != 1060:
            raise


def criar_banco_e_tabelas():
    conexao = get_connection(use_database=False)
    cursor = conexao.cursor()
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS {Config.MYSQL_DATABASE} "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
    )
    conexao.commit()
    cursor.close()
    conexao.close()

    conexao = get_connection(use_database=True)
    cursor = conexao.cursor()

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS sorteios (
        id INT AUTO_INCREMENT PRIMARY KEY,
        concurso INT NOT NULL UNIQUE,
        data_sorteio DATE NOT NULL,
        n1 INT NOT NULL,
        n2 INT NOT NULL,
        n3 INT NOT NULL,
        n4 INT NOT NULL,
        n5 INT NOT NULL,
        n6 INT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS estatisticas_numeros (
        id INT AUTO_INCREMENT PRIMARY KEY,
        numero INT NOT NULL UNIQUE,
        numero_saidas INT DEFAULT 0,
        percentual_saidas DECIMAL(8,2) DEFAULT 0,
        ultimo_sorteio VARCHAR(30) NULL,
        data_ultimo_sorteio DATE NULL,
        ausencias INT DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS importacoes_estatistica (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome_ficheiro VARCHAR(255) NOT NULL,
        sha256 CHAR(64) NOT NULL,
        registos_aceites INT NOT NULL,
        criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # Migração segura para projetos já criados.
    # Permite valores oficiais como 21/2026 e também correções de Excel como set-26 -> 9/2026.
    normalizar_coluna_ultimo_sorteio(cursor)

    garantir_coluna(cursor, "estatisticas_numeros", "probabilidade_teorica", "DECIMAL(8,2) DEFAULT 13.33")
    garantir_coluna(cursor, "estatisticas_numeros", "desvio_frequencia", "DECIMAL(8,2) DEFAULT 0")
    garantir_coluna(cursor, "estatisticas_numeros", "frequencia_ultimos_5", "INT DEFAULT 0")
    garantir_coluna(cursor, "estatisticas_numeros", "frequencia_ultimos_10", "INT DEFAULT 0")
    garantir_coluna(cursor, "estatisticas_numeros", "media_intervalo", "DECIMAL(8,2) NULL")
    garantir_coluna(cursor, "estatisticas_numeros", "indice_quente", "DECIMAL(8,2) DEFAULT 0")
    garantir_coluna(cursor, "estatisticas_numeros", "indice_atraso", "DECIMAL(8,2) DEFAULT 0")

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS jogos_gerados (
        id INT AUTO_INCREMENT PRIMARY KEY,
        concurso INT NULL,
        tipo_aposta VARCHAR(30) NOT NULL,
        estrategia VARCHAR(80) NOT NULL,
        numeros VARCHAR(120) NOT NULL,
        apostas_simples INT NOT NULL,
        score DECIMAL(5,2) NOT NULL,
        custo_total DECIMAL(12,2) NOT NULL,
        incluir_joker BOOLEAN DEFAULT FALSE,
        custo_joker DECIMAL(12,2) DEFAULT 0,
        custo_final DECIMAL(12,2) NOT NULL,
        observacao TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    garantir_coluna(cursor, "jogos_gerados", "comprado", "BOOLEAN NOT NULL DEFAULT FALSE")

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS estrategias (
        id INT AUTO_INCREMENT PRIMARY KEY,
        nome VARCHAR(80) NOT NULL UNIQUE,
        descricao TEXT NULL,
        peso_frequencia DECIMAL(6,2) DEFAULT 1,
        peso_ausencia DECIMAL(6,2) DEFAULT 1,
        peso_equilibrio DECIMAL(6,2) DEFAULT 1,
        peso_soma DECIMAL(6,2) DEFAULT 1,
        peso_baixa_popularidade DECIMAL(6,2) DEFAULT 1,
        ativa BOOLEAN DEFAULT TRUE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS configuracoes (
        id INT AUTO_INCREMENT PRIMARY KEY,
        total_numeros INT DEFAULT 45,
        numeros_por_jogo INT DEFAULT 6,
        preco_aposta_simples DECIMAL(12,2) DEFAULT 30,
        preco_joker DECIMAL(12,2) DEFAULT 70,
        orcamento_semanal DECIMAL(12,2) DEFAULT 1000,
        moeda VARCHAR(10) DEFAULT 'CVE'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS controle_banca (
        id INT AUTO_INCREMENT PRIMARY KEY,
        concurso INT NULL,
        valor_gasto DECIMAL(12,2) DEFAULT 0,
        valor_retorno DECIMAL(12,2) DEFAULT 0,
        lucro_prejuizo DECIMAL(12,2) DEFAULT 0,
        observacao TEXT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS geracoes_semanais (
        id INT AUTO_INCREMENT PRIMARY KEY,
        concurso INT NULL,
        data_geracao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        estrategia VARCHAR(80) NOT NULL,
        tipo_aposta VARCHAR(30) NOT NULL,
        quantidade_jogos INT NOT NULL,
        custo_total DECIMAL(12,2) NOT NULL,
        observacao TEXT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS joker_resultados (
        id INT AUTO_INCREMENT PRIMARY KEY,
        concurso VARCHAR(30) NOT NULL UNIQUE,
        data_sorteio DATE NOT NULL,
        numero_joker VARCHAR(12) NOT NULL,
        premio VARCHAR(80) DEFAULT '1.º Prémio',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    executar(cursor, """
    CREATE TABLE IF NOT EXISTS joker_estatisticas (
        id INT AUTO_INCREMENT PRIMARY KEY,
        posicao INT NOT NULL,
        digito INT NOT NULL,
        total_saidas INT DEFAULT 0,
        percentual DECIMAL(8,2) DEFAULT 0,
        ultimo_concurso VARCHAR(30) NULL,
        data_ultimo_sorteio DATE NULL,
        ausencias INT DEFAULT 0,
        frequencia_ultimos_5 INT DEFAULT 0,
        frequencia_ultimos_10 INT DEFAULT 0,
        media_intervalo DECIMAL(8,2) NULL,
        indice_quente DECIMAL(8,2) DEFAULT 0,
        indice_atraso DECIMAL(8,2) DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uniq_posicao_digito (posicao, digito)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)


    executar(cursor, """
    INSERT IGNORE INTO configuracoes
    (id, total_numeros, numeros_por_jogo, preco_aposta_simples, preco_joker, orcamento_semanal, moeda)
    VALUES (1, 45, 6, 30, 70, 1000, 'CVE');
    """)

    estrategias = [
        ("Equilibrada", "Combina frequência, ausência, janelas recentes, paridade, zonas e soma sem prometer resultado.", 1.00, 1.00, 1.00, 1.00, 1.00),
        ("Frequentes", "Prioriza números com mais saídas e maior índice quente, mantendo filtros de equilíbrio.", 1.90, 0.20, 0.80, 0.80, 0.60),
        ("Atrasados", "Prioriza ausência e atraso relativo, sem montar jogo somente com números frios.", 0.20, 1.90, 0.80, 0.80, 0.60),
        ("Mista", "Mistura números frequentes, atrasados e intermediários para evitar extremos estatísticos.", 1.20, 1.20, 1.00, 1.00, 1.00),
        ("Conservadora", "Privilegia equilíbrio de paridade, baixos/altos, zonas e soma próxima da média teórica.", 0.70, 0.70, 1.70, 1.30, 1.10),
        ("Agressiva", "Aceita maior variação estatística e dá mais peso a extremos de frequência e atraso.", 1.50, 1.50, 0.70, 0.60, 1.30),
        ("Aleatória Inteligente", "Gera aleatoriamente, mas passa por filtros matemáticos e evita padrões fracos.", 0.60, 0.60, 0.90, 0.90, 1.00),
    ]
    cursor.executemany("""
    INSERT INTO estrategias
    (nome, descricao, peso_frequencia, peso_ausencia, peso_equilibrio, peso_soma, peso_baixa_popularidade, ativa)
    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
    ON DUPLICATE KEY UPDATE
        descricao = VALUES(descricao),
        peso_frequencia = VALUES(peso_frequencia),
        peso_ausencia = VALUES(peso_ausencia),
        peso_equilibrio = VALUES(peso_equilibrio),
        peso_soma = VALUES(peso_soma),
        peso_baixa_popularidade = VALUES(peso_baixa_popularidade),
        ativa = TRUE
    """, estrategias)

    for numero in range(1, Config.TOTAL_NUMEROS + 1):
        cursor.execute("""
        INSERT IGNORE INTO estatisticas_numeros
        (numero, numero_saidas, percentual_saidas, probabilidade_teorica, ausencias)
        VALUES (%s, 0, 0, 13.33, 0)
        """, (numero,))

    for posicao in range(1, 7):
        for digito in range(10):
            cursor.execute("""
            INSERT IGNORE INTO joker_estatisticas
            (posicao, digito, total_saidas, percentual, ausencias)
            VALUES (%s, %s, 0, 0, 0)
            """, (posicao, digito))

    conexao.commit()
    cursor.close()
    conexao.close()
    print("Banco 'totoloto_analyzer' e tabelas criados/actualizados com sucesso.")


if __name__ == "__main__":
    criar_banco_e_tabelas()
