import sqlite3

conexao = sqlite3.connect('almoxarifado.db')
cursor = conexao.cursor()

# Adiciona a coluna de Unidade de Medida na tabela de Produtos
try:
    cursor.execute("ALTER TABLE Produtos ADD COLUMN unidade_medida TEXT DEFAULT 'UN'")
except:
    pass # Se a coluna já existir, ele ignora

conexao.commit()
conexao.close()

print("Banco atualizado com sucesso! Coluna de Unidades de Medida criada.")