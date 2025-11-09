"""
StudyHub - User Profile Management
Handles profile viewing, editing, stats, badges, and customization
"""

from flask import Blueprint, request, jsonify, current_app, render_template
from werkzeug.utils import secure_filename
from sqlalchemy import func, desc
import os
import datetime

from models import (
    User, StudentProfile, Post, Comment, Thread, ThreadMember,
    UserBadge, Badge, ReputationHistory, UserActivity, Connection,
    PostLike, PostReaction, Bookmark
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response,
    save_file, ALLOWED_IMAGE_EXT
)

profile_bp = Blueprint("student_profile", __name__)


# ============================================================================
# PROFILE VIEWING
# ============================================================================
@profile_bp.route("/profile/notifications", methods=["GET"])
@token_required
def notifications_page(current_user):
    return render_template("notifications.html")
    
@profile_bp.route("/profile/notifications/data", methods=["GET"])
@token_required
def notifications(current_user):
    if request.method == "GET":
        return render_template("notifications.html")
    try:
        # Fetch user notifications ordered by creation time (latest first)
        notifications = (
            Notification.query
            .filter_by(user_id=current_user.id)
            .order_by(Notification.created_at.desc())
            .all()
        )

        if not notifications:
            return jsonify({
                "status": "success",
                "data": [],
                "message": "No notifications at the moment"
            }), 200

        notification_list = [
            {
                "id": n.id,
                "title": n.title,
                "body": n.body,
                "type": n.notification_type,
                "related_id": n.related_id,
                "related_type": n.related_type,
                "is_read": n.is_read,
                "created_at": n.created_at,
            }
            for n in notifications
        ]

        return jsonify({
            "status": "success",
            "data": notification_list
        }), 200

    except Exception as e:
        # Optional: Log the actual error for debugging
        print(f"Error loading notifications: {e}")
        return jsonify({
            "status": "error",
            "message": "An error occurred while loading notifications"
        })

@profile_bp.route("/profile/notifications/<int:notif_id>", methods=["DELETE"])
@token_required
def delete_notification(current_user, notif_id):
    """Delete a notification"""
    try:
        notif = Notification.query.get(notif_id)
        if not notif or notif.user_id != current_user.id:
            return error_response('Notification not found', 404)
        
        db.session.delete(notif)
        db.session.commit()
        
        return success_response('Notification deleted')
    except Exception as e:
        db.session.rollback()
        return error_response('Failed to delete notification')
   

@profile_bp.route("/profile/notifications/grouped", methods=["GET"])
@token_required
def get_grouped_notifications(current_user):
    """Get notifications grouped by type for better UX"""
    try:
        notifications = Notification.query.filter_by(
            user_id=current_user.id
        ).order_by(Notification.created_at.desc()).limit(100).all()
        
        grouped = {
            'posts': [],
            'badges': [],
            'connections': [],
            'threads': [],
            'messages': [],
            'mentions': [],
            'study_buddy': []
        }
        
        for notif in notifications:
            data = {
                'id': notif.id,
                'title': notif.title,
                'body': notif.body,
                'type': notif.notification_type,
                'related_type': notif.related_type,
                'related_id': notif.related_id,
                'is_read': notif.is_read,
                'created_at': notif.created_at.isoformat()
            }
            
            # Group by category
            if notif.notification_type in ['like', 'comment', 'helpful', 'solution_accepted']:
                grouped['posts'].append(data)
            elif notif.notification_type in ['badge_earned', 'reputation_level_up']:
                grouped['badges'].append(data)
            elif notif.notification_type in ['connection_request', 'connection_accepted']:
                grouped['connections'].append(data)
            elif notif.notification_type.startswith('thread_'):
                grouped['threads'].append(data)
            elif notif.notification_type == 'message':
                grouped['messages'].append(data)
            elif notif.notification_type == 'mention':
                grouped['mentions'].append(data)
            elif notif.notification_type.startswith('study_buddy_'):
                grouped['study_buddy'].append(data)
        
        return jsonify({
            'status': 'success',
            'data': {
                'grouped': grouped,
                'unread_count': sum(1 for n in notifications if not n.is_read)
            }
        })
    except Exception as e:
        return error_response('Failed to load notifications')

@profile_bp.route("/profile/notifications/<int:notif_id>/read", methods=["POST"])
@token_required
def mark_notification_read(current_user, notif_id):
    """Mark single notification as read"""
    try:
        notif = Notification.query.get(notif_id)
        if not notif or notif.user_id != current_user.id:
            return error_response('Notification not found', 404)
        
        notif.is_read = True
        notif.read_at = datetime.datetime.utcnow()
        db.session.commit()
        
        return success_response('Marked as read')
    except Exception as e:
        db.session.rollback()
        return error_response('Failed to mark as read')

@profile_bp.route("/profile/notifications/read-all", methods=["POST"])
@token_required
def mark_all_read(current_user):
    """Mark all notifications as read"""
    try:
        Notification.query.filter_by(
            user_id=current_user.id,
            is_read=False
        ).update({'is_read': True, 'read_at': datetime.datetime.utcnow()})
        db.session.commit()
        return success_response('All marked as read')
    except Exception as e:
        db.session.rollback()
        return error_response('Failed to mark all as read')
           
    
@profile_bp.route("/profile", methods=["GET"])
@token_required
def get_own_profile(current_user):
    """
    Get current user's full profile including stats, badges, and activity.
    """
    if request.method == "GET":
        return render_template("profile.html")
    try:
        # Fetch the profile
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        if not profile:
            return error_response("Profile not found", 404)

        # Activity stats
        total_posts = Post.query.filter_by(student_id=current_user.id).count()
        total_comments = Comment.query.filter_by(student_id=current_user.id).count()
        total_threads = ThreadMember.query.filter_by(student_id=current_user.id).count()

        # Engagement stats
        posts_liked = db.session.query(func.count(PostLike.id)).join(
            Post, PostLike.post_id == Post.id
        ).filter(Post.student_id == current_user.id).scalar() or 0

        helpful_count = db.session.query(func.count(PostReaction.id)).join(
            Post, PostReaction.post_id == Post.id
        ).filter(
            Post.student_id == current_user.id,
            PostReaction.reaction_type == "helpful"
        ).scalar() or 0

        # Badges
        user_badges = UserBadge.query.filter_by(user_id=current_user.id).join(Badge).order_by(
            UserBadge.is_featured.desc(),
            Badge.rarity.desc()
        ).limit(6).all()

        badges_data = [{
            "id": ub.badge.id,
            "name": ub.badge.name,
            "description": ub.badge.description,
            "icon": ub.badge.icon,
            "rarity": ub.badge.rarity,
            "earned_at": ub.earned_at.isoformat(),
            "is_featured": ub.is_featured
        } for ub in user_badges]

        # Recent posts
        recent_posts = Post.query.filter_by(student_id=current_user.id).order_by(
            Post.posted_at.desc()
        ).limit(5).all()
        
        
        posts_data = [{
            "id": p.id,
            "title": p.title,
            "post_type": p.post_type,
            "likes_count": p.likes_count,
            "comments_count": p.comments_count,
            "posted_at": p.posted_at.isoformat(),
            "is_pinned": p.is_pinned, 
            "is_featured": current_user.featured_post_id == p.id, 
            "is_solved": p.is_solved
        } for p in recent_posts]

        # Active threads
        active_threads = db.session.query(Thread).join(
            ThreadMember, Thread.id == ThreadMember.thread_id
        ).filter(ThreadMember.student_id == current_user.id).order_by(
            Thread.last_activity.desc()
        ).limit(5).all()

        threads_data = [{
            "id": t.id,
            "title": t.title,
            "member_count": t.member_count,
            "is_creator": t.creator_id == current_user.id,
            "last_activity": t.last_activity.isoformat()
        } for t in active_threads]

        # Activity heatmap (last 30 days)
        thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)
        activity_data = UserActivity.query.filter(
            UserActivity.user_id == current_user.id,
            UserActivity.activity_date >= thirty_days_ago
        ).order_by(UserActivity.activity_date.asc()).all()

        heatmap = [{
            "date": act.activity_date.isoformat(),
            "score": act.activity_score,
            "posts": act.posts_created,
            "comments": act.comments_created
        } for act in activity_data]

        # Skills & learning goals
        skills = current_user.skills if current_user.skills else []
        learning_goals = current_user.learning_goals if current_user.learning_goals else []

        # Privacy settings
        privacy = current_user.privacy_settings if current_user.privacy_settings else {}
        show_stats = privacy.get("show_stats", True)

        return jsonify({
            "status": "success",
            "data": {
                "user": {
                    "id": current_user.id,
                    "username": current_user.username,
                    "name": current_user.name,
                    "bio": current_user.bio,
                    "avatar": current_user.avatar,
                    "department": profile.department,
                    "class_level": profile.class_name,
                    "reputation": current_user.reputation if show_stats else None,
                    "reputation_level": current_user.reputation_level if show_stats else None,
                    "login_streak": current_user.login_streak if show_stats else None,
                    "joined_at": current_user.joined_at.isoformat(),
                    "last_active": current_user.last_active.isoformat() if current_user.last_active else None
                },
                "stats": {
                    "total_posts": total_posts,
                    "total_comments": total_comments,
                    "total_threads": total_threads,
                    "posts_liked": posts_liked,
                    "helpful_count": helpful_count,
                    "total_helpful": current_user.total_helpful
                } if show_stats else None,
                "badges": badges_data,
                "featured_posts": featured_post,
                "active_threads": threads_data,
                "activity_heatmap": heatmap if show_stats else None,
                "skills": skills,
                "learning_goals": learning_goals,
                "featured_post_id": current_user.featured_post_id,
                "is_own_profile": True,
                "can_message": False  # messaging self not needed
            }
        })

    except Exception as e:
        current_app.logger.error(f"Get own profile error: {str(e)}")
        return error_response("Failed to load profile")

@profile_bp.route("/profile/counts", methods=["GET"])
@token_required
def get_counts(current_user):
    try:
        # Fetch profile (optional)
        student_profile = StudentProfile.query.filter_by(user_id=current_user.id).first()

        # Unread notifications
        notifications = Notification.query.filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        ).count()

        # Unread messages (only those not deleted by sender or receiver)
        messages = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.deleted_by_sender == False,
            Message.deleted_by_receiver == False
        ).count()

        total_counts = messages + notifications

        return jsonify({
            "status": "success",
            "data": {
                "total_counts": total_counts,
                "messages": messages,
                "notifications": notifications
            }
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": "Failed to load counts"}), 500
        
        
       
        
@profile_bp.route("/profile/<username>", methods=["GET"])
@token_required
def view_profile(current_user, username):
    """
    View any user's profile - complete stats and activity
    
    Frontend gets:
    - Basic info (name, bio, department, avatar)
    - Stats (posts, threads, reputation, streak)
    - Badges earned
    - Recent activity
    - Active threads
    - Connection status with viewer
    """
    try:
        # Find user by username
        user = User.query.filter_by(username=username).first()
        if not user:
            return error_response("User not found", 404)
        
        profile = StudentProfile.query.filter_by(user_id=user.id).first()
        if not profile:
            return error_response("Profile not found", 404)
        
        # Check connectio    n status with current viewer
        connection_status = "none"  # none, pending_sent, pending_received, connected
        if current_user.id != user.id:
            connection = Connection.query.filter(
                ((Connection.requester_id == current_user.id) & (Connection.receiver_id == user.id)) |
                ((Connection.requester_id == user.id) & (Connection.receiver_id == current_user.id))
            ).first()
            
            if connection:
                if connection.status == "accepted":
                    connection_status = "connected"
                elif connection.requester_id == current_user.id:
                    connection_status = "pending_sent"
                else:
                    connection_status = "pending_received"
        
        # Activity stats
        total_posts = Post.query.filter_by(student_id=user.id).count()
        total_comments = Comment.query.filter_by(student_id=user.id).count()
        total_threads = ThreadMember.query.filter_by(student_id=user.id).count()
        
        # Engagement stats
        posts_liked = db.session.query(func.count(PostLike.id)).join(
            Post, PostLike.post_id == Post.id
        ).filter(Post.student_id == user.id).scalar() or 0
        
        helpful_count = db.session.query(func.count(PostReaction.id)).join(
            Post, PostReaction.post_id == Post.id
        ).filter(
            Post.student_id == user.id,
            PostReaction.reaction_type == "helpful"
        ).scalar() or 0
        
        # Badges (show featured first, then by rarity)
        user_badges = UserBadge.query.filter_by(user_id=user.id).join(Badge).order_by(
            UserBadge.is_featured.desc(),
            Badge.rarity.desc()
        ).limit(6).all()
        
        badges_data = [{
            "id": ub.badge.id,
            "name": ub.badge.name,
            "description": ub.badge.description,
            "icon": ub.badge.icon,
            "rarity": ub.badge.rarity,
            "earned_at": ub.earned_at.isoformat(),
            "is_featured": ub.is_featured
        } for ub in user_badges]
        
       featured_post = Post.query.filter(student_id == user.id, user.featured_post_id == Post.id).first()
       pinned_posts =  Post.query.filter(Post.student_id == user.id, Post.is_featured == True).all()
       
        
        # Recent posts (last 5)
        recent_posts = Post.query.filter_by(student_id=user.id).order_by(
            Post.posted_at.desc()
        ).limit(5).all()
        
        posts_data = [{
            "id": p.id,
            "title": p.title,
            "post_type": p.post_type,
            "likes_count": p.likes_count,
            "comments_count": p.comments_count,
            "posted_at": p.posted_at.isoformat(),
            "is_solved": p.is_solved
        } for p in recent_posts]
        
        # Active threads
        active_threads = db.session.query(Thread).join(
            ThreadMember, Thread.id == ThreadMember.thread_id
        ).filter(ThreadMember.student_id == user.id).order_by(
            Thread.last_activity.desc()
        ).limit(5).all()
        
        threads_data = [{
            "id": t.id,
            "title": t.title,
            "member_count": t.member_count,
            "is_creator": t.creator_id == user.id,
            "last_activity": t.last_activity.isoformat()
        } for t in active_threads]
        
        # Activity heatmap (last 30 days)
        thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)
        activity_data = UserActivity.query.filter(
            UserActivity.user_id == user.id,
            UserActivity.activity_date >= thirty_days_ago
        ).order_by(UserActivity.activity_date.asc()).all()
        
        heatmap = [{
            "date": act.activity_date.isoformat(),
            "score": act.activity_score,
            "posts": act.posts_created,
            "comments": act.comments_created
        } for act in activity_data]
        
        # Skills & learning goals
        skills = user.skills if user.skills else []
        learning_goals = user.learning_goals if user.learning_goals else []
        
        # Privacy check - respect user's privacy settings
        privacy = user.privacy_settings if user.privacy_settings else {}
        show_stats = privacy.get("show_stats", True)
        profile_visible = privacy.get("profile_visible", "public")
        
        # If profile is private and not connected, hide details
        if profile_visible == "private" and connection_status != "connected" and current_user.id != user.id:
            return jsonify({
                "status": "success",
                "data": {
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "name": user.name,
                        "avatar": user.avatar,
                        "department": profile.department,
                        "featured_post": featured_post, 
                        "pinned_posts": pinned_posts, 
                        "class_level": profile.class_name
                    },
                    "privacy": {
                        "is_private": True,
                        "message": "This profile is private. Connect to view details."
                    },
                    "connection_status": connection_status,
                    "is_own_profile": False
                }
            })
        
        # Full profile data
        return jsonify({
            "status": "success",
            "data": {
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "bio": user.bio,
                    "avatar": user.avatar,
                    "department": profile.department,
                    "class_level": profile.class_name,
                    "reputation": user.reputation if show_stats else None,
                    "reputation_level": user.reputation_level if show_stats else None,
                    "login_streak": user.login_streak if show_stats else None,
                    "joined_at": user.joined_at.isoformat(),
                    "last_active": user.last_active.isoformat() if user.last_active else None
                },
                "stats": {
                    "total_posts": total_posts,
                    "total_comments": total_comments,
                    "total_threads": total_threads,
                    "posts_liked": posts_liked,
                    "helpful_count": helpful_count,
                    "total_helpful": user.total_helpful
                } if show_stats else None,
                "badges": badges_data,
                "recent_posts": posts_data,
                "active_threads": threads_data,
                "activity_heatmap": heatmap if show_stats else None,
                "skills": skills,
                "learning_goals": learning_goals,
                "featured_post_id": user.featured_post_id,
                "connection_status": connection_status,
                "is_own_profile": current_user.id == user.id,
                "can_message": connection_status == "connected"
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"View profile error: {str(e)}")
        return error_response("Failed to load profile")
        
        
@profile_bp.route("/profile/me", methods=["GET"])
@token_required
def my_profile(current_user):
    """
    Get current user's own profile - includes private data
    """
    return view_profile(current_user, current_user.username)


# ============================================================================
# PROFILE EDITING
# ============================================================================

@profile_bp.route("/profile/update", methods=["PATCH"])
@token_required
def update_profile(current_user):
    """
    Update profile info: name, bio, department, class
    
    Accepts JSON or form data:
    - name: Full name
    - bio: Short bio (max 500 chars)
    - department: Department (must be valid)
    - class_level: Class level
    """
    try:
        data = request.get_json(silent=True) or request.form.to_dict()
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        if not profile:
            return error_response("Profile not found", 404)
        
        changes = []
        
        # Update name
        if "name" in data and data["name"].strip():
            new_name = data["name"].strip()
            if len(new_name) < 3:
                return error_response("Name must be at least 3 characters")
            if new_name != current_user.name:
                current_user.name = new_name
                profile.full_name = new_name
                changes.append("name")
        
        # Update bio
        if "bio" in data:
            new_bio = data["bio"].strip()
            if len(new_bio) > 500:
                return error_response("Bio must be less than 500 characters")
            if new_bio != current_user.bio:
                current_user.bio = new_bio
                changes.append("bio")
        
        # Update department (validate against allowed list)
        if "department" in data and data["department"].strip():
            new_dept = data["department"].strip()
            # You can add validation here against DEPARTMENTS list
            if new_dept != profile.department:
                profile.department = new_dept
                changes.append("department")
        
        # Update class level
        if "class_level" in data and data["class_level"].strip():
            new_class = data["class_level"].strip()
            # Validate against CLASS_LEVELS
            if new_class != profile.class_name:
                profile.class_name = new_class
                changes.append("class_level")
        
        if changes:
            db.session.commit()
            return success_response(
                "Profile updated successfully",
                data={
                    "changes": changes,
                    "user": {
                        "name": current_user.name,
                        "bio": current_user.bio,
                        "department": profile.department,
                        "class_level": profile.class_name
                    }
                }
            )
        else:
            return success_response("No changes made")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Profile update error: {str(e)}")
        return error_response("Failed to update profile")


@profile_bp.route("/profile/avatar/upload", methods=["POST"])
@token_required
def upload_avatar(current_user):
    """
    Upload profile picture
    
    Accepts: multipart/form-data with 'avatar' file
    Allowed: jpg, jpeg, png, gif
    Max size: 5MB
    """
    try:
        if 'avatar' not in request.files:
            return error_response("No file provided")
        
        file = request.files['avatar']
        
        if file.filename == '':
            return error_response("No file selected")
        
        # Validate file type
        if not file.filename.lower().endswith(tuple(ALLOWED_IMAGE_EXT)):
            return error_response(
                f"Invalid file type. Allowed: {', '.join(ALLOWED_IMAGE_EXT)}"
            )
        
        # Save file
        filename = save_file(file, "avatars", ALLOWED_IMAGE_EXT)
        
        # Update user avatar
        old_avatar = current_user.avatar
        current_user.avatar = filename
        
        db.session.commit()
        
        # Delete old avatar if exists (optional)
        if old_avatar:
            try:
                old_path = os.path.join(
                    current_app.config['UPLOAD_FOLDER'],
                    "avatars",
                    old_avatar
                )
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception as e:
                current_app.logger.warning(f"Failed to delete old avatar: {str(e)}")
        
        return success_response(
            "Avatar uploaded successfully",
            data={
                "avatar": filename,
                "avatar_url": f"/static/upload/avatars/{filename}"
            }
        )
        
    except ValueError as e:
        return error_response(str(e))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Avatar upload error: {str(e)}")
        return error_response("Failed to upload avatar")
        


@profile_bp.route("/profile/avatar", methods=["DELETE"])
@token_required
def remove_avatar(current_user):
    """
    Remove profile picture (set to default)
    """
    try:
        old_avatar = current_user.avatar
        current_user.avatar = None
        
        db.session.commit()
        
        # Delete file
        if old_avatar:
            try:
                old_path = os.path.join(
                    current_app.config['UPLOAD_FOLDER'],
                    "avatars",
                    old_avatar
                )
                if os.path.exists(old_path):
                    os.remove(old_path)
            except Exception as e:
                current_app.logger.warning(f"Failed to delete avatar file: {str(e)}")
        
        return success_response("Avatar removed")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Remove avatar error: {str(e)}")
        return error_response("Failed to remove avatar")


# ============================================================================
# SKILLS & LEARNING GOALS
# ============================================================================

@profile_bp.route("/profile/skills", methods=["POST"])
@token_required
def add_skill(current_user):
    """
    Add a skill to profile
    
    Body: {"skill": "Python"}
    """
    try:
        data = request.get_json()
        skill = data.get("skill", "").strip()
        
        if not skill:
            return error_response("Skill name required")
        
        if len(skill) > 50:
            return error_response("Skill name too long (max 50 chars)")
        
        # Get current skills
        skills = current_user.skills if current_user.skills else []
        
        # Check if already exists (case-insensitive)
        if any(s.lower() == skill.lower() for s in skills):
            return error_response("Skill already added")
        
        # Limit to 10 skills
        if len(skills) >= 10:
            return error_response("Maximum 10 skills allowed")
        
        skills.append(skill)
        current_user.skills = skills
        
        db.session.commit()
        
        return success_response(
            "Skill added",
            data={"skills": skills}
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Add skill error: {str(e)}")
        return error_response("Failed to add skill")


@profile_bp.route("/profile/skills/<skill_name>", methods=["DELETE"])
@token_required
def remove_skill(current_user, skill_name):
    """
    Remove a skill from profile
    """
    try:
        skills = current_user.skills if current_user.skills else []
        
        # Remove skill (case-insensitive)
        skills = [s for s in skills if s.lower() != skill_name.lower()]
        
        current_user.skills = skills
        db.session.commit()
        
        return success_response(
            "Skill removed",
            data={"skills": skills}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Remove skill error: {str(e)}")
        return error_response("Failed to remove skill")


@profile_bp.route("/profile/learning-goals", methods=["POST"])
@token_required
def add_learning_goal(current_user):
    """
    Add learning goal to profile
    
    Body: {"goal": "Learn Machine Learning"}
    """
    try:
        data = request.get_json()
        goal = data.get("goal", "").strip()
        
        if not goal:
            return error_response("Goal required")
        
        if len(goal) > 100:
            return error_response("Goal too long (max 100 chars)")
        
        goals = current_user.learning_goals if current_user.learning_goals else []
        
        if goal in goals:
            return error_response("Goal already added")
        
        if len(goals) >= 5:
            return error_response("Maximum 5 learning goals allowed")
        
        goals.append(goal)
        current_user.learning_goals = goals
        
        db.session.commit()
        
        return success_response(
            "Learning goal added",
            data={"learning_goals": goals}
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Add goal error: {str(e)}")
        return error_response("Failed to add goal")


@profile_bp.route("/profile/learning-goals/<int:index>", methods=["DELETE"])
@token_required
def remove_learning_goal(current_user, index):
    """
    Remove learning goal by index
    """
    try:
        goals = current_user.learning_goals if current_user.learning_goals else []
        
        if index < 0 or index >= len(goals):
            return error_response("Invalid goal index")
        
        goals.pop(index)
        current_user.learning_goals = goals
        
        db.session.commit()
        
        return success_response(
            "Learning goal removed",
            data={"learning_goals": goals}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Remove goal error: {str(e)}")
        return error_response("Failed to remove goal")


# ============================================================================
# FEATURED POST
# ============================================================================

@profile_bp.route("/profile/pin-post/<int:post_id>", methods=["POST"])
@token_required
def pin_post(current_user, post_id):
    """
    Pin a post to profile as featured content
    """
    try:
        # Verify post belongs to user
        post = Post.query.filter_by(id=post_id, student_id=current_user.id).first()
        total_pinned = Post.query.filter_by(student_id = current_user.id, Post.is_pinned = True).count()
        
        if not post:
            return error_response("Post not found or not yours")
        if post.is_pinned:
            return success_response("Post has already been pinned")
        if total_pinned >= 5:
            return error_response("You cant pin more than 5 posts kindly a post")
        
            
        post.is_pinned = True
        
        db.session.commit()
        
        return success_response("Post pinned successfully")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Pin post error: {str(e)}")
        return error_response("Failed to pin post")

@profile_bp.route("/profile/unpin-post/<int:post_id>", methods=["POST"])
@token_required
def unpin_post(current_user, post_id):
    """
    Pin a post to profile as featured content
    """
    try:
        # Verify post belongs to user
        post = Post.query.filter_by(id=post_id, student_id=current_user.id).first()
        
        if not post:
            return error_response("Post not found or not yours")
        post.is_pinned = False
        db.session.commit()
        
        
        return success_response("Post unpinned successfully")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unpin post error: {str(e)}")
        return error_response("Failed to un:pin post")



@profile_bp.route("/profile/study-schedule", methods=["GET"])
@token_required
def get_study_schedule(current_user):
    """
    Get user's study schedule (when they're usually online)
    
    Returns: {
        "monday": ["morning", "evening"],
        "tuesday": ["afternoon"],
        ...
    }
    """
    schedule = current_user.study_schedule if current_user.study_schedule else {}
    
    # Default empty schedule
    default_schedule = {
        "monday": [],
        "tuesday": [],
        "wednesday": [],
        "thursday": [],
        "friday": [],
        "saturday": [],
        "sunday": []
    }
    
    return jsonify({
        "status": "success",
        "data": {
            "study_schedule": {**default_schedule, **schedule}
        }
    })


@profile_bp.route("/profile/study-schedule", methods=["POST"])
@token_required
def update_study_schedule(current_user):
    """
    Update study schedule
    
    Body: {
        "monday": ["morning", "evening"],
        "wednesday": ["afternoon"],
        "friday": ["evening", "night"]
    }
    
    Time slots: morning (6am-12pm), afternoon (12pm-6pm), evening (6pm-10pm), night (10pm-2am)
    """
    try:
        data = request.get_json()
        
        if not isinstance(data, dict):
            return error_response("Schedule must be an object")
        
        valid_days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        valid_times = ["morning", "afternoon", "evening", "night"]
        
        schedule = {}
        
        for day, times in data.items():
            day_lower = day.lower()
            
            if day_lower not in valid_days:
                return error_response(f"Invalid day: {day}")
            
            if not isinstance(times, list):
                return error_response(f"Times for {day} must be a list")
            
            # Validate time slots
            for time in times:
                if time not in valid_times:
                    return error_response(f"Invalid time slot: {time}")
            
            schedule[day_lower] = times
        
        current_user.study_schedule = schedule
        db.session.commit()
        
        return success_response(
            "Study schedule updated",
            data={"study_schedule": schedule}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update study schedule error: {str(e)}")
        return error_response("Failed to update study schedule")

@profile_bp.route("/skills/popular", methods=["GET"])
def get_popular_skills():
    """
    Get list of popular skills across all users
    Used for autocomplete/suggestions in frontend
    
    No auth required - public endpoint
    """
    try:
        # Aggregate all skills from all users
        users = User.query.filter(User.skills.isnot(None)).all()
        
        skill_counts = {}
        for user in users:
            if user.skills:
                for skill in user.skills:
                    skill_lower = skill.lower()
                    if skill_lower in skill_counts:
                        skill_counts[skill_lower]["count"] += 1
                    else:
                        skill_counts[skill_lower] = {
                            "name": skill,
                            "count": 1
                        }
        
        # Sort by popularity
        popular_skills = sorted(
            skill_counts.values(),
            key=lambda x: x["count"],
            reverse=True
        )[:50]  # Top 50 skills
        
        return jsonify({
            "status": "success",
            "data": {
                "skills": [s["name"] for s in popular_skills],
                "detailed": popular_skills
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get popular skills error: {str(e)}")
        return error_response("Failed to load skills")

@profile_bp.route("/profile/homepage", methods=["GET"])
def homepage():
    return render_template('base.html')
    

       