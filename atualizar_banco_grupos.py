import sqlite3

conexao = sqlite3.connect('almoxarifado.db')
cursor = conexao.cursor()

# 1. Cria a tabela de Grupos
cursor.execute('''
    CREATE TABLE IF NOT EXISTS Grupos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE
    )
''')

# 2. Insere alguns grupos padrão da Virtron se eles não existirem
grupos_padrao = ['Linha PVC', 'Cabos Elétricos', 'Estruturas', 'Módulos', 'Inversores', 'Material de Escritório']
for grupo in grupos_padrao:
    try:
        cursor.execute("INSERT INTO Grupos (nome) VALUES (?)", (grupo,))
    except sqlite3.IntegrityError:
        pass

# 3. Adiciona a coluna de grupo na tabela de Produtos
try:
    cursor.execute("ALTER TABLE Produtos ADD COLUMN grupo_id INTEGER REFERENCES Grupos(id)")
except:
    pass

conexao.commit()
conexao.close()

print("✅ Banco atualizado com sucesso! A tabela Grupos foi criada.")