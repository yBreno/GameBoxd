import sqlite3

def criar_tabela():
    conexao = sqlite3.connect("banco.db")
    cursor = conexao.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banco (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_do_jogo TEXT NOT NULL,
            nota REAL,
            comentario TEXT,
            onde_baixar TEXT,
            valor REAL
        )
    """)
    conexao.commit()
    conexao.close()
    return sqlite3.connect("banco.db")
    
def adicionar():
    nome = input("Digite o nome do jogo >>> ")
    nota = int(input("Digite a nota de 0 a 10 >>> "))
    comentario = input("Digite um comentario sobre o jogo >>> ")
    onde_baixar = input("Em que plataforma é feita a instalação do jogo >>> ")
    valor = input("Qual o valor do jogo >>> ")
    
    cursor.execute("INSERT INTO banco (nome_do_jogo, nota, comentario, onde_baixar, valor) values(?,?,?,?,?)",
                   (nome, nota, comentario, onde_baixar, valor))
    conexao.commit()
   
def printar():
    cursor.execute("SELECT * FROM banco")
    resultado = cursor.fetchall()
    print(resultado)

conexao = criar_tabela()
cursor = conexao.cursor()
adicionar()
printar()