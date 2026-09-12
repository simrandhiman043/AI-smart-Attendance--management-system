# Main Flask application
from flask import Flask, render_template, request, redirect, url_for,session, flash, jsonify
from google import genai
import mysql.connector
from dotenv import load_dotenv
import os
from routes.student_registration import student_registration_bp
from routes.teacher_registration import teacher_registration_bp
from routes.course_management import course_management_bp
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")
app.secret_key = "ai-attendance-secret-key-2026"
load_dotenv()  # Load environment variables from .env file
app.register_blueprint(student_registration_bp)
app.register_blueprint(teacher_registration_bp)
app.register_blueprint(course_management_bp)



db = mysql.connector.connect(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE"),
    use_pure=True,
    autocommit=True
)

client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)

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

    # Get student's enrolled courses
    cursor.execute(
        """
        SELECT
            c.course_id,
            c.course_name,
            c.course_code
        FROM courses c
        INNER JOIN enrollments e
            ON c.course_id = e.course_id
        WHERE e.student_id = %s
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

        # Verify selected course belongs to logged-in student
        cursor.execute(
            """
            SELECT
                c.course_id,
                c.course_name,
                c.course_code
            FROM courses c
            INNER JOIN enrollments e
                ON c.course_id = e.course_id
            WHERE c.course_id = %s
            AND e.student_id = %s
            """,
            (course_id, student_id)
        )

        selected_course = cursor.fetchone()

        if selected_course:

            # Base attendance query
            attendance_query = """
                SELECT
                    attendance_date,
                    status
                FROM attendance
                WHERE student_id = %s
                AND course_id = %s
            """

            query_params = [student_id, course_id]

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

            # Calculate summary
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

    cursor.execute(
        "SELECT * FROM teachers WHERE teacher_id = %s",
        (teacher_id,)
    )

    teacher = cursor.fetchone()

    cursor.execute(
        """
        SELECT course_id, course_name, course_code
        FROM courses
        WHERE teacher_id = %s
        """,
        (teacher_id,)
    )

    courses = cursor.fetchall()
    cursor.close()

    return render_template(
        "teacher-dashboard.html",
        teacher=teacher,
        courses=courses
    )

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

    cursor.execute(
        """
        SELECT course_id, course_name, course_code
        FROM courses
        WHERE teacher_id = %s
        """,
        (teacher_id,)
    )

    courses = cursor.fetchall()

    # Get enrolled students for each course
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
        courses=courses
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
                AND a.teacher_id = %s
                AND a.attendance_date = %s
                ORDER BY s.roll_number
                """,
                (
                    view_course,
                    teacher_id,
                    view_date
                )
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

    # STUDENT ASSISTANT

    student_id = session.get("student_id")

    if student_id:

        cursor = db.cursor(dictionary=True)

        # Get student's attendance summary
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

        # Get subject-wise attendance
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

            GROUP BY c.course_id, c.course_name

            ORDER BY c.course_name
            """,
            (student_id,)
        )

        subject_attendance = cursor.fetchall()

        # Get attendance history
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
            """,
            (student_id,)
        )

        attendance_history = cursor.fetchall()

        cursor.close()

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

        attendance_data = f"""
        Overall Attendance:
        Total classes: {total_classes}
        Present classes: {present_classes}
        Absent classes: {absent_classes}
        Overall percentage: {overall_percentage}%

        Subject-wise Attendance:
        {subject_attendance}

        Attendance History:
        {attendance_history}
        """

        prompt = f"""
        You are the AI Assistant of an AI Smart Attendance Management System.

        The logged-in user is a STUDENT.

        Answer the student's question using ONLY the attendance data
        provided below.

        Student Attendance Data:
        {attendance_data}

        Student Question:
        {message}

        Rules:
        1. Give a simple and clear answer.
        2. Do not make up attendance information.
        3. For subject-wise questions, use the subject-wise data.
        4. For history questions, use the attendance history.
        5. If the student asks about their lowest or highest attendance,
           compare the subject-wise percentages.
        6. If the student asks whether their attendance is good,
           explain their percentage clearly.
        7. If the question is unrelated to attendance,
           politely say that you mainly help with attendance-related queries.
        """

        try:

            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )

            return jsonify({
                "response": response.text
            })

        except Exception as e:

            print("Gemini Error:", e)

            return jsonify({
                "response":
                    "Sorry, I could not connect to the AI Assistant right now."
            }), 500

    # TEACHER ASSISTANT

    teacher_id = session.get("teacher_id")

    if teacher_id:

        cursor = db.cursor(dictionary=True)

        # Get teacher's courses
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

        # Get attendance data for teacher's courses
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

            WHERE a.teacher_id = %s

            ORDER BY a.attendance_date DESC
            """,
            (teacher_id,)
        )

        teacher_attendance = cursor.fetchall()

        cursor.close()

        teacher_data = f"""
        Teacher's Courses:
        {courses}

        Attendance Records:
        {teacher_attendance}
        """

        prompt = f"""
        You are the AI Assistant of an AI Smart Attendance Management System.

        The logged-in user is a TEACHER.

        Answer the teacher's question using ONLY the data provided below.

        Teacher Data:
        {teacher_data}

        Teacher Question:
        {message}

        Rules:
        1. Give a simple and clear answer.
        2. Do not make up student, course or attendance information.
        3. For course questions, use the teacher's course data.
        4. For student attendance questions, use the attendance records.
        5. For low attendance questions, identify students with attendance
           below 75% when enough data is available.
        6. For date-wise questions, use the attendance date.
        7. If the question is unrelated to attendance or the teacher's
           courses, politely say that you mainly help with attendance
           management queries.
        """

        try:

            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt
            )

            return jsonify({
                "response": response.text
            })

        except Exception as e:

            print("Gemini Error:", e)

            return jsonify({
                "response":
                    "Sorry, I could not connect to the AI Assistant right now."
            }), 500

    return jsonify({
        "response": "Please login first."
    }), 401
if __name__ == "__main__":
    app.run(debug=True)

