import os
from flask import Flask, render_template, request, redirect, Response, session, flash
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf.csrf import CSRFProtect
from datetime import datetime
import csv
import io
from dotenv import load_dotenv
from io import StringIO

# (mantenha os outros imports que você já tem, como render_template, request, etc)

load_dotenv(encoding='latin-1')

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'chave-dev-nao-usar-em-producao')
csrf = CSRFProtect(app)


def conectar_banco():
    return psycopg2.connect(os.environ.get('DATABASE_URL'))

@app.route('/exportar_estoque')
def exportar_estoque():
    try:
        from flask import make_response
        import traceback # O nosso "espião" de erros

        if 'usuario_id' not in session:
            return redirect('/login')

        conexao = conectar_banco()
        cursor = conexao.cursor()

        cursor.execute('''
            SELECT p.id, p.nome, p.quantidade_atual, p.estoque_minimo, 
                   p.estoque_maximo, p.ponto_pedido, p.unidade_medida, 
                   g.nome, p.grupo_id, p.preco_unitario, p.estoque_separado 
            FROM Produtos p 
            LEFT JOIN Grupos g ON p.grupo_id = g.id 
            ORDER BY p.estoque_separado DESC, p.nome
        ''')
        produtos = cursor.fetchall()
        conexao.close()

        linhas = []
        linhas.append("ID;Tipo de Estoque;Grupo;Equipamento/Material;Qtd Atual;Unidade;Valor Unitario (R$);Total em Estoque (R$)")

        for p in produtos:
            id_prod = p[0]
            nome = str(p[1])
            qtd = float(p[2] or 0)
            unidade = str(p[6]) if p[6] else "UN"
            grupo = str(p[7]) if p[7] else "Sem Grupo"
            valor_uni = float(p[9] or 0)
            es_separado = p[10]

            tipo = "Módulos/Inversores" if es_separado else "Almoxarifado Geral"
            total = qtd * valor_uni

            qtd_str = str(qtd).replace('.', ',')
            valor_uni_str = f"{valor_uni:.2f}".replace('.', ',')
            total_str = f"{total:.2f}".replace('.', ',')

            linha = f"{id_prod};{tipo};{grupo};{nome};{qtd_str};{unidade};{valor_uni_str};{total_str}"
            linhas.append(linha)

        texto_csv = "\n".join(linhas)

        response = make_response(texto_csv.encode('utf-8-sig'))
        response.headers['Content-Type'] = 'text/csv; charset=utf-8-sig'
        response.headers['Content-Disposition'] = 'attachment; filename=Relatorio_Estoque_Virtron.csv'
        return response

    except Exception as e:
        # SE DER ERRO, VAI MOSTRAR NA TELA DO NAVEGADOR!
        erro_completo = traceback.format_exc()
        return f"<h1>Opa! O Python encontrou este erro:</h1><pre style='background:#f4f4f4; padding:20px; border-left:5px solid red;'>{erro_completo}</pre>"


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
def index():
    if 'usuario_id' not in session:
        return redirect('/login')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    # 1. Pega os GRUPOS reais para o formulário de cadastro
    cursor.execute("SELECT id, nome FROM Grupos ORDER BY nome")
    grupos = cursor.fetchall()

    # 2. Pega apenas os PRODUTOS COMUNS (sem WMS) para o formulário de retirada
    cursor.execute("SELECT id, nome FROM Produtos WHERE estoque_separado = FALSE OR estoque_separado IS NULL ORDER BY nome")
    produtos_para_retirada = cursor.fetchall()

    pesquisa_atual = request.args.get('pesquisa', '')
    grupo_atual = request.args.get('grupo_filtro', '')

    query = '''
        SELECT p.id, p.nome, p.quantidade_atual, p.estoque_minimo, 
               p.estoque_maximo, p.ponto_pedido, p.unidade_medida, 
               g.nome, p.grupo_id, p.preco_unitario, p.estoque_separado 
        FROM Produtos p 
        LEFT JOIN Grupos g ON p.grupo_id = g.id 
        WHERE 1=1
    '''
    params = []

    if pesquisa_atual:
        query += " AND p.nome ILIKE %s"
        params.append(f"%{pesquisa_atual}%")
    if grupo_atual:
        query += " AND p.grupo_id = %s"
        params.append(grupo_atual)

    query += " ORDER BY p.nome"
    
    cursor.execute(query, params)
    produtos_brutos = cursor.fetchall()
    conexao.close()

    produtos_gerais = []
    produtos_separados = []
    alertas = []

    for p in produtos_brutos:
        # p[10] é a coluna estoque_separado
        if p[10]: 
            produtos_separados.append(p)
        else:
            produtos_gerais.append(p)
            
            # BLOQUEIO DO GRUPO TECH: Não entra no cálculo de alertas de compra
            nome_grupo = p[7]
            if nome_grupo == 'TECH':
                continue # Pula para o próximo produto sem gerar alerta
                
            # ALERTA RODA APENAS PARA O ESTOQUE GERAL (e que não seja TECH)
            try:
                def pega_numero(valor):
                    if valor is None or str(valor).strip() == '': return 0.0
                    return float(valor)

                qtd_atual = pega_numero(p[2])
                estoque_min = pega_numero(p[3])
                estoque_max = pega_numero(p[4])
                ponto_pedido = pega_numero(p[5])
                
                gatilho = ponto_pedido if ponto_pedido > 0 else estoque_min
                
                if qtd_atual <= gatilho:
                    sugestao = estoque_max - qtd_atual if estoque_max > qtd_atual else 1
                    alertas.append({
                        'nome': str(p[1]),
                        'atual': int(qtd_atual) if qtd_atual.is_integer() else qtd_atual,
                        'ponto': int(gatilho) if gatilho.is_integer() else gatilho,
                        'sugestao': int(sugestao) if sugestao.is_integer() else sugestao,
                        'unidade': str(p[6]) if p[6] else 'un'
                    })
            except Exception as e:
                print(f"Erro ao gerar alerta: {e}")
                continue

    return render_template('index.html', 
                           produtos=produtos_gerais, 
                           produtos_para_retirada=produtos_para_retirada, # <-- Adicionado aqui
                           produtos_separados=produtos_separados,
                           grupos=grupos, # Agora enviando os grupos corretos!
                           alertas=alertas, 
                           pesquisa_atual=pesquisa_atual, 
                           grupo_atual=grupo_atual)
                           
@app.route('/adicionar', methods=['POST'])
def adicionar_produto():
    if 'usuario_id' not in session:
        return redirect('/login')
        
    if session.get('usuario_nivel') != 'admin':
        flash('Acesso negado. Apenas administradores podem cadastrar itens.', 'erro')
        return redirect('/')

   # Captura os dados normais
    nome = request.form['nome']
    grupo_id = request.form.get('grupo_id')
    unidade = request.form['unidade']
    quantidade = request.form['quantidade']
    preco_unitario = request.form['preco_unitario']
    
    # TRATAMENTO PARA CAMPOS VAZIOS (EVITA ERRO DE INTEIRO NO BANCO)
    minimo = request.form.get('minimo')
    minimo = int(minimo) if minimo and minimo.strip() != "" else 0

    maximo = request.form.get('maximo')
    maximo = int(maximo) if maximo and maximo.strip() != "" else 0

    ponto = request.form.get('ponto')
    ponto = int(ponto) if ponto and ponto.strip() != "" else 0
    
    estoque_separado = True if request.form.get('estoque_separado') else False

    conexao = conectar_banco()
    cursor = conexao.cursor()

    cursor.execute("SELECT id FROM Produtos WHERE LOWER(nome) = LOWER(%s)", (nome,))
    if cursor.fetchone():
        conexao.close()
        flash(f'Bloqueado: Já existe um material cadastrado com o nome "{nome}".', 'erro')
        return redirect('/')

    try:
        cursor.execute('''
            INSERT INTO Produtos (nome, grupo_id, unidade_medida, quantidade_atual, preco_unitario, estoque_minimo, estoque_maximo, ponto_pedido, estoque_separado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (nome, grupo_id, unidade, quantidade, preco_unitario, minimo, maximo, ponto, estoque_separado))
        conexao.commit()
        flash(f'Material "{nome}" cadastrado com sucesso!', 'sucesso')
    except Exception as e:
        conexao.rollback()
        flash(f'Erro ao cadastrar material: {e}', 'erro')
    finally:
        conexao.close()

    return redirect('/')


from datetime import datetime # Certifique-se de que isso está no topo do seu app.py, junto com os outros imports

@app.route('/adicionar_estoque', methods=['POST'])
def adicionar_estoque():
    if 'usuario_id' not in session:
        return redirect('/login')

    if session.get('usuario_nivel') != 'admin':
        flash('Acesso negado. Apenas administradores podem registrar entrada.', 'erro')
        return redirect('/')

    # Recebe as listas de múltiplos itens enviados pelo formulário
    produto_ids = request.form.getlist('produto_id_entrada')
    quantidades = request.form.getlist('quantidade_entrada')
    precos = request.form.getlist('preco_unitario_entrada')

    if not produto_ids:
        flash('Nenhum material foi selecionado.', 'erro')
        return redirect('/')

    # GERA O PROTOCOLO DE ENTRADA (Faltava isso!)
    codigo_protocolo = datetime.now().strftime("ENT-%Y%m%d%H%M%S")

    conexao = conectar_banco()
    cursor = conexao.cursor()

    try:
        # Percorre a lista item por item
        for i in range(len(produto_ids)):
            p_id = produto_ids[i]
            
            # Pula a linha se o usuário adicionou um campo a mais mas deixou vazio
            if not p_id or not quantidades[i] or not precos[i]:
                continue

            qtd = float(quantidades[i])
            preco = float(precos[i])

            # 1. Atualiza o produto com o novo saldo e o preço mais recente
            cursor.execute('''
                UPDATE Produtos 
                SET quantidade_atual = quantidade_atual + %s, preco_unitario = %s
                WHERE id = %s
            ''', (qtd, preco, p_id))

            # 2. Grava no histórico de transações (Entrada)
            # CORREÇÃO: Variáveis ajustadas para p_id e qtd
            cursor.execute('''
                INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id)
                VALUES (%s, %s, %s, %s, %s)
            ''', (p_id, -qtd, "Entrada/Reposição", codigo_protocolo, session['usuario_id']))
            
        conexao.commit()
        flash('Entrada múltipla de materiais registrada com sucesso!', 'sucesso')

    except Exception as e:
        conexao.rollback()
        flash(f'Erro ao registrar entrada: {e}', 'erro')
        print(f"ERRO CRÍTICO NA ENTRADA MÚLTIPLA: {e}")
    finally:
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

    if request.method == 'GET':
        # Busca os dados atuais do produto para preencher a tela
        cursor.execute('''
            SELECT id, nome, grupo_id, unidade_medida, quantidade_atual, 
                   preco_unitario, estoque_minimo, estoque_maximo, ponto_pedido, estoque_separado 
            FROM Produtos WHERE id = %s
        ''', (id,))
        produto = cursor.fetchone()
        
        cursor.execute("SELECT id, nome FROM Grupos ORDER BY nome")
        grupos = cursor.fetchall()
        conexao.close()

        if not produto:
            flash('Produto não encontrado.', 'erro')
            return redirect('/')

        return render_template('editar.html', produto=produto, grupos=grupos)

    if request.method == 'POST':
        try:
            # Captura os dados básicos
            nome = request.form['nome']
            grupo_id = request.form.get('grupo_id')
            unidade = request.form['unidade']
            quantidade = request.form['quantidade']
            preco_unitario = request.form['preco_unitario']

            # 🛡️ BLINDAGEM MATEMÁTICA: Se o campo vier vazio (oculto), vira 0 automaticamente
            minimo = request.form.get('minimo')
            minimo = int(minimo) if minimo and str(minimo).strip() != "" else 0

            maximo = request.form.get('maximo')
            maximo = int(maximo) if maximo and str(maximo).strip() != "" else 0

            ponto = request.form.get('ponto')
            ponto = int(ponto) if ponto and str(ponto).strip() != "" else 0

            # Salva no banco de dados
            cursor.execute('''
                UPDATE Produtos 
                SET nome = %s, grupo_id = %s, unidade_medida = %s, 
                    quantidade_atual = %s, preco_unitario = %s, 
                    estoque_minimo = %s, estoque_maximo = %s, ponto_pedido = %s
                WHERE id = %s
            ''', (nome, grupo_id, unidade, quantidade, preco_unitario, minimo, maximo, ponto, id))
            
            conexao.commit()
            flash(f'Material "{nome}" atualizado com sucesso!', 'sucesso')
            
        except Exception as e:
            conexao.rollback()
            flash(f'Erro ao atualizar material: {e}', 'erro')
            print(f"ERRO CRÍTICO NA EDIÇÃO: {e}") # Ajuda a rastrear no console do servidor
        finally:
            conexao.close()

        return redirect('/')

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

    try:
        # 1. PASSO DE VALIDAÇÃO: Testa estoque e blinda Módulos/Inversores antes de mexer em qualquer saldo
        for i in range(len(produto_ids)):
            p_id = produto_ids[i]
            qtd = int(quantidades[i]) if quantidades[i] else 0
            
            if p_id and qtd > 0:
                # Buscamos a quantidade, o nome E a coluna estoque_separado
                cursor.execute('SELECT quantidade_atual, nome, estoque_separado FROM Produtos WHERE id = %s', (p_id,))
                produto = cursor.fetchone()
                
                if produto:
                    qtd_disponivel = produto[0]
                    nome_produto = produto[1]
                    eh_do_wms = produto[2] # Posição 2 da lista (estoque_separado)

                    # TRAVA DO WMS: Se for módulo ou inversor (True), bloqueia na hora!
                    if eh_do_wms == True:
                        conexao.close()
                        flash(f'Acesso Negado! O item "{nome_produto}" pertence ao WMS e só pode ser retirado pelo painel de Logística.', 'erro')
                        return redirect('/')

                    # VALIDAÇÃO DE SALDO: Se tentar retirar mais do que tem na prateleira
                    if qtd_disponivel < qtd:
                        conexao.close()
                        flash(f'Estoque insuficiente para "{nome_produto}". Disponível: {qtd_disponivel}, solicitado: {qtd}.', 'erro')
                        return redirect('/')

        # 2. PASSO DE EXECUÇÃO: Se nenhum item falhou nas regras acima, o sistema roda os updates com segurança
        for i in range(len(produto_ids)):
            p_id = produto_ids[i]
            qtd = int(quantidades[i]) if quantidades[i] else 0
            
            if p_id and qtd > 0:
                # Grava no histórico de transações
                cursor.execute('''
                    INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id) 
                    VALUES (%s, %s, %s, %s, %s)
                ''', (p_id, qtd, solicitante, codigo_protocolo, session['usuario_id']))
                
                # Desconta o saldo da prateleira do almoxarifado
                cursor.execute('''
                    UPDATE Produtos 
                    SET quantidade_atual = quantidade_atual - %s 
                    WHERE id = %s
                ''', (qtd, p_id))

        conexao.commit()
        flash('Retirada de materiais registrada com sucesso!', 'sucesso')

    except Exception as e:
        conexao.rollback()
        flash(f'Erro inesperado ao processar retirada: {e}', 'erro')
    finally:
        conexao.close()
        
    return redirect('/')

@app.route('/inventario', methods=['GET', 'POST'])
def inventario():
    if 'usuario_id' not in session:
        return redirect('/login')
        
    # Trava de Segurança: Apenas Admin, Operador comum e Operador Logístico podem acessar
    nivel = session.get('usuario_nivel')
    if nivel not in ['admin', 'operador', 'operador logistico']:
        flash('Acesso negado para o seu nível de usuário.', 'erro')
        return redirect('/')
        
    conexao = conectar_banco()
    cursor = conexao.cursor()
    
    if request.method == 'POST':
        produto_id = request.form['produto_id']
        nova_quantidade = float(request.form['quantidade'])
        codigo_protocolo = datetime.now().strftime("INV-%Y%m%d%H%M%S")
        
        try:
            # 1. Busca a quantidade antiga para calcular a diferença pro histórico
            cursor.execute("SELECT quantidade_atual, nome FROM Produtos WHERE id = %s", (produto_id,))
            produto = cursor.fetchone()
            
            if produto:
                qtd_antiga = produto[0]
                nome_produto = produto[1]
                
                # Calcula a diferença matemática para o histórico de transações
                # No seu sistema: saídas/perdas são positivas, entradas/sobras são negativas.
                diferenca = qtd_antiga - nova_quantidade
                
                # 2. Atualiza APENAS a quantidade na prateleira com o valor exato do inventário
                cursor.execute("UPDATE Produtos SET quantidade_atual = %s WHERE id = %s", (nova_quantidade, produto_id))
                
                # 3. Registra o ajuste no histórico geral para auditoria futura
                cursor.execute('''
                    INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (produto_id, diferenca, f"Ajuste de Inventário (De {qtd_antiga} para {nova_quantidade})", codigo_protocolo, session['usuario_id']))
                
                conexao.commit()
                flash(f'Inventário de "{nome_produto}" atualizado para {nova_quantidade} com sucesso!', 'sucesso')
            else:
                flash('Produto não encontrado.', 'erro')
                
        except Exception as e:
            conexao.rollback()
            flash(f'Erro ao salvar inventário: {e}', 'erro')
        finally:
            conexao.close()
            
        return redirect('/inventario')
        
    else:
        # Método GET: Carrega todos os produtos para preencher a caixinha de seleção
        cursor.execute("SELECT id, nome, quantidade_atual, COALESCE(unidade_medida, 'un') FROM Produtos ORDER BY nome")
        produtos = cursor.fetchall()
        conexao.close()
        
        return render_template('inventario.html', produtos=produtos)

# ========================================================
#   PARTE 2: MOTOR DO KANBAN DE LOGÍSTICA (MÓDULOS/INVERSORES)
# ========================================================

@app.route('/logistica')
def painel_logistica():
    if 'usuario_id' not in session:
        return redirect('/login')

# BLINDAGEM DE ACESSO: Só admin e operador logístico passam
    if session.get('usuario_nivel') not in ['admin', 'operador logistico']:
        flash('Acesso negado. Esta área é restrita à equipe de Logística.', 'erro')
        return redirect('/')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    # 1. Busca todos os pedidos e seus respectivos itens em um único cruzamento (JOIN)
    cursor.execute('''
        SELECT p.id, p.numero_pedido, p.cliente, p.status,
               pr.nome, ip.quantidade, pr.unidade_medida
        FROM Pedidos p
        LEFT JOIN Itens_Pedido ip ON p.id = ip.pedido_id
        LEFT JOIN Produtos pr ON ip.produto_id = pr.id
        ORDER BY p.data_criacao ASC
    ''')
    dados = cursor.fetchall()

    # Organiza os dados brutos do banco em um dicionário estruturado para o HTML
    pedidos = {}
    for linha in dados:
        p_id = linha[0]
        if p_id not in pedidos:
            pedidos[p_id] = {
                'id': p_id,
                'numero_pedido': linha[1],
                'cliente': linha[2],
                'status': linha[3],
                'itens': []
            }
        # Se o pedido tiver itens cadastrados, adiciona na lista interna dele
        if linha[4]: 
            pedidos[p_id]['itens'].append({
                'nome': linha[4],
                'quantidade': linha[5],
                'unidade': linha[6] or 'un'
            })

    # Separa os pedidos em 3 listas com base no status atual do Kanban
    separados = [p for p in pedidos.values() if p['status'] == 'SEPARADO']
    em_rota = [p for p in pedidos.values() if p['status'] == 'EM ROTA']
    entregues = [p for p in pedidos.values() if p['status'] == 'ENTREGUE']

    # 2. Busca apenas Módulos e Inversores disponíveis para o formulário de novos pedidos
    cursor.execute('''
        SELECT id, nome, quantidade_atual 
        FROM Produtos 
        WHERE estoque_separado = TRUE 
        ORDER BY nome
    ''')
    produtos_separados = cursor.fetchall()
    conexao.close()

    return render_template('logistica.html', 
                           separados=separados, 
                           em_rota=em_rota, 
                           entregues=entregues, 
                           produtos_separados=produtos_separados)


@app.route('/logistica/novo_pedido', methods=['POST'])
def novo_pedido():
    if 'usuario_id' not in session:
        return redirect('/login')

# BLINDAGEM DE ACESSO: Só admin e operador logístico passam
    if session.get('usuario_nivel') not in ['admin', 'operador logistico']:
        flash('Acesso negado. Esta área é restrita à equipe de Logística.', 'erro')
        return redirect('/')

    numero_pedido = request.form['numero_pedido'].strip()
    cliente = request.form['cliente'].strip()
    produto_ids = request.form.getlist('produto_id_item')
    quantidades = request.form.getlist('quantidade_item')

    if not numero_pedido or not cliente or not produto_ids:
        flash('Por favor, preencha todos os campos do pedido.', 'erro')
        return redirect('/logistica')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    try:
        # 1. VALIDAÇÃO DE SEGURANÇA: Confere o estoque de todas as linhas antes de mexer no banco
        for i in range(len(produto_ids)):
            p_id = produto_ids[i]
            qtd = int(quantidades[i]) if quantidades[i] else 0
            
            if p_id and qtd > 0:
                cursor.execute('SELECT quantidade_atual, nome FROM Produtos WHERE id = %s', (p_id,))
                prod = cursor.fetchone()
                if prod and prod[0] < qtd:
                    conexao.close()
                    flash(f'Estoque insuficiente para "{prod[1]}". Disponível: {prod[0]}, Solicitado: {qtd}.', 'erro')
                    return redirect('/logistica')

        # 2. CRIA A CAPA DO PEDIDO (Gera o card na coluna SEPARADO)
        cursor.execute('''
            INSERT INTO Pedidos (numero_pedido, cliente, status) 
            VALUES (%s, %s, 'SEPARADO') RETURNING id
        ''', (numero_pedido, cliente))
        pedido_id = cursor.fetchone()[0]

        # 3. INSERSÃO DOS ITENS, SUBTRAÇÃO DO ESTOQUE E LOG DE TRANSAÇÃO
        for i in range(len(produto_ids)):
            p_id = produto_ids[i]
            qtd = int(quantidades[i]) if quantidades[i] else 0
            
            if p_id and qtd > 0:
                # Vincula o material ao pedido
                cursor.execute('INSERT INTO Itens_Pedido (pedido_id, produto_id, quantidade) VALUES (%s, %s, %s)', (pedido_id, p_id, qtd))
                
                # MATEMÁTICA: Remove da prateleira geral (Reserva Imediata)
                cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual - %s WHERE id = %s', (qtd, p_id))
                
                # AUDITORIA: Grava no histórico geral quem realizou essa reserva/separação
                cursor.execute('''
                    INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (p_id, qtd, f"Reserva: {cliente}", numero_pedido, session['usuario_id']))

        conexao.commit()
        flash(f'Pedido Nº {numero_pedido} criado e materiais reservados com sucesso!', 'sucesso')

    except Exception as e:
        conexao.rollback()
        flash(f'Erro ao processar a separação do pedido: {e}', 'erro')
        print(f"ERRO CRÍTICO KANBAN: {e}")
    finally:
        conexao.close()

    return redirect('/logistica')

@app.route('/logistica/atualizar_status/<int:pedido_id>/<novo_status>')
def atualizar_status_pedido(pedido_id, novo_status):
    if 'usuario_id' not in session:
        return redirect('/login')

# BLINDAGEM DE ACESSO: Só admin e operador logístico passam
    if session.get('usuario_nivel') not in ['admin', 'operador logistico']:
        flash('Acesso negado. Esta área é restrita à equipe de Logística.', 'erro')
        return redirect('/')

    # Valida para evitar que digitem status inventados na URL
    if novo_status not in ['SEPARADO', 'EM ROTA', 'ENTREGUE']:
        return redirect('/logistica')

    conexao = conectar_banco()
    cursor = conexao.cursor()
    try:
        cursor.execute('UPDATE Pedidos SET status = %s WHERE id = %s', (novo_status, pedido_id))
        conexao.commit()
    except Exception as e:
        print(f"Erro ao mover card: {e}")
    finally:
        conexao.close()

    return redirect('/logistica')

@app.route('/logistica/editar/<int:pedido_id>', methods=['GET', 'POST'])
def editar_pedido(pedido_id):
    if 'usuario_id' not in session:
        return redirect('/login')

# BLINDAGEM DE ACESSO: Só admin e operador logístico passam
    if session.get('usuario_nivel') not in ['admin', 'operador logistico']:
        flash('Acesso negado. Esta área é restrita à equipe de Logística.', 'erro')
        return redirect('/')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    if request.method == 'GET':
        # 1. Busca a "capa" do pedido
        cursor.execute('SELECT id, numero_pedido, cliente, status FROM Pedidos WHERE id = %s', (pedido_id,))
        pedido = cursor.fetchone()

        # Proteção: Não deixa editar pedido que já foi entregue
        if not pedido or pedido[3] == 'ENTREGUE':
            conexao.close()
            flash('Não é possível editar pedidos já entregues.', 'erro')
            return redirect('/logistica')

        # 2. Busca os itens atuais do pedido
        cursor.execute('SELECT produto_id, quantidade FROM Itens_Pedido WHERE pedido_id = %s', (pedido_id,))
        itens_atuais = cursor.fetchall()

        # 3. Busca lista de Módulos/Inversores para o select
        cursor.execute('SELECT id, nome, quantidade_atual FROM Produtos WHERE estoque_separado = TRUE ORDER BY nome')
        produtos_separados = cursor.fetchall()
        conexao.close()

        return render_template('editar_pedido.html', pedido=pedido, itens_atuais=itens_atuais, produtos_separados=produtos_separados)

    if request.method == 'POST':
        try:
            novo_cliente = request.form['cliente'].strip()
            produto_ids = request.form.getlist('produto_id_item')
            quantidades = request.form.getlist('quantidade_item')

            cursor.execute('SELECT numero_pedido FROM Pedidos WHERE id = %s', (pedido_id,))
            numero_pedido = cursor.fetchone()[0]

            # 1. BUSCA O PEDIDO ANTIGO E FAZ O ESTORNO GERAL
            cursor.execute('SELECT produto_id, quantidade FROM Itens_Pedido WHERE pedido_id = %s', (pedido_id,))
            itens_antigos = cursor.fetchall()

            for item in itens_antigos:
                p_id_antigo = item[0]
                qtd_antiga = item[1]
                
                # Devolve para o saldo atual
                cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual + %s WHERE id = %s', (qtd_antiga, p_id_antigo))
                
                # Grava a devolução no histórico como uma Entrada (quantidade negativa = entrada no seu sistema)
                cursor.execute('''
                    INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id)
                    VALUES (%s, %s, %s, %s, %s)
                ''', (p_id_antigo, -qtd_antiga, f"Estorno (Edição Pedido {numero_pedido})", numero_pedido, session['usuario_id']))

            # 2. LIMPA OS ITENS ANTIGOS DA TABELA DE LIGAÇÃO
            cursor.execute('DELETE FROM Itens_Pedido WHERE pedido_id = %s', (pedido_id,))

            # 3. VALIDA E INSERE OS NOVOS ITENS
            for i in range(len(produto_ids)):
                p_id = produto_ids[i]
                qtd = int(quantidades[i]) if quantidades[i] else 0
                
                if p_id and qtd > 0:
                    # Checa se o novo saldo (já com o estorno) suporta a nova quantidade
                    cursor.execute('SELECT quantidade_atual, nome FROM Produtos WHERE id = %s', (p_id,))
                    prod = cursor.fetchone()
                    if prod and prod[0] < qtd:
                        # Se não suportar, cancela tudo! O estorno é desfeito e nada muda.
                        conexao.rollback()
                        conexao.close()
                        flash(f'Estoque insuficiente para "{prod[1]}". Disponível: {prod[0]}. A edição foi cancelada.', 'erro')
                        return redirect(f'/logistica/editar/{pedido_id}')

                    # Insere o novo item no pedido
                    cursor.execute('INSERT INTO Itens_Pedido (pedido_id, produto_id, quantidade) VALUES (%s, %s, %s)', (pedido_id, p_id, qtd))
                    
                    # Retira o estoque da prateleira
                    cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual - %s WHERE id = %s', (qtd, p_id))
                    
                    # Grava a nova saída no histórico
                    cursor.execute('''
                        INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id)
                        VALUES (%s, %s, %s, %s, %s)
                    ''', (p_id, qtd, f"Reserva Atualizada: {novo_cliente}", numero_pedido, session['usuario_id']))

            # 4. ATUALIZA A CAPA (Se mudou o nome do cliente)
            cursor.execute('UPDATE Pedidos SET cliente = %s WHERE id = %s', (novo_cliente, pedido_id))

            conexao.commit()
            flash(f'O Pedido Nº {numero_pedido} foi atualizado com sucesso!', 'sucesso')

        except Exception as e:
            conexao.rollback()
            flash(f'Erro ao editar pedido: {e}', 'erro')
        finally:
            conexao.close()

        return redirect('/logistica')

@app.route('/logistica/excluir/<int:pedido_id>')
def excluir_pedido(pedido_id):
    if 'usuario_id' not in session:
        return redirect('/login')

    # BLINDAGEM MÁXIMA: Apenas Administradores podem excluir
    if session.get('usuario_nivel') != 'admin':
        flash('Acesso negado. Apenas o Administrador pode excluir pedidos.', 'erro')
        return redirect('/logistica')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    try:
        # 1. Pega os dados do pedido para os logs
        cursor.execute('SELECT numero_pedido, cliente FROM Pedidos WHERE id = %s', (pedido_id,))
        pedido = cursor.fetchone()
        
        if not pedido:
            return redirect('/logistica')
            
        numero_pedido, cliente = pedido[0], pedido[1]

        # 2. Busca os itens reservados para fazer o estorno
        cursor.execute('SELECT produto_id, quantidade FROM Itens_Pedido WHERE pedido_id = %s', (pedido_id,))
        itens = cursor.fetchall()

        for item in itens:
            p_id, qtd = item[0], item[1]

            # Devolve o saldo para a prateleira
            cursor.execute('UPDATE Produtos SET quantidade_atual = quantidade_atual + %s WHERE id = %s', (qtd, p_id))

            # Grava a devolução no histórico geral (quantidade negativa no Excel = Entrada)
            cursor.execute('''
                INSERT INTO Transacoes (produto_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id)
                VALUES (%s, %s, %s, %s, %s)
            ''', (p_id, -qtd, f"Cancelamento/Exclusão WMS: {cliente}", numero_pedido, session['usuario_id']))

        # 3. Apaga os registros das tabelas do Kanban
        cursor.execute('DELETE FROM Itens_Pedido WHERE pedido_id = %s', (pedido_id,))
        cursor.execute('DELETE FROM Pedidos WHERE id = %s', (pedido_id,))

        conexao.commit()
        flash(f'O Pedido Nº {numero_pedido} foi excluído e os materiais voltaram ao estoque!', 'sucesso')

    except Exception as e:
        conexao.rollback()
        flash(f'Erro ao excluir o pedido: {e}', 'erro')
    finally:
        conexao.close()

    return redirect('/logistica')

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


# === ROTA DO EXPORTAR EXCEL (VERSÃO FINAL E CORRIGIDA) ===
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
            t.solicitante,
            COALESCE(u.usuario, 'Não Identificado') -- O SEGREDO ESTAVA AQUI!
        FROM Transacoes t
        LEFT JOIN Produtos p ON t.produto_id = p.id
        LEFT JOIN Kits k ON t.kit_id = k.id
        LEFT JOIN Usuarios u ON t.usuario_id = u.id
        ORDER BY t.data_hora DESC
    ''')
    transacoes = cursor.fetchall()
    conexao.close()
    
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow(['Nº Registro/Protocolo', 'Data e Hora', 'Tipo da Movimentacao', 'Material', 'Quantidade', 'Solicitante / Fornecedor', 'Usuário Responsável'])
    
    for t in transacoes:
        writer.writerow(t)
        
    response = Response(output.getvalue().encode('utf-8-sig'), mimetype='text/csv; charset=utf-8-sig')
    response.headers["Content-Disposition"] = "attachment; filename=historico_almoxarifado.csv"
    return response

@app.route('/kits')
def gerenciar_kits():
    if 'usuario_id' not in session:
        return redirect('/login')

    conexao = conectar_banco()
    cursor = conexao.cursor()

    try:
        # 1. Busca todos os kits
        cursor.execute("SELECT id, nome, quantidade_atual FROM Kits ORDER BY nome")
        lista_kits_bruta = cursor.fetchall()

        # 2. Busca os ingredientes e seus respectivos PREÇOS
        cursor.execute('''
            SELECT ki.kit_id, p.nome, ki.quantidade_necessaria, COALESCE(p.unidade_medida, 'un'), p.preco_unitario
            FROM Kit_Itens ki
            JOIN Produtos p ON ki.produto_id = p.id
        ''')
        composicao_bruta = cursor.fetchall()

        # 3. Monta um "pacote" organizado calculando o custo total dos itens
        lista_kits = []
        for kit in lista_kits_bruta:
            itens_deste_kit = []
            valor_total_kit = 0.0 # Inicializa o somador do custo
            
            for comp in composicao_bruta:
                if comp[0] == kit[0]:
                    # MATEMÁTICA BLINDADA: Garante que quantidades e preços virem números válidos
                    try:
                        qtd = float(comp[2]) if comp[2] is not None else 0.0
                    except:
                        qtd = 0.0

                    try:
                        # Se o preço for nulo, vira 0. Se tiver vírgula, troca por ponto.
                        preco_str = str(comp[4]).replace(',', '.') if comp[4] is not None else '0'
                        preco = float(preco_str)
                    except:
                        preco = 0.0
                    
                    # Faz a conta e guarda no valor total do kit
                    valor_total_kit += (qtd * preco)
                    
                    itens_deste_kit.append({
                        'nome': comp[1], 
                        'quantidade': comp[2], 
                        'unidade': comp[3]
                    })
                    
            lista_kits.append({
                'id': kit[0],
                'nome': kit[1],
                'quantidade_atual': kit[2],
                'itens': itens_deste_kit,
                'valor_total': valor_total_kit
            })

        cursor.execute("SELECT id, nome FROM Produtos ORDER BY nome")
        lista_produtos = cursor.fetchall()
        
        # Envia para o HTML se tudo deu certo
        return render_template('kits.html', kits=lista_kits, produtos=lista_produtos)

    except Exception as e:
        # O DEDO DURO: Se der erro, imprime na tela em vez de dar o Erro 500 genérico
        import traceback
        erro_real = traceback.format_exc()
        return f"<h1>Opa! Achamos o culpado:</h1><pre style='background: #f8f9fa; padding: 20px; color: red;'>{erro_real}</pre>"
    finally:
        conexao.close()

        
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
    
    # INJETADO: usuario_id e session['usuario_id'] salvos no INSERT
    cursor.execute(
        'INSERT INTO Transacoes (kit_id, quantidade_retirada, solicitante, codigo_protocolo, usuario_id) VALUES (%s, %s, %s, %s, %s)',
        (kit_id, qtd_retirar, solicitante, codigo_protocolo, session['usuario_id'])
    )
    conexao.commit()
    conexao.close()
    
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


# === DASHBOARD FINANCEIRO COM DOIS GRÁFICOS (APENAS ADMIN) ===
@app.route('/financeiro')
def dashboard_financeiro():
    if 'usuario_id' not in session:
        return redirect('/login')
    if session.get('usuario_nivel') != 'admin':
        return "Acesso negado. Você não tem permissão para visualizar o Dashboard Financeiro.", 403

    conexao = conectar_banco()
    cursor = conexao.cursor()

    # 1. Busca o Valor Total de Patrimônio
    cursor.execute("SELECT SUM(quantidade_atual * preco_unitario) FROM Produtos")
    patrimonio_total = cursor.fetchone()[0] or 0.0

    # 2. Busca o Patrimônio por Categoria (Dados para a tabela e GRÁFICO 1)
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

    # Processa os Arrays para o GRÁFICO 1 (Patrimônio)
    graf_labels_patrimonio = [c[0] for c in categorias_bruto]
    graf_valores_patrimonio = [c[1] if c[1] else 0.0 for c in categorias_bruto]

    # 3. Busca a Movimentação/Saídas por Período (Dados para o GRÁFICO 2)
    periodo = request.args.get('periodo', '30')
    cursor.execute('''
        SELECT COALESCE(g.nome, 'Sem Grupo') as grupo,
               SUM(ABS(t.quantidade_retirada) * p.preco_unitario) as total_movimentado
        FROM Transacoes t
        JOIN Produtos p ON t.produto_id = p.id
        LEFT JOIN Grupos g ON p.grupo_id = g.id
        WHERE t.data_hora >= NOW() - (%s || ' days')::interval
        GROUP BY p.grupo_id, g.nome
        ORDER BY total_movimentado DESC
    ''', (periodo,))
    dados_grafico_saidas = cursor.fetchall()
    conexao.close()

    # Processa os Arrays para o GRÁFICO 2 (Saídas/Movimentação)
    graf_labels_saidas = [item[0] for item in dados_grafico_saidas]
    graf_valores_saidas = [item[1] if item[1] else 0.0 for item in dados_grafico_saidas]

    return render_template(
        'financeiro.html',
        patrimonio_total=patrimonio_total,
        valores_categoria=valores_categoria,
        graf_labels_patrimonio=graf_labels_patrimonio,
        graf_valores_patrimonio=graf_valores_patrimonio,
        graf_labels_saidas=graf_labels_saidas,
        graf_valores_saidas=graf_valores_saidas,
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
