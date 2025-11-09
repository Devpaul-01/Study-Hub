# app.py
from flask import Flask, render_template
from extensions import db, login_manager, mail
import os
from routes.student import student_bp
from models import User


# --- Configuration class ---
class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'sqlite:///school.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", "static/upload")

    # Email settings
 
   
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file upload
    
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = os.environ.get("MAIL_PORT")
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.environ.get("MAIL_DEFAULT_SENDER")
    BREVO_API_KEY = os.environ.get("BREVO_API_KEY")
  


# --- Application Factory ---
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)


    # Initialize extensions
    db.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    # Configure login manager
    login_manager.login_view = "student.student_auth.login"
    login_manager.login_message_category = "info"

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    app.register_blueprint(student_bp, url_prefix="/student")

    # Example route
    @app.route("/")
    def home():
        return render_template("home.html")

    return app


# --- Run the app ---
if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host="0.0.0.0", port=5001)  # changed port to 5001