import sqlite3

conexao = sqlite3.connect('almoxarifado.db')
cursor = conexao.cursor()

# Adiciona uma coluna de agrupamento para saídas múltiplas
try:
    cursor.execute("ALTER TABLE Transacoes ADD COLUMN codigo_protocolo TEXT")
except:
    pass # Se a coluna já existir, ele ignora

conexao.commit()
conexao.close()

print("Banco atualizado com sucesso para agrupamento de protocolos!")