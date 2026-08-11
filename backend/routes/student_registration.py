from flask import Blueprint, request, jsonify, redirect, url_for
import mysql.connector
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

student_registration_bp = Blueprint('student_registration', __name__)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        use_pure=True
    )


@student_registration_bp.route('/register/student', methods=['POST'])
def register_student():

    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    roll_number = request.form.get('roll_number')
    semester = request.form.get('semester')

    if not all([name, email, password, roll_number, semester]):
        return jsonify({"error": "All fields are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT student_id FROM students WHERE email = %s",
        (email,)
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "This email is already registered."}), 409

    cursor.execute(
        "SELECT student_id FROM students WHERE roll_number = %s",
        (roll_number,)
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "This roll number is already registered."}), 409

    hashed_password = generate_password_hash(password)

    cursor.execute(
        "INSERT INTO students (name, email, password, roll_number, semester) "
        "VALUES (%s, %s, %s, %s, %s)",
        (name, email, hashed_password, roll_number, semester)
    )

    conn.commit()

    cursor.close()
    conn.close()

    return redirect(url_for("student_login"))