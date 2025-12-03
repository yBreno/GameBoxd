from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
import requests
from urllib.parse import quote_plus
import time
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = 'abacate'

RAWG_API_KEY = os.environ.get('RAWG_API_KEY')
_rawg_cache = {}
_RAWG_CACHE_TTL = 60 * 60


#aqui eh deus e muito cafe, (api do rawg pra pegar as imagens e colcoar os nomes, tambem colocar em https)
def fix_url(url):
    if not url:
        return None
    return url.replace("http://", "https://")


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


def rawg_search(query, limit=6):
    if not RAWG_API_KEY or not query:
        return []

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
    except Exception:
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
    except Exception:
        return None


#conectar com o banco
def get_db():
    return sqlite3.connect("banco.db")


def init_db():
    if not os.path.exists("banco.db"):
        db = get_db()
        c = db.cursor()

        c.execute("""CREATE TABLE usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE jogos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_do_jogo TEXT UNIQUE NOT NULL
        )""")

        c.execute("""CREATE TABLE avaliacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            jogo_id INTEGER,
            nota REAL,
            comentario TEXT,
            onde_baixar TEXT,
            valor TEXT,
            UNIQUE(usuario_id, jogo_id)
        )""")

        db.commit()


init_db()


#tela principal
@app.route('/')
def index():
    return render_template("index.html")

#tela inicial
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    c = db.cursor()

    c.execute("""
        SELECT avaliacoes.id, jogos.nome_do_jogo, avaliacoes.nota,
               avaliacoes.comentario, avaliacoes.onde_baixar, avaliacoes.valor
        FROM avaliacoes
        JOIN jogos ON jogos.id = avaliacoes.jogo_id
        WHERE avaliacoes.usuario_id = ?
    """, (session['user_id'],))

    dados = c.fetchall()
    avaliacoes = []

    for a in dados:
        rawg_info = None
        try:
            r = rawg_search(a[1], 1)
            if r:
                rawg_info = rawg_details_by_id(r[0]['id'])
        except:
            rawg_info = None

        avaliacoes.append({
            'id': a[0],
            'name': a[1].title(),
            'nota': a[2],
            'comentario': a[3],
            'onde': a[4],
            'valor': a[5],
            'rawg': rawg_info
        })

    return render_template("dashboard.html", avaliacoes=avaliacoes)


#avalicao
@app.route('/avaliar', methods=['GET', 'POST'])
def avaliar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name'].strip()
        nota = request.form['nota']
        comentario = request.form['comentario']
        onde = request.form['onde']
        valor = request.form['valor']

        db = get_db()
        c = db.cursor()

        name_norm = name.lower()

        c.execute("INSERT OR IGNORE INTO jogos (nome_do_jogo) VALUES (?)", (name_norm,))
        db.commit()

        c.execute("SELECT id FROM jogos WHERE nome_do_jogo = ?", (name_norm,))
        jogo_id = c.fetchone()[0]

        c.execute("""INSERT INTO avaliacoes 
            (usuario_id, jogo_id, nota, comentario, onde_baixar, valor)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session['user_id'], jogo_id, nota, comentario, onde, valor))

        db.commit()
        flash("Avaliação criada com sucesso!", "success")
        return redirect(url_for('dashboard'))

    return render_template("avaliar.html")


#editar
@app.route('/editar/<int:avaliacao_id>', methods=['GET', 'POST'])
def editar_avaliacao(avaliacao_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    c = db.cursor()

    c.execute("""
        SELECT avaliacoes.id, jogos.nome_do_jogo, avaliacoes.nota,
               avaliacoes.comentario, avaliacoes.onde_baixar, avaliacoes.valor
        FROM avaliacoes
        JOIN jogos ON jogos.id = avaliacoes.jogo_id
        WHERE avaliacoes.id = ? AND avaliacoes.usuario_id = ?
    """, (avaliacao_id, session['user_id']))

    aval = c.fetchone()

    if not aval:
        flash("Avaliação não encontrada.", "error")
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        nota = request.form['nota']
        comentario = request.form['comentario']
        onde = request.form['onde']
        valor = request.form['valor']

        c.execute("""
            UPDATE avaliacoes
            SET nota=?, comentario=?, onde_baixar=?, valor=?
            WHERE id=? AND usuario_id=?
        """, (nota, comentario, onde, valor, avaliacao_id, session['user_id']))

        db.commit()
        flash("Avaliação editada!", "success")
        return redirect(url_for('dashboard'))

    avaliacao = {
        'id': aval[0],
        'name': aval[1].title(),
        'nota': aval[2],
        'comentario': aval[3],
        'onde': aval[4],
        'valor': aval[5]
    }
    return render_template("avaliar.html", aval=avaliacao)

#excluir
@app.route('/deletar_avaliacao/<int:avaliacao_id>', methods=['POST'])
def deletar_avaliacao(avaliacao_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    c = db.cursor()

    c.execute("""
        DELETE FROM avaliacoes
        WHERE id = ? AND usuario_id = ?
    """, (avaliacao_id, session['user_id']))

    db.commit()
    flash("Avaliação deletada!", "success")
    return redirect(url_for('dashboard'))

#registrar
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username'].lower()
        senha = request.form['senha']

        db = get_db()
        c = db.cursor()

        try:
            c.execute("INSERT INTO usuarios (username, senha) VALUES (?, ?)", (username, senha))
            db.commit()
            flash("Conta criada!", "success")
            return redirect(url_for('login'))
        except:
            flash("Usuário já existe!", "error")

    return render_template("registro.html")

#login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].lower()
        senha = request.form['senha']

        db = get_db()
        c = db.cursor()
        c.execute("SELECT * FROM usuarios WHERE username=? AND senha=?", (username, senha))
        user = c.fetchone()

        if user:
            session['user_id'] = user[0]
            session['username'] = username
            return redirect(url_for('dashboard'))

        flash("Login inválido!", "error")

    return render_template("login.html")

#logout
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


#Rodar o codigo
if __name__ == "__main__":
    app.run(debug=True)
