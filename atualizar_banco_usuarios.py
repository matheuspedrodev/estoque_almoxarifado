import sqlite3

conexao = sqlite3.connect('almoxarifado.db')
cursor = conexao.cursor()

# 1. Cria a tabela de Usuários
cursor.execute('''
    CREATE TABLE IF NOT EXISTS Usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL UNIQUE,
        senha TEXT NOT NULL,
        nivel TEXT NOT NULL -- 'admin' ou 'operador'
    )
''')

# 2. Cadastra um administrador padrão se ele não existir
try:
    cursor.execute('''
        INSERT INTO Usuarios (usuario, senha, nivel) 
        VALUES ('admin', 'virtron123', 'admin')
    ''')
    print("✅ Tabela criada e usuário 'admin' (senha: virtron123) cadastrado!")
except sqlite3.IntegrityError:
    print("ℹ️ A tabela de usuários já existe e o admin já está cadastrado.")

conexao.commit()
conexao.close()