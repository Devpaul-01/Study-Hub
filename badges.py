"""
StudyHub - Badges & Achievements System
Award badges for accomplishments, track progress, and showcase achievements

Badge Categories:
- engagement: Activity-based (posts, comments, likes)
- quality: Quality content (helpful reactions, solutions)
- consistency: Streaks and regular activity
- social: Connections, threads, helping others
- milestone: Special achievements

Badge Rarity:
- common: Easy to get (gray)
- rare: Moderate effort (blue)
- epic: Significant achievement (purple)
- legendary: Very rare (gold)
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func, desc, and_, or_
import datetime

from models import (
    User, Badge, UserBadge, Post, Comment, Thread, ThreadMember,
    PostReaction, Connection, UserActivity, Notification
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response
)

badges_bp = Blueprint("student_badges", __name__)


# ============================================================================
# BADGE DEFINITIONS (Seed Data)
# ============================================================================

BADGE_DEFINITIONS = [
    # ENGAGEMENT BADGES
    {
        "name": "First Post",
        "description": "Created your first post",
        "icon": "✍️",
        "category": "engagement",
        "rarity": "common",
        "criteria": {"posts_count": 1},
        "color": "#6B7280"
    },
    {
        "name": "Prolific Writer",
        "description": "Created 50 posts",
        "icon": "📝",
        "category": "engagement",
        "rarity": "rare",
        "criteria": {"posts_count": 50},
        "color": "#3B82F6"
    },
    {
        "name": "Content Creator",
        "description": "Created 100 posts",
        "icon": "🎨",
        "category": "engagement",
        "rarity": "epic",
        "criteria": {"posts_count": 100},
        "color": "#8B5CF6"
    },
    
    # QUALITY BADGES
    {
        "name": "Helpful Hero",
        "description": "Received 50 helpful reactions",
        "icon": "💡",
        "category": "quality",
        "rarity": "rare",
        "criteria": {"helpful_count": 50},
        "color": "#3B82F6"
    },
    {
        "name": "Problem Solver",
        "description": "Had 10 answers marked as solutions",
        "icon": "🎯",
        "category": "quality",
        "rarity": "epic",
        "criteria": {"solutions_count": 10},
        "color": "#8B5CF6"
    },
    {
        "name": "Genius",
        "description": "Had 50 answers marked as solutions",
        "icon": "🧠",
        "category": "quality",
        "rarity": "legendary",
        "criteria": {"solutions_count": 50},
        "color": "#EF4444"
    },
    
    # CONSISTENCY BADGES
    {
        "name": "7-Day Streak",
        "description": "Active for 7 consecutive days",
        "icon": "🔥",
        "category": "consistency",
        "rarity": "rare",
        "criteria": {"login_streak": 7},
        "color": "#F59E0B"
    },
    {
        "name": "30-Day Warrior",
        "description": "Active for 30 consecutive days",
        "icon": "⚔️",
        "category": "consistency",
        "rarity": "epic",
        "criteria": {"login_streak": 30},
        "color": "#8B5CF6"
    },
    {
        "name": "Unstoppable",
        "description": "Active for 100 consecutive days",
        "icon": "💎",
        "category": "consistency",
        "rarity": "legendary",
        "criteria": {"login_streak": 100},
        "color": "#EF4444"
    },
    
    # SOCIAL BADGES
    {
        "name": "Social Butterfly",
        "description": "Made 10 connections",
        "icon": "🦋",
        "category": "social",
        "rarity": "common",
        "criteria": {"connections_count": 10},
        "color": "#6B7280"
    },
    {
        "name": "Networker",
        "description": "Made 50 connections",
        "icon": "🤝",
        "category": "social",
        "rarity": "rare",
        "criteria": {"connections_count": 50},
        "color": "#3B82F6"
    },
    {
        "name": "Thread Starter",
        "description": "Created 5 study threads",
        "icon": "🧵",
        "category": "social",
        "rarity": "rare",
        "criteria": {"threads_created": 5},
        "color": "#3B82F6"
    },
    {
        "name": "Thread Leader",
        "description": "Created a thread with 10+ active members",
        "icon": "👑",
        "category": "social",
        "rarity": "epic",
        "criteria": {"thread_leader": True},
        "color": "#8B5CF6"
    },
    {
        "name": "Community Builder",
        "description": "Created 10 threads with 10+ members each",
        "icon": "🏗️",
        "category": "social",
        "rarity": "legendary",
        "criteria": {"threads_large": 10},
        "color": "#EF4444"
    },
    
    # MILESTONE BADGES
    {
        "name": "Early Adopter",
        "description": "Joined StudyHub in the first month",
        "icon": "🌟",
        "category": "milestone",
        "rarity": "epic",
        "criteria": {"early_adopter": True},
        "color": "#8B5CF6"
    },
    {
        "name": "Reputation Master",
        "description": "Reached 1000 reputation points",
        "icon": "⭐",
        "category": "milestone",
        "rarity": "legendary",
        "criteria": {"reputation": 1000},
        "color": "#EF4444"
    },
    {
        "name": "Department Hero",
        "description": "Top 3 in your department leaderboard",
        "icon": "🏆",
        "category": "milestone",
        "rarity": "legendary",
        "criteria": {"department_rank": 3},
        "color": "#EF4444"
    },
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def seed_badges():
    """
    Seed initial badges into database
    Run once during setup
    """
    for badge_data in BADGE_DEFINITIONS:
        existing = Badge.query.filter_by(name=badge_data["name"]).first()
        if not existing:
            badge = Badge(
                name=badge_data["name"],
                description=badge_data["description"],
                icon=badge_data["icon"],
                category=badge_data["category"],
                rarity=badge_data["rarity"],
                criteria=badge_data["criteria"]
            )
            db.session.add(badge)
    
    db.session.commit()
    print("✅ Badges seeded successfully!")


def check_and_award_badge(user_id, badge_name):
    """
    Check if user qualifies for a badge and award it
    
    Returns:
        UserBadge if awarded, None if already has it or doesn't qualify
    """
    # Check if already has badge
    badge = Badge.query.filter_by(name=badge_name).first()
    if not badge:
        return None
    
    existing = UserBadge.query.filter_by(
        user_id=user_id,
        badge_id=badge.id
    ).first()
    
    if existing:
        return None  # Already has badge
    
    # Check if user meets criteria
    user = User.query.get(user_id)
    if not user:
        return None
    
    criteria = badge.criteria
    qualifies = False
    
    # Check each criteria type
    if "posts_count" in criteria:
        qualifies = user.total_posts >= criteria["posts_count"]
    
    elif "helpful_count" in criteria:
        qualifies = user.total_helpful >= criteria["helpful_count"]
    
    elif "solutions_count" in criteria:
        solutions = Comment.query.filter_by(
            student_id=user_id,
            is_solution=True
        ).count()
        qualifies = solutions >= criteria["solutions_count"]
    
    elif "login_streak" in criteria:
        qualifies = user.login_streak >= criteria["login_streak"]
    
    elif "connections_count" in criteria:
        connections = Connection.query.filter(
            or_(
                Connection.requester_id == user_id,
                Connection.receiver_id == user_id
            ),
            Connection.status == "accepted"
        ).count()
        qualifies = connections >= criteria["connections_count"]
    
    elif "threads_created" in criteria:
        threads = Thread.query.filter_by(creator_id=user_id).count()
        qualifies = threads >= criteria["threads_created"]
    
    elif "thread_leader" in criteria:
        # Has at least one thread with 10+ members
        large_thread = Thread.query.filter(
            Thread.creator_id == user_id,
            Thread.member_count >= 10
        ).first()
        qualifies = bool(large_thread)
    
    elif "threads_large" in criteria:
        # Has X threads with 10+ members each
        large_threads = Thread.query.filter(
            Thread.creator_id == user_id,
            Thread.member_count >= 10
        ).count()
        qualifies = large_threads >= criteria["threads_large"]
    
    elif "reputation" in criteria:
        qualifies = user.reputation >= criteria["reputation"]
    
    elif "early_adopter" in criteria:
        # Joined within first 30 days of platform launch
        # Assuming launch date is first user's join date
        first_user = User.query.order_by(User.joined_at.asc()).first()
        if first_user:
            launch_date = first_user.joined_at
            cutoff = launch_date + datetime.timedelta(days=30)
            qualifies = user.joined_at <= cutoff
    
    elif "department_rank" in criteria:
        # Check if user is in top X of department
        from models import StudentProfile
        profile = StudentProfile.query.filter_by(user_id=user_id).first()
        if profile:
            rank = db.session.query(func.count(User.id)).join(StudentProfile).filter(
                StudentProfile.department == profile.department,
                User.reputation > user.reputation,
                User.status == "approved"
            ).scalar() + 1
            qualifies = rank <= criteria["department_rank"]
    
    # Award badge if qualified
    if qualifies:
        user_badge = UserBadge(
            user_id=user_id,
            badge_id=badge.id
        )
        db.session.add(user_badge)
        
        # Update badge awarded count
        badge.awarded_count += 1
        
        # Create notification
        notification = Notification(
            user_id=user_id,
            title=f"Badge Earned: {badge.name}!",
            body=f"{badge.icon} {badge.description}",
            notification_type="badge_earned",
            related_type="badge",
            related_id=badge.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return user_badge
    
    return None


def check_all_badges_for_user(user_id):
    """
    Check all possible badges for a user
    Called after significant actions (post created, streak updated, etc.)
    
    Returns:
        List of newly awarded badges
    """
    all_badges = Badge.query.filter_by(is_active=True).all()
    awarded = []
    
    for badge in all_badges:
        result = check_and_award_badge(user_id, badge.name)
        if result:
            awarded.append(badge)
    
    if awarded:
        db.session.commit()
    
    return awarded


def calculate_badge_progress(user_id, badge_id):
    """
    Calculate user's progress toward a specific badge
    
    Returns:
        dict with current/required values and percentage
    """
    badge = Badge.query.get(badge_id)
    user = User.query.get(user_id)
    
    if not badge or not user:
        return None
    
    criteria = badge.criteria
    current = 0
    required = 0
    progress_type = ""
    
    if "posts_count" in criteria:
        current = user.total_posts
        required = criteria["posts_count"]
        progress_type = "posts"
    
    elif "helpful_count" in criteria:
        current = user.total_helpful
        required = criteria["helpful_count"]
        progress_type = "helpful reactions"
    
    elif "solutions_count" in criteria:
        current = Comment.query.filter_by(
            student_id=user_id,
            is_solution=True
        ).count()
        required = criteria["solutions_count"]
        progress_type = "solutions"
    
    elif "login_streak" in criteria:
        current = user.login_streak
        required = criteria["login_streak"]
        progress_type = "day streak"
    
    elif "connections_count" in criteria:
        current = Connection.query.filter(
            or_(
                Connection.requester_id == user_id,
                Connection.receiver_id == user_id
            ),
            Connection.status == "accepted"
        ).count()
        required = criteria["connections_count"]
        progress_type = "connections"
    
    elif "threads_created" in criteria:
        current = Thread.query.filter_by(creator_id=user_id).count()
        required = criteria["threads_created"]
        progress_type = "threads created"
    
    elif "reputation" in criteria:
        current = user.reputation
        required = criteria["reputation"]
        progress_type = "reputation points"
    
    else:
        # Special badges (can't track progress)
        return {
            "current": 0,
            "required": 1,
            "percentage": 0,
            "type": "special",
            "message": "Complete special requirements"
        }
    
    percentage = min((current / required) * 100, 100) if required > 0 else 0
    
    return {
        "current": current,
        "required": required,
        "percentage": round(percentage, 1),
        "type": progress_type,
        "remaining": max(required - current, 0)
    }


# ============================================================================
# BADGE ENDPOINTS
# ============================================================================

@badges_bp.route("/badges/available", methods=["GET"])
@token_required
def get_available_badges(current_user):
    """
    Get all available badges in the system
    
    Query params:
    - category: Filter by category
    - rarity: Filter by rarity
    """
    try:
        category = request.args.get("category", "").strip()
        rarity = request.args.get("rarity", "").strip()
        
        query = Badge.query.filter_by(is_active=True)
        
        if category:
            query = query.filter_by(category=category)
        
        if rarity:
            query = query.filter_by(rarity=rarity)
        
        badges = query.order_by(
            Badge.rarity.desc(),
            Badge.awarded_count.desc()
        ).all()
        
        # Check which badges user has earned
        user_badge_ids = [ub.badge_id for ub in UserBadge.query.filter_by(user_id=current_user.id).all()]
        
        badges_data = []
        for badge in badges:
            has_earned = badge.id in user_badge_ids
            
            badges_data.append({
                "id": badge.id,
                "name": badge.name,
                "description": badge.description,
                "icon": badge.icon,
                "category": badge.category,
                "rarity": badge.rarity,
                "awarded_count": badge.awarded_count,
                "has_earned": has_earned,
                "earned_at": next(
                    (ub.earned_at.isoformat() for ub in UserBadge.query.filter_by(
                        user_id=current_user.id,
                        badge_id=badge.id
                    ).all()),
                    None
                ) if has_earned else None
            })
        
        # Group by category
        categories = {}
        for badge in badges_data:
            cat = badge["category"]
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(badge)
        
        return jsonify({
            "status": "success",
            "data": {
                "badges": badges_data,
                "by_category": categories,
                "total": len(badges_data),
                "earned": len(user_badge_ids)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get available badges error: {str(e)}")
        return error_response("Failed to load badges")


@badges_bp.route("/badges/my-badges", methods=["GET"])
@token_required
def get_my_badges(current_user):
    """
    Get all badges earned by current user
    """
    try:
        user_badges = UserBadge.query.filter_by(
            user_id=current_user.id
        ).order_by(UserBadge.earned_at.desc()).all()
        
        badges_data = []
        for ub in user_badges:
            badge = Badge.query.get(ub.badge_id)
            if badge:
                badges_data.append({
                    "id": badge.id,
                    "name": badge.name,
                    "description": badge.description,
                    "icon": badge.icon,
                    "category": badge.category,
                    "rarity": badge.rarity,
                    "earned_at": ub.earned_at.isoformat(),
                    "is_featured": ub.is_featured
                })
        
        # Group by rarity
        by_rarity = {}
        for badge in badges_data:
            rarity = badge["rarity"]
            if rarity not in by_rarity:
                by_rarity[rarity] = []
            by_rarity[rarity].append(badge)
        
        return jsonify({
            "status": "success",
            "data": {
                "badges": badges_data,
                "by_rarity": by_rarity,
                "total_earned": len(badges_data),
                "featured": [b for b in badges_data if b["is_featured"]]
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get my badges error: {str(e)}")
        return error_response("Failed to load your badges")


@badges_bp.route("/badges/progress", methods=["GET"])
@token_required
def get_badge_progress(current_user):
    """
    Get progress toward all unearned badges
    Shows how close user is to earning each badge
    """
    try:
        # Get all badges user hasn't earned yet
        earned_badge_ids = [ub.badge_id for ub in UserBadge.query.filter_by(user_id=current_user.id).all()]
        
        unearned_badges = Badge.query.filter(
            Badge.is_active == True,
            Badge.id.notin_(earned_badge_ids)
        ).all()
        
        progress_data = []
        for badge in unearned_badges:
            progress = calculate_badge_progress(current_user.id, badge.id)
            
            if progress:
                progress_data.append({
                    "badge": {
                        "id": badge.id,
                        "name": badge.name,
                        "description": badge.description,
                        "icon": badge.icon,
                        "category": badge.category,
                        "rarity": badge.rarity
                    },
                    "progress": progress
                })
        
        # Sort by percentage (closest to completion first)
        progress_data.sort(key=lambda x: x["progress"]["percentage"], reverse=True)
        
        return jsonify({
            "status": "success",
            "data": {
                "progress": progress_data,
                "total_unearned": len(progress_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get badge progress error: {str(e)}")
        return error_response("Failed to load badge progress")


@badges_bp.route("/badges/<int:badge_id>/details", methods=["GET"])
@token_required
def get_badge_details(current_user, badge_id):
    """
    Get detailed information about a specific badge
    Including requirements and progress
    """
    try:
        badge = Badge.query.get(badge_id)
        
        if not badge:
            return error_response("Badge not found", 404)
        
        # Check if user has earned it
        user_badge = UserBadge.query.filter_by(
            user_id=current_user.id,
            badge_id=badge_id
        ).first()
        
        has_earned = bool(user_badge)
        
        # Get progress if not earned
        progress = None
        if not has_earned:
            progress = calculate_badge_progress(current_user.id, badge_id)
        
        # Get recent earners (last 10)
        recent_earners = UserBadge.query.filter_by(
            badge_id=badge_id
        ).order_by(UserBadge.earned_at.desc()).limit(10).all()
        
        earners_data = []
        for ub in recent_earners:
            user = User.query.get(ub.user_id)
            if user:
                earners_data.append({
                    "username": user.username,
                    "name": user.name,
                    "avatar": user.avatar,
                    "earned_at": ub.earned_at.isoformat()
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "badge": {
                    "id": badge.id,
                    "name": badge.name,
                    "description": badge.description,
                    "icon": badge.icon,
                    "category": badge.category,
                    "rarity": badge.rarity,
                    "criteria": badge.criteria,
                    "awarded_count": badge.awarded_count
                },
                "has_earned": has_earned,
                "earned_at": user_badge.earned_at.isoformat() if user_badge else None,
                "progress": progress,
                "recent_earners": earners_data
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get badge details error: {str(e)}")
        return error_response("Failed to load badge details")


@badges_bp.route("/badges/feature/<int:badge_id>", methods=["POST"])
@token_required
def feature_badge(current_user, badge_id):
    """
    Feature a badge on profile (show prominently)
    Max 3 featured badges per user
    """
    try:
        user_badge = UserBadge.query.filter_by(
            user_id=current_user.id,
            badge_id=badge_id
        ).first()
        
        if not user_badge:
            return error_response("You haven't earned this badge", 404)
        
        # Check current featured count
        featured_count = UserBadge.query.filter_by(
            user_id=current_user.id,
            is_featured=True
        ).count()
        
        if featured_count >= 3 and not user_badge.is_featured:
            return error_response("Maximum 3 featured badges allowed", 400)
        
        # Toggle featured status
        user_badge.is_featured = not user_badge.is_featured
        db.session.commit()
        
        return success_response(
            f"Badge {'featured' if user_badge.is_featured else 'unfeatured'}",
            data={"is_featured": user_badge.is_featured}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Feature badge error: {str(e)}")
        return error_response("Failed to feature badge")


@badges_bp.route("/badges/award", methods=["POST"])
@token_required
def award_badge_endpoint(current_user):
    """
    Internal endpoint to award badge
    Should only be called by system/admin (add auth check later)
    
    Body: {
        "user_id": 123,
        "badge_name": "Helpful Hero"
    }
    """
    try:
        data = request.get_json()
        
        user_id = data.get("user_id")
        badge_name = data.get("badge_name")
        
        if not user_id or not badge_name:
            return error_response("user_id and badge_name required")
        
        # Award badge
        user_badge = check_and_award_badge(user_id, badge_name)
        
        if not user_badge:
            return error_response("Badge already earned or user doesn't qualify")
        
        badge = Badge.query.get(user_badge.badge_id)
        
        return success_response(
            f"Badge '{badge.name}' awarded",
            data={
                "user_id": user_id,
                "badge": {
                    "id": badge.id,
                    "name": badge.name,
                    "icon": badge.icon,
                    "rarity": badge.rarity
                },
                "earned_at": user_badge.earned_at.isoformat()
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Award badge error: {str(e)}")
        return error_response("Failed to award badge")


@badges_bp.route("/badges/check-all", methods=["POST"])
@token_required
def check_all_badges(current_user):
    """
    Manually trigger badge check for current user
    Useful for testing or after bulk actions
    """
    try:
        awarded = check_all_badges_for_user(current_user.id)
        
        if not awarded:
            return success_response("No new badges earned")
        
        badges_data = [{
            "name": b.name,
            "icon": b.icon,
            "rarity": b.rarity
        } for b in awarded]
        
        return success_response(
            f"Earned {len(awarded)} new badge(s)!",
            data={"badges": badges_data}
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Check all badges error: {str(e)}")
        return error_response("Failed to check badges")
        
        
        
        