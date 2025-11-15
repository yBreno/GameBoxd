from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import os

app = Flask(__name__)
app.secret_key = 'abacate'

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
    return render_template("index.html")

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username'].lower()
        senha = request.form['senha']
        conexao = get_db()
        cursor = conexao.cursor()
        try:
            cursor.execute("INSERT INTO usuarios (username, senha) VALUES (?, ?)",
                           (username, senha))
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
            flash(f"Bem-vindo, {username}!", "success")
            return redirect(url_for('dashboard', user_id=user[0]))
        flash("Login inválido!", "error")
        return redirect(url_for('login'))
    return render_template("login.html")



@app.route('/dashboard/<int:user_id>')
def dashboard(user_id):
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
    return render_template("dashboard.html", avaliacoes=dados, user_id=user_id)



@app.route('/avaliar/<int:user_id>', methods=['GET', 'POST'])
def avaliar(user_id):
    conexao = get_db()
    cursor = conexao.cursor()
    if request.method == 'POST':
        jogo = request.form['jogo']
        nota = request.form['nota']
        comentario = request.form['comentario']
        onde = request.form['onde']
        valor = request.form['valor']
        cursor.execute("INSERT OR IGNORE INTO jogos (nome_do_jogo) VALUES (?)", (jogo,))
        conexao.commit()
        cursor.execute("SELECT id FROM jogos WHERE nome_do_jogo=?", (jogo,))
        jogo_id = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM avaliacoes WHERE usuario_id=? AND jogo_id=?",
                       (user_id, jogo_id))
        if cursor.fetchone():
            flash("Você já avaliou esse jogo!", "error")
            return redirect(url_for('dashboard', user_id=user_id))
        cursor.execute("""
            INSERT INTO avaliacoes (usuario_id, jogo_id, nota, comentario, onde_baixar, valor)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, jogo_id, nota, comentario, onde, valor))
        conexao.commit()
        flash("Avaliação adicionada com sucesso!", "success")
        return redirect(url_for('dashboard', user_id=user_id))
    return render_template("avaliar.html", user_id=user_id)


if __name__ == "__main__":
    app.run(debug=True)
