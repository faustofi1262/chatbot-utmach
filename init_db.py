import sqlite3
# Conexión a base de datos (se creará si no existe)
conn = sqlite3.connect('documentos.db')
cursor = conn.cursor()

# Crear tabla
cursor.execute('''
    CREATE TABLE IF NOT EXISTS documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        ruta TEXT NOT NULL,
        fecha_subida TEXT NOT NULL,
        usuario TEXT
    )
''')

conn.commit()
conn.close()
print("✅ Base de datos y tabla creadas.")
