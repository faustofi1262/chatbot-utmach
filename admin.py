from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import pdfplumber
import openai
import mysql.connector
from pinecone import Pinecone, ServerlessSpec
import pinecone  # ✅ NUEVA LIBRERÍA IMPORTADA
import re  # ✅ IMPORTACIÓN NUEVA PARA USAR expresiones regulares
from nltk.tokenize import sent_tokenize
from nltk import download 
# ----------------------------
# CONFIGURACIONES GENERALES
# ----------------------------
app = Flask(__name__)
CORS(app, supports_credentials=True)

# ----------------------------
# CONEXIÓN A LA BASE DE DATOS
# ----------------------------
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="",
    database="chatbot_utmach"
)
cursor = conn.cursor()

# ----------------------------
# CONFIGURACIÓN DE API KEYS
# ---------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("INDEX_NAME")  # Mejor también cargar el nombre del índice
# ----------------------------
# COMPROBAR SI ESTA CONFIGURADO CONRRECTAMENTE
# ----------------------------
@app.route("/test_openai", methods=["GET"])
def test_openai():
    try:
        response = openai.Engine.list()  # Solicitud simple a OpenAI para listar motores disponibles
        return jsonify({"message": "Conexión exitosa con OpenAI.", "data": response}), 200
    except Exception as e:
        return jsonify({"error": f"Error al conectar con OpenAI: {str(e)}"}), 500
# ----------------------------
# CONFIGURACIÓN DE PINECONE
# ----------------------------
pc = Pinecone(api_key=PINECONE_API_KEY)
index = pc.Index(INDEX_NAME)
index_name = "chatbot-utmach"
if index_name not in pc.list_indexes().names():
    pc.create_index(
        name=index_name,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")  # Cambia la región si es diferente
    )
    print(f"✅ Índice '{index_name}' creado correctamente")
else:
    print(f"✅ El índice '{index_name}' ya existe")

    index = pc.Index(index_name)
    print("✅ Pinecone configurado correctamente.")

# Carpeta de carga
UPLOAD_FOLDER = "./upload"
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ----------------------------
# FUNCIONES AUXILIARES
# ----------------------------
def dividir_texto(texto, max_tokens=1000):
    # Divide el texto en oraciones usando expresiones regulares
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
        conn.commit()

        return jsonify({"message": f"Documento {filename} almacenado correctamente."})

    except Exception as e:
        return jsonify({"error": f"Error en el servidor: {str(e)}"}), 500
# ----------------------------
# ENTRENAR PDF
# ----------------------------
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
                
                # 🔄 Intentar varias veces si falla al enviar a Pinecone
                max_retries = 3
                retries = 0
                success = False

                while retries < max_retries and not success:
                    try:
                        index.upsert(
                            vectors=[
                                (f"{filename}_fragmento_{i}", embedding, {"response": fragmento[:500]})
                            ],
                            namespace="pdf_files"
                        )
                        success = True
                        fragmentos_guardados += 1
                    except Exception as e:
                        retries += 1
                        print(f"❌ Error al enviar fragmento {i} a Pinecone. Intento {retries}/{max_retries}. Error: {str(e)}")
                
                if success:
                    print(f"✅ Fragmento {i} almacenado correctamente en Pinecone.")
                else:
                    print(f"❌ Fragmento {i} falló después de {max_retries} intentos.")
                
            except Exception as e:
                print(f"❌ Error al procesar un fragmento {i}: {str(e)}")
                continue

        # 🔥 REGISTRO EN LA TABLA pdf_entrenados
        cursor.execute(
            "INSERT INTO pdf_entrenados (nombre, fecha_entrenamiento, texto_muestra) VALUES (%s, NOW(), %s)",
            (filename, texto_completo[:500])
        )
        conn.commit()

        # 🔔 Si todo se ejecuta correctamente
        return jsonify({"message": f"PDF {filename} entrenado correctamente con {fragmentos_guardados} fragmentos."})

    except Exception as e:
        return jsonify({"error": f"Error al entrenar PDF: {str(e)}"}), 500

@app.route("/upload/<filename>")
def get_uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/delete/<filename>", methods=["DELETE"])
def delete_pdf(filename):
    try:
        # Ruta completa del archivo
        file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

        # 🔥 Eliminar el archivo del sistema de archivos si existe
        if os.path.exists(file_path):
            os.remove(file_path)
        
        # 🔥 Eliminar el registro del archivo en la base de datos
        cursor.execute("DELETE FROM pdf_archivos WHERE nombre = %s", (filename,))
        cursor.execute("DELETE FROM pdf_entrenados WHERE nombre = %s", (filename,))
        conn.commit()

         # 🔥 Eliminar todos los fragmentos relacionados al archivo de Pinecone
        index.delete(
            ids=[f"{filename}_fragmento_{i}" for i in range(50)],  # Cambia 50 si usas otro número de fragmentos
            namespace="pdf_files"  # Indica el namespace específico
        )

        return jsonify({"message": f"✅ Archivo {filename} eliminado correctamente de la base de datos, almacenamiento y Pinecone."})
    
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
# ----------------------------
# LISTAR VECTORES EN PINECONE
# ----------------------------
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
# ----------------------------
# MONITOREAR PINECONE USO DE ESPACIO Y VECTORES
# ----------------------------
@app.route("/monitorear_pinecone")
def monitorear_pinecone():
    try:
        stats = index.describe_index_stats()
        index_fullness_percentage = stats['index_fullness'] * 100
        total_vectors = stats['total_vector_count']
        
        # Asegúrate de retornar un JSON válido con jsonify()
        #return jsonify({
        data = {
              "index_fullness_percentage": index_fullness_percentage,  # Convertir a porcentaje
              "total_vectors": total_vectors
            }
        #})
        return jsonify({"data": data}), 200  # 👈 Respuesta JSON bien estructurada
    except Exception as e:
        return jsonify({"error": f"Error al obtener datos de Pinecone: {str(e)}"}), 500
# ----------------------------
# LIMPIAR  PINECONE 
# ----------------------------   
@app.route("/limpiar_pinecone", methods=["DELETE"])
def limpiar_pinecone():
    try:
        index.delete(delete_all=True, namespace="pdf_files")

        # Eliminar todos los archivos de la carpeta upload
        folder = './upload'
        for filename in os.listdir(folder):
            file_path = os.path.join(folder, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

        # Limpiar las tablas de la base de datos
        cursor.execute("TRUNCATE TABLE pdf_archivos")
        cursor.execute("TRUNCATE TABLE pdf_entrenados")
        conn.commit()

        return jsonify({"message": "✅ Todos los datos en Pinecone, la base de datos y la carpeta upload han sido eliminados correctamente."})

    except Exception as e:
        return jsonify({"error": f"❌ Error al limpiar Pinecone: {str(e)}"}), 500

if __name__ == "__main__":
    print("📌 Vectores en Pinecone:", index.describe_index_stats())
    app.run(host="0.0.0.0", port=8081, debug=True)
