import sqlite3

conexao = sqlite3.connect('almoxarifado.db')
cursor = conexao.cursor()

# Adiciona controle de estoque próprio para os Kits
try:
    cursor.execute("ALTER TABLE Kits ADD COLUMN quantidade_atual INTEGER DEFAULT 0")
except:
    pass # A coluna já existe

# Permite que o Protocolo (Transações) registre a saída de um Kit
try:
    cursor.execute("ALTER TABLE Transacoes ADD COLUMN kit_id INTEGER")
except:
    pass # A coluna já existe

conexao.commit()
conexao.close()

print("Banco atualizado com sucesso para o novo formato de montagem física de Kits!")