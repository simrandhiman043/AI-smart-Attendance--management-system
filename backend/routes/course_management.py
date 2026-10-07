from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template
import mysql.connector
import os
from dotenv import load_dotenv

load_dotenv()

course_management_bp = Blueprint(
    "course_management",
    __name__
)


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        use_pure=True
    )


# ---------------------------------------------------------
# Make teacher's allowed streams available to templates
# ---------------------------------------------------------
@course_management_bp.context_processor
def inject_teacher_streams():

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return {
            "streams": []
        }

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute(
            """
            SELECT s.stream_id, s.stream_name
            FROM streams s
            INNER JOIN teacher_streams ts
                ON s.stream_id = ts.stream_id
            WHERE ts.teacher_id = %s
            ORDER BY s.stream_name
            """,
            (teacher_id,)
        )

        streams = cursor.fetchall()

        return {
            "streams": streams
        }

    finally:
        cursor.close()
        conn.close()


# ---------------------------------------------------------
# Add Course
# ---------------------------------------------------------
@course_management_bp.route("/teacher-course", methods=["POST"])
def teacher_course():

    course_name = request.form.get("course_name")
    course_code = request.form.get("course_code")
    stream_id = request.form.get("stream_id")
    semester = request.form.get("semester")
    section = request.form.get("section")

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    if not all([
        course_name,
        course_code,
        stream_id,
        semester,
        section
    ]):
        return "All fields are required.", 400

    # Validate semester
    try:
        semester = int(semester)
    except ValueError:
        return "Invalid semester selected.", 400

    if semester < 1 or semester > 8:
        return "Invalid semester selected.", 400

    # Validate section
    if section not in {"A", "B", "C", "D"}:
        return "Invalid section selected.", 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # Check that selected stream exists
        cursor.execute(
            """
            SELECT stream_id
            FROM streams
            WHERE stream_id = %s
            """,
            (stream_id,)
        )

        stream = cursor.fetchone()

        if not stream:
            return "Invalid stream selected.", 400

        # Check that this teacher teaches the selected stream
        cursor.execute(
            """
            SELECT stream_id
            FROM teacher_streams
            WHERE teacher_id = %s
            AND stream_id = %s
            """,
            (
                teacher_id,
                stream_id
            )
        )

        allowed_stream = cursor.fetchone()

        if not allowed_stream:
            return (
                "You are not allowed to create a course "
                "for this stream."
            ), 403

        # Insert course
        cursor.execute(
            """
            INSERT INTO courses
            (
                course_name,
                course_code,
                teacher_id,
                stream_id,
                semester,
                section
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                course_name,
                course_code,
                teacher_id,
                stream_id,
                semester,
                section
            )
        )

        conn.commit()

    except mysql.connector.Error as error:

        conn.rollback()

        return f"Database error: {error}", 500

    finally:

        cursor.close()
        conn.close()

    return redirect(url_for("manage_courses"))


# ---------------------------------------------------------
# Delete Course
# ---------------------------------------------------------
@course_management_bp.route(
    "/delete-course/<int:course_id>",
    methods=["POST"]
)
def delete_course(course_id):

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        cursor.execute(
            """
            DELETE FROM courses
            WHERE course_id = %s
            AND teacher_id = %s
            """,
            (
                course_id,
                teacher_id
            )
        )

        conn.commit()

    except mysql.connector.Error as error:

        conn.rollback()

        return f"Database error: {error}", 500

    finally:

        cursor.close()
        conn.close()

    return redirect(url_for("manage_courses"))


# ---------------------------------------------------------
# Edit Course
# ---------------------------------------------------------
@course_management_bp.route(
    "/edit-course/<int:course_id>",
    methods=["POST"]
)
def edit_course(course_id):

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    course_name = request.form.get("course_name")
    course_code = request.form.get("course_code")
    stream_id = request.form.get("stream_id")
    semester = request.form.get("semester")
    section = request.form.get("section")

    if not all([
        course_name,
        course_code,
        stream_id,
        semester,
        section
    ]):
        return "All fields are required.", 400

    # Validate semester
    try:
        semester = int(semester)
    except ValueError:
        return "Invalid semester selected.", 400

    if semester < 1 or semester > 8:
        return "Invalid semester selected.", 400

    # Validate section
    if section not in {"A", "B", "C", "D"}:
        return "Invalid section selected.", 400

    conn = get_db_connection()
    cursor = conn.cursor()

    try:

        # Check course belongs to logged-in teacher
        cursor.execute(
            """
            SELECT
                stream_id,
                semester,
                section
            FROM courses
            WHERE course_id = %s
            AND teacher_id = %s
            """,
            (
                course_id,
                teacher_id
            )
        )

        course = cursor.fetchone()

        if not course:
            return "Course not found or access denied.", 404

        old_stream_id = course[0]
        old_semester = course[1]
        old_section = course[2]

        # Check selected stream is taught by this teacher
        cursor.execute(
            """
            SELECT stream_id
            FROM teacher_streams
            WHERE teacher_id = %s
            AND stream_id = %s
            """,
            (
                teacher_id,
                stream_id
            )
        )

        allowed_stream = cursor.fetchone()

        if not allowed_stream:
            return "You are not allowed to use this stream.", 403

        # Check whether stream, semester or section is changing
        details_changed = (
            int(old_stream_id) != int(stream_id)
            or old_semester != semester
            or old_section != section
        )

        # If course already has enrolled students,
        # these matching fields cannot be changed
        if details_changed:

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM enrollments
                WHERE course_id = %s
                """,
                (course_id,)
            )

            enrolled_count = cursor.fetchone()[0]

            if enrolled_count > 0:
                return (
                    "This course already has enrolled students. "
                    "Its stream, semester or section cannot be changed."
                ), 400

        # Update course
        cursor.execute(
            """
            UPDATE courses
            SET
                course_name = %s,
                course_code = %s,
                stream_id = %s,
                semester = %s,
                section = %s
            WHERE course_id = %s
            AND teacher_id = %s
            """,
            (
                course_name,
                course_code,
                stream_id,
                semester,
                section,
                course_id,
                teacher_id
            )
        )

        conn.commit()

    except mysql.connector.Error as error:

        conn.rollback()

        return f"Database error: {error}", 500

    finally:

        cursor.close()
        conn.close()

    return redirect(url_for("manage_courses"))

