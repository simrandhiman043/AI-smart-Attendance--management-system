from flask import Blueprint, request, jsonify, session
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

course_management_bp = Blueprint('course_management', __name__)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        use_pure=True
    )


@course_management_bp.route('/add-course', methods=['POST'])
def add_course():

    course_name = request.form.get('course_name')
    course_code = request.form.get('course_code')
    teacher_id = session.get("teacher_id")

    if not all([course_name, course_code, teacher_id]):
        return jsonify({"error": "All fields are required."}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT course_id FROM courses WHERE course_code = %s",
        (course_code,)
    )

    if cursor.fetchone():
        cursor.close()
        conn.close()
        return jsonify({"error": "This course code already exists."}), 409

    cursor.execute(
        """
        INSERT INTO courses (course_name, course_code, teacher_id)
        VALUES (%s, %s, %s)
        """,
        (course_name, course_code, teacher_id)
    )

    conn.commit()

    cursor.close()
    conn.close()

    return jsonify({"message": "Course added successfully."}), 201