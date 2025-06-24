# monitor.py corregido para conexión persistente con PostgreSQL (Neon)
from flask import Flask, render_template, redirect, session, url_for, jsonify, request
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import psycopg2
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'clave-secreta'
CORS(app, supports_credentials=True)

# Conexión a la base de datos
load_dotenv()
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_DATABASE"),
        sslmode='require'
    )

@app.route("/")
def home():
    return redirect("/login")

@app.route("/login", methods=["GET"])
def mostrar_login():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def procesar_login():
    data = request.json
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if user and check_password_hash(user[2], password):
            session["username"] = user[1]
            session["rol"] = user[3]
            return jsonify({"message": "✅ Login exitoso"})
        else:
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
    except Exception as e:
        return jsonify({"error": f"❌ Error de base de datos: {str(e)}"}), 500

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("mostrar_login"))

@app.route("/monitor")
def monitor_interface():
    if "username" not in session:
        return redirect("/login")
    if session.get("rol") != "admin":
        return "❌ Acceso no autorizado. Debes ser administrador.", 403
    return render_template("monitor.html")

@app.route("/registrar_usuario", methods=["POST"])
def registrar_usuario():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    rol = data.get("rol", "usuario")

    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        hashed = generate_password_hash(password)
        cur.execute("INSERT INTO usuarios (username, password, rol) VALUES (%s, %s, %s)", (username, hashed, rol))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "✅ Usuario registrado correctamente"})
    except Exception as e:
        return jsonify({"error": f"❌ Error al registrar usuario: {str(e)}"}), 500

@app.route('/metricas', methods=['GET'])
def obtener_metricas():
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        hoy = datetime.now().date()
        hace_una_semana = hoy - timedelta(days=7)
        hace_un_mes = hoy - timedelta(days=30)

        cur.execute("SELECT COUNT(*) FROM conversaciones WHERE DATE(fecha) = %s", (hoy,))
        consultas_dia = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM conversaciones WHERE DATE(fecha) >= %s", (hace_una_semana,))
        consultas_semana = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM conversaciones WHERE DATE(fecha) >= %s", (hace_un_mes,))
        consultas_mes = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT user_id) FROM conversaciones")
        ids_unicas = cur.fetchone()[0]

        cur.close()
        conn.close()

        return jsonify({
            "consultas_dia": consultas_dia,
            "consultas_semana": consultas_semana,
            "consultas_mes": consultas_mes,
            "ids_unicas": ids_unicas
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Lanzar la aplicación en Render (puerto dinámico)
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)), debug=False)

