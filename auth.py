# routes/student/auth.py
# FIXED: Proper email verification flow and added missing endpoints
from flask import Blueprint, request, jsonify, redirect, url_for, current_app, make_response, render_template
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import login_user, logout_user
import re

from models import User, StudentProfile
from extensions import db
from utils import generate_verification_token, send_verification_email, verify_token
from .helpers import (
    generate_tokens_for_user, decode_token,
    success_response, error_response
)

auth_bp = Blueprint("student_auth", __name__)

# ============================================================================
# CONSTANTS
# ============================================================================
DEPARTMENTS = [
    "Architecture", "Computer Science", "Engineering (Civil)", "Engineering (Electrical)",
    "Engineering (Mechanical)", "Medicine & Surgery", "Pharmacy", "Nursing", "Law",
    "Accounting", "Business Administration", "Economics", "Mass Communication", "English",
    "History", "Biology", "Chemistry", "Physics", "Mathematics", "Statistics",
    "Psychology", "Sociology", "Political Science", "Agricultural Science",
    "Fine Arts", "Music", "Theatre Arts"
]

CLASS_LEVELS = ["100 Level", "200 Level", "300 Level", "400 Level", "500 Level"]


# ============================================================================
# REGISTER
# ============================================================================
@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Render registration page or handle registration API"""
    if request.method == "GET":
        return render_template("auth/register.html")
    
    try:
        data = request.get_json()
        if not data:
            return error_response("No data provided")
        
        full_name = data.get("full_name", "").strip()
        email = data.get("email", "").strip().lower()
        class_level = data.get("class_level", "").strip()
        department = data.get("department", "").strip()

        if not all([full_name, email, class_level, department]):
            return error_response("All fields are required")
        if class_level not in CLASS_LEVELS:
            return error_response("Invalid class level")
        if department not in DEPARTMENTS:
            return error_response("Invalid department")

        email_pattern = r'^[^\s@]+@[^\s@]+\.[^\s@]+$'
        if not re.match(email_pattern, email):
            return error_response("Invalid email format")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            return error_response("Email already registered")

        new_user = User(
            name=full_name,
            email=email,
            role="student",
            pin="PENDING_VERIFICATION",
            status="pending_verification",
            email_verified=False
        )
        db.session.add(new_user)
        db.session.flush()

        student_profile = StudentProfile(
            user_id=new_user.id,
            full_name=full_name,
            class_name=class_level,
            department=department,
            date_of_birth=None,
            pin="PENDING_VERIFICATION",
            status="incomplete"
        )
        db.session.add(student_profile)
        db.session.commit()

        token = generate_verification_token(email)
        verification_url = url_for("student.student_auth.verify_email", token=token, _external=True)
        send_verification_email(email, verification_url)

        return success_response(
            "Registration started! Check your email to continue.",
            data={"email": email}
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Registration error: {str(e)}")
        return error_response(f"Registration failed: {str(e)}")


# ============================================================================
# VERIFY EMAIL (FIXED - Returns email to frontend)
# ============================================================================
@auth_bp.route("/verify-email/<token>", methods=["GET"])
def verify_email(token):
    """Render verification page"""
    return render_template("auth/verify-email.html")


@auth_bp.route("/api/verify-email/<token>", methods=["GET"])
def verify_email_api(token):
    """API endpoint for email verification"""
    try:
        email = verify_token(token)
        if not email:
            return error_response("Verification link expired or invalid")

        user = User.query.filter_by(email=email).first()
        if not user:
            return error_response("User not found")

        if user.email_verified and user.status == "approved":
            return success_response(
                "Email already verified!",
                data={"email": email, "already_verified": True}
            )

        user.email_verified = True
        db.session.commit()

        return success_response(
            "Email verified successfully!",
            data={"email": email, "redirect_url": f"/student/complete-registration?email={email}"}
        )

    except Exception as e:
        current_app.logger.error(f"Verification error: {str(e)}")
        return error_response("Verification failed")

# ============================================================================
# CHECK USERNAME AVAILABILITY (NEW)
# ============================================================================
@auth_bp.route("/check-username", methods=["POST"])
def check_username():
    """Check if username is available"""
    try:
        data = request.get_json()
        username = data.get("username", "").strip().lower()
        
        if not username:
            return error_response("Username required"), 400
        
        if not re.match(r'^[a-z0-9]{3,20}$', username):
            return error_response("Invalid username format"), 400
        
        existing = User.query.filter_by(username=username).first()
        
        if existing:
            return error_response("Username taken"), 409
        
        return success_response("Username available", data={"available": True})
        
    except Exception as e:
        current_app.logger.error(f"Check username error: {str(e)}")
        return error_response("Check failed"), 500


# ============================================================================
# COMPLETE REGISTRATION
# ============================================================================
@auth_bp.route("/complete-registration", methods=["GET", "POST"])
def complete_registration():
    """Render complete registration page or handle API"""
    if request.method == "GET":
        return render_template("auth/complete-registration.html")
    
    try:
        data = request.get_json()
        if not data:
            return error_response("No data provided"), 400
        
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        confirm_password = data.get("confirm_password", "")
        username = data.get("username", "").strip().lower()

        if not all([email, password, confirm_password, username]):
            return error_response("All fields are required"), 400
        if password != confirm_password:
            return error_response("Passwords do not match"), 400
        if len(password) < 6:
            return error_response("Password must be at least 6 characters"), 400
        if not re.match(r'^[a-z0-9]{3,20}$', username):
            return error_response("Username must be 3-20 lowercase letters and numbers only"), 400

        user = User.query.filter_by(email=email, email_verified=True).first()
        if not user:
            return error_response("User not found or email not verified"), 404

        existing_username = User.query.filter_by(username=username).first()
        if existing_username:
            return error_response("Username already taken"), 409

        hashed_password = generate_password_hash(password)
        user.pin = hashed_password
        user.username = username
        user.status = "approved"

        student_profile = StudentProfile.query.filter_by(user_id=user.id).first()
        if student_profile:
            student_profile.pin = hashed_password
            student_profile.username = username
            student_profile.status = "active"

        db.session.commit()

        return success_response(
            f"Registration complete! Welcome, @{username}!",
            data={"username": username}
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Complete registration error: {str(e)}")
        return error_response(f"Registration failed: {str(e)}"), 500


# ============================================================================
# LOGIN
# ============================================================================
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render login page or handle login API"""
    if request.method == "GET":
        return render_template("auth/login.html")
    
    try:
        data = request.get_json()
        if not data:
            return error_response("No data provided")
        
        username_or_email = data.get("username_or_email", "").strip().lower()
        password = data.get("password", "")

        if not username_or_email or not password:
            return error_response("Username/Email and password required")

        user = User.query.filter(
            (User.username == username_or_email) | (User.email == username_or_email)
        ).first()

        if not user or not check_password_hash(user.pin, password):
            return error_response("Invalid credentials")

        if not user.email_verified:
            return error_response("Please verify your email first")
        if user.pin == "PENDING_VERIFICATION":
            return error_response("Please complete your registration")
        if not user.username:
            return error_response("Please complete your registration")
        if user.status != "approved":
            return error_response("Your registration is incomplete")

        access_token, refresh_token = generate_tokens_for_user(user)
        login_user(user)

        response = make_response(success_response(
            f"Welcome back, @{user.username}!",
            data={
                "user": {
                    "id": user.id,
                    "name": user.name,
                    "username": user.username,
                    "email": user.email
                },
                "redirect": "/student/profile/homepage"
            }
        ))

        response.set_cookie("access_token", access_token, httponly=True,
                            secure=False, samesite="Lax", max_age=30 * 60)
        response.set_cookie("refresh_token", refresh_token, httponly=True,
                            secure=False, samesite="Lax", max_age=7 * 24 * 60 * 60)

        return response

    except Exception as e:
        current_app.logger.error(f"Login error: {str(e)}")
        return error_response(f"Login failed: {str(e)}")


# ============================================================================
# LOGOUT
# ============================================================================
@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Logout user"""
    try:
        logout_user()
        if request.method == "GET":
            return redirect(url_for("student_auth.login"))
        response = make_response(success_response("Logged out successfully"))
        response.set_cookie("access_token", "", max_age=0)
        response.set_cookie("refresh_token", "", max_age=0)
        return response
    except Exception as e:
        current_app.logger.error(f"Logout error: {str(e)}")
        return error_response("Logout failed"), 500