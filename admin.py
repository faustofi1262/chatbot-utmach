from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import pdfplumber
import openai
from pinecone import Pinecone, ServerlessSpec
import pinecone
import re
from nltk.tokenize import sent_tokenize
from nltk import download
import os
import psycopg2
from dotenv import load_dotenv

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
    dbname="chatbot_utmach_db"
    sslmode='require'  # 🔐 Añade esta línea
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

# Carpeta de carga
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
# RUTAS PRINCIPALES
# ----------------------------
@app.route("/upload", methods=["POST", "OPTIONS"])
def upload_pdf():
    try:
        if request.method == "OPTIONS":
            return jsonify({"message": "Método OPTIONS permitido"}), 200

        if "file" not in request.files:
            return jsonify({"error": "No se envió ningún archivo."}), 400

        pdf_file = request.files["file"]
        filename = pdf_file.filename
        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        pdf_file.save(pdf_path)

        cursor.execute("INSERT INTO pdf_archivos (nombre, ruta_archivo) VALUES (%s, %s)", (filename, pdf_path))
        db.commit()

        return jsonify({"message": f"Documento {filename} almacenado correctamente."})
    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500

@app.route("/entrenar_pdf", methods=["POST"])
def entrenar_pdf():
    try:
        data = request.get_json()
        filename = data.get("nombre")
        if not filename:
            return jsonify({"error": "Nombre de archivo no proporcionado"}), 400

        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if not os.path.exists(pdf_path):
            return jsonify({"error": "Archivo no encontrado."}), 404

        texto_completo = ""
        with pdfplumber.open(pdf_path) as pdf:
            for pagina in pdf.pages:
                texto_completo += pagina.extract_text() or ""

        if not texto_completo.strip():
            return jsonify({"error": "El PDF no contiene texto o no se pudo extraer."}), 400

        fragmentos = dividir_texto(texto_completo, max_tokens=1000)
        fragmentos_guardados = 0

        for i, fragmento in enumerate(fragmentos):
            try:
                response = openai.Embedding.create(
                    model="text-embedding-ada-002",
                    input=fragmento
                )
                embedding = response['data'][0]['embedding']

                index.upsert(
                    vectors=[
                        (f"{filename}_fragmento_{i}", embedding, {"response": fragmento[:500]})
                    ],
                    namespace="pdf_files"
                )
                fragmentos_guardados += 1
            except Exception as e:
                print(f"❌ Error en fragmento {i}: {str(e)}")
                continue

        cursor.execute(
            "INSERT INTO pdf_entrenados (nombre, fecha_entrenamiento, texto_muestra) VALUES (%s, NOW(), %s)",
            (filename, texto_completo[:500])
        )
        db.commit()

        return jsonify({"message": f"PDF {filename} entrenado correctamente con {fragmentos_guardados} fragmentos."})
    except Exception as e:
        return jsonify({"error": f"Error al entrenar PDF: {str(e)}"}), 500

@app.route("/upload/<filename>")
def get_uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/delete/<filename>", methods=["DELETE"])
def delete_pdf(filename):
    try:
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        if os.path.exists(file_path):
            os.remove(file_path)

        cursor.execute("DELETE FROM pdf_archivos WHERE nombre = %s", (filename,))
        cursor.execute("DELETE FROM pdf_entrenados WHERE nombre = %s", (filename,))
        db.commit()

        index.delete(
            ids=[f"{filename}_fragmento_{i}" for i in range(50)],
            namespace="pdf_files"
        )

        return jsonify({"message": f"✅ Archivo {filename} eliminado correctamente."})
    except Exception as e:
        return jsonify({"error": f"❌ Error al eliminar el archivo: {str(e)}"}), 500

@app.route("/list_files")
def lista_archivos():
    try:
        cursor.execute("SELECT nombre FROM pdf_archivos")
        resultados = cursor.fetchall()
        nombres = [fila[0] for fila in resultados]
        return jsonify({"files": nombres})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
        return jsonify({"error": f"Error al obtener datos de Pinecone: {str(e)}"}), 500

@app.route("/limpiar_pinecone", methods=["DELETE"])
def limpiar_pinecone():
    try:
        index.delete(delete_all=True, namespace="pdf_files")

        folder = './upload'
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

        cursor.execute("TRUNCATE TABLE pdf_archivos RESTART IDENTITY CASCADE")
        cursor.execute("TRUNCATE TABLE pdf_entrenados RESTART IDENTITY CASCADE")
        db.commit()

        return jsonify({"message": "✅ Todos los datos en Pinecone, la base de datos y la carpeta upload han sido eliminados correctamente."})
    except Exception as e:
        return jsonify({"error": f"❌ Error al limpiar Pinecone: {str(e)}"}), 500
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

if __name__ == "__main__":
    print("📌 Vectores en Pinecone:", index.describe_index_stats())
    app.run(host="0.0.0.0", port=8081, debug=True)
