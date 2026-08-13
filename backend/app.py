# Main Flask application
from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
from dotenv import load_dotenv
import os
from routes.student_registration import student_registration_bp
from routes.teacher_registration import teacher_registration_bp
from werkzeug.security import check_password_hash

app = Flask(__name__)
load_dotenv()  # Load environment variables from .env file
app.register_blueprint(student_registration_bp)
app.register_blueprint(teacher_registration_bp)


db = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE"),
    use_pure=True
)

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/student-login", methods=["GET", "POST"])
def student_login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM students WHERE email = %s",
            (email,)
        )

        student = cursor.fetchone()
        cursor.close()

        if student and check_password_hash(student["password"], password):
            return render_template("student-dashboard.html", student=student)

        return "Invalid email or password", 401

    return render_template("student-login.html")

@app.route("/teacher-login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        cursor = db.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM teachers WHERE email = %s",
            (email,)
        )

        teacher = cursor.fetchone()
        cursor.close()

        if teacher and check_password_hash(teacher["password"], password):
            return render_template(
                "teacher-dashboard.html",
                teacher=teacher
            )

        return "Invalid email or password", 401

    return render_template("teacher-login.html")

@app.route("/student-dashboard")
def student_dashboard():  
    return render_template("student-dashboard.html")  

@app.route("/teacher-dashboard")
def teacher_dashboard():
    return render_template("teacher-dashboard.html")

@app.route('/student-register')
def student_register():
    return render_template('student-register.html')

@app.route("/teacher-register")
def teacher_register():
    return render_template("teacher-register.html")



if __name__ == "__main__":
    app.run(debug=True)

