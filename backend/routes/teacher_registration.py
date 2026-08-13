from flask import Blueprint, request, jsonify
import mysql.connector
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

teacher_registration_bp = Blueprint('teacher_registration', __name__)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        use_pure=True
    )


@teacher_registration_bp.route('/register/teacher', methods=['POST'])
def register_teacher():

    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')

    if not all([name, email, password]):
        return jsonify({"error": "All fields are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT teacher_id FROM teachers WHERE email = %s",
        (email,)
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "This email is already registered."}), 409

    hashed_password = generate_password_hash(password)

    cursor.execute(
        "INSERT INTO teachers (name, email, password) VALUES (%s, %s, %s)",
        (name, email, hashed_password)
    )

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"message": "Teacher registered successfully."}), 201