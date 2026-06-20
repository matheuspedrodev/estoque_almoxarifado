import os
from flask import Flask, render_template, request, redirect, Response, session, flash
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from datetime import datetime
import csv
import io
from dotenv import load_dotenv

load_dotenv(encoding='latin-1')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chave-dev-nao-usar-em-producao')
csrf = CSRFProtect(app)


def conectar_banco():
    return psycopg2.connect(os.environ.get('DATABASE_URL'))


# === SISTEMA DE LOGIN E LOGOUT ===
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario_digitado = request.form['usuario']
        senha_digitada = request.form['senha']

        conexao = conectar_banco()
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT id, usuario, senha, nivel FROM Usuarios WHERE usuario = %s",
            (usuario_digitado,)
        )
        usuario_encontrado = cursor.fetchone()
        conexao.close()

        if usuario_encontrado and check_password_hash(usuario_encontrado[2], senha_digitada):
            session['usuario_id'] = usuario_encontrado[0]
            session['usuario_nome'] = usuario_encontrado[1]
            session['usuario_nivel'] = usuario_encontrado[3]
            return redirect('/')
        else:
            return render_template('login.html', erro="Usuário ou senha inválidos.")

    return render_template('login.html', erro=None)


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# === TELA INICIAL (COM FILTROS E PESQUISA) ===
@app.route('/')
def pagina_inicial():
    if 'usuario_id' not in session:
        return redirect('/login')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    pesquisa = request.args.get('pesquisa', '')
    grupo_filtro = request.args.get('grupo_filtro', '')

    query = '''
        SELECT p.id, p.nome, p.quantidade_atual, p.estoque_minimo, p.estoque_maximo,
               p.ponto_pedido, p.unidade_medida, g.nome, p.grupo_id, p.preco_unitario
        FROM Produtos p
        LEFT JOIN Grupos g ON p.grupo_id = g.id
        WHERE 1=1
    '''
    parametros = []
    if pesquisa:
        query += " AND p.nome ILIKE %s"
        parametros.append(f"%{pesquisa}%")
    if grupo_filtro:
        query += " AND p.grupo_id = %s"
        parametros.append(grupo_filtro)

    cursor.execute(query, parametros)
    lista_produtos = cursor.fetchall()

    cursor.execute("SELECT * FROM Grupos ORDER BY nome")
    lista_grupos = cursor.fetchall()
    conexao.close()

    itens_comprar = []
    for p in lista_produtos:
        if p[2] <= p[5]:
            itens_comprar.append({
                'nome': p[1], 'atual': p[2],
                'ponto': p[5], 'sugestao': p[4] - p[2], 'unidade': p[6]
            })

    return render_template(
        'index.html',
        produtos=lista_produtos,
        grupos=lista_grupos,
        alertas=itens_comprar,
        pesquisa_atual=pesquisa,
        grupo_atual=grupo_filtro
    )


@app.route('/adicionar', methods=['POST'])
def adicionar_produto():
    if 'usuario_id' not in session:
        return redirect('/login')

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
        INSERT INTO Produtos (nome, quantidade_atual, estoque_minimo, estoque_maximo,
                              ponto_pedido, unidade_medida, grupo_id, preco_unitario)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    ''', (nome, quantidade, minimo, maximo, ponto, unidade, grupo_id, preco_unitario))
    conexao.commit()
    conexao.close()
    return redirect('/')


@app.route('/adicionar_estoque', methods=['POST'])
def adicionar_estoque():
    if 'usuario_id' not in session:
        return redirect('/login')

    produto_id = request.form['produto_id']
    qtd_entrada = int(request.form['quantidade_entrada'])
    preco_novo = float(request.form['preco_unitario'])

    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute(
        'UPDATE Produtos SET quantidade_atual = quantidade_atual + %s, preco_unitario = %s WHERE id = %s',
        (qtd_entrada, preco_novo, produto_id)
    )
    cursor.execute(
        "INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo) VALUES (%s, %s, 'FORNECEDOR / ENTRADA', 'ENTRADA')",
        (produto_id, -qtd_entrada)
    )
    conexao.commit()
    conexao.close()
    return redirect('/')


@app.route('/excluir/<int:id>')
def excluir_produto(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso negado. Apenas administradores podem excluir itens.", 403

    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("DELETE FROM Produtos WHERE id = %s", (id,))
    conexao.commit()
    conexao.close()
    return redirect('/')


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar_produto(id):
    if 'usuario_id' not in session:
        return redirect('/login')

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
            UPDATE Produtos
            SET nome=%s, quantidade_atual=%s, estoque_minimo=%s, estoque_maximo=%s,
                ponto_pedido=%s, unidade_medida=%s, grupo_id=%s, preco_unitario=%s
            WHERE id=%s
        ''', (nome, quantidade, minimo, maximo, ponto, unidade, grupo_id, preco_unitario, id))
        conexao.commit()
        conexao.close()
        return redirect('/')
    else:
        cursor.execute("SELECT * FROM Produtos WHERE id = %s", (id,))
        produto = cursor.fetchone()
        cursor.execute("SELECT * FROM Grupos ORDER BY nome")
        grupos = cursor.fetchall()
        conexao.close()
        return render_template('editar.html', produto=produto, grupos=grupos)


@app.route('/retirar', methods=['POST'])
def retirar_produto():
    if 'usuario_id' not in session:
        return redirect('/login')

    produto_ids = request.form.getlist('produto_id')
    quantidades = request.form.getlist('quantidade_retirada')
    solicitante = request.form['solicitante']
    codigo_protocolo = datetime.now().strftime("%Y%m%d%H%M%S")

    conexao = conectar_banco()
    cursor = conexao.cursor()

    # Valida estoque de todos os itens antes de registrar qualquer saída
    for i in range(len(produto_ids)):
        p_id = produto_ids[i]
        qtd = int(quantidades[i]) if quantidades[i] else 0
        if p_id and qtd > 0:
            cursor.execute('SELECT quantidade_atual, nome FROM Produtos WHERE id = %s', (p_id,))
            produto = cursor.fetchone()
            if produto and produto[0] < qtd:
                conexao.close()
                flash(f'Estoque insuficiente para "{produto[1]}". Disponível: {produto[0]}, solicitado: {qtd}.', 'erro')
                return redirect('/')

    for i in range(len(produto_ids)):
        p_id = produto_ids[i]
        qtd = int(quantidades[i]) if quantidades[i] else 0
        if p_id and qtd > 0:
            cursor.execute(
                'INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo) VALUES (%s, %s, %s, %s)',
                (p_id, qtd, solicitante, codigo_protocolo)
            )
            cursor.execute(
                'UPDATE Produtos SET quantidade_atual = quantidade_atual - %s WHERE id = %s',
                (qtd, p_id)
            )
    conexao.commit()
    conexao.close()
    return redirect('/')


# === ROTA DO HISTÓRICO SEPARADO ===
@app.route('/historico')
def historico_protocolos():
    if 'usuario_id' not in session:
        return redirect('/login')

    conexao = conectar_banco()
    cursor = conexao.cursor()
    
    cursor.execute('''
        SELECT 
            COALESCE(t.codigo_protocolo, CAST(t.id AS VARCHAR)), 
            TO_CHAR(t.data_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI:SS'),
            CASE 
                WHEN t.quantidade_retirada < 0 THEN p.nome
                WHEN t.produto_id IS NOT NULL THEN CONCAT(p.nome, ' (', COALESCE(p.unidade_medida, 'un'), ')')
                WHEN t.kit_id IS NOT NULL THEN CONCAT(k.nome, ' (Kit Montado)')
                ELSE 'Item Excluído ou Desconhecido'
            END as material,
            ABS(t.quantidade_retirada), 
            t.solicitante,
            t.id,
            CASE WHEN t.quantidade_retirada < 0 THEN 'ENTRADA' ELSE 'SAIDA' END as tipo
        FROM Transacoes t
        LEFT JOIN Produtos p ON t.produto_id = p.id
        LEFT JOIN Kits k ON t.kit_id = k.id
        ORDER BY t.data_hora DESC
    ''')
    transacoes_brutas = cursor.fetchall()
    conexao.close()

    protocolos_saida = {}
    protocolos_entrada = {}

    for linha in transacoes_brutas:
        codigo, data_hora, material, quantidade, solicitante, transacao_id, tipo = linha
        
        # Como as Entradas tinham o código padrão "ENTRADA", nós usamos o ID único para não agrupar todas juntas
        chave_agrupamento = codigo if tipo == 'SAIDA' else f"ENT_{transacao_id}"

        if tipo == 'SAIDA':
            if chave_agrupamento not in protocolos_saida:
                protocolos_saida[chave_agrupamento] = {
                    'codigo': codigo, 'data_hora': data_hora,
                    'solicitante': solicitante, 'itens': []
                }
            protocolos_saida[chave_agrupamento]['itens'].append({'material': material, 'quantidade': quantidade, 'id': transacao_id})
        else:
            if chave_agrupamento not in protocolos_entrada:
                protocolos_entrada[chave_agrupamento] = {
                    'codigo': transacao_id, # Mostra o ID do banco como Nº de Registro
                    'data_hora': data_hora,
                    'solicitante': solicitante, 'itens': []
                }
            protocolos_entrada[chave_agrupamento]['itens'].append({'material': material, 'quantidade': quantidade, 'id': transacao_id})
            
    return render_template(
        'historico.html', 
        saidas=list(protocolos_saida.values()), 
        entradas=list(protocolos_entrada.values())
    )


# === ROTA DO EXPORTAR EXCEL (AGORA COM COLUNA TIPO) ===
@app.route('/exportar')
def exportar_csv():
    if 'usuario_id' not in session:
        return redirect('/login')

    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute('''
        SELECT 
            COALESCE(t.codigo_protocolo, CAST(t.id AS VARCHAR)), 
            TO_CHAR(t.data_hora AT TIME ZONE 'UTC' AT TIME ZONE 'America/Sao_Paulo', 'DD/MM/YYYY HH24:MI:SS'),
            CASE WHEN t.quantidade_retirada < 0 THEN 'ENTRADA' ELSE 'SAIDA' END as tipo,
            CASE 
                WHEN t.quantidade_retirada < 0 THEN p.nome
                WHEN t.produto_id IS NOT NULL THEN CONCAT(p.nome, ' (', COALESCE(p.unidade_medida, 'un'), ')')
                WHEN t.kit_id IS NOT NULL THEN CONCAT(k.nome, ' (Kit Montado)')
                ELSE 'Item Excluído ou Desconhecido'
            END,
            ABS(t.quantidade_retirada), 
            t.solicitante
        FROM Transacoes t
        LEFT JOIN Produtos p ON t.produto_id = p.id
        LEFT JOIN Kits k ON t.kit_id = k.id
        ORDER BY t.data_hora DESC
    ''')
    transacoes = cursor.fetchall()
    conexao.close()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Nº Registro/Protocolo', 'Data e Hora', 'Tipo da Movimentacao', 'Material', 'Quantidade', 'Solicitante / Fornecedor'])
    for t in transacoes:
        writer.writerow(t)
        
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers["Content-Disposition"] = "attachment; filename=historico_almoxarifado.csv"
    return response
    
@app.route('/kits')
def gerenciar_kits():
    if 'usuario_id' not in session:
        return redirect('/login')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    # 1. Busca todos os kits
    cursor.execute("SELECT id, nome, quantidade_atual FROM Kits ORDER BY nome")
    lista_kits_bruta = cursor.fetchall()

    # 2. Busca os ingredientes de TODOS os kits de uma vez (Evita sobrecarregar o banco)
    cursor.execute('''
        SELECT ki.kit_id, p.nome, ki.quantidade_necessaria, COALESCE(p.unidade_medida, 'un')
        FROM Kit_Itens ki
        JOIN Produtos p ON ki.produto_id = p.id
    ''')
    composicao_bruta = cursor.fetchall()

    # 3. Monta um "pacote" organizado juntando o kit com os seus itens
    lista_kits = []
    for kit in lista_kits_bruta:
        itens_deste_kit = [
            {'nome': comp[1], 'quantidade': comp[2], 'unidade': comp[3]}
            for comp in composicao_bruta if comp[0] == kit[0]
        ]
        lista_kits.append({
            'id': kit[0],
            'nome': kit[1],
            'quantidade_atual': kit[2],
            'itens': itens_deste_kit
        })

    cursor.execute("SELECT id, nome FROM Produtos ORDER BY nome")
    lista_produtos = cursor.fetchall()
    conexao.close()

    # Agora enviamos a lista montada e rica em detalhes para o HTML
    return render_template('kits.html', kits=lista_kits, produtos=lista_produtos)


@app.route('/criar_kit', methods=['POST'])
def criar_kit():
    if 'usuario_id' not in session:
        return redirect('/login')
        
    nome_kit = request.form['nome_kit']
    # O getlist pega todos os produtos e quantidades enviados na mesma tela
    produtos_ids = request.form.getlist('produto_id[]')
    quantidades = request.form.getlist('quantidade[]')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    try:
        # Cria o kit e já "pega" o ID gerado pelo PostgreSQL na mesma hora
        cursor.execute("INSERT INTO Kits (nome, quantidade_atual) VALUES (%s, 0) RETURNING id", (nome_kit,))
        kit_id = cursor.fetchone()[0]

        # Faz um laço de repetição para inserir todos os ingredientes do kit de uma vez
        for i in range(len(produtos_ids)):
            p_id = produtos_ids[i]
            qtd = quantidades[i]
            if p_id and qtd and int(qtd) > 0:
                cursor.execute(
                    "INSERT INTO Kit_Itens (kit_id, produto_id, quantidade_necessaria) VALUES (%s, %s, %s)",
                    (kit_id, p_id, qtd)
                )
        conexao.commit()
    except Exception as e:
        conexao.rollback()
    finally:
        conexao.close()

    return redirect('/kits')


@app.route('/adicionar_item_kit', methods=['POST'])
def adicionar_item_kit():
    if 'usuario_id' not in session:
        return redirect('/login')
    kit_id = request.form['kit_id']
    produto_id = request.form['produto_id']
    quantidade = request.form['quantidade']
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute(
        "INSERT INTO Kit_Itens (kit_id, produto_id, quantidade_necessaria) VALUES (%s, %s, %s)",
        (kit_id, produto_id, quantidade)
    )
    conexao.commit()
    conexao.close()
    return redirect('/kits')


@app.route('/montar_kit', methods=['POST'])
def montar_kit():
    if 'usuario_id' not in session:
        return redirect('/login')
    kit_id = request.form['kit_id']
    qtd_montar = int(request.form['quantidade'])
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("SELECT produto_id, quantidade_necessaria FROM Kit_Itens WHERE kit_id = %s", (kit_id,))
    itens = cursor.fetchall()

    # Valida estoque de todos os componentes antes de montar
    for item in itens:
        cursor.execute('SELECT quantidade_atual, nome FROM Produtos WHERE id = %s', (item[0],))
        produto = cursor.fetchone()
        necessario = item[1] * qtd_montar
        if produto and produto[0] < necessario:
            conexao.close()
            flash(
                f'Estoque insuficiente para montar {qtd_montar} kit(s). '
                f'"{produto[1]}" tem {produto[0]}, precisa de {necessario}.',
                'erro'
            )
            return redirect('/kits')

    for item in itens:
        cursor.execute(
            'UPDATE Produtos SET quantidade_atual = quantidade_atual - %s WHERE id = %s',
            (item[1] * qtd_montar, item[0])
        )
    cursor.execute(
        'UPDATE Kits SET quantidade_atual = quantidade_atual + %s WHERE id = %s',
        (qtd_montar, kit_id)
    )
    conexao.commit()
    conexao.close()
    return redirect('/kits')


# === CORREÇÃO DA ROTA DE RETIRADA DE KIT (Redirecionar para /kits ao invés de /historico) ===
@app.route('/retirar_kit', methods=['POST'])
def retirar_kit():
    if 'usuario_id' not in session:
        return redirect('/login')
    kit_id = request.form['kit_id']
    qtd_retirar = int(request.form['quantidade'])
    solicitante = request.form['solicitante']
    codigo_protocolo = datetime.now().strftime("%Y%m%d%H%M%S")
    
    conexao = conectar_banco()
    cursor = conexao.cursor()

    # Valida estoque de kits antes de retirar
    cursor.execute('SELECT quantidade_atual FROM Kits WHERE id = %s', (kit_id,))
    kit = cursor.fetchone()
    if kit and kit[0] < qtd_retirar:
        conexao.close()
        flash(f'Quantidade de kits insuficiente. Disponível: {kit[0]}.', 'erro')
        return redirect('/kits')

    cursor.execute(
        'UPDATE Kits SET quantidade_atual = quantidade_atual - %s WHERE id = %s',
        (qtd_retirar, kit_id)
    )
    cursor.execute(
        'INSERT INTO Transacoes (kit_id, quantidade_retirada, solicitante, codigo_protocolo) VALUES (%s, %s, %s, %s)',
        (kit_id, qtd_retirar, solicitante, codigo_protocolo)
    )
    conexao.commit()
    conexao.close()
    
    # CORREÇÃO AQUI: Agora retorna para a própria página de kits com mensagem de sucesso
    flash('Retirada de kit registrada com sucesso!', 'sucesso')
    return redirect('/kits')


# === NOVA ROTA: EXCLUIR KIT (APENAS ADMIN) ===
@app.route('/excluir_kit/<int:id>')
def excluir_kit(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        flash('Acesso negado. Apenas administradores podem excluir kits.', 'erro')
        return redirect('/kits')

    conexao = conectar_banco()
    cursor = conexao.cursor()
    try:
        # Primeiro removemos as dependências da receita do kit para não quebrar a chave estrangeira
        cursor.execute("DELETE FROM Kit_Itens WHERE kit_id = %s", (id,))
        # Depois apagamos o kit
        cursor.execute("DELETE FROM Kits WHERE id = %s", (id,))
        conexao.commit()
        flash('Kit e sua receita foram excluídos permanentemente.', 'sucesso')
    except Exception:
        conexao.rollback()
        flash('Erro ao tentar excluir o kit.', 'erro')
    finally:
        conexao.close()
        
    return redirect('/kits')

# === NOVA ROTA: EDITAR KIT (APENAS ADMIN) ===
@app.route('/editar_kit/<int:id>', methods=['GET', 'POST'])
def editar_kit(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    
    # Trava de segurança para Admin
    if session.get('usuario_nivel') != 'admin':
        flash('Acesso negado. Apenas administradores podem editar kits.', 'erro')
        return redirect('/kits')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    if request.method == 'POST':
        nome_kit = request.form['nome_kit']
        produtos_ids = request.form.getlist('produto_id[]')
        quantidades = request.form.getlist('quantidade[]')

        try:
            # 1. Atualiza o nome do kit
            cursor.execute("UPDATE Kits SET nome = %s WHERE id = %s", (nome_kit, id))
            
            # 2. Deleta a receita antiga por completo
            cursor.execute("DELETE FROM Kit_Itens WHERE kit_id = %s", (id,))
            
            # 3. Insere a nova receita atualizada
            for i in range(len(produtos_ids)):
                p_id = produtos_ids[i]
                qtd = quantidades[i]
                if p_id and qtd and int(qtd) > 0:
                    cursor.execute(
                        "INSERT INTO Kit_Itens (kit_id, produto_id, quantidade_necessaria) VALUES (%s, %s, %s)",
                        (id, p_id, qtd)
                    )
            conexao.commit()
            flash('Kit atualizado com sucesso!', 'sucesso')
        except Exception:
            conexao.rollback()
            flash('Erro ao tentar atualizar o kit.', 'erro')
        finally:
            conexao.close()
            
        return redirect('/kits')

    else: # Quando a página carrega no método GET
        # Pega os dados básicos do kit
        cursor.execute("SELECT id, nome FROM Kits WHERE id = %s", (id,))
        kit_atual = cursor.fetchone()

        # Pega a receita atual para preencher os campos
        cursor.execute("SELECT produto_id, quantidade_necessaria FROM Kit_Itens WHERE kit_id = %s", (id,))
        itens_atuais = cursor.fetchall()

        # Pega todos os produtos para a lista de opções
        cursor.execute("SELECT id, nome FROM Produtos ORDER BY nome")
        todos_produtos = cursor.fetchall()
        conexao.close()

        return render_template('editar_kit.html', kit=kit_atual, itens_atuais=itens_atuais, produtos=todos_produtos)

# === NOVA ROTA: APAGAR REGISTRO DE TRANSAÇÃO/HISTÓRICO (APENAS ADMIN) ===
@app.route('/excluir_transacao/<int:id>')
def excluir_transacao(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso negado.", 403

    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("DELETE FROM Transacoes WHERE id = %s", (id,))
    conexao.commit()
    conexao.close()
    
    flash('Registro de movimentação apagado do histórico.', 'sucesso')
    return redirect('/historico')


@app.route('/gerenciar_grupos', methods=['GET', 'POST'])
def gerenciar_grupos():
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso restrito.", 403

    conexao = conectar_banco()
    cursor = conexao.cursor()
    if request.method == 'POST':
        nome_grupo = request.form['nome_grupo']
        try:
            cursor.execute("INSERT INTO Grupos (nome) VALUES (%s)", (nome_grupo,))
            conexao.commit()
        except Exception:
            conexao.rollback()
        conexao.close()
        return redirect('/gerenciar_grupos')
    cursor.execute("SELECT * FROM Grupos ORDER BY nome")
    lista_grupos = cursor.fetchall()
    conexao.close()
    return render_template('grupos.html', grupos=lista_grupos)


@app.route('/excluir_grupo/<int:id>')
def excluir_grupo(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso restrito.", 403
    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("UPDATE Produtos SET grupo_id = NULL WHERE grupo_id = %s", (id,))
    cursor.execute("DELETE FROM Grupos WHERE id = %s", (id,))
    conexao.commit()
    conexao.close()
    return redirect('/gerenciar_grupos')


# === DASHBOARD FINANCEIRO (APENAS ADMIN) ===
@app.route('/financeiro')
def dashboard_financeiro():
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso negado. Você não tem permissão para visualizar o Dashboard Financeiro.", 403

    conexao = conectar_banco()
    cursor = conexao.cursor()

    cursor.execute("SELECT SUM(quantidade_atual * preco_unitario) FROM Produtos")
    patrimonio_total = cursor.fetchone()[0] or 0.0

    cursor.execute('''
        SELECT COALESCE(g.nome, 'Sem Grupo') as grupo,
               SUM(p.quantidade_atual * p.preco_unitario) as total
        FROM Produtos p
        LEFT JOIN Grupos g ON p.grupo_id = g.id
        GROUP BY p.grupo_id, g.nome
        ORDER BY total DESC
    ''')
    categorias_bruto = cursor.fetchall()
    valores_categoria = [{'grupo': c[0], 'total': c[1] if c[1] else 0.0} for c in categorias_bruto]

    periodo = request.args.get('periodo', '30')
    cursor.execute('''
        SELECT COALESCE(g.nome, 'Sem Grupo') as grupo,
               SUM(t.quantidade_retirada * p.preco_unitario) as total_movimentado
        FROM Transacoes t
        JOIN Produtos p ON t.produto_id = p.id
        LEFT JOIN Grupos g ON p.grupo_id = g.id
        WHERE t.data_hora >= NOW() - (%s || ' days')::interval
        GROUP BY p.grupo_id, g.nome
        ORDER BY total_movimentado DESC
    ''', (periodo,))
    dados_grafico = cursor.fetchall()
    conexao.close()

    graf_labels = [item[0] for item in dados_grafico]
    graf_valores = [item[1] if item[1] else 0.0 for item in dados_grafico]

    return render_template(
        'financeiro.html',
        patrimonio_total=patrimonio_total,
        valores_categoria=valores_categoria,
        graf_labels=graf_labels,
        graf_valores=graf_valores,
        periodo_atual=periodo
    )


# === GERENCIAMENTO DE USUÁRIOS (APENAS ADMIN) ===
@app.route('/gerenciar_usuarios', methods=['GET', 'POST'])
def gerenciar_usuarios():
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso restrito.", 403

    conexao = conectar_banco()
    cursor = conexao.cursor()

    if request.method == 'POST':
        novo_usuario = request.form['usuario']
        nova_senha = request.form['senha']
        nivel = request.form['nivel']
        senha_hash = generate_password_hash(nova_senha)
        try:
            cursor.execute(
                "INSERT INTO Usuarios (usuario, senha, nivel) VALUES (%s, %s, %s)",
                (novo_usuario, senha_hash, nivel)
            )
            conexao.commit()
        except Exception:
            conexao.rollback()
        conexao.close()
        return redirect('/gerenciar_usuarios')

    cursor.execute("SELECT id, usuario, nivel FROM Usuarios ORDER BY usuario")
    lista_usuarios = cursor.fetchall()
    conexao.close()
    return render_template('usuarios.html', usuarios=lista_usuarios)


@app.route('/excluir_usuario/<int:id>')
def excluir_usuario(id):
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso restrito.", 403

    if id == session.get('usuario_id'):
        return "Você não pode excluir seu próprio usuário logado.", 400

    conexao = conectar_banco()
    cursor = conexao.cursor()
    cursor.execute("DELETE FROM Usuarios WHERE id = %s", (id,))
    conexao.commit()
    conexao.close()
    return redirect('/gerenciar_usuarios')


if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')
