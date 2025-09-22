import os
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
