import os
import psycopg2
from werkzeug.security import generate_password_hash

os.environ['PGCLIENTENCODING'] = 'UTF8'

URL_CONEXAO_SUPABASE = os.environ.get('DATABASE_URL')

if not URL_CONEXAO_SUPABASE:
    print("ERRO: variavel DATABASE_URL nao encontrada.")
    print("Execute antes de rodar o script:")
    print('  $env:DATABASE_URL = "sua_url_aqui"')
    exit(1)

# Senha inicial do administrador — troque após o primeiro login
SENHA_ADMIN_INICIAL = "virtron123"

try:
    conexao = psycopg2.connect(URL_CONEXAO_SUPABASE)
    cursor = conexao.cursor()
    print("Conectado ao Supabase com sucesso! Criando tabelas...")

    # 1. Tabela de Grupos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Grupos (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(100) NOT NULL UNIQUE
        );
    ''')

    # 2. Tabela de Usuários
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Usuarios (
            id SERIAL PRIMARY KEY,
            usuario VARCHAR(100) NOT NULL UNIQUE,
            senha VARCHAR(256) NOT NULL,
            nivel VARCHAR(20) NOT NULL
        );
    ''')

    # 3. Tabela de Produtos
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Produtos (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(200) NOT NULL,
            quantidade_atual INTEGER NOT NULL,
            estoque_minimo INTEGER NOT NULL,
            estoque_maximo INTEGER NOT NULL,
            ponto_pedido INTEGER NOT NULL,
            unidade_medida VARCHAR(20) NOT NULL,
            grupo_id INTEGER REFERENCES Grupos(id) ON DELETE SET NULL,
            preco_unitario NUMERIC(10, 2) DEFAULT 0.0
        );
    ''')

    # 4. Tabela de Kits
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Kits (
            id SERIAL PRIMARY KEY,
            nome VARCHAR(200) NOT NULL UNIQUE,
            quantidade_atual INTEGER DEFAULT 0
        );
    ''')

    # 5. Tabela de Itens do Kit
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Kit_Itens (
            id SERIAL PRIMARY KEY,
            kit_id INTEGER REFERENCES Kits(id) ON DELETE CASCADE,
            produto_id INTEGER REFERENCES Produtos(id) ON DELETE CASCADE,
            quantidade_necessaria INTEGER NOT NULL
        );
    ''')

    # 6. Tabela de Transações / Histórico
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Transacoes (
            id SERIAL PRIMARY KEY,
            produto_id INTEGER REFERENCES Produtos(id) ON DELETE SET NULL,
            kit_id INTEGER REFERENCES Kits(id) ON DELETE SET NULL,
            quantidade_retirada INTEGER NOT NULL,
            solicitante VARCHAR(200) NOT NULL,
            codigo_protocolo VARCHAR(50) NOT NULL,
            data_hora TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    ''')

    # Carga inicial de Grupos padrão
    grupos_padrao = [
        'Linha PVC', 'Cabos Elétricos', 'Estruturas',
        'Módulos', 'Inversores', 'Material de Escritório'
    ]
    for grupo in grupos_padrao:
        cursor.execute(
            "INSERT INTO Grupos (nome) VALUES (%s) ON CONFLICT (nome) DO NOTHING;",
            (grupo,)
        )

    # Criação do administrador inicial com senha hasheada
    senha_hash = generate_password_hash(SENHA_ADMIN_INICIAL)
    cursor.execute(
        "INSERT INTO Usuarios (usuario, senha, nivel) VALUES ('admin', %s, 'admin') ON CONFLICT (usuario) DO NOTHING;",
        (senha_hash,)
    )

    conexao.commit()
    print("Estrutura do Almoxarifado criada na nuvem com sucesso!")
    print(f"Login: admin | Senha: {SENHA_ADMIN_INICIAL}")
    print("IMPORTANTE: Troque a senha do admin pelo sistema apos o primeiro acesso.")

except Exception as e:
    print(f"Erro ao configurar o banco no Supabase: {e}")
finally:
    if 'conexao' in locals() and conexao:
        cursor.close()
        conexao.close()
