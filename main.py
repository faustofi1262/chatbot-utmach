import subprocess

try:
    chatbot = subprocess.Popen(["python", "chatbot.py"])
    admin = subprocess.Popen(["python", "admin.py"])
    print("✅ Ambos procesos iniciados.")
except Exception as e:
    print(f"❌ Error al iniciar procesos: {e}")