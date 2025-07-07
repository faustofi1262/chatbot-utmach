from flask import Flask, request, jsonify, render_template, send_from_directory
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

UPLOAD_FOLDER = "./upload"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

@app.route("/admin")
def admin():
    return render_template("admin.html")

@app.route("/upload", methods=["POST"])
def upload_pdf():
    try:
        pdf_file = request.files["file"]
        filename = pdf_file.filename
        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        pdf_file.save(pdf_path)

        cursor.execute("INSERT INTO pdf_archivos (nombre, ruta_archivo) VALUES (%s, %s)", (filename, pdf_path))
        db.commit()
        return jsonify({"message": f"Archivo {filename} subido correctamente."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/entrenar_pdf", methods=["POST"])
def entrenar_pdf():
    try:
        data = request.get_json()
        filename = data.get("nombre")
        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        texto_completo = ""
        with pdfplumber.open(pdf_path) as pdf:
            for pagina in pdf.pages:
                texto_completo += pagina.extract_text() or ""

        fragmentos = re.findall(r'[^.!?]*[.!?]', texto_completo)
        for i, frag in enumerate(fragmentos):
            response = openai.Embedding.create(model="text-embedding-ada-002", input=frag)
            embedding = response["data"][0]["embedding"]
            index.upsert(vectors=[(f"{filename}_{i}", embedding)], namespace="pdf_files")

        cursor.execute("INSERT INTO pdf_entrenados (nombre, fecha_entrenamiento, texto_muestra) VALUES (%s, NOW(), %s)", (filename, texto_completo[:500]))
        db.commit()
        return jsonify({"message": f"PDF {filename} entrenado correctamente."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/list_files")
def list_files():
    cursor.execute("SELECT nombre FROM pdf_archivos")
    files = [row[0] for row in cursor.fetchall()]
    return jsonify({"files": files})

@app.route("/delete/<filename>", methods=["DELETE"])
def delete_pdf(filename):
    try:
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        cursor.execute("DELETE FROM pdf_archivos WHERE nombre = %s", (filename,))
        cursor.execute("DELETE FROM pdf_entrenados WHERE nombre = %s", (filename,))
        db.commit()

        return jsonify({"message": f"Archivo {filename} eliminado correctamente."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
