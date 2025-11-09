"""
StudyHub - Student Routes Package
Combines all student-related sub-blueprints into main student blueprint

Structure:
- Auth: Registration, login, verification
- Dashboard: Overview, stats
- Posts: Create, view, interact with posts
- Comments: Add, edit comments
- Threads: Collaboration groups
- Connections: Friend requests
- Messages: Private messaging
- Profile: View/edit profile
- Badges: Achievement system
- Reputation: Points and leaderboards
- Analytics: Activity tracking
- Search: Find users/posts/threads
- Study Buddy: Find study partners
"""

from flask import Blueprint

# ============================================================================
# CREATE MAIN STUDENT BLUEPRINT
# ============================================================================

student_bp = Blueprint('student', __name__, url_prefix='/student')


# ============================================================================
# IMPORT ALL SUB-BLUEPRINTS
# ============================================================================

from .auth import auth_bp
from .posts import posts_bp
from .profile import profile_bp
from .connections import connections_bp
from .messages import messages_bp
from .threads import threads_bp
from .badges import badges_bp
from .reputation import reputation_bp
from .analytics import analytics_bp
from .search import search_bp
from .study_buddy import study_buddy_bp

# Optional routes (uncomment if you have them)
# from .assignments import assignments_bp
# from .grades import grades_bp
# from .attendance import attendance_bp
# from .fees import fees_bp
# from .account import account_bp
# from .notifications import notifications_bp
# from .resources import resources_bp
# from .extras import extras_bp
# from .password_reset import password_reset_bp


# ============================================================================
# REGISTER ALL SUB-BLUEPRINTS
# ============================================================================

# Core features
student_bp.register_blueprint(auth_bp)
student_bp.register_blueprint(posts_bp)
student_bp.register_blueprint(profile_bp)

# Social features
student_bp.register_blueprint(connections_bp)
student_bp.register_blueprint(messages_bp)
student_bp.register_blueprint(threads_bp)
student_bp.register_blueprint(study_buddy_bp)

# Gamification
student_bp.register_blueprint(badges_bp)
student_bp.register_blueprint(reputation_bp)

# Discovery & Analytics
student_bp.register_blueprint(search_bp)
student_bp.register_blueprint(analytics_bp)





