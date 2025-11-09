"""
StudyHub - Reputation System
Tracks user reputation through helpful actions and quality contributions
Includes leaderboards, history tracking, and auto-award logic

Reputation Points:
+5  → Post gets 10 likes
+10 → Comment marked as solution
+15 → Post marked helpful (reaction)
+20 → Post gets 50 likes
-2  → Post gets disliked
-10 → Content reported and confirmed

Reputation Levels:
0-50:    🌱 Newbie
51-200:  📚 Learner
201-500: 🎓 Contributor
501-1K:  🌟 Expert
1K+:     👑 Master
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func, desc, and_, or_
import datetime

from models import (
    User, StudentProfile, ReputationHistory, Post, Comment,
    PostLike, PostReaction, PostReport
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response
)

reputation_bp = Blueprint("student_reputation", __name__)


# ============================================================================
# REPUTATION CONSTANTS
# ============================================================================

REPUTATION_LEVELS = [
    {"min": 0, "max": 50, "name": "Newbie", "icon": "🌱", "color": "#6B7280"},
    {"min": 51, "max": 200, "name": "Learner", "icon": "📚", "color": "#3B82F6"},
    {"min": 201, "max": 500, "name": "Contributor", "icon": "🎓", "color": "#8B5CF6"},
    {"min": 501, "max": 1000, "name": "Expert", "icon": "🌟", "color": "#F59E0B"},
    {"min": 1001, "max": 999999, "name": "Master", "icon": "👑", "color": "#EF4444"}
]

REPUTATION_ACTIONS = {
    "post_10_likes": {"points": 5, "description": "Post reached 10 likes"},
    "post_50_likes": {"points": 20, "description": "Post reached 50 likes"},
    "post_100_likes": {"points": 50, "description": "Post reached 100 likes"},
    "comment_marked_solution": {"points": 15, "description": "Comment marked as solution"},
    "post_marked_helpful": {"points": 5, "description": "Post marked helpful"},
    "post_disliked": {"points": -2, "description": "Post received dislike"},
    "content_reported": {"points": -10, "description": "Content reported"},
    "helpful_streak_7": {"points": 10, "description": "7 helpful reactions in a week"},
    "thread_created": {"points": 3, "description": "Created study thread"},
    "thread_completed": {"points": 10, "description": "Thread reached 10+ members"},
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_reputation_level(reputation_points):
    """
    Calculate user's reputation level based on points
    Returns: dict with level info (name, icon, color, range)
    """
    for level in REPUTATION_LEVELS:
        if level["min"] <= reputation_points <= level["max"]:
            return level
    return REPUTATION_LEVELS[-1]  # Master (highest level)


def award_reputation(user_id, action_key, related_type=None, related_id=None, custom_points=None):
    """
    Award (or deduct) reputation points to a user
    
    Args:
        user_id: User receiving reputation
        action_key: Key from REPUTATION_ACTIONS dict
        related_type: "post", "comment", "thread" (optional)
        related_id: ID of related content (optional)
        custom_points: Override points (optional)
    
    Returns:
        ReputationHistory record
    """
    user = User.query.get(user_id)
    if not user:
        return None
    
    # Get action details
    action = REPUTATION_ACTIONS.get(action_key)
    if not action and not custom_points:
        return None
    
    points_change = custom_points if custom_points else action["points"]
    description = action["description"] if action else f"Custom: {points_change} points"
    
    # Store old reputation
    reputation_before = user.reputation
    
    # Update user reputation
    user.reputation += points_change
    user.reputation = max(0, user.reputation)  # Never go below 0
    
    # Update reputation level
    user.update_reputation_level()
    
    # Create history record
    history = ReputationHistory(
        user_id=user_id,
        action=action_key if action_key else "custom",
        points_change=points_change,
        related_type=related_type,
        related_id=related_id,
        reputation_before=reputation_before,
        reputation_after=user.reputation
    )
    db.session.add(history)
    
    # Check for level-up notification
    old_level = get_reputation_level(reputation_before)
    new_level = get_reputation_level(user.reputation)
    
    if old_level["name"] != new_level["name"]:
        # User leveled up! (Handle in notifications later)
        from models import Notification
        notification = Notification(
            user_id=user_id,
            title=f"Level Up! You're now a {new_level['name']}!",
            body=f"You've reached {user.reputation} reputation points {new_level['icon']}",
            notification_type="reputation_level_up",
            related_type="user",
            related_id=user_id
        )
        db.session.add(notification)
    
    db.session.commit()
    
    return history


def check_and_award_milestone(user_id, post_id=None, comment_id=None):
    """
    Check if user reached reputation milestones and award accordingly
    Called after likes/reactions are added
    
    Checks:
    - Post reached 10/50/100 likes
    - Post received helpful reactions
    """
    if post_id:
        post = Post.query.get(post_id)
        if post and post.student_id == user_id:
            # Check like milestones
            if post.likes_count == 10:
                award_reputation(user_id, "post_10_likes", "post", post_id)
            elif post.likes_count == 50:
                award_reputation(user_id, "post_50_likes", "post", post_id)
            elif post.likes_count == 100:
                award_reputation(user_id, "post_100_likes", "post", post_id)


# ============================================================================
# REPUTATION ENDPOINTS
# ============================================================================

@reputation_bp.route("/reputation/me", methods=["GET"])
@token_required
def get_my_reputation(current_user):
    """
    Get current user's reputation stats
    
    Returns:
    - Current reputation points
    - Reputation level (name, icon, color)
    - Progress to next level
    - Rank (position in global leaderboard)
    - Recent changes (last 5)
    """
    try:
        # Get current level
        level = get_reputation_level(current_user.reputation)
        
        # Calculate progress to next level
        next_level = None
        progress_percentage = 0
        
        for idx, lvl in enumerate(REPUTATION_LEVELS):
            if lvl["name"] == level["name"] and idx < len(REPUTATION_LEVELS) - 1:
                next_level = REPUTATION_LEVELS[idx + 1]
                points_needed = next_level["min"] - current_user.reputation
                level_range = next_level["min"] - level["min"]
                progress_percentage = ((current_user.reputation - level["min"]) / level_range) * 100
                break
        
        # Get global rank
        rank = db.session.query(func.count(User.id)).filter(
            User.reputation > current_user.reputation,
            User.status == "approved"
        ).scalar() + 1
        
        # Get recent reputation changes (last 5)
        recent_changes = ReputationHistory.query.filter_by(
            user_id=current_user.id
        ).order_by(ReputationHistory.created_at.desc()).limit(5).all()
        
        changes_data = [{
            "action": change.action,
            "points_change": change.points_change,
            "reputation_after": change.reputation_after,
            "related_type": change.related_type,
            "related_id": change.related_id,
            "created_at": change.created_at.isoformat()
        } for change in recent_changes]
        
        return jsonify({
            "status": "success",
            "data": {
                "reputation": {
                    "points": current_user.reputation,
                    "level": {
                        "name": level["name"],
                        "icon": level["icon"],
                        "color": level["color"],
                        "min": level["min"],
                        "max": level["max"]
                    },
                    "next_level": {
                        "name": next_level["name"],
                        "icon": next_level["icon"],
                        "points_needed": next_level["min"] - current_user.reputation,
                        "progress_percentage": round(progress_percentage, 1)
                    } if next_level else None,
                    "rank": {
                        "global": rank,
                        "total_users": User.query.filter_by(status="approved").count()
                    }
                },
                "recent_changes": changes_data
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get reputation error: {str(e)}")
        return error_response("Failed to load reputation data")


@reputation_bp.route("/reputation/history", methods=["GET"])
@token_required
def get_reputation_history(current_user):
    """
    Get full reputation change history
    
    Query params:
    - page: Page number (default 1)
    - per_page: Items per page (default 20, max 50)
    - action: Filter by action type
    """
    try:
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 20, type=int), 50)
        action_filter = request.args.get("action", "").strip()
        
        query = ReputationHistory.query.filter_by(user_id=current_user.id)
        
        # Filter by action if specified
        if action_filter:
            query = query.filter_by(action=action_filter)
        
        # Paginate
        paginated = query.order_by(
            ReputationHistory.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        history_data = []
        for record in paginated.items:
            history_data.append({
                "id": record.id,
                "action": record.action,
                "points_change": record.points_change,
                "reputation_before": record.reputation_before,
                "reputation_after": record.reputation_after,
                "related_type": record.related_type,
                "related_id": record.related_id,
                "created_at": record.created_at.isoformat()
            })
        
        # Calculate total gained/lost
        total_gained = db.session.query(
            func.sum(ReputationHistory.points_change)
        ).filter(
            ReputationHistory.user_id == current_user.id,
            ReputationHistory.points_change > 0
        ).scalar() or 0
        
        total_lost = abs(db.session.query(
            func.sum(ReputationHistory.points_change)
        ).filter(
            ReputationHistory.user_id == current_user.id,
            ReputationHistory.points_change < 0
        ).scalar() or 0)
        
        return jsonify({
            "status": "success",
            "data": {
                "history": history_data,
                "summary": {
                    "total_gained": int(total_gained),
                    "total_lost": int(total_lost),
                    "net_change": int(total_gained - total_lost),
                    "current_reputation": current_user.reputation
                },
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": paginated.total,
                    "pages": paginated.pages
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get reputation history error: {str(e)}")
        return error_response("Failed to load reputation history")


@reputation_bp.route("/reputation/leaderboard", methods=["GET"])
@token_required
def get_global_leaderboard(current_user):
    """
    Get global reputation leaderboard
    
    Query params:
    - limit: Number of users (default 50, max 100)
    - period: Time period (all_time, month, week)
    """
    try:
        limit = min(request.args.get("limit", 50, type=int), 100)
        period = request.args.get("period", "all_time")
        
        # Base query - approved users only
        query = User.query.filter_by(status="approved")
        
        # Filter by period (based on last_active)
        if period == "week":
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=7)
            query = query.filter(User.last_active >= cutoff)
        elif period == "month":
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=30)
            query = query.filter(User.last_active >= cutoff)
        
        # Get top users
        top_users = query.order_by(User.reputation.desc()).limit(limit).all()
        
        leaderboard_data = []
        for idx, user in enumerate(top_users, 1):
            profile = StudentProfile.query.filter_by(user_id=user.id).first()
            level = get_reputation_level(user.reputation)
            
            leaderboard_data.append({
                "rank": idx,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "avatar": user.avatar,
                    "department": profile.department if profile else None
                },
                "reputation": {
                    "points": user.reputation,
                    "level": {
                        "name": level["name"],
                        "icon": level["icon"],
                        "color": level["color"]
                    }
                },
                "stats": {
                    "total_posts": user.total_posts,
                    "total_helpful": user.total_helpful
                },
                "is_you": user.id == current_user.id
            })
        
        # Find current user's rank if not in top list
        your_rank = None
        if current_user.id not in [u["user"]["id"] for u in leaderboard_data]:
            your_rank = db.session.query(func.count(User.id)).filter(
                User.reputation > current_user.reputation,
                User.status == "approved"
            ).scalar() + 1
        
        return jsonify({
            "status": "success",
            "data": {
                "leaderboard": leaderboard_data,
                "period": period,
                "your_rank": your_rank,
                "total_users": User.query.filter_by(status="approved").count()
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get leaderboard error: {str(e)}")
        return error_response("Failed to load leaderboard")


@reputation_bp.route("/reputation/leaderboard/department/<department>", methods=["GET"])
@token_required
def get_department_leaderboard(current_user, department):
    """
    Get department-specific reputation leaderboard
    """
    try:
        limit = min(request.args.get("limit", 50, type=int), 100)
        
        # Get users from this department
        top_users = db.session.query(User).join(StudentProfile).filter(
            StudentProfile.department == department,
            User.status == "approved"
        ).order_by(User.reputation.desc()).limit(limit).all()
        
        leaderboard_data = []
        for idx, user in enumerate(top_users, 1):
            profile = StudentProfile.query.filter_by(user_id=user.id).first()
            level = get_reputation_level(user.reputation)
            
            leaderboard_data.append({
                "rank": idx,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "avatar": user.avatar,
                    "class_level": profile.class_name if profile else None
                },
                "reputation": {
                    "points": user.reputation,
                    "level": {
                        "name": level["name"],
                        "icon": level["icon"],
                        "color": level["color"]
                    }
                },
                "stats": {
                    "total_posts": user.total_posts,
                    "total_helpful": user.total_helpful
                },
                "is_you": user.id == current_user.id
            })
        
        # Find current user's rank in department
        your_rank = None
        current_profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        if current_profile and current_profile.department == department:
            your_rank = db.session.query(func.count(User.id)).join(StudentProfile).filter(
                StudentProfile.department == department,
                User.reputation > current_user.reputation,
                User.status == "approved"
            ).scalar() + 1
        
        # Total users in department
        total_dept_users = db.session.query(func.count(User.id)).join(StudentProfile).filter(
            StudentProfile.department == department,
            User.status == "approved"
        ).scalar()
        
        return jsonify({
            "status": "success",
            "data": {
                "leaderboard": leaderboard_data,
                "department": department,
                "your_rank": your_rank,
                "total_users": total_dept_users
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get department leaderboard error: {str(e)}")
        return error_response("Failed to load department leaderboard")


@reputation_bp.route("/reputation/award", methods=["POST"])
@token_required
def award_reputation_endpoint(current_user):
    """
    Internal endpoint to award reputation
    Should only be called by system/admin (add auth check later)
    
    Body: {
        "user_id": 123,
        "action": "post_10_likes",
        "related_type": "post",
        "related_id": 456
    }
    """
    try:
        data = request.get_json()
        
        user_id = data.get("user_id")
        action = data.get("action")
        related_type = data.get("related_type")
        related_id = data.get("related_id")
        custom_points = data.get("points")
        
        if not user_id or (not action and not custom_points):
            return error_response("user_id and (action or points) required")
        
        # Award reputation
        history = award_reputation(
            user_id, 
            action, 
            related_type, 
            related_id,
            custom_points
        )
        
        if not history:
            return error_response("Failed to award reputation")
        
        user = User.query.get(user_id)
        
        return success_response(
            "Reputation awarded",
            data={
                "user_id": user_id,
                "points_change": history.points_change,
                "new_reputation": user.reputation,
                "new_level": user.reputation_level
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Award reputation error: {str(e)}")
        return error_response("Failed to award reputation")


# ============================================================================
# REPUTATION LEVELS INFO (Public)
# ============================================================================

@reputation_bp.route("/reputation/levels", methods=["GET"])
def get_reputation_levels():
    """
    Get all reputation levels and their requirements
    Public endpoint - no auth required
    """
    return jsonify({
        "status": "success",
        "data": {
            "levels": REPUTATION_LEVELS,
            "actions": [
                {
                    "key": key,
                    "points": value["points"],
                    "description": value["description"]
                }
                for key, value in REPUTATION_ACTIONS.items()
            ]
        }
    })