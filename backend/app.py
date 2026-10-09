# Main Flask application

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from google import genai
from datetime import date
import time
import re
from collections import defaultdict
from google.genai import types
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_mail import Mail, Message
import mysql.connector
from dotenv import load_dotenv
import os
from routes.student_registration import student_registration_bp
from routes.teacher_registration import teacher_registration_bp
from routes.course_management import course_management_bp
from werkzeug.security import check_password_hash, generate_password_hash

# Load environment variables
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Secret key
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")

# Password reset serializer
serializer = URLSafeTimedSerializer(app.secret_key)

# Email configuration
app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT", 587))
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
app.config["MAIL_USE_TLS"] = True

mail = Mail(app)

# Register blueprints
app.register_blueprint(student_registration_bp)
app.register_blueprint(teacher_registration_bp)
app.register_blueprint(course_management_bp)

# Database connection
db = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE"),
    use_pure=True,
    autocommit=True
)

def get_teacher_stream_ids(teacher_id):
    cursor = db.cursor()

    cursor.execute("""
        SELECT stream_id
        FROM teacher_streams
        WHERE teacher_id = %s
    """, (teacher_id,))

    stream_ids = [row[0] for row in cursor.fetchall()]

    cursor.close()

    return stream_ids

# Gemini AI client
# 10 seconds is the minimum deadline accepted by the Gemini API.
client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY"),
    http_options=types.HttpOptions(timeout=10000)
)


def ask_gemini(prompt):
    """Use one fast Gemini model only; do not wait for a second fallback call."""
    try:
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                max_output_tokens=120,
                thinking_config=types.ThinkingConfig(
                    thinking_level="minimal"
                )
            )
        )

        if response and response.text:
            print("Gemini response from gemini-3.1-flash-lite")
            return response.text.strip()

        print("gemini-3.1-flash-lite: empty response")

    except Exception as e:
        print(
            "gemini-3.1-flash-lite error: "
            f"{type(e).__name__}: {e}"
        )

    return None


def local_student_answer(message_lower, overall_percentage, present_classes, total_classes, subject_attendance, attendance_history, needs_history):
    """Answer common attendance questions instantly without calling Gemini."""

    # Recent/history questions are deterministic from the database.
    if needs_history:
        if not attendance_history:
            return "I could not find any recent attendance history."

        lines = ["Here is your recent attendance history:"]
        for record in attendance_history[:15]:
            lines.append(
                f"• {record['subject']} — {record['attendance_date']} — {record['status']}"
            )
        return "\n".join(lines)

    # Advice questions: calculate from the actual attendance data.
    advice_words = (
        "improve", "how can", "how do", "how to",
        "what should", "need to improve", "fix my attendance",
        "increase my attendance", "raise my attendance",
        "maintain good attendance", "maintain attendance",
        "keep my attendance", "keep attendance",
        "good attendance", "practical ways", "attendance tips",
        "attendance advice", "ways to maintain", "ways to improve",
        "tips to maintain", "tips for attendance",
        "stay above 75", "stay above 75%"
    )

    # Treat broad attendance-maintenance/improvement wording as one intent.
    # This is intentionally intent-based, not a list of exact questions.
    general_advice_intent = bool(
        re.search(
            r"\\b(attendance|attend)\\b.*\\b("
            r"improv|maintain|keep|increase|raise|better|"
            r"tips?|advice|ways|strateg|regular|"
            r"avoid|stay|good|semester"
            r")\\b",
            message_lower
        )
        or
        re.search(
            r"\\b("
            r"improv|maintain|keep|increase|raise|better|"
            r"tips?|advice|ways|strateg|regular|avoid|stay"
            r")\\b.*\\b(attendance|attend)\\b",
            message_lower
        )
    )

    if any(word in message_lower for word in advice_words) or general_advice_intent:
        mentioned = [
            subject for subject in subject_attendance
            if str(subject["subject"]).lower() in message_lower
        ]

        if mentioned:
            target = min(mentioned, key=lambda x: float(x["attendance_percentage"] or 0))
            total = int(target["total_classes"] or 0)
            present = int(target["present_classes"] or 0)
            pct = float(target["attendance_percentage"] or 0)

            if pct < 75:
                needed = max(0, (3 * total) - (4 * present))
                return (
                    f"Your {target['subject']} attendance is {pct}%. "
                    f"You need to attend the next {needed} class(es) consecutively "
                    f"to reach 75%. Try not to miss upcoming classes."
                )

            return (
                f"Your {target['subject']} attendance is {pct}%, which is above 75%. "
                f"Keep attending regularly so it stays above the required level."
            )

        # General attendance improvement.
        weak = [
            subject for subject in subject_attendance
            if float(subject["attendance_percentage"] or 0) < 75
        ]

        if weak:
            weak.sort(key=lambda x: float(x["attendance_percentage"] or 0))
            target = weak[0]
            total = int(target["total_classes"] or 0)
            present = int(target["present_classes"] or 0)
            pct = float(target["attendance_percentage"] or 0)
            needed = max(0, (3 * total) - (4 * present))

            return (
                f"Your overall attendance is {overall_percentage}%. "
                f"Your weakest subject is {target['subject']} at {pct}%. "
                f"To improve, attend your upcoming classes regularly and avoid absences. "
                f"For {target['subject']}, you need about {needed} consecutive present "
                f"classes to reach 75%."
            )

        return (
            f"Your overall attendance is {overall_percentage}%, which is at or above 75%. "
            "Keep attending classes regularly and avoid unnecessary absences."
        )

    return None

def send_low_attendance_email(student_name, student_email, course_name, percentage):

    msg = Message(
        subject="Low Attendance Warning - AI Attendance System",
        sender=os.getenv("MAIL_USERNAME"),
        recipients=[student_email]
    )

    msg.body = f"""
Hello {student_name},

This is an attendance warning notification.

Course: {course_name}
Your Attendance: {percentage}%

Your attendance is below the required 75%.

Please maintain regular attendance.

Regards,
AI Smart Attendance Management System
"""

    mail.send(msg)
    
@app.route("/")
def home():
    return render_template("index.html")

@app.route('/student-register')
def student_register():
    return render_template('student-register.html')


@app.route("/student-login", methods=["GET", "POST"])
def student_login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        cursor = db.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT *
            FROM students
            WHERE email = %s
            """,
            (email,)
        )

        student = cursor.fetchone()

        cursor.close()

        if student and check_password_hash(
            student["password"],
            password
        ):
            # Store logged-in student's ID in session
            session["student_id"] = student["student_id"]

            return redirect(
                url_for("student_dashboard")
            )

        return "Invalid email or password", 401

    return render_template("student-login.html")

@app.route("/student-dashboard")
def student_dashboard():

    student_id = session.get("student_id")

    if not student_id:
        return redirect(url_for("student_login"))

    cursor = db.cursor(dictionary=True)

    # Student details
    cursor.execute(
        """
        SELECT
            student_id,
            name,
            email,
            roll_number,
            semester
        FROM students
        WHERE student_id = %s
        """,
        (student_id,)
    )

    student = cursor.fetchone()

    if not student:
        cursor.close()
        return redirect(url_for("student_login"))

    # Overall attendance
    cursor.execute(
        """
        SELECT
            COUNT(attendance_id) AS total_classes,
            SUM(
                CASE
                    WHEN status = 'Present'
                    THEN 1
                    ELSE 0
                END
            ) AS present_classes,
            SUM(
                CASE
                    WHEN status = 'Absent'
                    THEN 1
                    ELSE 0
                END
            ) AS absent_classes
        FROM attendance
        WHERE student_id = %s
        """,
        (student_id,)
    )

    overall = cursor.fetchone()

    # Subject-wise attendance
    cursor.execute(
        """
        SELECT
            c.course_name AS subject,

            COUNT(a.attendance_id) AS total_classes,

            SUM(
                CASE
                    WHEN a.status = 'Present'
                    THEN 1
                    ELSE 0
                END
            ) AS present_classes,

            SUM(
                CASE
                    WHEN a.status = 'Absent'
                    THEN 1
                    ELSE 0
                END
            ) AS absent_classes,

            ROUND(
                (
                    SUM(
                        CASE
                            WHEN a.status = 'Present'
                            THEN 1
                            ELSE 0
                        END
                    )
                    / COUNT(a.attendance_id)
                ) * 100,
                2
            ) AS attendance_percentage

        FROM attendance a

        INNER JOIN courses c
            ON a.course_id = c.course_id

        WHERE a.student_id = %s

        GROUP BY
            c.course_id,
            c.course_name

        ORDER BY c.course_name
        """,
        (student_id,)
    )

    subject_attendance = cursor.fetchall()

    cursor.close()

    # Overall percentage
    total_classes = overall["total_classes"] or 0
    present_classes = overall["present_classes"] or 0
    absent_classes = overall["absent_classes"] or 0

    if total_classes > 0:
        overall_percentage = round(
            (present_classes / total_classes) * 100,
            2
        )
    else:
        overall_percentage = 0

    return render_template(
        "student-dashboard.html",
        student=student,
        total_classes=total_classes,
        present_classes=present_classes,
        absent_classes=absent_classes,
        overall_percentage=overall_percentage,
        subject_attendance=subject_attendance
    )

@app.route("/student-logout")
def student_logout():

    session.pop("student_id", None)

    return redirect(url_for("student_login"))

@app.route("/student-attendance", methods=["GET", "POST"])
def student_attendance():

    student_id = session.get("student_id")

    if not student_id:
        return redirect(url_for("student_login"))

    cursor = db.cursor(dictionary=True)

    # Get the student's enrolled courses matching
    # stream, semester and section
    cursor.execute(
        """
        SELECT
            c.course_id,
            c.course_name,
            c.course_code
        FROM courses c
        INNER JOIN enrollments e
            ON c.course_id = e.course_id
        INNER JOIN students s
            ON e.student_id = s.student_id
        WHERE e.student_id = %s
        AND c.stream_id = s.stream_id
        AND c.semester = s.semester
        AND c.section = s.section
        ORDER BY c.course_name
        """,
        (student_id,)
    )

    courses = cursor.fetchall()

    selected_course = None
    attendance_records = []

    total_classes = 0
    present_classes = 0
    absent_classes = 0
    attendance_percentage = 0

    selected_from_date = ""
    selected_to_date = ""

    if request.method == "POST":

        course_id = request.form.get("course_id")

        selected_from_date = request.form.get("from_date") or ""
        selected_to_date = request.form.get("to_date") or ""

        # Verify that the selected course is enrolled
        # and matches all three student details
        cursor.execute(
            """
            SELECT
                c.course_id,
                c.course_name,
                c.course_code
            FROM courses c
            INNER JOIN enrollments e
                ON c.course_id = e.course_id
            INNER JOIN students s
                ON e.student_id = s.student_id
            WHERE c.course_id = %s
            AND e.student_id = %s
            AND c.stream_id = s.stream_id
            AND c.semester = s.semester
            AND c.section = s.section
            """,
            (course_id, student_id)
        )

        selected_course = cursor.fetchone()

        if selected_course:

            attendance_query = """
                SELECT
                    attendance_date,
                    status
                FROM attendance
                WHERE student_id = %s
                AND course_id = %s
            """

            query_params = [
                student_id,
                course_id
            ]

            # From date filter
            if selected_from_date:
                attendance_query += """
                    AND attendance_date >= %s
                """
                query_params.append(selected_from_date)

            # To date filter
            if selected_to_date:
                attendance_query += """
                    AND attendance_date <= %s
                """
                query_params.append(selected_to_date)

            attendance_query += """
                ORDER BY attendance_date DESC
            """

            cursor.execute(
                attendance_query,
                tuple(query_params)
            )

            attendance_records = cursor.fetchall()

            # Calculate attendance summary
            total_classes = len(attendance_records)

            for record in attendance_records:

                if record["status"] == "Present":
                    present_classes += 1

                elif record["status"] == "Absent":
                    absent_classes += 1

            if total_classes > 0:
                attendance_percentage = round(
                    (present_classes / total_classes) * 100,
                    2
                )

    cursor.close()

    return render_template(
        "student-attendance.html",
        courses=courses,
        selected_course=selected_course,
        attendance_records=attendance_records,
        total_classes=total_classes,
        present_classes=present_classes,
        absent_classes=absent_classes,
        attendance_percentage=attendance_percentage,
        selected_from_date=selected_from_date,
        selected_to_date=selected_to_date
    )

@app.route("/teacher-register")
def teacher_register():
    return render_template("teacher-register.html")


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
            session["teacher_id"] = teacher["teacher_id"]

            return redirect(url_for("teacher_dashboard"))

        return "Invalid email or password", 401

    return render_template("teacher-login.html")


@app.route("/teacher-dashboard")
def teacher_dashboard():

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    cursor = db.cursor(dictionary=True)

    # Teacher details
    cursor.execute(
        """
        SELECT *
        FROM teachers
        WHERE teacher_id = %s
        """,
        (teacher_id,)
    )

    teacher = cursor.fetchone()

    # Teacher's courses with stream, semester and section
    cursor.execute(
        """
        SELECT
            c.course_id,
            c.course_name,
            c.course_code,
            c.stream_id,
            c.semester,
            c.section,
            s.stream_name
        FROM courses c
        LEFT JOIN streams s
            ON c.stream_id = s.stream_id
        WHERE c.teacher_id = %s
        ORDER BY c.course_name
        """,
        (teacher_id,)
    )

    courses = cursor.fetchall()

    # Get only students matching each course
    for course in courses:

        cursor.execute(
            """
            SELECT
                student_id,
                name,
                email,
                roll_number,
                semester,
                stream_id,
                section
            FROM students
            WHERE stream_id = %s
            AND semester = %s
            AND section = %s
            ORDER BY name
            """,
            (
                course["stream_id"],
                course["semester"],
                course["section"]
            )
        )

        course["students"] = cursor.fetchall()

    cursor.close()

    return render_template(
        "teacher-dashboard.html",
        teacher=teacher,
        courses=courses
    )

@app.route("/manage-enrollments", methods=["POST"])
def manage_enrollments():

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    course_id = request.form.get("course_id")
    student_ids = request.form.getlist("student_ids")

    if not course_id or not student_ids:
        return redirect(url_for("teacher_dashboard"))

    cursor = db.cursor()

    # Make sure the selected course belongs to the logged-in teacher
    cursor.execute(
        """
        SELECT course_id
        FROM courses
        WHERE course_id = %s
        AND teacher_id = %s
        """,
        (course_id, teacher_id)
    )

    course = cursor.fetchone()

    if not course:
        cursor.close()
        return redirect(url_for("teacher_dashboard"))

    # Enroll selected students
    for student_id in student_ids:

        cursor.execute(
            """
            INSERT IGNORE INTO enrollments
            (student_id, course_id)
            VALUES (%s, %s)
            """,
            (student_id, course_id)
        )

    db.commit()
    cursor.close()

    return redirect(url_for("teacher_dashboard"))

@app.route("/teacher-logout")
def teacher_logout():
    session.pop("teacher_id", None)
    return redirect(url_for("teacher_login"))


@app.route("/manage-courses")
def manage_courses():

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    cursor = db.cursor(dictionary=True)

    # -------------------------------------------------
    # Get courses created by this teacher
    # -------------------------------------------------

    cursor.execute(
        """
        SELECT
            course_id,
            course_name,
            course_code,
            stream_id,
            semester,
            section
        FROM courses
        WHERE teacher_id = %s
        """,
        (teacher_id,)
    )

    courses = cursor.fetchall()


    # -------------------------------------------------
    # Get streams assigned to this teacher
    # -------------------------------------------------

    cursor.execute(
        """
        SELECT
            s.stream_id,
            s.stream_name
        FROM streams s
        INNER JOIN teacher_streams ts
            ON s.stream_id = ts.stream_id
        WHERE ts.teacher_id = %s
        ORDER BY s.stream_name
        """,
        (teacher_id,)
    )

    streams = cursor.fetchall()


    # -------------------------------------------------
    # Get enrolled students for each course
    # -------------------------------------------------

    for course in courses:

        cursor.execute(
            """
            SELECT
                s.student_id,
                s.name,
                s.roll_number
            FROM students s
            INNER JOIN enrollments e
                ON s.student_id = e.student_id
            WHERE e.course_id = %s
            ORDER BY s.roll_number
            """,
            (course["course_id"],)
        )

        course["students"] = cursor.fetchall()


    cursor.close()


    return render_template(
        "manage-courses.html",
        courses=courses,
        streams=streams
    )
    
@app.route("/mark-attendance", methods=["GET", "POST"])
def mark_attendance():

    teacher_id = session.get("teacher_id")

    if not teacher_id:
        return redirect(url_for("teacher_login"))

    cursor = db.cursor(dictionary=True)

    # Teacher ke courses
    cursor.execute(
        """
        SELECT course_id, course_name, course_code
        FROM courses
        WHERE teacher_id = %s
        """,
        (teacher_id,)
    )

    courses = cursor.fetchall()

    students = []
    selected_course = None
    selected_date = None

    attendance_records = []
    attendance_percentage = []

    view_course = None
    view_date = None

    attendance_history = []

    if request.method == "POST":

        course_id = request.form.get("course_id")
        attendance_date = request.form.get("attendance_date")

        selected_date = attendance_date

        # Selected course verify
        if course_id:

            cursor.execute(
                """
                SELECT course_id, course_name, course_code
                FROM courses
                WHERE course_id = %s
                AND teacher_id = %s
                """,
                (course_id, teacher_id)
            )

            selected_course = cursor.fetchone()

        # Enrolled students
        if selected_course:

            cursor.execute(
                """
                SELECT
                    s.student_id,
                    s.name,
                    s.roll_number
                FROM students s
                INNER JOIN enrollments e
                    ON s.student_id = e.student_id
                WHERE e.course_id = %s
                ORDER BY s.roll_number
                """,
                (course_id,)
            )

            students = cursor.fetchall()

        # SAVE ATTENDANCE

        if request.form.get("save_attendance"):

            for student in students:

                status = request.form.get(
                    f"attendance_{student['student_id']}"
                )

                if status:

                    cursor.execute(
                        """
                        INSERT INTO attendance
                        (
                            student_id,
                            course_id,
                            teacher_id,
                            attendance_date,
                            status
                        )
                        VALUES (%s, %s, %s, %s, %s)

                        ON DUPLICATE KEY UPDATE
                        status = VALUES(status)
                        """,
                        (
                            student["student_id"],
                            course_id,
                            teacher_id,
                            attendance_date,
                            status
                        )
                    )

            db.commit()

            # Check for low attendance and send email notification

            for student in students:

                cursor.execute(
                    """
                    SELECT
                        COUNT(attendance_id) AS total_classes,
                        SUM(
                            CASE
                                WHEN status = 'Present'
                                THEN 1
                                ELSE 0
                            END
                        ) AS present_classes
                    FROM attendance
                    WHERE student_id = %s
                    AND course_id = %s
                    """,
                    (
                        student["student_id"],
                        course_id
                    )
                )

                attendance = cursor.fetchone()

                total_classes = attendance["total_classes"] or 0
                present_classes = attendance["present_classes"] or 0

                if total_classes > 0:

                    percentage = round(
                        (present_classes / total_classes) * 100,
                        2
                    )

                    if percentage < 75:

                        cursor.execute(
                            """
                            SELECT email
                            FROM students
                            WHERE student_id = %s
                            """,
                            (student["student_id"],)
                        )

                        student_email = cursor.fetchone()

                        if student_email:

                            send_low_attendance_email(
                                student["name"],
                                student_email["email"],
                                selected_course["course_name"],
                                percentage
                            )

            cursor.close()

            flash(
                "Attendance marked successfully!",
                "success"
            )

            return redirect(url_for("mark_attendance"))

        # VIEW ATTENDANCE

        if request.form.get("view_attendance"):

            view_course = request.form.get("view_course_id")
            view_date = request.form.get("view_date")
            
            
            cursor.execute(
                """
                SELECT
                    s.name,
                    s.roll_number,
                    a.attendance_date,
                    a.status
                FROM attendance a
                INNER JOIN students s
                    ON a.student_id = s.student_id
                WHERE a.course_id = %s
                AND a.attendance_date = %s
                ORDER BY s.roll_number
                """,
                (view_course, view_date)
            )

            attendance_records = cursor.fetchall()
            

            # Attendance percentage

            cursor.execute(
                """
                SELECT
                    s.student_id,
                    s.name,
                    s.roll_number,

                    COUNT(a.attendance_id) AS total_classes,

                    SUM(
                        CASE
                            WHEN a.status = 'Present'
                            THEN 1
                            ELSE 0
                        END
                    ) AS present_classes,

                    ROUND(
                        (
                            SUM(
                                CASE
                                    WHEN a.status = 'Present'
                                    THEN 1
                                    ELSE 0
                                END
                            )
                            / COUNT(a.attendance_id)
                        ) * 100,
                        2
                    ) AS attendance_percentage

                FROM students s

                INNER JOIN enrollments e
                    ON s.student_id = e.student_id

                LEFT JOIN attendance a
                    ON s.student_id = a.student_id
                    AND a.course_id = e.course_id
                    AND a.teacher_id = %s

                WHERE e.course_id = %s

                GROUP BY
                    s.student_id,
                    s.name,
                    s.roll_number

                ORDER BY s.roll_number
                """,
                (
                    teacher_id,
                    view_course
                )
            )

            attendance_percentage = cursor.fetchall()

        # ATTENDANCE HISTORY

        if request.form.get("view_history"):

            history_course = request.form.get("history_course_id")

            cursor.execute(
                """
                SELECT
                    a.attendance_date,

                    COUNT(a.attendance_id) AS total_students,

                    SUM(
                        CASE
                            WHEN a.status = 'Present'
                            THEN 1
                            ELSE 0
                        END
                    ) AS present_students,

                    SUM(
                        CASE
                            WHEN a.status = 'Absent'
                            THEN 1
                            ELSE 0
                        END
                    ) AS absent_students

                FROM attendance a

                WHERE a.course_id = %s
                AND a.teacher_id = %s

                GROUP BY a.attendance_date

                ORDER BY a.attendance_date DESC
                """,
                (
                    history_course,
                    teacher_id
                )
            )

            attendance_history = cursor.fetchall()

    cursor.close()

    return render_template(
        "mark-attendance.html",
        courses=courses,
        students=students,
        selected_course=selected_course,
        selected_date=selected_date,
        attendance_records=attendance_records,
        view_course=view_course,
        view_date=view_date,
        attendance_percentage=attendance_percentage,
        attendance_history=attendance_history
    )
    
@app.route("/teacher-course")
def teacher_course():
    return render_template("teacher-course.html")

@app.route("/assistant")
def assistant():

    if not session.get("student_id") and not session.get("teacher_id"):
        return redirect(url_for("home"))

    return render_template("assistant.html")

@app.route("/assistant/ask", methods=["POST"])
def assistant_ask():

    message = request.form.get("message", "").strip()

    if not message:
        return jsonify({
            "response": "Please ask me something about attendance."
        })

    message_lower = message.lower()

    # =========================================================
    # STUDENT ASSISTANT
    # =========================================================

    student_id = session.get("student_id")

    if student_id:

        cursor = db.cursor(dictionary=True)

        # -----------------------------------------------------
        # Overall attendance
        # -----------------------------------------------------

        cursor.execute(
            """
            SELECT
                COUNT(a.attendance_id) AS total_classes,

                SUM(
                    CASE
                        WHEN a.status = 'Present'
                        THEN 1
                        ELSE 0
                    END
                ) AS present_classes,

                SUM(
                    CASE
                        WHEN a.status = 'Absent'
                        THEN 1
                        ELSE 0
                    END
                ) AS absent_classes

            FROM attendance a

            WHERE a.student_id = %s
            """,
            (student_id,)
        )

        overall = cursor.fetchone()

        total_classes = int(overall["total_classes"] or 0)
        present_classes = int(overall["present_classes"] or 0)
        absent_classes = int(overall["absent_classes"] or 0)

        if total_classes > 0:
            overall_percentage = round(
                (present_classes / total_classes) * 100,
                2
            )
        else:
            overall_percentage = 0

        # -----------------------------------------------------
        # Subject-wise attendance
        # -----------------------------------------------------

        cursor.execute(
            """
            SELECT
                c.course_name AS subject,
                COUNT(a.attendance_id) AS total_classes,

                SUM(
                    CASE
                        WHEN a.status = 'Present'
                        THEN 1
                        ELSE 0
                    END
                ) AS present_classes,

                SUM(
                    CASE
                        WHEN a.status = 'Absent'
                        THEN 1
                        ELSE 0
                    END
                ) AS absent_classes,

                ROUND(
                    (
                        SUM(
                            CASE
                                WHEN a.status = 'Present'
                                THEN 1
                                ELSE 0
                            END
                        ) / COUNT(a.attendance_id)
                    ) * 100,
                    2
                ) AS attendance_percentage

            FROM attendance a

            INNER JOIN courses c
                ON a.course_id = c.course_id

            WHERE a.student_id = %s

            GROUP BY c.course_id, c.course_name

            ORDER BY c.course_name
            """,
            (student_id,)
        )

        subject_attendance = cursor.fetchall()

        # -----------------------------------------------------
        # Detect questions that need advice / explanation
        # -----------------------------------------------------

        advice_words = (
            "improve",
            "how can",
            "how do",
            "how to",
            "why",
            "should",
            "if i",
            "can i",
            "need to",
            "what should"
        )

        is_advice = any(
            word in message_lower
            for word in advice_words
        )

        # -----------------------------------------------------
        # Check whether a specific subject was mentioned
        # -----------------------------------------------------

        mentions_subject = any(
            str(subject["subject"]).lower() in message_lower
            for subject in subject_attendance
        )

        # Direct shortcuts should NOT hijack:
        # - advice questions
        # - subject-specific questions
        use_shortcuts = not is_advice and not mentions_subject

        # =====================================================
        # DIRECT STUDENT ANSWERS
        # =====================================================

        # -----------------------------------------------------
        # 1. Overall attendance
        # -----------------------------------------------------

        overall_keywords = [
            "overall attendance",
            "my attendance percentage",
            "my attendance %",
            "overall percentage",
            "what is my attendance",
            "what's my attendance",
            "how much attendance do i have"
        ]

        if (
            use_shortcuts
            and any(
                keyword in message_lower
                for keyword in overall_keywords
            )
        ):

            cursor.close()

            return jsonify({
                "response":
                    f"Your overall attendance is "
                    f"{overall_percentage}%. "
                    f"You have attended "
                    f"{present_classes} out of "
                    f"{total_classes} classes."
            })

        # -----------------------------------------------------
        # 2. Lowest attendance subject
        # -----------------------------------------------------

        lowest_keywords = [
            "lowest attendance",
            "least attendance",
            "lowest percentage",
            "worst attendance",
            "which subject has low attendance",
            "which subject has the lowest",
            "where is my attendance low",
            "which subject is low"
        ]

        if (
            use_shortcuts
            and any(
                keyword in message_lower
                for keyword in lowest_keywords
            )
        ):

            if subject_attendance:

                lowest_subject = min(
                    subject_attendance,
                    key=lambda x: x["attendance_percentage"]
                )

                cursor.close()

                return jsonify({
                    "response":
                        f"Your lowest attendance is in "
                        f"{lowest_subject['subject']} "
                        f"with "
                        f"{lowest_subject['attendance_percentage']}%."
                })

            else:

                cursor.close()

                return jsonify({
                    "response":
                        "I could not find any subject-wise "
                        "attendance data."
                })

        # -----------------------------------------------------
        # 3. Highest attendance subject
        # -----------------------------------------------------

        highest_keywords = [
            "highest attendance",
            "best attendance",
            "highest percentage",
            "which subject has highest",
            "which subject is highest"
        ]

        if (
            use_shortcuts
            and any(
                keyword in message_lower
                for keyword in highest_keywords
            )
        ):

            if subject_attendance:

                highest_subject = max(
                    subject_attendance,
                    key=lambda x: x["attendance_percentage"]
                )

                cursor.close()

                return jsonify({
                    "response":
                        f"Your highest attendance is in "
                        f"{highest_subject['subject']} "
                        f"with "
                        f"{highest_subject['attendance_percentage']}%."
                })

            else:

                cursor.close()

                return jsonify({
                    "response":
                        "I could not find any subject-wise "
                        "attendance data."
                })

        # -----------------------------------------------------
        # 4. Subject-wise attendance
        # -----------------------------------------------------

        subject_keywords = [
            "subject wise attendance",
            "subject-wise attendance",
            "attendance of all subjects",
            "attendance in all subjects",
            "attendance for each subject",
            "attendance by subject"
        ]

        if (
            use_shortcuts
            and any(
                keyword in message_lower
                for keyword in subject_keywords
            )
        ):

            if subject_attendance:

                response_text = (
                    "Your subject-wise attendance is:\n"
                )

                for subject in subject_attendance:

                    response_text += (
                        f"\n• {subject['subject']}: "
                        f"{subject['attendance_percentage']}%"
                    )

                cursor.close()

                return jsonify({
                    "response": response_text
                })

            else:

                cursor.close()

                return jsonify({
                    "response":
                        "I could not find subject-wise "
                        "attendance data."
                })

        # =====================================================
        # ATTENDANCE HISTORY
        # =====================================================

        history_keywords = [
            "history",
            "attendance history",
            "attendance record",
            "attendance records",
            "when was i present",
            "when was i absent",
            "which dates",
            "date wise",
            "date-wise"
        ]

        needs_history = any(
            keyword in message_lower
            for keyword in history_keywords
        )

        attendance_history = []

        if needs_history:

            cursor.execute(
                """
                SELECT
                    c.course_name AS subject,
                    a.attendance_date,
                    a.status

                FROM attendance a

                INNER JOIN courses c
                    ON a.course_id = c.course_id

                WHERE a.student_id = %s

                ORDER BY a.attendance_date DESC
                LIMIT 100
                """,
                (student_id,)
            )

            attendance_history = cursor.fetchall()

        # =====================================================
        # COMPACT STUDENT CONTEXT
        # =====================================================

        student_lines = [
            f"Overall attendance: "
            f"{present_classes}/{total_classes} "
            f"({overall_percentage}%).",

            f"Present classes: {present_classes}.",
            f"Absent classes: {absent_classes}.",
            "Required minimum attendance: 75%."
        ]

        for subject in subject_attendance:

            total = int(subject["total_classes"] or 0)
            present = int(subject["present_classes"] or 0)
            percentage = float(
                subject["attendance_percentage"] or 0
            )

            # Classes required consecutively to reach 75%
            needed = max(
                0,
                (3 * total) - (4 * present)
            )

            # Classes that can still be missed
            can_miss = max(
                0,
                (4 * present) // 3 - total
            )

            student_lines.append(
                f"{subject['subject']}: "
                f"{present}/{total} classes present "
                f"({percentage}%). "
                f"Needs approximately {needed} "
                f"consecutive present classes to reach 75%. "
                f"Can currently miss approximately "
                f"{can_miss} class(es) while staying at or above 75%."
            )

        attendance_data = "\n".join(student_lines)

        # -----------------------------------------------------
        # Add history only when question actually needs it
        # -----------------------------------------------------

        if needs_history:

            history_lines = []

            for record in attendance_history:

                history_lines.append(
                    f"{record['subject']} - "
                    f"{record['attendance_date']} - "
                    f"{record['status']}"
                )

            attendance_data += (
                "\n\nAttendance History:\n"
                + "\n".join(history_lines)
            )

        # =====================================================
        # INSTANT STUDENT ANSWERS
        # =====================================================
        # Common attendance questions should not wait for Gemini.
        # We still keep Gemini for genuinely open-ended questions.
        local_answer = local_student_answer(
            message_lower,
            overall_percentage,
            present_classes,
            total_classes,
            subject_attendance,
            attendance_history,
            needs_history
        )

        if local_answer:
            cursor.close()
            return jsonify({"response": local_answer})

        cursor.close()

        # =====================================================
        # STUDENT GEMINI PROMPT
        # =====================================================

        prompt = f"""
You are the AI Assistant of an AI Smart Attendance Management System.

The logged-in user is a STUDENT.

Answer the student's attendance-related question using ONLY
the attendance information provided below. The question may be
phrased in any natural way; understand its intent from the
question and use the relevant data.

Student Attendance Data:
{attendance_data}

Student Question:
{message}

Rules:
1. Give a short, simple and clear answer.
2. Do not make up attendance information.
3. Use only the provided attendance data.
4. You may calculate percentages, required classes, or other
   simple attendance-related values using the provided numbers.
5. If the student asks how to improve attendance, give
   practical advice based on their actual attendance data.
6. If a specific subject is mentioned, focus on that subject.
7. If the question is unrelated to attendance, politely say
   that you mainly help with attendance-related queries.
"""

        # =====================================================
        # GEMINI
        # =====================================================

        answer = ask_gemini(prompt)

        if answer:

            return jsonify({
                "response": answer
            })

        return jsonify({
            "response":
                "The AI Assistant is temporarily busy. "
                "Please try again in a moment."
        }), 503

    # =========================================================
    # TEACHER ASSISTANT
    # =========================================================

    teacher_id = session.get("teacher_id")

    if teacher_id:

        cursor = db.cursor(dictionary=True)

        # -----------------------------------------------------
        # Teacher courses
        # -----------------------------------------------------

        cursor.execute(
            """
            SELECT
                course_id,
                course_name,
                course_code

            FROM courses

            WHERE teacher_id = %s

            ORDER BY course_name
            """,
            (teacher_id,)
        )

        courses = cursor.fetchall()

        # =====================================================
        # DIRECT TEACHER COURSE ANSWER
        # =====================================================

        course_question_keywords = [
            "what courses do i have",
            "which courses do i have",
            "my courses",
            "my subjects",
            "which subjects do i teach",
            "what subjects do i teach",
            "list my courses"
        ]

        if any(
            keyword in message_lower
            for keyword in course_question_keywords
        ):

            if courses:

                response_text = "You have these courses:\n"

                for course in courses:

                    response_text += (
                        f"\n• {course['course_name']} "
                        f"({course['course_code']})"
                    )

                cursor.close()

                return jsonify({
                    "response": response_text
                })

            else:

                cursor.close()

                return jsonify({
                    "response":
                        "You currently do not have any "
                        "courses assigned."
                })

        # =====================================================
        # TEACHER ATTENDANCE SUMMARY
        # =====================================================
        # IMPORTANT:
        # Unlike the old route, attendance summary is ALWAYS
        # loaded so Gemini can answer general questions too.

        cursor.execute(
            """
            SELECT
                s.student_id,
                s.name AS student_name,
                s.roll_number,
                c.course_id,
                c.course_name AS subject,

                COUNT(a.attendance_id) AS total_classes,

                SUM(
                    CASE
                        WHEN a.status = 'Present'
                        THEN 1
                        ELSE 0
                    END
                ) AS present_classes

            FROM attendance a

            INNER JOIN courses c
                ON a.course_id = c.course_id

            INNER JOIN students s
                ON a.student_id = s.student_id

            WHERE a.teacher_id = %s

            GROUP BY
                s.student_id,
                s.name,
                s.roll_number,
                c.course_id,
                c.course_name

            ORDER BY
                c.course_name,
                s.name
            """,
            (teacher_id,)
        )

        attendance_rows = cursor.fetchall()

        # -----------------------------------------------------
        # Build compact teacher summary
        # -----------------------------------------------------

        by_course = defaultdict(list)

        for row in attendance_rows:

            total = int(row["total_classes"] or 0)
            present = int(row["present_classes"] or 0)

            percentage = (
                round((present / total) * 100, 1)
                if total > 0 else 0
            )

            by_course[row["subject"]].append({
                "student_name": row["student_name"],
                "roll_number": row["roll_number"],
                "total_classes": total,
                "present_classes": present,
                "percentage": percentage
            })

        teacher_summary_lines = []

        for subject, students in by_course.items():

            if not students:
                continue

            average = round(
                sum(student["percentage"] for student in students)
                / len(students),
                1
            )

            low_count = sum(
                1 for student in students
                if student["percentage"] < 75
            )

            teacher_summary_lines.append(
                f"{subject}: {len(students)} students, "
                f"class average {average}%, "
                f"{low_count} below 75%."
            )

            # Keep useful student-level information without dumping
            # an unlimited amount of attendance data into Gemini.
            for student in sorted(
                students,
                key=lambda x: x["percentage"]
            )[:30]:

                teacher_summary_lines.append(
                    f"  - {student['student_name']} "
                    f"({student['roll_number']}): "
                    f"{student['present_classes']}/"
                    f"{student['total_classes']} present "
                    f"({student['percentage']}%)."
                )

        teacher_summary = "\n".join(teacher_summary_lines)

        if not teacher_summary:

            teacher_summary = (
                "No attendance summary is currently available."
            )

        # =====================================================
        # TEACHER LOW ATTENDANCE DIRECT ANSWER
        # =====================================================

        low_attendance_keywords = [
            "low attendance",
            "below 75",
            "below 75%",
            "less than 75",
            "under 75",
            "students below",
            "students with low attendance"
        ]

        teacher_advice_words = (
            "improve",
            "how can",
            "how do",
            "how to",
            "why",
            "should",
            "if i",
            "can i",
            "need to",
            "what should"
        )

        teacher_is_advice = any(
            word in message_lower
            for word in teacher_advice_words
        )

        needs_low_attendance = (
            not teacher_is_advice
            and any(
                keyword in message_lower
                for keyword in low_attendance_keywords
            )
        )

        if needs_low_attendance:

            low_attendance_students = []

            for subject, students in by_course.items():

                for student in students:

                    if student["percentage"] < 75:

                        low_attendance_students.append({
                            "student_name":
                                student["student_name"],

                            "roll_number":
                                student["roll_number"],

                            "subject":
                                subject,

                            "attendance_percentage":
                                student["percentage"]
                        })

            cursor.close()

            if low_attendance_students:

                response_text = (
                    "Students with attendance below 75%:\n"
                )

                for student in sorted(
                    low_attendance_students,
                    key=lambda x: x["attendance_percentage"]
                ):

                    response_text += (
                        f"\n• {student['student_name']} "
                        f"({student['roll_number']}) - "
                        f"{student['subject']}: "
                        f"{student['attendance_percentage']}%"
                    )

                return jsonify({
                    "response": response_text
                })

            return jsonify({
                "response":
                    "No students currently have "
                    "attendance below 75%."
            })

        # =====================================================
        # TEACHER DATE QUESTIONS
        # =====================================================

        # IMPORTANT:
        # Do NOT use "date" substring matching because words
        # like "candidate" / "update" can accidentally match.

        needs_date_data = bool(
            re.search(
                r"\b(?:today|yesterday|dates?)\b",
                message_lower
            )
            or "attendance on" in message_lower
            or "present today" in message_lower
            or "absent today" in message_lower
        )

        teacher_attendance = []

        if needs_date_data:

            cursor.execute(
                """
                SELECT
                    c.course_name AS subject,
                    c.course_code,
                    s.name AS student_name,
                    s.roll_number,
                    a.attendance_date,
                    a.status

                FROM attendance a

                INNER JOIN courses c
                    ON a.course_id = c.course_id

                INNER JOIN students s
                    ON a.student_id = s.student_id

                WHERE
                    a.teacher_id = %s
                    AND a.attendance_date >=
                        CURDATE() - INTERVAL 30 DAY

                ORDER BY a.attendance_date DESC

                LIMIT 300
                """,
                (teacher_id,)
            )

            teacher_attendance = cursor.fetchall()

        cursor.close()

        # =====================================================
        # COMPACT TEACHER DATA
        # =====================================================

        teacher_data = f"""
Today's Date:
{date.today()}

Teacher's Courses:
"""

        for course in courses:

            teacher_data += (
                f"- {course['course_name']} "
                f"({course['course_code']})\n"
            )

        teacher_data += f"""

Attendance Summary:
{teacher_summary}
"""

        # -----------------------------------------------------
        # Add detailed date records only when necessary
        # -----------------------------------------------------

        if needs_date_data:

            teacher_data += "\nAttendance Records:\n"

            for record in teacher_attendance:

                teacher_data += (
                    f"- {record['subject']} "
                    f"({record['course_code']}) | "
                    f"{record['student_name']} "
                    f"({record['roll_number']}) | "
                    f"{record['attendance_date']} | "
                    f"{record['status']}\n"
                )

        # =====================================================
        # TEACHER GEMINI PROMPT
        # =====================================================

        prompt = f"""
You are the AI Assistant of an AI Smart Attendance Management System.

The logged-in user is a TEACHER.

Answer the teacher's attendance-management question using ONLY
the data provided below. The question may be phrased in any
natural way; understand its intent from the question and use
the relevant course, student, attendance, or date data.

Teacher Data:
{teacher_data}

Teacher Question:
{message}

Rules:
1. Give a short, simple and clear answer.
2. Do not make up student, course or attendance information.
3. Use only the provided data.
4. You may calculate simple values, percentages, comparisons,
   or attendance requirements using the provided data.
5. If the teacher asks about student performance,
   use the attendance summary.
6. If the teacher asks about improving attendance,
   give practical suggestions based on the provided data.
7. For date questions, use the attendance records and
   attendance dates provided.
8. If the question is unrelated to attendance or courses,
   politely say that you mainly help with attendance management.
"""

        # =====================================================
        # GEMINI
        # =====================================================

        answer = ask_gemini(prompt)

        if answer:

            return jsonify({
                "response": answer
            })

        return jsonify({
            "response":
                "The AI Assistant is temporarily busy. "
                "Please try again in a moment."
        }), 503

    # =========================================================
    # NOT LOGGED IN
    # =========================================================

    return jsonify({
        "response": "Please login first."
    }), 401
    
@app.route("/register")
def register():
    return render_template("register.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":

        email = request.form.get("email")
        user_type = request.form.get("user_type")

        if user_type not in ("student", "teacher"):
            return "Invalid account type.", 400

        if not email:
            return "Please enter your email.", 400

        table = "students" if user_type == "student" else "teachers"

        cursor = db.cursor(dictionary=True)

        cursor.execute(
            f"SELECT * FROM {table} WHERE email = %s",
            (email,)
        )

        user = cursor.fetchone()
        cursor.close()

        if not user:
            return "No account found with this email.", 404

        token = serializer.dumps(
            {
                "email": email,
                "user_type": user_type
            },
            salt="password-reset"
        )

        reset_link = url_for(
            "reset_password",
            token=token,
            _external=True
        )

        msg = Message(
            subject="Password Reset - AI Attendance System",
            sender=os.getenv("MAIL_USERNAME"),
            recipients=[email]
        )

        msg.body = f"""
Hello,

Click the link below to reset your password:

{reset_link}

This link will expire in 10 minutes.

Regards,
AI Smart Attendance Management System
"""

        mail.send(msg)

        return "Password reset link sent to your email."

    return render_template(
        "forgot-password.html",
        mode="forgot"
    )


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):

    try:
        data = serializer.loads(
            token,
            salt="password-reset",
            max_age=600
        )

    except (SignatureExpired, BadSignature):
        return "This password reset link is invalid or expired.", 400

    email = data["email"]
    user_type = data["user_type"]

    table = "students" if user_type == "student" else "teachers"

    if request.method == "POST":

        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")

        if not password or not confirm_password:
            return "Please fill all password fields.", 400

        if password != confirm_password:
            return "Passwords do not match.", 400

        if len(password) < 6:
            return "Password must contain at least 6 characters.", 400

        hashed_password = generate_password_hash(password)

        cursor = db.cursor()

        cursor.execute(
            f"UPDATE {table} SET password = %s WHERE email = %s",
            (hashed_password, email)
        )

        db.commit()
        cursor.close()

        if user_type == "student":
            return redirect(url_for("student_login"))

        return redirect(url_for("teacher_login"))

    return render_template(
        "forgot-password.html",
        mode="reset",
        token=token
    )
    
if __name__ == "__main__":
    app.run(debug=True)

