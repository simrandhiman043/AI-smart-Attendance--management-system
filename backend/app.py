# Main Flask application
from flask import Flask, render_template, request, redirect, url_for,session, flash
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

@app.route("/")
def home():
    return render_template("index.html")

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

    if request.method == "POST":

        course_id = request.form.get("course_id")

        # Make sure the course belongs to this student
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

            # Attendance records
            cursor.execute(
                """
                SELECT
                    attendance_date,
                    status
                FROM attendance
                WHERE student_id = %s
                AND course_id = %s
                ORDER BY attendance_date DESC
                """,
                (student_id, course_id)
            )

            attendance_records = cursor.fetchall()

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
        attendance_percentage=attendance_percentage
    )

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

        # --------------------------------
        # SAVE ATTENDANCE
        # --------------------------------

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

        # --------------------------------
        # VIEW ATTENDANCE
        # --------------------------------

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

        # --------------------------------
        # ATTENDANCE HISTORY
        # --------------------------------

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



@app.route('/student-register')
def student_register():
    return render_template('student-register.html')

@app.route("/teacher-register")
def teacher_register():
    return render_template("teacher-register.html")

@app.route("/teacher-course")
def teacher_course():
    return render_template("teacher-course.html")



if __name__ == "__main__":
    app.run(debug=True)

