
import os
import csv
import io
from flask import Flask, render_template, request, redirect, session, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename
import psycopg2
from datetime import datetime



from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, session
from flask_cors import CORS
import os
import psycopg2
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
CORS(app)
app.secret_key = 'clave_secreta'

# Configuración base de datos Neon
def get_db_connection():
    return psycopg2.connect(
        host="ep-calm-tooth-a4teb7mi-pooler.us-east-1.aws.neon.tech",
        port=5432,
        user="chatbot-utmach_db_owner",
        password="npg_Tq8jFbxgQk0L",
        dbname="chatbot-utmach_db",
        sslmode="require"
    )

# Ruta para renderizar login
@app.route("/login", methods=["GET"])
def mostrar_login():
    return render_template("login.html")

# Ruta para procesar login
@app.route("/login", methods=["POST"])
def procesar_login():
    try:
        data = request.json
        username = data.get("username")
        password = data.get("password")

        db = get_db_connection()
        cur = db.cursor()
        cur.execute("SELECT * FROM usuarios WHERE username = %s AND password = %s", (username, password))
        user = cur.fetchone()
        cur.close()
        db.close()

        if user:
            session["usuario_id"] = user[0]
            session["nombre_usuario"] = user[1]
            session["rol"] = user[3]
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    except Exception as e:
        print("❌ Error:", e)
        return jsonify({"error": str(e)}), 500

# Ruta protegida para subir archivos
@app.route("/admin")
def admin_interface():
    if session.get("rol") != "admin":
        return redirect("/login")
    return render_template("admin.html")

# SUBIDA de PDF con verificación
@app.route("/upload", methods=["POST"])
def subir_pdf():
    try:
        if "pdf" not in request.files:
            return jsonify({"error": "No se envió ningún archivo PDF"}), 400

        file = request.files["pdf"]
        if file.filename == "":
            return jsonify({"error": "Nombre de archivo vacío"}), 400

        filename = secure_filename(file.filename)

        # Crear carpeta "archivos" si no existe
        folder = "archivos"
        if not os.path.exists(folder):
            os.makedirs(folder)
            print("📁 Carpeta 'archivos' creada")

        filepath = os.path.join(folder, filename)
        file.save(filepath)

        db = get_db_connection()
        cur = db.cursor()
        cur.execute("INSERT INTO pdf_archivos (nombre_archivo, ruta_archivo, fecha_subida) VALUES (%s, %s, %s)",
                    (filename, filepath, datetime.now()))
        db.commit()
        cur.close()
        db.close()

        return jsonify({"success": True, "message": "Archivo subido correctamente."})

    except Exception as e:
        print("❌ Error al subir PDF:", e)
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return redirect("/login")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)



@app.route("/metricas")
def metricas():
    try:
        cur = get_db_connection().cursor()
        cur.execute("""
            SELECT 
                DATE(fecha) AS dia, 
                COUNT(*) AS total 
            FROM metricas 
            GROUP BY dia 
            ORDER BY dia DESC 
            LIMIT 10
        """)
        datos = cur.fetchall()
        return jsonify({"datos": datos})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/exportar_csv")
def exportar_csv():
    try:
        cur = get_db_connection().cursor()
        cur.execute("SELECT * FROM metricas ORDER BY fecha DESC")
        registros = cur.fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Usuario', 'Consulta', 'Fecha'])
        writer.writerows(registros)
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=metricas.csv"}
        )
    except Exception as e:
        return f"Error exportando: {str(e)}", 500


@app.route("/chatbot")
def abrir_chatbot():
    if not session.get("rol"):
        return redirect("/login")
    return "<h1>Chatbot funcionando... (aquí va tu integración)</h1>"
