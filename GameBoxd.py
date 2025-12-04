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


# ============================================================
# CORREÇÃO PRINCIPAL: fix_url funcionando e usado corretamente
# ============================================================
def fix_url(url):
    if not url:
        return None

    # Caso já seja URL completa
    if url.startswith("http://") or url.startswith("https://"):
        return url.replace("http://", "https://")

    # Caso venha só o caminho do RAWG
    if url.startswith("/media"):
        return "https://media.rawg.io" + url

    return url


# ============================================================
# Cache simples
# ============================================================
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


# ============================================================
# RAWG SEARCH
# ============================================================
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
                'cover': fix_url(item.get('background_image'))  # CORRIGIDO
            })

        _cache_set(key, results)
        return results

    except Exception:
        return []


# ============================================================
# RAWG DETAILS
# ============================================================
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
            name = s.get('store', {}).get('name')
            link = s.get('url')
            if name and link:
                stores.append({'name': name, 'url': link})

        out = {
            'cover': fix_url(details.get('background_image')),  # CORRIGIDO
            'rating': details.get('rating'),
            'stores': stores,
            'metacritic': details.get('metacritic'),
            'name': details.get('name')
        }

        _cache_set(key, out)
        return out

    except Exception:
        return None


# ============================================================
# BANCO DE DADOS
# ============================================================
def get_db():
    return sqlite3.connect("banco.db")


def init_db():
    if not os.path.exists("banco.db"):
        db = get_db()
        c = db.cursor()

        c.execute("""
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE jogos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_do_jogo TEXT UNIQUE NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE avaliacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                jogo_id INTEGER,
                nota REAL,
                comentario TEXT,
                onde_baixar TEXT,
                valor TEXT,
                UNIQUE(usuario_id, jogo_id)
            )
        """)

        db.commit()


init_db()


# ============================================================
# ROTAS PRINCIPAIS
# ============================================================
@app.route('/')
def index():
    return render_template("index.html")


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    c = db.cursor()

    c.execute("""
        SELECT jogos.nome_do_jogo, avaliacoes.nota, avaliacoes.comentario,
               avaliacoes.onde_baixar, avaliacoes.valor
        FROM avaliacoes
        JOIN jogos ON jogos.id = avaliacoes.jogo_id
        WHERE usuario_id = ?
    """, (session['user_id'],))

    dados = c.fetchall()
    avaliacoes = []

    for nome, nota, comentario, onde, valor in dados:
        rawg_info = None
        try:
            results = rawg_search(nome, 1)
            if results:
                gid = results[0]['id']
                rawg_info = rawg_details_by_id(gid)
        except:
            rawg_info = None

        default_cover = url_for('static', filename='default_cover.svg')

        avaliacoes.append({
            'name': rawg_info['name'] if rawg_info else nome.title(),
            'nota': nota,
            'comentario': comentario,
            'onde': onde,
            'valor': valor,
            'rawg': {
                'cover': rawg_info['cover'] if rawg_info and rawg_info['cover'] else default_cover,
                'rating': rawg_info['rating'] if rawg_info else None,
                'stores': rawg_info['stores'] if rawg_info else []
            }
        })

    return render_template("dashboard.html", avaliacoes=avaliacoes)


# ============================================================
# AVALIAR
# ============================================================
@app.route('/avaliar', methods=['GET', 'POST'])
def avaliar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    db = get_db()
    c = db.cursor()

    if request.method == 'POST':
        jogo = request.form['jogo'].lower().strip()
        nota = request.form['nota']
        comentario = request.form['comentario']
        onde = request.form['onde']
        valor = request.form['valor']

        c.execute("INSERT OR IGNORE INTO jogos (nome_do_jogo) VALUES (?)", (jogo,))
        db.commit()

        c.execute("SELECT id FROM jogos WHERE nome_do_jogo=?", (jogo,))
        jogo_id = c.fetchone()[0]

        c.execute("""
            INSERT INTO avaliacoes (usuario_id, jogo_id, nota, comentario, onde_baixar, valor)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session['user_id'], jogo_id, nota, comentario, onde, valor))

        db.commit()
        return redirect(url_for('dashboard'))

    return render_template("avaliar.html")


# ============================================================
# LOGIN / REGISTRO / LOGOUT
# ============================================================
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
            return redirect(url_for('login'))
        except:
            flash("Usuário já existe!", "error")

    return render_template("registro.html")


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ============================================================
# START
# ============================================================
if __name__ == "__main__":
    app.run(debug=True)
