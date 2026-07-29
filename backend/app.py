# Main Flask application
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "<h1>AI Smart Attendance Management System</h1>"

if __name__ == "__main__":
    app.run(debug=True)
