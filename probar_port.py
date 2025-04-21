from flask import Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "OK"

app.run(port=3001)
