from flask import Flask, render_template, request, jsonify
from flask_cors import CORS
import re
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from io import BytesIO
import fitz
from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
import pinecone

load_dotenv()
# ----------------------------
# CONFIGURACIONES GENERALES
# ----------------------------
app = Flask(__name__)
CORS(app, supports_credentials=True)

UPLOAD_FOLDER = os.path.join(os.getcwd(), 'archivos')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# ----------------------------
# CONEXIÓN A LA BASE DE DATOS
# ----------------------------
db = psycopg2.connect(
    host="ep-calm-tooth-a4teb7mi-pooler.us-east-1.aws.neon.tech",
    port=5432,
    user="chatbot-utmach_db_owner",
    password="npg_Tq8jFbxgQk0L",
    dbname="chatbot-utmach_db",
    sslmode='require'
)
cursor = db.cursor()

def get_db_connection():
    return psycopg2.connect(
        host="ep-calm-tooth-a4teb7mi-pooler.us-east-1.aws.neon.tech",
        port=5432,
        user="chatbot-utmach_db_owner",
        password="npg_Tq8jFbxgQk0L",
        dbname="chatbot-utmach_db",
        sslmode='require'
    )
# ----------------------------
# CONFIGURACIÓN DE PINECONE
# ----------------------------
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
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
# RUTAS PRINCIPALES
# ----------------------------
@app.route("/upload", methods=["POST"])
def subir_pdf():
    archivo = request.files.get('archivo')
    print('🟢 Archivo recibido:', archivo.filename)
    archivo.seek(0)

    if archivo is None or archivo.filename == '':
        return jsonify({"error": "❌ No se seleccionó ningún archivo"}), 400

    print("🟢 Archivo recibido:", archivo.filename)
    archivo.seek(0)
    contenido_binario = archivo.read()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pdf_archivos (nombre, contenido, fecha_subida) VALUES (%s, %s, NOW())",
            (archivo.filename, psycopg2.Binary(contenido_binario))
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "✅ Archivo guardado en Neon correctamente"})
    except Exception as e:
        return jsonify({"error": f"❌ Error al guardar el PDF en Neon: {str(e)}"}), 500

@app.route("/entrenar_pdf", methods=["POST"])
def entrenar_pdf():
    try:
        data = request.get_json()
        filename = data.get("nombre")
        if not filename:
            return jsonify({"error": "Nombre de archivo no proporcionado"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT contenido FROM pdf_archivos WHERE nombre = %s", (filename,))
        resultado = cur.fetchone()
        conn.close()

        if not resultado:
            return jsonify({"error": "Archivo no encontrado en la base de datos"}), 404

        buffer = BytesIO(resultado[0])
        doc = fitz.open(stream=buffer, filetype="pdf")
        texto_completo = "\n".join([pagina.get_text() for pagina in doc])
        doc.close()

        if not texto_completo.strip():
            return jsonify({"error": "El PDF no contiene texto o no se pudo extraer."}), 400

        fragmentos = dividir_texto(texto_completo, max_tokens=1000)
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        fragmentos_guardados = 0
        for i, fragmento in enumerate(fragmentos):
            try:
                response = client.embeddings.create(
                    model="text-embedding-ada-002",
                    input=fragmento
                )
                embedding = response.data[0].embedding
                index.upsert(
                    vectors=[(f"{filename}_fragmento_{i}", embedding, {"response": fragmento[:500]})],
                    namespace="pdf_files"
                )
                fragmentos_guardados += 1
            except Exception as e:
                print(f"❌ Error en fragmento {i}: {str(e)}")
                continue

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pdf_entrenados (nombre, fecha_entrenamiento, texto_muestra) VALUES (%s, NOW(), %s)",
            (filename, texto_completo[:500])
        )
        conn.commit()
        conn.close()

        return jsonify({"message": f"✅ PDF {filename} entrenado correctamente con {fragmentos_guardados} fragmentos."})
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"❌ Error al entrenar PDF: {str(e)}"}), 500
@app.route("/test_upload")
def test_upload():
        return render_template("test_upload")

