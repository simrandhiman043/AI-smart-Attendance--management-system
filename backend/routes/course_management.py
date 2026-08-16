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


@course_management_bp.route("/teacher-course", methods=["GET", "POST"])
def teacher_course():

    if request.method == "POST":

        course_name = request.form.get("course_name")
        course_code = request.form.get("course_code")
        teacher_id = session.get("teacher_id")

        if not all([course_name, course_code, teacher_id]):
            return "All fields are required.", 400

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO courses
                (course_name, course_code, teacher_id)
                VALUES (%s, %s, %s)
                """,
                (course_name, course_code, teacher_id)
            )

            conn.commit()

        except mysql.connector.Error as error:
            conn.rollback()
            return f"Database error: {error}", 500

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("manage_courses"))

    return render_template("teacher-course.html")

@course_management_bp.route("/delete-course/<int:course_id>", methods=["POST"])
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
            (course_id, teacher_id)
        )

        conn.commit()

    except mysql.connector.Error as error:
        conn.rollback()
        return f"Database error: {error}", 500

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("manage_courses"))


@course_management_bp.route("/edit-course/<int:course_id>", methods=["POST"])
def edit_course(course_id):

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    course_name = request.form.get("course_name")
    course_code = request.form.get("course_code")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE courses
        SET course_name = %s, course_code = %s
        WHERE course_id = %s
        AND teacher_id = %s
        """,
        (course_name, course_code, course_id, teacher_id)
    )

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("manage_courses"))