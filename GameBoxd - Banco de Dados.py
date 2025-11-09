import sqlite3

conexao = sqlite3.connect("banco.db")
cursor = conexao.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS banco (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome_do_jogo TEXT NOT NULL,
    nota REAL,
    comentario TEXT,
    onde_baixar TEXT,
    valor TEXT
)
""")
conexao.commit()


def adicionar():
    nome = input("Digite o nome do jogo >>> ").capitalize()
    cursor.execute("SELECT * FROM banco WHERE nome_do_jogo = ? ",(nome,))
    teste = cursor.fetchone()
    
    while True:
        nota = int(input("Digite a nota de 0 a 10 >>> "))
        if nota > 10 or nota < 0:
            print("Nota invalida tente novamente!")
        else:
            break
    comentario = input("Digite um comentario sobre o jogo >>> ")
    onde = input("Onde pode baixar o jogo >>> ").capitalize()
    valor = input("Qual o valor do jogo >>> ")
    promocao = input("O jogo estava em promoção? (S/N) >>> ").upper()
    while promocao != "S" and promocao != "N" :
        promocao = input("O jogo estava em promoção? (S/N) >>> ").upper()
        print(promocao)


    if teste: 
        id_jogo = teste[0]
        nota_antiga = teste[2] or ""
        comentario_antigo = teste[3] or ""

        nova_nota = (str(nota_antiga) + ", " + str(nota)).strip(", ")
        novo_comentario = (comentario_antigo + " , " + comentario).strip(" , ")
        if promocao ==  "N": # So para sempre deixar o valor sem promoção 
            cursor.execute("UPDATE banco SET nota = ?, comentario = ?, onde_baixar = ?, valor = ? WHERE id = ?",
                        (nova_nota, novo_comentario, onde, valor, id_jogo))
            conexao.commit()
            print(f"Avaliação adicionada ao jogo existente: {nome}")
        else:
            cursor.execute("UPDATE banco SET nota = ?, comentario = ?, onde_baixar = ? WHERE id = ?",
                        (nova_nota, novo_comentario, onde, id_jogo))
            conexao.commit()
            print(f"Avaliação adicionada ao jogo existente: {nome}")
    else:
        cursor.execute("INSERT INTO banco (nome_do_jogo, nota, comentario, onde_baixar, valor) VALUES (?, ?, ?, ?, ?)",
                       (nome, nota, comentario, onde, valor))
        conexao.commit()
        print(f"Jogo '{nome}' adicionado com sucesso!")


def mostrar():
    cursor.execute("SELECT * FROM banco")
    jogos = cursor.fetchall()
    for jogo in jogos:
        print(jogo)


adicionar()
mostrar()

conexao.close()
