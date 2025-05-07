# chatbot.py actualizado y corregido
from flask import Flask, request, jsonify
from flask_cors import CORS
import openai
from pinecone import Pinecone, ServerlessSpec
import psycopg2
import os
from dotenv import load_dotenv

# ----------------------------
# Cargar variables de entorno
# ----------------------------
load_dotenv()

# ----------------------------
# Configurar OpenAI
# ----------------------------
openai.api_key = os.getenv("OPENAI_API_KEY")

# ----------------------------
# Configurar Pinecone
# ----------------------------
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
INDEX_NAME = os.getenv("INDEX_NAME")

pc = Pinecone(api_key=PINECONE_API_KEY)

# Verificar si el índice existe
if INDEX_NAME not in pc.list_indexes().names():
    pc.create_index(
        name=INDEX_NAME,
        dimension=1536,
        metric="cosine",
        spec=ServerlessSpec(cloud="aws", region="us-east-1")
    )
    print(f"✅ Índice '{INDEX_NAME}' creado correctamente.")
else:
    print(f"✅ El índice '{INDEX_NAME}' ya existe.")

index = pc.Index(INDEX_NAME)

# ----------------------------
# Conectar a la base de datos PostgreSQL
# ----------------------------
db = psycopg2.connect(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
    dbname=os.getenv("DB_DATABASE")
)
cursor = db.cursor()

# ----------------------------
# Crear la app Flask
# ----------------------------
app = Flask(__name__)
CORS(app)

# ----------------------------
# Función para obtener embeddings
# ----------------------------
def get_embedding(text):
    response = openai.Embedding.create(
        input=text,
        model="text-embedding-ada-002"
    )
    return response['data'][0]['embedding']

# ----------------------------
# Buscar en Pinecone
# ----------------------------
def search_pinecone(query, user_id):
    try:
        query_embedding = get_embedding(query)

        result = index.query(
            vector=query_embedding,
            top_k=5,  # Puedes ajustar top_k
            include_metadata=True,
            namespace="pdf_files"
        )

        matches = result.get("matches", [])
        responses = [match['metadata']['response'] for match in matches]
        return responses
    except Exception as e:
        print(f"❌ Error al buscar en Pinecone: {str(e)}")
        return []

# ----------------------------
# Endpoint de Chat
# ----------------------------
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_id = data.get("user_id", "default")
    user_message = data.get("message", "")

    if not user_message:
        return jsonify({"response": "No se recibió ningún mensaje."}), 400

    # 1. Buscar primero en Pinecone
    context = search_pinecone(user_message, user_id)

    # 2. Preparar el contexto y preguntar a OpenAI
    try:
        messages = [{"role": "system", "content": "Eres un asistente experto en el proceso de admisión de la UTMACH."}]
        if context:
            for fragment in context:
                messages.append({"role": "user", "content": fragment})

        messages.append({"role": "user", "content": user_message})

        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        bot_response = response.choices[0].message.content

    except Exception as e:
        bot_response = f"❌ Error al conectar con OpenAI: {str(e)}"
        return jsonify({"response": bot_response})

    # 3. Guardar conversación en PostgreSQL
    try:
        cursor.execute(
            "INSERT INTO conversaciones (user_id, pregunta, respuesta) VALUES (%s, %s, %s)",
            (user_id, user_message, bot_response)
        )
        db.commit()
    except Exception as db_error:
        print(f"⚠️ Error al guardar conversación en base de datos: {str(db_error)}")

    return jsonify({"response": bot_response})

# ----------------------------
# Ejecutar la app
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8082, debug=True)
