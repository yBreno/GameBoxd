from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, g
import sqlite3
import os
import requests
from urllib.parse import quote_plus
import time
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'abacate_fallback_key_nao_use_em_producao') 

RAWG_API_KEY = os.environ.get('RAWG_API_KEY')
print(f"[DEBUG] RAWG_API_KEY carregada: {bool(RAWG_API_KEY)}")
if RAWG_API_KEY:
    print(f"[DEBUG] Primeiros 10 caracteres: {RAWG_API_KEY[:10]}")
_rawg_cache = {}
_RAWG_CACHE_TTL = 60 * 60 


DATABASE = 'banco.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    if os.path.exists(DATABASE):
        try:
            db = sqlite3.connect(DATABASE)
            c = db.cursor()
            c.execute("SELECT 1 FROM usuarios LIMIT 1")
            db.close()
            return
        except sqlite3.OperationalError:
            pass
    
    db = sqlite3.connect(DATABASE)
    c = db.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        senha_hash TEXT NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS jogos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome_do_jogo TEXT UNIQUE NOT NULL
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS avaliacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        jogo_id INTEGER,
        nota REAL,
        comentario TEXT,
        onde_baixar TEXT,
        valor TEXT,
        UNIQUE(usuario_id, jogo_id),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(jogo_id) REFERENCES jogos(id)
    )""")

    db.commit()
    db.close()


init_db()


def fix_url(url):
    if not url:
        return None
    
    if url.startswith("http://") or url.startswith("https://"):
        return url.replace("http://", "https://")

    if url.startswith("/media"):
        return "https://media.rawg.io" + url

    return url

def _cache_get(key):
    item = _rawg_cache.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > _RAWG_CACHE_TTL:
        del _rawg_cache[key]
        return None
    return val

def _cache_set(key, val):
    _rawg_cache[key] = (time.time(), val)

def rawg_search(query, limit=1):
    if not RAWG_API_KEY or not query:
        return []

    limit = max(1, min(6, limit))
    key = f"search:{query.lower()}:{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        q = quote_plus(query)
        url = f"https://api.rawg.io/api/games?search={q}&page_size={limit}&key={RAWG_API_KEY}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()

        results = []
        for item in data.get('results', []):
            results.append({
                'id': item.get('id'),
                'name': item.get('name'),
                'cover': fix_url(item.get('background_image'))
            })

        _cache_set(key, results)
        return results
    except (requests.exceptions.RequestException, ValueError, Exception) as e:
        print(f"Erro ao buscar na RAWG: {e}")
        return []


def rawg_details_by_id(gid):
    if not RAWG_API_KEY or not gid:
        return None

    key = f"details:{gid}"
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        url = f"https://api.rawg.io/api/games/{gid}?key={RAWG_API_KEY}"
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        details = r.json()

        stores = []
        for s in details.get('stores', []):
            store_name = s.get('store', {}).get('name')
            store_url = s.get('url') 
            if store_name and store_url:
                stores.append({'name': store_name, 'url': store_url})

        out = {
            'cover': fix_url(details.get('background_image')),
            'rating': details.get('rating'),
            'stores': stores,
            'metacritic': details.get('metacritic'),
            'name': details.get('name')
        }

        _cache_set(key, out)
        return out
    except (requests.exceptions.RequestException, ValueError, Exception) as e:
        print(f"Erro ao buscar detalhes na RAWG: {e}")
        return None

def get_populares(limit=8):
    db = get_db()
    
    populares_raw = db.execute("""
        SELECT 
            j.nome_do_jogo, 
            COUNT(a.id) as total, 
            AVG(a.nota) as avg_rating
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        GROUP BY j.nome_do_jogo
        HAVING total >= 1 
        ORDER BY total DESC, avg_rating DESC
        LIMIT ?
    """, (limit,)).fetchall()
    
    populares = []
    DEFAULT_COVER = "https://via.placeholder.com/420x220?text=Sem+Capa"
    for p in populares_raw:
        nome_jogo = p['nome_do_jogo']
        cover_url = DEFAULT_COVER 
        
        try:
            r = rawg_search(nome_jogo, 1)
            if r and r[0].get('id'):
                rawg_info = rawg_details_by_id(r[0]['id']) or {}
                if rawg_info.get('cover'):
                    cover_url = rawg_info['cover']
        except Exception as e:
            print(f"Erro ao buscar RAWG para populares {nome_jogo}: {e}")
            pass
        populares.append({
            'name': nome_jogo.title(),
            'total': p['total'],
            'avg_rating': f"{p['avg_rating']:.1f}", 
            'cover': cover_url
        })
        
    return populares


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash("Você precisa estar logado para acessar esta página.", "info")
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function


@app.route('/')
def index():
    
    username = session.get('username')
    DEFAULT_COVER = "https://via.placeholder.com/420x220?text=Sem+Capa"
    
    atividade = []
    if session.get('user_id'):
        db = get_db()
        dados = db.execute("""
            SELECT a.id, j.nome_do_jogo, a.nota
            FROM avaliacoes a
            JOIN jogos j ON j.id = a.jogo_id
            WHERE a.usuario_id = ?
            ORDER BY a.id DESC
            LIMIT 4
        """, (session['user_id'],)).fetchall()
        
        for a in dados:
            nome_jogo = a['nome_do_jogo']
            cover_url = DEFAULT_COVER 
            rating = None 
            
            try:
                r = rawg_search(nome_jogo, 1)
                if r and r[0].get('id'):
                    rawg_info = rawg_details_by_id(r[0]['id']) or {} 
                    
                    if rawg_info.get('cover'):
                        cover_url = rawg_info['cover']
                    rating = rawg_info.get('rating')
                    
            except Exception as e:
                print(f"Erro ao buscar RAWG para atividade {nome_jogo}: {e}")
                pass 

            atividade.append({
                'id': a['id'],
                'name': nome_jogo.title(),
                'nota': a['nota'],
                'cover': cover_url, 
                'rating': rating
            })
    
    jogos_populares = get_populares(limit=8)
    
    return render_template("index.html", 
                           username=username.title() if username else None,
                           populares=jogos_populares,
                           atividade=atividade) 

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        user = db.execute("SELECT id, username, senha_hash FROM usuarios WHERE username = ?", (username,)).fetchone()

        if user and check_password_hash(user['senha_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            flash(f"Bem-vindo(a), {user['username'].title()}!", "success")
            next_page = request.args.get('next') or url_for('dashboard')
            return redirect(next_page)
        else:
            flash("Nome de usuário ou senha incorretos.", "error")
    
    return render_template("login.html")

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if len(username) < 3 or len(password) < 6:
            flash("O nome de usuário deve ter pelo menos 3 caracteres e a senha 6.", "error")
            return redirect(url_for('cadastro'))

        password_hash = generate_password_hash(password)
        db = get_db()
        c = db.cursor()
        
        try:
            c.execute("INSERT INTO usuarios (username, senha_hash) VALUES (?, ?)", (username, password_hash))
            db.commit()
            flash("Cadastro realizado com sucesso! Faça login.", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Este nome de usuário já está em uso.", "error")
        except Exception as e:
            flash(f"Ocorreu um erro no cadastro: {e}", "error")
            db.rollback()
            
    return render_template("cadastro.html")

@app.route('/logout')
def logout():
    session.clear()
    flash("Você foi desconectado(a).", "info")
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    DEFAULT_COVER = "https://via.placeholder.com/420x220?text=Sem+Capa"
    
    dados = db.execute("""
        SELECT a.id, j.nome_do_jogo, a.nota, a.comentario, a.onde_baixar, a.valor
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        WHERE a.usuario_id = ?
        ORDER BY a.id DESC
    """, (session['user_id'],)).fetchall()
    
    avaliacoes = []

    for a in dados:
        rawg_info = {} 
        cover_url = DEFAULT_COVER 
        nome_jogo = a['nome_do_jogo'] 
        
        try:
            r = rawg_search(nome_jogo, 1)
            if r and r[0].get('id'):
                rawg_info = rawg_details_by_id(r[0]['id']) or {}
                if rawg_info.get('cover'):
                    cover_url = rawg_info['cover']
        except Exception as e:
            print(f"Erro ao buscar RAWG para {nome_jogo} no dashboard: {e}")

        avaliacoes.append({
            'id': a['id'],
            'name': nome_jogo.title(), 
            'nota': a['nota'],
            'comentario': a['comentario'],
            'onde': a['onde_baixar'],
            'valor': a['valor'],
            'cover': cover_url,
            'rating': rawg_info.get('rating'),
            'rawg': rawg_info 
        })
    
    username = session.get('username', 'Usuário') 
    
    total_avaliacoes = db.execute("SELECT COUNT(id) FROM avaliacoes WHERE usuario_id = ?", 
                                  (session['user_id'],)).fetchone()[0]
    
    media_notas = db.execute("SELECT AVG(nota) FROM avaliacoes WHERE usuario_id = ?", 
                             (session['user_id'],)).fetchone()[0]
    
    if media_notas:
        media_notas = f"{media_notas:.2f}"
    else:
        media_notas = "N/A"

    return render_template("dashboard.html", 
                           avaliacoes=avaliacoes, 
                           username=username.title(),
                           total_avaliacoes=total_avaliacoes,
                           media_notas=media_notas)


@app.route('/avaliar', methods=['GET', 'POST'])
@login_required
def avaliar():
    if request.method == 'POST':
        name = request.form['name'].strip()
        try:
            nota = float(request.form['nota']) 
            if not 0.0 <= nota <= 10.0:
                raise ValueError("Nota fora do intervalo permitido.")
        except ValueError:
            flash("Nota deve ser um número entre 0.0 e 10.0.", "error")
            return redirect(url_for('avaliar'))
            
        comentario = request.form['comentario'].strip()
        onde = request.form['onde'].strip()
        valor = request.form['valor'].strip()

        if not name:
            flash("O nome do jogo não pode estar vazio.", "error")
            return redirect(url_for('avaliar'))

        db = get_db()
        c = db.cursor()
        name_norm = name.lower()

        try:
            c.execute("INSERT OR IGNORE INTO jogos (nome_do_jogo) VALUES (?)", (name_norm,))
            c.execute("SELECT id FROM jogos WHERE nome_do_jogo = ?", (name_norm,))
            jogo_id = c.fetchone()[0]

            c.execute("""INSERT INTO avaliacoes 
                (usuario_id, jogo_id, nota, comentario, onde_baixar, valor)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session['user_id'], jogo_id, nota, comentario, onde, valor))

            db.commit()
            flash(f"Avaliação de '{name.title()}' criada com sucesso!", "success")
            return redirect(url_for('dashboard'))
            
        except sqlite3.IntegrityError:
            flash(f"Você já avaliou o jogo '{name.title()}'. Use a função de editar.", "error")
        except Exception as e:
            db.rollback()
            flash(f"Ocorreu um erro ao salvar a avaliação: {e}", "error")

    return render_template("avaliar.html")


@app.route('/editar/<int:avaliacao_id>', methods=['GET', 'POST'])
@login_required
def editar_avaliacao(avaliacao_id):
    db = get_db()
    c = db.cursor()

    aval_raw = c.execute("""
        SELECT a.id, j.nome_do_jogo, a.nota, a.comentario, a.onde_baixar, a.valor, j.id as jogo_id
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        WHERE a.id = ? AND a.usuario_id = ?
    """, (avaliacao_id, session['user_id'])).fetchone()

    if aval_raw is None:
        flash("Avaliação não encontrada ou você não tem permissão para editá-la.", "error")
        return redirect(url_for('dashboard'))

    aval = {
        'id': aval_raw['id'],
        'name': aval_raw['nome_do_jogo'].title(),
        'nota': aval_raw['nota'],
        'comentario': aval_raw['comentario'],
        'onde': aval_raw['onde_baixar'],
        'valor': aval_raw['valor'],
        'jogo_id': aval_raw['jogo_id']
    }

    if request.method == 'POST':
        try:
            nota = float(request.form['nota']) 
            if not 0.0 <= nota <= 10.0:
                raise ValueError("Nota fora do intervalo permitido.")
        except ValueError:
            flash("Nota deve ser um número entre 0.0 e 10.0.", "error")
            return redirect(url_for('editar_avaliacao', avaliacao_id=avaliacao_id))

        comentario = request.form['comentario'].strip()
        onde = request.form['onde'].strip()
        valor = request.form['valor'].strip()
        
        try:
            c.execute("""
                UPDATE avaliacoes 
                SET nota = ?, comentario = ?, onde_baixar = ?, valor = ?
                WHERE id = ? AND usuario_id = ?
            """, (nota, comentario, onde, valor, avaliacao_id, session['user_id']))
            
            db.commit()
            flash(f"Avaliação de '{aval['name']}' atualizada com sucesso!", "success")
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            db.rollback()
            flash(f"Ocorreu um erro ao atualizar a avaliação: {e}", "error")

    return render_template("avaliar.html", aval=aval)


@app.route('/deletar/<int:avaliacao_id>', methods=['POST'])
@login_required
def deletar_avaliacao(avaliacao_id):
    db = get_db()
    c = db.cursor()
    
    aval_raw = c.execute("""
        SELECT a.id, j.nome_do_jogo
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        WHERE a.id = ? AND a.usuario_id = ?
    """, (avaliacao_id, session['user_id'])).fetchone()

    if aval_raw is None:
        flash("Avaliação não encontrada ou você não tem permissão para deletá-la.", "error")
        return redirect(url_for('dashboard'))
    
    nome_jogo = aval_raw['nome_do_jogo'].title()
    try:
        c.execute("DELETE FROM avaliacoes WHERE id = ? AND usuario_id = ?", 
                  (avaliacao_id, session['user_id']))
        db.commit()
        
        flash(f"Avaliação de '{nome_jogo}' removida com sucesso.", "info")
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        db.rollback()
        flash(f"Ocorreu um erro ao deletar a avaliação: {e}", "error")
        return redirect(url_for('dashboard'))


@app.route('/api/search_game')
def api_search_game():
    query = request.args.get('q', '').strip()
    
    if not query or len(query) < 3:
        return jsonify([])

    try:
        results = rawg_search(query, limit=6)
        suggestions = [{'name': r['name']} for r in results]
        return jsonify(suggestions)
    except Exception as e:
        print(f"Erro em api_search_game para '{query}': {e}")
        return jsonify([]), 500


if __name__ == '__main__':
    app.run(debug=True)