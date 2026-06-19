from flask import Flask, render_template, request, redirect, Response, session
# SUBSTITUA NO SEU APP.PY:
import psycopg2

URL_CONEXAO_SUPABASE = "postgresql://postgres.sua_string_aqui:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"

def conectar_banco():
    return psycopg2.connect(URL_CONEXAO_SUPABASE)
from datetime import datetime
import csv
import io

app = Flask(__name__)

# CHAVE DE SEGURANÇA: Necessária para o Flask gerenciar os logins (Sessões)
app.secret_key = 'virtron_chave_secreta_super_segura'

def conectar_banco():
    return sqlite3.connect('almoxarifado.db')

# === SISTEMA DE LOGIN E LOGOUT ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario_digitado = request.form['usuario']
        senha_digitada = request.form['senha']
        
        conexao = conectar_banco()
        cursor = conexao.cursor()
        cursor.execute("SELECT id, usuario, nivel FROM Usuarios WHERE usuario = ? AND senha = ?", (usuario_digitado, senha_digitada))
        usuario_encontrado = cursor.fetchone()
        conexao.close()
        
        if usuario_encontrado:
            # Salva os dados do usuário na memória do navegador (Sessão)
            session['usuario_id'] = usuario_encontrado[0]
            session['usuario_nome'] = usuario_encontrado[1]
            session['usuario_nivel'] = usuario_encontrado[2]
            return redirect('/')
        else:
            return render_template('login.html', erro="Usuário ou senha inválidos.")
            
    return render_template('login.html', erro=None)

@app.route('/logout')
def logout():
    # Limpa a memória do login e desloga
    session.clear()
    return redirect('/login')


# === TELA INICIAL (COM FILTROS E PESQUISA) ===
@app.route('/')
def pagina_inicial():
    # BARREIRA DE SEGURANÇA: Se não estiver logado, vai para o login
    if 'usuario_id' not in session:
        return redirect('/login')
        
    conexao = conectar_banco()
    cursor = conexao.cursor()
    
    pesquisa = request.args.get('pesquisa', '')
    grupo_filtro = request.args.get('grupo_filtro', '')
    
    query = '''
        SELECT p.id, p.nome, p.quantidade_atual, p.estoque_minimo, p.estoque_maximo, p.ponto_pedido, p.unidade_medida, g.nome, p.grupo_id, p.preco_unitario
        FROM Produtos p
        LEFT JOIN Grupos g ON p.grupo_id = g.id
        WHERE 1=1
    '''
    parametros = []
    if pesquisa:
        query += " AND p.nome LIKE ?"
        parametros.append(f"%{pesquisa}%")
    if grupo_filtro:
        query += " AND p.grupo_id = ?"
        parametros.append(grupo_filtro)
        
    cursor.execute(query, parametros)
    lista_produtos = cursor.fetchall()
    
    cursor.execute("SELECT * FROM Grupos ORDER BY nome")
    lista_grupos = cursor.fetchall()
    conexao.close()
    
    itens_comprar = []
    for p in lista_produtos:
        if p[2] <= p[5]:
            itens_comprar.append({'nome': p[1], 'atual': p[2], 'ponto': p[5], 'sugestao': p[4] - p[2], 'unidade': p[6]})
            
    return render_template('index.html', produtos=lista_produtos, grupos=lista_grupos, alertas=itens_comprar, pesquisa_atual=pesquisa, grupo_atual=grupo_filtro)

@app.route('/adicionar', methods=['POST'])
def adicionar_produto():
    if 'usuario_id' not in session: return redirect('/login')
    
    nome = request.form['nome']
    quantidade = request.form['quantidade']
    minimo = request.form['minimo']
    maximo = request.form['maximo']
    ponto = request.form['ponto']
    unidade = request.form['unidade']
    grupo_id = request.form['grupo_id']
    preco_unitario = request.form['preco_unitario']
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute('''
        INSERT INTO Produtos (nome, quantidade_atual, estoque_minimo, estoque_maximo, ponto_pedido, unidade_medida, grupo_id, preco_unitario)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (nome, quantidade, minimo, maximo, ponto, unidade, grupo_id, preco_unitario))
    conexao.commit()
    conexao.close()
    return redirect('/')

@app.route('/adicionar_estoque', methods=['POST'])
def adicionar_estoque():
    if 'usuario_id' not in session: return redirect('/login')
    
    produto_id = request.form['produto_id']
    qtd_entrada = int(request.form['quantidade_entrada'])
    preco_novo = float(request.form['preco_unitario'])
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual + ?, preco_unitario = ? WHERE id = ?', (qtd_entrada, preco_novo, produto_id))
    cursor.execute("INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo) VALUES (?, ?, 'FORNECEDOR / ENTRADA', 'ENTRADA')", (produto_id, -qtd_entrada))
    conexao.commit()
    conexao.close()
    return redirect('/')

@app.route('/excluir/<int:id>')
def excluir_produto(id):
    if 'usuario_id' not in session: return redirect('/login')
    # APENAS ADMIN PODE EXCLUIR
    if session.get('usuario_nivel') != 'admin':
        return "Acesso negado. Apenas administradores podem excluir itens.", 403
        
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("DELETE FROM Produtos WHERE id = ?", (id,))
    conexao.commit()
    conexao.close()
    return redirect('/')

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar_produto(id):
    if 'usuario_id' not in session: return redirect('/login')
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    
    if request.method == 'POST':
        nome = request.form['nome']
        quantidade = request.form['quantidade']
        minimo = request.form['minimo']
        maximo = request.form['maximo']
        ponto = request.form['ponto']
        unidade = request.form['unidade']
        grupo_id = request.form['grupo_id']
        preco_unitario = request.form['preco_unitario']
        
        cursor.execute('''
            UPDATE Produtos SET nome=?, quantidade_atual=?, estoque_minimo=?, estoque_maximo=?, ponto_pedido=?, unidade_medida=?, grupo_id=?, preco_unitario=?
            WHERE id=?
        ''', (nome, quantidade, minimo, maximo, ponto, unidade, grupo_id, preco_unitario, id))
        conexao.commit()
        conexao.close()
        return redirect('/')
    else:
        cursor.execute("SELECT * FROM Produtos WHERE id = ?", (id,))
        produto = cursor.fetchone()
        cursor.execute("SELECT * FROM Grupos ORDER BY nome")
        grupos = cursor.fetchall()
        conexao.close()
        return render_template('editar.html', produto=produto, grupos=grupos)

@app.route('/retirar', methods=['POST'])
def retirar_produto():
    if 'usuario_id' not in session: return redirect('/login')
    
    produto_ids = request.form.getlist('produto_id')
    quantidades = request.form.getlist('quantidade_retirada')
    solicitante = request.form['solicitante']
    codigo_protocolo = datetime.now().strftime("%Y%m%d%H%M%S")
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    for i in range(len(produto_ids)):
        p_id = produto_ids[i]
        qtd = int(quantidades[i])
        if p_id and qtd > 0:
            cursor.execute('INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo) VALUES (?, ?, ?, ?)', (p_id, qtd, solicitante, codigo_protocolo))
            cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual - ? WHERE id = ?', (qtd, p_id))
    conexao.commit()
    conexao.close()
    return redirect('/')

@app.route('/historico')
def historico_protocolos():
    if 'usuario_id' not in session: return redirect('/login')
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute('''
        SELECT COALESCE(t.codigo_protocolo, t.id), t.data_hora, 
               CASE WHEN t.quantidade_retirada < 0 THEN COALESCE(p.nome, '') || ' (🛒 ENTRADA DE ESTOQUE)'
                    ELSE COALESCE(p.nome || ' (' || p.unidade_medida || ')', k.nome || ' (Kit Montado)') END,
               ABS(t.quantidade_retirada), t.solicitante
        FROM Transacoes t LEFT JOIN Produtos p ON t.produto_id = p.id LEFT JOIN Kits k ON t.kit_id = k.id ORDER BY t.data_hora DESC
    ''')
    transacoes_brutas = cursor.fetchall()
    conexao.close()
    
    protocolos_agrupados = {}
    for linha in transacoes_brutas:
        codigo, data_hora, material, quantidade, solicitante = linha
        if codigo not in protocolos_agrupados:
            protocolos_agrupados[codigo] = {'codigo': codigo, 'data_hora': data_hora, 'solicitante': solicitante, 'itens': []}
        protocolos_agrupados[codigo]['itens'].append({'material': material, 'quantidade': quantidade})
    return render_template('historico.html', protocols=list(protocolos_agrupados.values()))

@app.route('/exportar')
def exportar_csv():
    if 'usuario_id' not in session: return redirect('/login')
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute('''
        SELECT COALESCE(t.codigo_protocolo, t.id), t.data_hora, COALESCE(p.nome || ' (' || p.unidade_medida || ')', k.nome || ' (Kit Montado)'), t.quantidade_retirada, t.solicitante
        FROM Transacoes t LEFT JOIN Produtos p ON t.produto_id = p.id LEFT JOIN Kits k ON t.kit_id = k.id ORDER BY t.data_hora DESC
    ''')
    transacoes = cursor.fetchall()
    conexao.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Protocolo', 'Data e Hora', 'Material Retirado', 'Quantidade', 'Solicitante'])
    for t in transacoes: writer.writerow(t)
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers["Content-Disposition"] = "attachment; filename=historico_almoxarifado.csv"
    return response

@app.route('/kits')
def gerenciar_kits():
    if 'usuario_id' not in session: return redirect('/login')
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("SELECT id, nome, quantidade_atual FROM Kits")
    lista_kits = cursor.fetchall()
    cursor.execute("SELECT id, nome FROM Produtos")
    lista_produtos = cursor.fetchall()
    conexao.close()
    return render_template('kits.html', kits=lista_kits, produtos=lista_produtos)

@app.route('/criar_kit', methods=['POST'])
def criar_kit():
    if 'usuario_id' not in session: return redirect('/login')
    nome_kit = request.form['nome_kit']
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("INSERT INTO Kits (nome, quantidade_atual) VALUES (?, 0)", (nome_kit,))
    conexao.commit()
    conexao.close()
    return redirect('/kits')

@app.route('/adicionar_item_kit', methods=['POST'])
def adicionar_item_kit():
    if 'usuario_id' not in session: return redirect('/login')
    kit_id, produto_id, quantidade = request.form['kit_id'], request.form['produto_id'], request.form['quantidade']
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("INSERT INTO Kit_Itens (kit_id, produto_id, quantidade_necessaria) VALUES (?, ?, ?)", (kit_id, produto_id, quantidade))
    conexao.commit()
    conexao.close()
    return redirect('/kits')

@app.route('/montar_kit', methods=['POST'])
def montar_kit():
    if 'usuario_id' not in session: return redirect('/login')
    kit_id, qtd_montar = request.form['kit_id'], int(request.form['quantidade'])
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("SELECT produto_id, quantidade_necessaria FROM Kit_Itens WHERE kit_id = ?", (kit_id,))
    itens = cursor.fetchall()
    for item in itens:
        cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual - ? WHERE id = ?', (item[1] * qtd_montar, item[0]))
    cursor.execute('UPDATE Kits SET quantidade_atual = quantidade_atual + ? WHERE id = ?', (qtd_montar, kit_id))
    conexao.commit()
    conexao.close()
    return redirect('/kits')

@app.route('/retirar_kit', methods=['POST'])
def retirar_kit():
    if 'usuario_id' not in session: return redirect('/login')
    kit_id, qtd_retirar, solicitante = request.form['kit_id'], int(request.form['quantidade']), request.form['solicitante']
    codigo_protocolo = datetime.now().strftime("%Y%m%d%H%M%S")
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute('UPDATE Kits SET quantidade_atual = quantidade_atual - ? WHERE id = ?', (kit_id, qtd_retirar))
    cursor.execute('INSERT INTO Transacoes (kit_id, quantidade_retirada, solicitante, codigo_protocolo) VALUES (?, ?, ?, ?)', (kit_id, qtd_retirar, solicitante, codigo_protocolo))
    conexao.commit()
    conexao.close()
    return redirect('/historico')

@app.route('/gerenciar_grupos', methods=['GET', 'POST'])
def gerenciar_grupos():
    if 'usuario_id' not in session: return redirect('/login')
    if session.get('usuario_nivel') != 'admin': return "Acesso restrito.", 403
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    if request.method == 'POST':
        nome_grupo = request.form['nome_grupo']
        try:
            cursor.execute("INSERT INTO Grupos (nome) VALUES (?)", (nome_grupo,))
            conexao.commit()
        except: pass
        return redirect('/gerenciar_grupos')
    cursor.execute("SELECT * FROM Grupos ORDER BY nome")
    lista_grupos = cursor.fetchall()
    conexao.close()
    return render_template('grupos.html', grupos=lista_grupos)

@app.route('/excluir_grupo/<int:id>')
def excluir_grupo(id):
    if 'usuario_id' not in session: return redirect('/login')
    if session.get('usuario_nivel') != 'admin': return "Acesso restrito.", 403
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("UPDATE Produtos SET grupo_id = NULL WHERE grupo_id = ?", (id,))
    cursor.execute("DELETE FROM Grupos WHERE id = ?", (id,))
    conexao.commit()
    conexao.close()
    return redirect('/gerenciar_grupos')

# === TRAVA COMPLETA DA ROTA DO DASHBOARD FINANCEIRO ===
@app.route('/financeiro')
def dashboard_financeiro():
    if 'usuario_id' not in session: 
        return redirect('/login')
    
    # 🛑 SEGURANÇA MÁXIMA: Se não for administrador, barra na hora!
    if session.get('usuario_nivel') != 'admin':
        return "❌ ERRO: Acesso negado. Você não tem permissão para visualizar o Dashboard Financeiro.", 403
        
    conexao = conectar_banco()
    cursor = conexao.cursor()
    
    cursor.execute("SELECT SUM(quantidade_atual * preco_unitario) FROM Produtos")
    patrimonio_total = cursor.fetchone()[0] or 0.0

    cursor.execute('''
        SELECT COALESCE(g.nome, 'Sem Grupo') as grupo, SUM(p.quantidade_atual * p.preco_unitario) as total
        FROM Produtos p LEFT JOIN Grupos g ON p.grupo_id = g.id GROUP BY p.grupo_id ORDER BY total DESC
    ''')
    categorias_bruto = cursor.fetchall()
    valores_categoria = [{'grupo': c[0], 'total': c[1] if c[1] else 0.0} for c in categorias_bruto]

    periodo = request.args.get('periodo', '30')
    cursor.execute('''
        SELECT COALESCE(g.nome, 'Sem Grupo') as grupo, SUM(t.quantidade_retirada * p.preco_unitario) as total_movimentado
        FROM Transacoes t JOIN Produtos p ON t.produto_id = p.id LEFT JOIN Grupos g ON p.grupo_id = g.id
        WHERE t.data_hora >= datetime('now', '-' || ? || ' days') GROUP BY p.grupo_id ORDER BY total_movimentado DESC
    ''', (periodo,))
    dados_grafico = cursor.fetchall()
    conexao.close()

    graf_labels = [item[0] for item in dados_grafico]
    graf_valores = [item[1] if item[1] else 0.0 for item in dados_grafico]

    return render_template('financeiro.html', patrimonio_total=patrimonio_total, valores_categoria=valores_categoria, graf_labels=graf_labels, graf_valores=graf_valores, periodo_atual=periodo)

# === GERENCIAMENTO DE USUÁRIOS (APENAS ADMIN) ===
@app.route('/gerenciar_usuarios', methods=['GET', 'POST'])
def gerenciar_usuarios():
    if 'usuario_id' not in session: return redirect('/login')
    if session.get('usuario_nivel') != 'admin': return "Acesso restrito.", 403
    
    conexao = conectar_banco()
    cursor = conexao.cursor()
    
    if request.method == 'POST':
        novo_usuario = request.form['usuario']
        nova_senha = request.form['senha']
        nivel = request.form['nivel']
        try:
            cursor.execute("INSERT INTO Usuarios (usuario, senha, nivel) VALUES (?, ?, ?)", (novo_usuario, nova_senha, nivel))
            conexao.commit()
        except:
            pass # Se o usuário já existir (ID único), ignora o erro
        return redirect('/gerenciar_usuarios')
        
    cursor.execute("SELECT id, usuario, nivel FROM Usuarios ORDER BY usuario")
    lista_usuarios = cursor.fetchall()
    conexao.close()
    return render_template('usuarios.html', usuarios=lista_usuarios)

@app.route('/excluir_usuario/<int:id>')
def excluir_usuario(id):
    if 'usuario_id' not in session: return redirect('/login')
    if session.get('usuario_nivel') != 'admin': return "Acesso restrito.", 403
    
    # Impede que o admin se exclua por acidente e fique trancado para fora do sistema
    if id == session.get('usuario_id'):
        return "Você não pode excluir seu próprio usuário logado.", 400
        
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("DELETE FROM Usuarios WHERE id = ?", (id,))
    conexao.commit()
    conexao.close()
    return redirect('/gerenciar_usuarios')

if __name__ == '__main__':
    app.run(debug=True)