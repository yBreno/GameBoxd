# imports padrão
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
_rawg_cache = {}
_RAWG_CACHE_TTL = 60 * 60  # cache simples

DATABASE = 'banco.db'


# arruma url de imagem quebrada
def fix_url(url: str):
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return url.replace("http://", "https://", 1)
    if url.startswith("/media"):
        return "https://media.rawg.io" + url
    return url


# pega conexão com o banco
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


# fecha banco ao terminar a request
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db:
        db.close()


# cria banco caso não exista
def init_db():
    if os.path.exists(DATABASE):
        try:
            db = sqlite3.connect(DATABASE)
            cur = db.cursor()
            cur.execute("SELECT 1 FROM usuarios LIMIT 1")
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
        UNIQUE(usuario_id, jogo_id)
    )""")

    db.commit()
    db.close()


init_db()


# pega item do cache
def _cache_get(key):
    item = _rawg_cache.get(key)
    if not item:
        return None
    ts, val = item
    if time.time() - ts > _RAWG_CACHE_TTL:
        del _rawg_cache[key]
        return None
    return val


# salva no cache
def _cache_set(key, val):
    _rawg_cache[key] = (time.time(), val)


# busca no RAWG pelo nome
def rawg_search(query, limit=1):
    if not RAWG_API_KEY or not query:
        return []

    limit = max(1, min(6, limit))
    key = f"search:{query.lower()}:{limit}"
    cached = _cache_get(key)
    if cached:
        return cached

    try:
        q = quote_plus(query)
        url = f"https://api.rawg.io/api/games?search={q}&page_size={limit}&key={RAWG_API_KEY}"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()

        results = []
        for item in data.get("results", []):
            results.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "cover": fix_url(item.get("background_image"))
            })

        _cache_set(key, results)
        return results

    except Exception:
        return []


# pega detalhes do jogo pelo id
def rawg_details_by_id(gid):
    if not RAWG_API_KEY or not gid:
        return None

    key = f"details:{gid}"
    cached = _cache_get(key)
    if cached:
        return cached

    try:
        url = f"https://api.rawg.io/api/games/{gid}?key={RAWG_API_KEY}"
        r = requests.get(url, timeout=6)
        r.raise_for_status()
        details = r.json()

        stores = []
        for s in details.get("stores", []):
            name = s.get("store", {}).get("name")
            link = s.get("url")
            if name and link:
                stores.append({"name": name, "url": link})

        out = {
            "cover": fix_url(details.get("background_image")),
            "rating": details.get("rating"),
            "stores": stores,
            "metacritic": details.get("metacritic"),
            "name": details.get("name")
        }

        _cache_set(key, out)
        return out

    except Exception:
        return None


# pega jogos mais avaliados no site
def get_populares(limit=8):
    db = get_db()

    dados = db.execute("""
        SELECT j.nome_do_jogo, COUNT(a.id) AS total, AVG(a.nota) AS avg_rating
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        GROUP BY j.nome_do_jogo
        ORDER BY total DESC, avg_rating DESC
        LIMIT ?
    """, (limit,)).fetchall()

    populares = []
    DEFAULT_COVER = "https://via.placeholder.com/420x220?text=Sem+Capa"

    for p in dados:
        nome = p["nome_do_jogo"]
        cover = DEFAULT_COVER
        try:
            r = rawg_search(nome, 1)
            if r and r[0]["id"]:
                info = rawg_details_by_id(r[0]["id"]) or {}
                if info.get("cover"):
                    cover = fix_url(info["cover"])
        except:
            pass

        populares.append({
            "name": nome.title(),
            "total": p["total"],
            "avg_rating": f"{p['avg_rating']:.1f}",
            "cover": cover
        })

    return populares


# checa login
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kw):
        if "user_id" not in session:
            flash("Faça login antes.", "info")
            return redirect(url_for("login"))
        return f(*args, **kw)
    return wrapper


# página inicial
@app.route("/")
def index():
    username = session.get("username")
    DEFAULT_COVER = "https://via.placeholder.com/420x220?text=Sem+Capa"

    atividade = []
    if session.get("user_id"):
        db = get_db()
        dados = db.execute("""
            SELECT a.id, j.nome_do_jogo, a.nota
            FROM avaliacoes a
            JOIN jogos j ON j.id = a.jogo_id
            WHERE a.usuario_id = ?
            ORDER BY a.id DESC
            LIMIT 4
        """, (session["user_id"],)).fetchall()

        for a in dados:
            nome = a["nome_do_jogo"]
            cover = DEFAULT_COVER
            rating = None

            try:
                r = rawg_search(nome, 1)
                if r and r[0]["id"]:
                    info = rawg_details_by_id(r[0]["id"]) or {}
                    if info.get("cover"):
                        cover = fix_url(info["cover"])
                    rating = info.get("rating")
            except:
                pass

            atividade.append({
                "id": a["id"],
                "name": nome.title(),
                "nota": a["nota"],
                "cover": cover,
                "rating": rating
            })

    populares = get_populares()

    return render_template("index.html",
                           username=username.title() if username else None,
                           populares=populares,
                           atividade=atividade)


# login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        db = get_db()
        user = db.execute(
            "SELECT id, username, senha_hash FROM usuarios WHERE username = ?",
            (username,)
        ).fetchone()

        if user and check_password_hash(user["senha_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))

        flash("Login inválido.", "error")

    return render_template("login.html")


# cadastro
@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if len(username) < 3 or len(password) < 6:
            flash("Nome mínimo 3, senha mínimo 6.", "error")
            return redirect(url_for("cadastro"))

        password_hash = generate_password_hash(password)
        db = get_db()

        try:
            db.execute("INSERT INTO usuarios (username, senha_hash) VALUES (?, ?)",
                       (username, password_hash))
            db.commit()
            flash("Cadastro feito!", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Usuário já existe.", "error")

    return render_template("cadastro.html")


# logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# dashboard do usuário
@app.route("/dashboard")
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
    """, (session["user_id"],)).fetchall()

    avaliacoes = []

    for a in dados:
        nome = a["nome_do_jogo"]
        cover = DEFAULT_COVER
        info = {}

        try:
            r = rawg_search(nome, 1)
            if r and r[0]["id"]:
                info = rawg_details_by_id(r[0]["id"]) or {}
                if info.get("cover"):
                    cover = fix_url(info["cover"])
        except:
            pass

        avaliacoes.append({
            "id": a["id"],
            "name": nome.title(),
            "nota": a["nota"],
            "comentario": a["comentario"],
            "onde": a["onde_baixar"],
            "valor": a["valor"],
            "cover": cover,
            "rating": info.get("rating")
        })

    username = session.get("username", "Usuário")
    total = db.execute("SELECT COUNT(*) FROM avaliacoes WHERE usuario_id = ?",
                       (session["user_id"],)).fetchone()[0]
    media = db.execute("SELECT AVG(nota) FROM avaliacoes WHERE usuario_id = ?",
                       (session["user_id"],)).fetchone()[0]

    media = f"{media:.2f}" if media else "N/A"

    return render_template("dashboard.html",
                           avaliacoes=avaliacoes,
                           username=username.title(),
                           total_avaliacoes=total,
                           media_notas=media)


# avaliar jogo
@app.route("/avaliar", methods=["GET", "POST"])
@login_required
def avaliar():
    if request.method == "POST":
        name = request.form["name"].strip()

        try:
            nota = float(request.form["nota"])
            if not 0 <= nota <= 10:
                raise ValueError
        except:
            flash("Nota inválida.", "error")
            return redirect(url_for("avaliar"))

        comentario = request.form["comentario"].strip()
        onde = request.form["onde"].strip()
        valor = request.form["valor"].strip()

        if not name:
            flash("Nome do jogo obrigatório.", "error")
            return redirect(url_for("avaliar"))

        db = get_db()
        name_norm = name.lower()

        try:
            db.execute("INSERT OR IGNORE INTO jogos (nome_do_jogo) VALUES (?)",
                       (name_norm,))
            jogo_id = db.execute(
                "SELECT id FROM jogos WHERE nome_do_jogo = ?", (name_norm,)
            ).fetchone()[0]

            db.execute("""
                INSERT INTO avaliacoes (usuario_id, jogo_id, nota, comentario, onde_baixar, valor)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (session["user_id"], jogo_id, nota, comentario, onde, valor))

            db.commit()
            flash("Avaliação criada!", "success")
            return redirect(url_for("dashboard"))

        except sqlite3.IntegrityError:
            flash("Você já avaliou esse jogo.", "error")

    return render_template("avaliar.html")


# editar avaliação
@app.route("/editar/<int:avaliacao_id>", methods=["GET", "POST"])
@login_required
def editar_avaliacao(avaliacao_id):
    db = get_db()

    aval_raw = db.execute("""
        SELECT a.id, j.nome_do_jogo, a.nota, a.comentario, a.onde_baixar, a.valor, j.id as jogo_id
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        WHERE a.id = ? AND a.usuario_id = ?
    """, (avaliacao_id, session["user_id"])).fetchone()

    if aval_raw is None:
        flash("Avaliação não encontrada.", "error")
        return redirect(url_for("dashboard"))

    aval = {
        "id": aval_raw["id"],
        "name": aval_raw["nome_do_jogo"].title(),
        "nota": aval_raw["nota"],
        "comentario": aval_raw["comentario"],
        "onde": aval_raw["onde_baixar"],
        "valor": aval_raw["valor"]
    }

    if request.method == "POST":
        try:
            nota = float(request.form["nota"])
            if not 0 <= nota <= 10:
                raise ValueError
        except:
            flash("Nota inválida.", "error")
            return redirect(url_for("editar_avaliacao", avaliacao_id=avaliacao_id))

        comentario = request.form["comentario"].strip()
        onde = request.form["onde"].strip()
        valor = request.form["valor"].strip()

        try:
            db.execute("""
                UPDATE avaliacoes
                SET nota = ?, comentario = ?, onde_baixar = ?, valor = ?
                WHERE id = ? AND usuario_id = ?
            """, (nota, comentario, onde, valor, avaliacao_id, session["user_id"]))

            db.commit()
            flash("Avaliação atualizada!", "success")
            return redirect(url_for("dashboard"))
        except:
            flash("Erro ao editar.", "error")

    return render_template("avaliar.html", aval=aval)


# deletar avaliação
@app.route("/deletar/<int:avaliacao_id>", methods=["POST"])
@login_required
def deletar_avaliacao(avaliacao_id):
    db = get_db()

    aval_raw = db.execute("""
        SELECT a.id, j.nome_do_jogo
        FROM avaliacoes a
        JOIN jogos j ON j.id = a.jogo_id
        WHERE a.id = ? AND a.usuario_id = ?
    """, (avaliacao_id, session["user_id"])).fetchone()

    if aval_raw is None:
        flash("Avaliação não encontrada.", "error")
        return redirect(url_for("dashboard"))

    try:
        db.execute(
            "DELETE FROM avaliacoes WHERE id = ? AND usuario_id = ?",
            (avaliacao_id, session["user_id"])
        )
        db.commit()
        flash("Avaliação removida.", "info")
    except:
        flash("Erro ao deletar.", "error")

    return redirect(url_for("dashboard"))


# autocomplete da busca
@app.route("/api/search_game")
def api_search_game():
    query = request.args.get("q", "").strip()

    if not query or len(query) < 3:
        return jsonify([])

    try:
        results = rawg_search(query, limit=6)
        return jsonify([{"name": r["name"]} for r in results])
    except:
        return jsonify([]), 500


if __name__ == "__main__":
    app.run(debug=True)