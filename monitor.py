# monitor.py actualizado y corregido para Render con PostgreSQL
from flask import Flask, render_template, redirect, session, url_for, jsonify, request, send_from_directory
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import subprocess
from datetime import datetime, timedelta
import os
import psycopg2
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'clave-secreta'
CORS(app, supports_credentials=True)

# Rutas de los archivos a ejecutar
MAIN_PATH = 'main.py'

# Procesos activos
processes = {}

# Conexión a la base de datos
load_dotenv()
db = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    dbname=os.getenv("DB_DATABASE")
)
cursor = db.cursor()

# Ejecutar main.py
@app.route("/ejecutar_main", methods=["POST"])
def ejecutar_main():
    try:
        if "main" in processes and processes["main"].poll() is None:
            return jsonify({"message": "El chatbot ya está en ejecución."}), 200

        proceso = subprocess.Popen(["python", MAIN_PATH], creationflags=subprocess.CREATE_NEW_CONSOLE)
        processes["main"] = proceso
        return jsonify({"message": "✅ main.py se está ejecutando correctamente."}), 200
    except Exception as e:
        return jsonify({"error": f"❌ Error al ejecutar main.py: {str(e)}"}), 500

# Detener main.py
@app.route("/detener_main", methods=["POST"])
def detener_main():
    try:
        if "main" not in processes or processes["main"].poll() is not None:
            return jsonify({"message": "El chatbot no está en ejecución."}), 200

        processes["main"].terminate()
        del processes["main"]
        return jsonify({"message": "✅ main.py ha sido detenido correctamente."}), 200
    except Exception as e:
        return jsonify({"error": f"❌ Error al detener main.py: {str(e)}"}), 500

# Estado de main.py
@app.route("/estado_main")
def estado_main():
    estado = "ejecutando" if "main" in processes and processes["main"].poll() is None else "detenido"
    return jsonify({"estado": estado})

# Métricas de uso
@app.route('/metricas', methods=['GET'])
def obtener_metricas():
    try:
        hoy = datetime.now().date()
        hace_una_semana = hoy - timedelta(days=7)
        hace_un_mes = hoy - timedelta(days=30)

        cur = db.cursor()

        cur.execute("SELECT COUNT(*) FROM conversaciones WHERE DATE(fecha) = %s", (hoy,))
        consultas_dia = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM conversaciones WHERE DATE(fecha) >= %s", (hace_una_semana,))
        consultas_semana = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM conversaciones WHERE DATE(fecha) >= %s", (hace_un_mes,))
        consultas_mes = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT user_id) FROM conversaciones")
        ids_unicas = cur.fetchone()[0]

        return jsonify({
            "consultas_dia": consultas_dia,
            "consultas_semana": consultas_semana,
            "consultas_mes": consultas_mes,
            "ids_unicas": ids_unicas
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Login GET
@app.route("/login", methods=["GET"])
def mostrar_login():
    return send_from_directory('', 'login.html')

# Login POST
@app.route("/login", methods=["POST"])
def procesar_login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400

    cur = db.cursor()
    cur.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
    user = cur.fetchone()

    if user and check_password_hash(user[2], password):  # Ajustado para PostgreSQL (sin dictionary=True)
        session["username"] = user[1]  # username
        session["rol"] = user[3]       # rol
        return jsonify({"message": "✅ Login exitoso"})
    else:
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

# Logout
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("mostrar_login"))

# Interfaz protegida
@app.route("/monitor")
def monitor_interface():
    if "username" not in session:
        return redirect("/login")
    if session.get("rol") != "admin":
        return "❌ Acceso no autorizado. Debes ser administrador.", 403
    return render_template("monitor.html")

# Registrar usuario
@app.route("/registrar_usuario", methods=["POST"])
def registrar_usuario():
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")
        rol = data.get("rol", "usuario")
        if not username or not password:
            return jsonify({"error": "Usuario y contraseña requeridos"}), 400

        hashed = generate_password_hash(password)
        cur = db.cursor()
        cur.execute("INSERT INTO usuarios (username, password, rol) VALUES (%s, %s, %s)", (username, hashed, rol))
        db.commit()
        return jsonify({"message": "✅ Usuario registrado correctamente"})
    except Exception as e:
        return jsonify({"error": f"❌ Error al registrar usuario: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
