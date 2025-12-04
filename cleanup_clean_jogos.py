import sqlite3
import shutil
import os

DB = 'banco.db'
BACKUP = 'banco.db.bak'

if not os.path.exists(DB):
    print('Arquivo banco.db não encontrado no diretório atual.')
    raise SystemExit(1)

# Backup
shutil.copy2(DB, BACKUP)
print(f'Backup criado: {BACKUP}')

conn = sqlite3.connect(DB)
cur = conn.cursor()

# Fetch all jogos
cur.execute('SELECT id, nome_do_jogo FROM jogos')
rows = cur.fetchall()

# Group by lower name
from collections import defaultdict
groups = defaultdict(list)
for id_, name in rows:
    groups[name.lower()].append((id_, name))

print(f'Found {len(rows)} jogos, {len(groups)} unique lowercased names')

changes = 0
for lower_name, items in groups.items():
    if len(items) <= 1:
        # ensure name stored in DB is lowered
        id0, name0 = items[0]
        if name0 != lower_name:
            print(f'Normalizing name id={id0} "{name0}" -> "{lower_name}"')
            cur.execute('UPDATE jogos SET nome_do_jogo = ? WHERE id = ?', (lower_name, id0))
            changes += 1
        continue

    # multiple entries: choose keeper
    keeper_id = None
    # prefer existing lowercase entry
    for id_, name in items:
        if name == lower_name:
            keeper_id = id_
            break
    if keeper_id is None:
        # pick first as keeper and rename to lower_name
        keeper_id, keeper_name = items[0]
        print(f'Updating keeper id={keeper_id} name "{keeper_name}" -> "{lower_name}"')
        cur.execute('UPDATE jogos SET nome_do_jogo = ? WHERE id = ?', (lower_name, keeper_id))
        changes += 1

    # now reassign others
    for id_, name in items:
        if id_ == keeper_id:
            continue
        print(f'Processing jogo id={id_} "{name}" -> keeper {keeper_id}')
        # For each avaliação that points to the old jogo id, reassign or remove duplicates
        cur.execute('SELECT id, usuario_id, nota, comentario, onde_baixar, valor FROM avaliacoes WHERE jogo_id = ?', (id_,))
        avals = cur.fetchall()
        for aval in avals:
            aval_id, usuario_id, nota, comentario, onde_baixar, valor = aval
            # check if user already has an avaliacao for keeper_id
            cur.execute('SELECT id FROM avaliacoes WHERE usuario_id = ? AND jogo_id = ?', (usuario_id, keeper_id))
            existing = cur.fetchone()
            if existing:
                # conflict: decide to remove the older/duplicate record (keep existing)
                print(f' Conflict for usuario_id={usuario_id}: existing avaliacao {existing[0]} kept; deleting {aval_id}')
                cur.execute('DELETE FROM avaliacoes WHERE id = ?', (aval_id,))
                changes += 1
            else:
                print(f' Reassigning avaliacao id={aval_id} from jogo_id={id_} to {keeper_id}')
                cur.execute('UPDATE avaliacoes SET jogo_id = ? WHERE id = ?', (keeper_id, aval_id))
                changes += 1

        print(f'Deleting jogo id={id_} "{name}"')
        cur.execute('DELETE FROM jogos WHERE id = ?', (id_,))
        changes += 1

conn.commit()
print(f'Completed. Total DB changes: {changes}')
conn.close()
print('Feito.')
