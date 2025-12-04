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

RAWG_API_KEY = os.environ.get('27cbf22057c4482f8a1c6e7d2021a2fe')
_rawg_cache = {}  
_RAWG_CACHE_TTL = 60 * 60  


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
        for item in (data.get('results') or []):
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
            name = s.get('store', {}).get('name')
            link = s.get('url')
            if name and link:
                stores.append({'name': name, 'url': link})

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


def get_db():
    return sqlite3.connect("banco.db")


def init_db():
    if not os.path.exists("banco.db"):
        conexao = get_db()
        cursor = conexao.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                senha TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS jogos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome_do_jogo TEXT NOT NULL UNIQUE
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS avaliacoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                jogo_id INTEGER NOT NULL,
                nota REAL,
                comentario TEXT,
                onde_baixar TEXT,
                valor TEXT,
                UNIQUE(usuario_id, jogo_id),
                FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
                FOREIGN KEY(jogo_id) REFERENCES jogos(id)
            )
        """)

        conexao.commit()


init_db()


@app.route('/')
def index():
    conexao = get_db()
    cursor = conexao.cursor()

    atividade = []
    if session.get('username'):
        cursor.execute("""
            SELECT jogos.nome_do_jogo, avaliacoes.nota
            FROM avaliacoes
            JOIN jogos ON jogos.id = avaliacoes.jogo_id
            WHERE avaliacoes.usuario_id = ?
            ORDER BY avaliacoes.id DESC
            LIMIT 5
        """, (session.get('user_id'),))

        raw_atividade = cursor.fetchall()

        for jogo_normalizado, nota in raw_atividade:
            rawg_data = None
            gid = None

            try:
                results = rawg_search(jogo_normalizado, limit=1)
                if results:
                    gid = results[0]['id']
                    rawg_data = rawg_details_by_id(gid)
            except:
                rawg_data = None

            jogo_display_name = rawg_data['name'] if rawg_data else jogo_normalizado.title()
            cover_url = rawg_data['cover'] if rawg_data else url_for('static', filename='default_cover.svg')

            atividade.append({
                'name': jogo_display_name,
                'nota': nota,
                'cover': fix_url(cover_url),
                'rating': rawg_data['rating'] if rawg_data else None,
                'id': gid
            })

    cursor.execute("""
        SELECT jogos.nome_do_jogo, COUNT(avaliacoes.id) AS total, AVG(avaliacoes.nota)
        FROM jogos
        LEFT JOIN avaliacoes ON jogos.id = avaliacoes.jogo_id
        GROUP BY jogos.id
        ORDER BY total DESC
        LIMIT 4
    """)

    raw_populares = cursor.fetchall()
    populares = []

    for jogo_normalizado, total, media_nota in raw_populares:
        rawg_data = None
        gid = None

        try:
            results = rawg_search(jogo_normalizado, limit=1)
            if results:
                gid = results[0]['id']
                rawg_data = rawg_details_by_id(gid)
        except:
            rawg_data = None

        jogo_display_name = rawg_data['name'] if rawg_data else jogo_normalizado.title()
        cover_url = rawg_data['cover'] if rawg_data else url_for('static', filename='default_cover.svg')

        populares.append({
            'name': jogo_display_name,
            'total': total,
            'cover': fix_url(cover_url),
            'avg_rating': f"{media_nota:.1f}" if media_nota else 'N/A',
            'id': gid
        })

    return render_template("index.html", atividade=atividade, populares=populares)


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conexao = get_db()
    cursor = conexao.cursor()

    cursor.execute("""
        SELECT jogos.nome_do_jogo, avaliacoes.nota, avaliacoes.comentario,
               avaliacoes.onde_baixar, avaliacoes.valor
        FROM avaliacoes
        JOIN jogos ON jogos.id = avaliacoes.jogo_id
        WHERE usuario_id = ?
    """, (user_id,))

    dados = cursor.fetchall()
    enriched = []

    for jogo_normalizado, nota, comentario, onde, valor in dados:
        rawg_info = None

        try:
            results = rawg_search(jogo_normalizado, limit=1)
            if results:
                gid = results[0]['id']
                rawg_info = rawg_details_by_id(gid)
        except:
            rawg_info = None

        default_cover = url_for('static', filename='default_cover.svg')

        jogo_display_name = rawg_info['name'] if rawg_info else jogo_normalizado.title()

        rawg_dict = {
            'cover': fix_url(rawg_info['cover'] if rawg_info else default_cover),
            'rating': rawg_info['rating'] if rawg_info else None,
            'stores': rawg_info['stores'] if rawg_info else [],
            'metacritic': rawg_info['metacritic'] if rawg_info else None
        }

        enriched.append({
            'name': jogo_display_name,
            'nota': nota,
            'comentario': comentario,
            'onde': onde,
            'valor': valor,
            'rawg': rawg_dict
        })

    return render_template("dashboard.html", avaliacoes=enriched, user_id=user_id)


@app.route('/avaliar', methods=['GET', 'POST'])
def avaliar():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conexao = get_db()
    cursor = conexao.cursor()

    if request.method == 'POST':
        jogo = request.form['jogo'].strip()
        nota = request.form['nota']
        comentario = request.form['comentario']
        onde = request.form['onde']
        valor = request.form['valor']

        jogo_normalizado = jogo.lower()

        if not jogo_normalizado:
            flash("O nome do jogo não pode estar vazio.", "error")
            return redirect(url_for('avaliar'))

        cursor.execute("INSERT OR IGNORE INTO jogos (nome_do_jogo) VALUES (?)", (jogo_normalizado,))
        conexao.commit()

        cursor.execute("SELECT id FROM jogos WHERE nome_do_jogo=?", (jogo_normalizado,))
        jogo_id = cursor.fetchone()[0]

        cursor.execute("SELECT * FROM avaliacoes WHERE usuario_id=? AND jogo_id=?", (user_id, jogo_id))
        if cursor.fetchone():
            flash(f"Você já avaliou {jogo.title()}!", "error")
            return redirect(url_for('dashboard'))

        cursor.execute("""
            INSERT INTO avaliacoes (usuario_id, jogo_id, nota, comentario, onde_baixar, valor)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, jogo_id, nota, comentario, onde, valor))

        conexao.commit()
        flash("Avaliação adicionada com sucesso!", "success")
        return redirect(url_for('dashboard'))

    return render_template("avaliar.html")


@app.route('/rawg_search')
def route_rawg_search():
    q = request.args.get('q', '').strip()
    if not q or not RAWG_API_KEY:
        return jsonify([])
    return jsonify(rawg_search(q, limit=8))


@app.route('/rawg_game')
def route_rawg_game():
    gid = request.args.get('id')
    if not gid or not RAWG_API_KEY:
        return jsonify({})
    return jsonify(rawg_details_by_id(gid) or {})


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username'].lower()
        senha = request.form['senha']
        conexao = get_db()
        cursor = conexao.cursor()

        try:
            cursor.execute("INSERT INTO usuarios (username, senha) VALUES (?, ?)", (username, senha))
            conexao.commit()
            flash("Conta criada com sucesso!", "success")
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash("Usuário já existe!", "error")
            return redirect(url_for('registro'))

    return render_template("registro.html")


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].lower()
        senha = request.form['senha']
        conexao = get_db()
        cursor = conexao.cursor()

        cursor.execute("SELECT * FROM usuarios WHERE username=? AND senha=?", (username, senha))
        user = cursor.fetchone()

        if user:
            session['user_id'] = user[0]
            session['username'] = username
            flash(f"Bem-vindo, {username}!", "success")
            return redirect(url_for('dashboard'))

        flash("Login inválido!", "error")
        return redirect(url_for('login'))

    return render_template("login.html")


if __name__ == "__main__":
    app.run(debug=True)
