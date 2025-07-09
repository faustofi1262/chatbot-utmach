from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_cors import CORS
import re
import os
import psycopg2
from datetime import datetime
from dotenv import load_dotenv
from io import BytesIO
import fitz  # ✅ Usamos PyMuPDF para extraer texto desde memoria
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
    print(f"✅ Índice '{INDEX_NAME}' creado correctamente")
else:
    print(f"✅ El índice '{INDEX_NAME}' ya existe")

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
@app.route("/admin")
def admin():
    return render_template("admin.html")

@app.route("/upload", methods=["POST"])
def subir_pdf():
    archivo = request.files.get('archivo')
    if archivo is None or archivo.filename == '':
        return jsonify({"error": "❌ No se seleccionó ningún archivo"}), 400

    nombre = archivo.filename
    contenido_binario = archivo.read()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO pdf_archivos (nombre, contenido, fecha_subida) VALUES (%s, %s, NOW())",
            (nombre, psycopg2.Binary(contenido_binario))
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

@app.route("/list_files")
def lista_archivos():
    try:
        cursor.execute("SELECT nombre FROM pdf_archivos")
        resultados = cursor.fetchall()
        nombres = [fila[0] for fila in resultados]
        return jsonify({"files": nombres})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500

@app.route("/delete/<filename>", methods=["DELETE"])
def delete_pdf(filename):
    try:
        cursor.execute("DELETE FROM pdf_archivos WHERE nombre = %s", (filename,))
        cursor.execute("DELETE FROM pdf_entrenados WHERE nombre = %s", (filename,))
        db.commit()

        index.delete(
            ids=[f"{filename}_fragmento_{i}" for i in range(50)],
            namespace="pdf_files"
        )

        return jsonify({"message": f"✅ Archivo {filename} eliminado correctamente."})
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"❌ Error al eliminar el archivo: {str(e)}"}), 500

@app.route("/listar_vectores")
def listar_vectores():
    try:
        stats = index.describe_index_stats()
        namespaces = stats.get("namespaces", {})

        if "pdf_files" in namespaces:
            vector_count = namespaces["pdf_files"].get("vector_count", 0)
            return jsonify({"message": f"Namespace 'pdf_files' contiene {vector_count} vectores."})
        else:
            return jsonify({"message": "No se encontraron vectores en el namespace 'pdf_files'."})
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Error al listar vectores: {str(e)}"}), 500

@app.route("/monitorear_pinecone")
def monitorear_pinecone():
    try:
        stats = index.describe_index_stats()
        index_fullness_percentage = stats['index_fullness'] * 100
        total_vectors = stats['total_vector_count']

        data = {
            "index_fullness_percentage": index_fullness_percentage,
            "total_vectors": total_vectors
        }
        return jsonify({"data": data}), 200
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"Error al obtener datos de Pinecone: {str(e)}"}), 500

@app.route("/limpiar_pinecone", methods=["DELETE"])
def limpiar_pinecone():
    try:
        index.delete(delete_all=True, namespace="pdf_files")

        cursor.execute("TRUNCATE TABLE pdf_archivos RESTART IDENTITY CASCADE")
        cursor.execute("TRUNCATE TABLE pdf_entrenados RESTART IDENTITY CASCADE")
        db.commit()

        return jsonify({"message": "✅ Todos los datos en Pinecone y la base de datos han sido eliminados correctamente."})
    except Exception as e:
        db.rollback()
        return jsonify({"error": f"❌ Error al limpiar Pinecone: {str(e)}"}), 500

@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        username = data.get("username").strip()
        password = data.get("password").strip()

        cursor.execute("SELECT password FROM usuarios WHERE username = %s", (username,))
        resultado = cursor.fetchone()

        if resultado and resultado[0].strip() == password:
            return jsonify({"message": "Login exitoso"}), 200
        else:
            return jsonify({"error": "Usuario o contraseña incorrectos"}), 401
    except Exception as e:
        return jsonify({"error": f"Error en la autenticación: {str(e)}"}), 500

@app.route("/")
def mostrar_login():
    return render_template("login.html")

@app.route("/monitor")
def monitor():
    return render_template("monitor.html")

print("📌 Vectores en Pinecone:", index.describe_index_stats())
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)


