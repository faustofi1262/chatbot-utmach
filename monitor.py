# monitor.py unificado y funcional
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from dotenv import load_dotenv
from pinecone import Pinecone, ServerlessSpec
import psycopg2
import pdfplumber
import os
import re
from openai import OpenAI

# === Configuración general ===
app = Flask(__name__)
app.secret_key = 'clave-secreta'
CORS(app, supports_credentials=True)
load_dotenv()

# === Conexión a DB ===
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_DATABASE"),
        sslmode='require'
    )

# === Pinecone y OpenAI ===
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
INDEX_NAME = os.getenv("INDEX_NAME")

pc = Pinecone(api_key=PINECONE_API_KEY)
if INDEX_NAME not in pc.list_indexes().names():
    pc.create_index(
        name=INDEX_NAME,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )
index = pc.Index(INDEX_NAME)

# === Uploads ===
UPLOAD_FOLDER = "./upload"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# === Función para dividir texto ===
def dividir_texto(texto, max_tokens=1000):
    oraciones = re.findall(r'[^.!?]*[.!?]', texto, re.DOTALL)
    fragmentos, actual = [], ""
    for oracion in oraciones:
        if len(actual) + len(oracion) <= max_tokens:
            actual += " " + oracion.strip()
        else:
            fragmentos.append(actual.strip())
            actual = oracion.strip()
    if actual:
        fragmentos.append(actual.strip())
    return fragmentos

# === Rutas ===
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE username = %s", (username,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user and user[2] == password:
        session["username"] = user[1]
        session["rol"] = user[3]
        return jsonify({"message": "✅ Login exitoso"})
    return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

@app.route("/monitor")
def monitor_interface():
    if session.get("rol") != "admin":
        return redirect("/login")
    return render_template("monitor.html")

@app.route("/admin")
def admin_interface():
    if session.get("rol") != "admin":
        return redirect("/login")
    return render_template("admin.html")

@app.route("/registrar_usuario", methods=["POST"])
def registrar_usuario():
    data = request.json
    username, password = data.get("username"), data.get("password")
    rol = data.get("rol", "usuario")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO usuarios (username, password, rol) VALUES (%s, %s, %s)",
                (username, generate_password_hash(password), rol))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "✅ Usuario registrado correctamente"})

@app.route("/upload", methods=["POST"])
def upload():
    archivo = request.files['archivo']
    if archivo.filename == '':
        return jsonify({'error': 'Nombre de archivo vacío'}), 400
    filepath = os.path.join(UPLOAD_FOLDER, secure_filename(archivo.filename))
    archivo.save(filepath)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO pdf_archivos (nombre) VALUES (%s)", (archivo.filename,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'message': 'Archivo subido correctamente'})

@app.route("/entrenar_pdf", methods=["POST"])
def entrenar_pdf():
    data = request.get_json()
    filename = data.get("nombre")
    pdf_path = os.path.join(UPLOAD_FOLDER, filename)
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Archivo no encontrado"}), 404

    with pdfplumber.open(pdf_path) as pdf:
        texto = "".join(p.extract_text() or "" for p in pdf.pages)

    fragmentos = dividir_texto(texto)
    cliente = OpenAI(api_key=OPENAI_API_KEY)
    guardados = 0
    for i, fragmento in enumerate(fragmentos):
        try:
            r = cliente.embeddings.create(model="text-embedding-ada-002", input=fragmento)
            emb = r.data[0].embedding
            index.upsert([(f"{filename}_frag_{i}", emb, {"response": fragmento[:500]})], namespace="pdf_files")
            guardados += 1
        except Exception as e:
            print("❌ Error en fragmento", i, ":", str(e))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO pdf_entrenados (nombre, fecha_entrenamiento, texto_muestra) VALUES (%s, NOW(), %s)",
                (filename, texto[:500]))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": f"✅ Entrenado {filename} con {guardados} fragmentos"})

@app.route("/list_files")
def lista_archivos():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT nombre FROM pdf_archivos")
    nombres = [fila[0] for fila in cur.fetchall()]
    cur.close()
    conn.close()
    return jsonify({"files": nombres})

@app.route("/listar_vectores")
def listar_vectores():
    try:
        stats = index.describe_index_stats()
        n = stats.get("namespaces", {}).get("pdf_files", {}).get("vector_count", 0)
        return jsonify({"message": f"Namespace pdf_files tiene {n} vectores"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/monitorear_pinecone")
def monitorear_pinecone():
    try:
        stats = index.describe_index_stats()
        fullness = stats['index_fullness'] * 100
        total = stats['total_vector_count']
        return jsonify({"data": {
            "index_fullness_percentage": fullness,
            "total_vectors": total
        }})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route("/limpiar_pinecone", methods=["DELETE"])
def limpiar_pinecone():
    try:
        index.delete(delete_all=True, namespace="pdf_files")
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE pdf_archivos RESTART IDENTITY CASCADE")
        cur.execute("TRUNCATE TABLE pdf_entrenados RESTART IDENTITY CASCADE")
        conn.commit()
        cur.close()
        conn.close()
        for f in os.listdir(UPLOAD_FOLDER):
            os.remove(os.path.join(UPLOAD_FOLDER, f))
        return jsonify({"message": "✅ Pinecone, BD y archivos limpiados"})
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8081)))
