
from flask import Blueprint, request, jsonify, redirect, url_for
import mysql.connector
import os
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

teacher_registration_bp = Blueprint("teacher_registration", __name__)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        use_pure=True
    )


@teacher_registration_bp.route("/register/teacher", methods=["POST"])
def register_teacher():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    registration_code = request.form.get("registration_code", "").strip()
    stream_ids = request.form.getlist("stream_ids")

    expected_code = os.getenv("TEACHER_REGISTRATION_CODE", "")

    # Verify teacher registration code
    if not expected_code or registration_code != expected_code:
        return jsonify({
            "error": "Invalid teacher registration code."
        }), 403

    # Validate required fields
    if not name or not email or not password or not stream_ids:
        return jsonify({
            "error": "Please fill all fields and select at least one stream."
        }), 400

    # Normalize stream IDs and remove duplicates
    stream_ids = list(dict.fromkeys(stream_ids))

    # Reject invalid ID formats
    if not all(stream_id.isdigit() for stream_id in stream_ids):
        return jsonify({
            "error": "Invalid stream selected."
        }), 400

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        print("Registration database:", conn.database)
        print("MySQL host:", conn.server_host)
        print("MySQL port:", conn.server_port)
        cursor.execute("SELECT @@server_uuid")
        print("Flask server UUID:", cursor.fetchone())
        # Read all streams visible to this connection
        cursor.execute(
            "SELECT stream_id, stream_name FROM streams ORDER BY stream_id"
        )
        all_streams = cursor.fetchall()
        print("Streams visible to registration:", all_streams)
        
        
        cursor.execute("""
            SELECT
                DATABASE(),
                @@autocommit,
                @@transaction_isolation,
                CONNECTION_ID(),
                (SELECT COUNT(*) FROM streams)
        """)
        print("DEBUG:", cursor.fetchone())



        available_ids = {int(row[0]) for row in all_streams}
        selected_ids = {int(stream_id) for stream_id in stream_ids}

        # Validate selected IDs against the available streams
        if not selected_ids.issubset(available_ids):
            print("Selected IDs:", selected_ids)
            print("Available IDs:", available_ids)

            return jsonify({
                "error": "Selected stream is not available in the database used by the application."
            }), 400

        # Check duplicate email
        cursor.execute(
            "SELECT teacher_id FROM teachers WHERE email = %s",
            (email,)
        )

        if cursor.fetchone():
            return jsonify({
                "error": "This email is already registered."
            }), 409

        # Create teacher account
        hashed_password = generate_password_hash(password)

        cursor.execute(
            """
            INSERT INTO teachers (name, email, password)
            VALUES (%s, %s, %s)
            """,
            (name, email, hashed_password)
        )

        teacher_id = cursor.lastrowid

        # Assign selected streams to the teacher
        for stream_id in sorted(selected_ids):
            cursor.execute(
                """
                INSERT INTO teacher_streams (teacher_id, stream_id)
                VALUES (%s, %s)
                """,
                (teacher_id, stream_id)
            )

        conn.commit()

        return redirect(url_for("teacher_login"))

    except mysql.connector.Error:
        if conn and conn.is_connected():
            conn.rollback()

        import traceback
        traceback.print_exc()

        return jsonify({
            "error": "Registration failed due to a database error. Check the Flask terminal."
        }), 500

    finally:
        if cursor:
            cursor.close()

        if conn and conn.is_connected():
            conn.close()

