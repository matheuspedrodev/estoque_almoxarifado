import sqlite3

conexao = sqlite3.connect('almoxarifado.db')
cursor = conexao.cursor()

# Adiciona a coluna de preço unitário na tabela de Produtos se ela não existir
try:
    cursor.execute("ALTER TABLE Produtos ADD COLUMN preco_unitario REAL DEFAULT 0.0")
    print("✅ Coluna 'preco_unitario' adicionada com sucesso!")
except sqlite3.OperationalError:
    print("ℹ️ A coluna de preço já existe no banco.")

conexao.commit()
conexao.close()