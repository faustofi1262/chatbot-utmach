from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pdfplumber
import openai
from pinecone import Pinecone, ServerlessSpec
import pinecone
import re
import os
import psycopg2

# ----------------------------
# CONFIGURACIONES GENERALES
# ----------------------------
app = Flask(__name__)
CORS(app, supports_credentials=True)

# ----------------------------
# CONEXIÓN A LA BASE DE DATOS
# ----------------------------
db = psycopg2.connect(
    host="dpg-d0cmqv3e5dus73ahtvi0-a.ohio-postgres.render.com",
    port=5432,
    user="chatbot_utmach_db_user",
    password="OtqdjEoPWs6Nmju61FtNuxKKHewZUm0K",
    dbname="chatbot_utmach_db",
    sslmode='require'
)
cursor = db.cursor()

# ----------------------------
# CONFIGURACIÓN DE API KEYS
# ----------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("INDEX_NAME")

# ----------------------------
# CONFIGURACIÓN DE PINECONE
# ----------------------------
pc = Pinecone(api_key=PINECONE_API_KEY)
index_name = INDEX_NAME

if index_name not in pc.list_indexes().names():
    pc.create_index(
        name=index_name,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )
    print(f"✅ Índice '{index_name}' creado correctamente")
else:
    print(f"✅ El índice '{index_name}' ya existe")

index = pc.Index(index_name)

# ----------------------------
# CARPETA DE CARGA
# ----------------------------
UPLOAD_FOLDER = "./upload"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ----------------------------
# FUNCIONES AUXILIARES
# ----------------------------
def dividir_texto(texto, max_tokens=1000):
    oraciones = re.findall(r'[^.!?]*[.!?]', texto, re.DOTALL)
    fragmentos = []
    actual = ""
    for oracion in oraciones:
        if len(actual) + len(oracion) <= max_tokens:
            actual += " " + oracion.strip()
        else:
            fragmentos.append(actual.strip())
            actual = oracion.strip()
    if actual:
        fragmentos.append(actual.strip())
    return fragmentos

# ----------------------------
# RUTAS DEL SISTEMA
# ----------------------------
@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")

        print("🔵 Usuario recibido:", username)
        print("🟠 Contraseña recibida:", password)

        cursor.execute("SELECT password FROM usuarios WHERE username = %s", (username,))
        resultado = cursor.fetchone()

        print("🟣 Resultado en base de datos:", resultado)

        if resultado and resultado[0] == password:
            print("✅ Coincidencia encontrada. Acceso permitido.")
            return jsonify({"message": "Login exitoso"}), 200
        else:
            print("❌ No coincide la contraseña o usuario.")
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
    except Exception as e:
        print(f"🔥 ERROR en backend: {str(e)}")
        return jsonify({"error": f"Error en la autenticación: {str(e)}"}), 500

@app.route("/debug", methods=["GET"])
def debug():
    return jsonify({"status": "API activa"}), 200

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"message": "Backend activo"}), 200

# (el resto de rutas como /upload, /entrenar_pdf, etc. deberían ir aquí)

# ----------------------------
# EJECUCIÓN DEL SERVIDOR
# ----------------------------
if __name__ == "__main__":
    print("📌 Vectores en Pinecone:", index.describe_index_stats())
    app.run(host="0.0.0.0", port=8081, debug=True)