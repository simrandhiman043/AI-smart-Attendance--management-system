from flask import Blueprint, request, jsonify, redirect, url_for
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
    stream_ids = request.form.getlist('stream_ids')

    if not all([name, email, password]) or not stream_ids:
        return jsonify({"error": "All fields are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Validate selected streams
    placeholders = ','.join(['%s'] * len(stream_ids))

    cursor.execute(
        f"""
        SELECT stream_id
        FROM streams
        WHERE stream_id IN ({placeholders})
        """,
        tuple(stream_ids)
    )

    valid_stream_ids = {str(row[0]) for row in cursor.fetchall()}

    if len(valid_stream_ids) != len(set(stream_ids)):
        cursor.close()
        conn.close()
        return jsonify({"error": "Invalid stream selected."}), 400

    # Check duplicate email
    cursor.execute(
        "SELECT teacher_id FROM teachers WHERE email = %s",
        (email,)
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "This email is already registered."}), 409

    hashed_password = generate_password_hash(password)

    # Create teacher
    cursor.execute(
        """
        INSERT INTO teachers (name, email, password)
        VALUES (%s, %s, %s)
        """,
        (name, email, hashed_password)
    )

    teacher_id = cursor.lastrowid

    # Assign selected streams
    for stream_id in set(stream_ids):
        cursor.execute(
            """
            INSERT INTO teacher_streams (teacher_id, stream_id)
            VALUES (%s, %s)
            """,
            (teacher_id, stream_id)
        )

    conn.commit()

    cursor.close()
    conn.close()

    return redirect(url_for("teacher_login"))