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
    stream_id = request.form.get('stream_id')
    section = request.form.get('section')

    if not all([
        name,
        email,
        password,
        roll_number,
        semester,
        stream_id,
        section
    ]):
        return jsonify({"error": "All fields are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Validate selected stream
    cursor.execute(
        "SELECT stream_id FROM streams WHERE stream_id = %s",
        (stream_id,)
    )

    if not cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid stream selected."}), 400

    # Validate selected section
    allowed_sections = {'A', 'B', 'C', 'D'}

    if section not in allowed_sections:
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid section selected."}), 400

    # Check duplicate email
    cursor.execute(
        "SELECT student_id FROM students WHERE email = %s",
        (email,)
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "This email is already registered."}), 409

    # Check duplicate roll number
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
        """
        INSERT INTO students
        (
            name,
            email,
            password,
            roll_number,
            semester,
            stream_id,
            section
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            name,
            email,
            hashed_password,
            roll_number,
            semester,
            stream_id,
            section
        )
    )

    conn.commit()

    cursor.close()
    conn.close()

    return redirect(url_for("student_login"))
