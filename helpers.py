# routes/student/helpers.py
# Shared helper functions used across student routes

from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename
from functools import wraps
from flask_login import current_user
import jwt
import datetime
import os
import secrets

from models import User
from extensions import db

# File upload settings
ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg"}
ALLOWED_DOCUMENT_EXT = {"pdf", "doc", "docx", "txt", "ppt", "pptx"}


def generate_tokens_for_user(user):
    """Generate JWT access and refresh tokens"""
    secret = current_app.config["SECRET_KEY"]
    
    access_payload = {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=30)
    }
    
    refresh_payload = {
        "user_id": user.id,
        "email": user.email,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    
    access_token = jwt.encode(access_payload, secret, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, secret, algorithm="HS256")
    
    if isinstance(access_token, bytes):
        access_token = access_token.decode("utf-8")
    if isinstance(refresh_token, bytes):
        refresh_token = refresh_token.decode("utf-8")
    
    return access_token, refresh_token


def decode_token(token):
    """Decode JWT token"""
    secret = current_app.config["SECRET_KEY"]
    return jwt.decode(token, secret, algorithms=["HS256"])


def token_required(f):
    """JWT authentication decorator"""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Try session-based authentication first
        if current_user and getattr(current_user, "is_authenticated", False):
            return f(current_user, *args, **kwargs)

        # Try token-based authentication
        auth_header = request.headers.get("Authorization")
        token = None
        
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        
        if not token:
            token = request.cookies.get("access_token")

        if not token:
            return jsonify({
                "status": "error",
                "message": "Authentication required. Please login."
            }), 401

        try:
            payload = decode_token(token)
            user = User.query.get(payload.get("user_id"))
            
            if not user:
                return jsonify({"status": "error", "message": "User not found."}), 401
                
            if user.role != "student":
                return jsonify({"status": "error", "message": "Access denied. Students only."}), 403
                
        except jwt.ExpiredSignatureError:
            return jsonify({"status": "error", "message": "Token expired. Please refresh your session."}), 401
        except jwt.InvalidTokenError:
            return jsonify({"status": "error", "message": "Invalid token."}), 401

        return f(user, *args, **kwargs)
    return decorated


def save_file(file, folder, allowed_extensions):
    """Securely save uploaded file with unique name"""
    if not file or not file.filename:
        return None
    
    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in allowed_extensions:
        raise ValueError(f"File type .{ext} not allowed")
    
    upload_folder = os.path.join(current_app.config.get("UPLOAD_FOLDER", "static/uploads"), folder)
    os.makedirs(upload_folder, exist_ok=True)
    
    unique_id = secrets.token_hex(8)
    safe_filename = secure_filename(file.filename)
    final_name = f"{unique_id}_{safe_filename}"
    
    file_path = os.path.join(upload_folder, final_name)
    file.save(file_path)
    
    return f"uploads/{folder}/{final_name}"




def is_ajax_request():
    """Check if request is an AJAX call"""
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def success_response(message, data=None, redirect_url=None):
    """Standard success response format"""
    response = {"status": "success", "message": message}
    if data:
        response["data"] = data
    if redirect_url:
        response["redirect"] = redirect_url
    return jsonify(response)


def error_response(message, status_code=400, errors=None):
    """Standard error response format"""
    response = {"status": "error", "message": message}
    if errors:
        response["errors"] = errors
    return jsonify(response), status_code