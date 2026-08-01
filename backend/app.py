# Main Flask application
from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/student-login")
def student_login():
    return render_template("student-login.html")

@app.route("/teacher-login")
def teacher_login():
    return render_template("Teacher-login.html")    

if __name__ == "__main__":
    app.run(debug=True)

