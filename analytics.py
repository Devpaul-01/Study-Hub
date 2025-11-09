"""
StudyHub - Analytics & Insights System
Provides engaging stats, activity tracking, and AI-like insights

Features:
- Personal dashboard with key metrics
- Activity heatmap (90-day contribution graph)
- Engagement breakdown (posts, comments, threads)
- AI-like insights and suggestions
- Comparison with average users
- Goal tracking and progress
- Post-specific analytics
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func, desc, and_, or_, case
import datetime
import calendar

from models import (
    User, StudentProfile, Post, Comment, Thread, ThreadMember,
    PostLike, PostReaction, PostView, UserActivity, Connection,
    ReputationHistory, UserBadge, ThreadMessage, Bookmark
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response
)

analytics_bp = Blueprint("student_analytics", __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_engagement_rate(views, likes, comments):
    """Calculate engagement rate as percentage"""
    if views == 0:
        return 0
    total_engagement = likes + (comments * 2)  # Comments worth more
    return round((total_engagement / views) * 100, 1)


def get_activity_level(activity_score):
    """Categorize activity level"""
    if activity_score >= 50:
        return {"level": "Very Active", "color": "#10B981", "emoji": "🔥"}
    elif activity_score >= 30:
        return {"level": "Active", "color": "#3B82F6", "emoji": "⚡"}
    elif activity_score >= 10:
        return {"level": "Moderate", "color": "#F59E0B", "emoji": "📊"}
    else:
        return {"level": "Low", "color": "#6B7280", "emoji": "💤"}


def generate_insights(user_id):
    """
    Generate AI-like insights based on user's activity patterns
    Uses pattern matching and statistical analysis (no external ML)
    """
    insights = []
    user = User.query.get(user_id)
    
    # Insight 1: Best posting day
    posts_by_day = db.session.query(
        func.strftime('%w', Post.posted_at).label('day'),
        func.count(Post.id).label('count'),
        func.avg(Post.likes_count).label('avg_likes')
    ).filter(
        Post.student_id == user_id,
        Post.posted_at >= datetime.datetime.utcnow() - datetime.timedelta(days=30)
    ).group_by('day').all()
    
    if posts_by_day:
        best_day = max(posts_by_day, key=lambda x: x.avg_likes)
        day_name = calendar.day_name[int(best_day.day)]
        insights.append({
            "type": "timing",
            "icon": "📅",
            "title": "Best Posting Day",
            "message": f"Your posts get {best_day.avg_likes:.1f} likes on {day_name}s - {int(best_day.avg_likes / (sum(p.avg_likes for p in posts_by_day) / len(posts_by_day)) * 100)}% above average!",
            "actionable": f"Try posting more on {day_name}s"
        })
    avg_response_time = db.session.query(
        func.avg(
            func.julianday(Comment.posted_at) - func.julianday(Post.posted_at)
        ) * 24
    ).join(Post, Comment.post_id == Post.id).filter(
        Comment.student_id == user_id
    ).scalar()
   
        
    
    if avg_response_time and avg_response_time < 3:
        insights.append({
            "type": "engagement",
            "icon": "⚡",
            "title": "Quick Responder",
            "message": f"You respond to posts in {avg_response_time:.1f} hours on average - faster than 75% of users!",
            "actionable": "Your quick responses help build reputation"
        })
    
    # Insight 3: Trending content
    recent_post = Post.query.filter_by(student_id=user_id).order_by(
        Post.posted_at.desc()
    ).first()
    
    if recent_post:
        views_today = PostView.query.filter(
            PostView.post_id == recent_post.id,
            PostView.view_date == datetime.date.today()
        ).count()
        
        if views_today >= 20:
            insights.append({
                "type": "trending",
                "icon": "🔥",
                "title": "You're Trending!",
                "message": f'Your post "{recent_post.title[:40]}..." has {views_today} views today!',
                "actionable": "Keep engaging with comments to maintain momentum"
            })
    
    # Insight 4: Badge progress
    from routes.student.badges import calculate_badge_progress
    
    # Check closest badge
    earned_badge_ids = [ub.badge_id for ub in UserBadge.query.filter_by(user_id=user_id).all()]
    from models import Badge
    unearned = Badge.query.filter(Badge.id.notin_(earned_badge_ids), Badge.is_active == True).all()
    
    closest_badge = None
    highest_progress = 0
    
    for badge in unearned:
        progress = calculate_badge_progress(user_id, badge.id)
        if progress and progress.get("percentage", 0) > highest_progress:
            highest_progress = progress["percentage"]
            closest_badge = (badge, progress)
    
    if closest_badge and highest_progress >= 50:
        badge, progress = closest_badge
        insights.append({
            "type": "achievement",
            "icon": "🏆",
            "title": "Badge Almost Unlocked!",
            "message": f"{badge.icon} {progress['remaining']} more {progress['type']} to earn '{badge.name}'",
            "actionable": f"You're {progress['percentage']:.0f}% there!"
        })
    
    # Insight 5: Audience engagement
    dept_rank = db.session.query(func.count(User.id)).join(StudentProfile).filter(
        StudentProfile.department == StudentProfile.query.filter_by(user_id=user_id).first().department,
        User.reputation > user.reputation
    ).scalar() + 1
    
    total_dept_users = db.session.query(func.count(User.id)).join(StudentProfile).filter(
        StudentProfile.department == StudentProfile.query.filter_by(user_id=user_id).first().department
    ).scalar()
    
    percentile = round((1 - (dept_rank / total_dept_users)) * 100)
    
    if percentile >= 90:
        insights.append({
            "type": "achievement",
            "icon": "🌟",
            "title": "Top Contributor",
            "message": f"You're in the top {100-percentile}% of your department!",
            "actionable": "Your expertise is valued by the community"
        })
    
    # Insight 6: Consistency check
    if user.login_streak >= 7:
        insights.append({
            "type": "consistency",
            "icon": "🔥",
            "title": "On Fire!",
            "message": f"{user.login_streak} day streak! You're building a strong learning habit.",
            "actionable": "Don't break the streak - come back tomorrow!"
        })
    
    return insights[:5]  # Return top 5 insights


def get_average_user_stats():
    """Calculate platform-wide average statistics"""
    total_users = User.query.filter_by(status="approved").count()
    
    if total_users == 0:
        return {}
    
    avg_stats = {
        "avg_posts": db.session.query(func.avg(User.total_posts)).scalar() or 0,
        "avg_reputation": db.session.query(func.avg(User.reputation)).scalar() or 0,
        "avg_helpful": db.session.query(func.avg(User.total_helpful)).scalar() or 0,
        "avg_connections": db.session.query(
            func.count(Connection.id)
        ).filter(Connection.status == "accepted").scalar() / total_users if total_users > 0 else 0
    }
    
    return avg_stats


# ============================================================================
# ANALYTICS ENDPOINTS
# ============================================================================

@analytics_bp.route("/analytics/overview", methods=["GET"])
@token_required
def get_analytics_overview(current_user):
    """
    Personal dashboard with key metrics
    Shows weekly impact, rank, reputation change, activity level
    """
    try:
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        # Calculate week-over-week changes
        week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        two_weeks_ago = datetime.datetime.utcnow() - datetime.timedelta(days=14)
        
        # This week's stats
        this_week_views = db.session.query(func.count(PostView.id)).join(
            Post, PostView.post_id == Post.id
        ).filter(
            Post.student_id == current_user.id,
            PostView.viewed_at >= week_ago
        ).scalar() or 0
        
        this_week_helpful = db.session.query(func.count(PostReaction.id)).join(
            Post, PostReaction.post_id == Post.id
        ).filter(
            Post.student_id == current_user.id,
            PostReaction.reaction_type == "helpful",
            PostReaction.reacted_at >= week_ago
        ).scalar() or 0
        
        this_week_rep = db.session.query(
            func.sum(ReputationHistory.points_change)
        ).filter(
            ReputationHistory.user_id == current_user.id,
            ReputationHistory.created_at >= week_ago
        ).scalar() or 0
        
        # Department rank
        dept_rank = db.session.query(func.count(User.id)).join(StudentProfile).filter(
            StudentProfile.department == profile.department,
            User.reputation > current_user.reputation,
            User.status == "approved"
        ).scalar() + 1
        
        # Activity level this week
        week_activity = db.session.query(
            func.sum(UserActivity.activity_score)
        ).filter(
            UserActivity.user_id == current_user.id,
            UserActivity.activity_date >= datetime.date.today() - datetime.timedelta(days=7)
        ).scalar() or 0
        
        activity_level = get_activity_level(week_activity)
        
        return jsonify({
            "status": "success",
            "data": {
                "hero_stats": {
                    "weekly_views": this_week_views,
                    "helpful_count": this_week_helpful,
                    "department_rank": dept_rank,
                    "reputation_change": int(this_week_rep),
                    "activity_level": activity_level
                },
                "current_stats": {
                    "total_posts": current_user.total_posts,
                    "total_reputation": current_user.reputation,
                    "reputation_level": current_user.reputation_level,
                    "login_streak": current_user.login_streak,
                    "total_helpful": current_user.total_helpful
                },
                "quick_facts": {
                    "joined_at": current_user.joined_at.isoformat(),
                    "days_active": (datetime.datetime.utcnow() - current_user.joined_at).days,
                    "department": profile.department if profile else None,
                    "class_level": profile.class_name if profile else None
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Analytics overview error: {str(e)}")
        return error_response("Failed to load analytics overview")


@analytics_bp.route("/analytics/activity-heatmap", methods=["GET"])
@token_required
def get_activity_heatmap(current_user):
    """
    GitHub-style contribution heatmap for last 90 days
    Shows daily activity score with color intensity
    """
    try:
        days = request.args.get("days", 90, type=int)
        days = min(days, 365)  # Max 1 year
        
        start_date = datetime.date.today() - datetime.timedelta(days=days)
        
        # Get all activity records
        activities = UserActivity.query.filter(
            UserActivity.user_id == current_user.id,
            UserActivity.activity_date >= start_date
        ).order_by(UserActivity.activity_date.asc()).all()
        
        # Create date map
        activity_map = {}
        for activity in activities:
            activity_map[activity.activity_date.isoformat()] = {
                "date": activity.activity_date.isoformat(),
                "score": activity.activity_score,
                "posts": activity.posts_created,
                "comments": activity.comments_created,
                "messages": activity.messages_sent,
                "helpful": activity.helpful_count,
                "level": 0  # Will calculate based on score
            }
        
        # Fill in missing dates with zero activity
        current_date = start_date
        while current_date <= datetime.date.today():
            date_str = current_date.isoformat()
            if date_str not in activity_map:
                activity_map[date_str] = {
                    "date": date_str,
                    "score": 0,
                    "posts": 0,
                    "comments": 0,
                    "messages": 0,
                    "helpful": 0,
                    "level": 0
                }
            else:
                # Calculate intensity level (0-4 for 5 color levels)
                score = activity_map[date_str]["score"]
                if score == 0:
                    level = 0
                elif score <= 5:
                    level = 1
                elif score <= 15:
                    level = 2
                elif score <= 30:
                    level = 3
                else:
                    level = 4
                activity_map[date_str]["level"] = level
            
            current_date += datetime.timedelta(days=1)
        
        # Convert to sorted list
        heatmap_data = sorted(activity_map.values(), key=lambda x: x["date"])
        
        # Calculate summary stats
        total_active_days = sum(1 for day in heatmap_data if day["score"] > 0)
        total_score = sum(day["score"] for day in heatmap_data)
        avg_daily_score = round(total_score / days, 1) if days > 0 else 0
        
        # Find best day
        best_day = max(heatmap_data, key=lambda x: x["score"]) if heatmap_data else None
        
        return jsonify({
            "status": "success",
            "data": {
                "heatmap": heatmap_data,
                "summary": {
                    "total_days": days,
                    "active_days": total_active_days,
                    "total_score": total_score,
                    "avg_daily_score": avg_daily_score,
                    "best_day": best_day,
                    "current_streak": current_user.login_streak
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Activity heatmap error: {str(e)}")
        return error_response("Failed to load activity heatmap")


@analytics_bp.route("/analytics/engagement", methods=["GET"])
@token_required
def get_engagement_stats(current_user):
    """
    Detailed engagement breakdown for posts, comments, threads
    """
    try:
        # Post engagement
        post_stats = db.session.query(
            func.count(Post.id).label('total'),
            func.sum(Post.views).label('total_views'),
            func.sum(Post.likes_count).label('total_likes'),
            func.sum(Post.comments_count).label('total_comments'),
            func.avg(Post.likes_count).label('avg_likes'),
            func.avg(Post.views).label('avg_views')
        ).filter(Post.student_id == current_user.id).first()
        
        # Best performing post
        best_post = Post.query.filter_by(student_id=current_user.id).order_by(
            (Post.likes_count + Post.comments_count).desc()
        ).first()
        
        # Comment engagement
        comment_stats = db.session.query(
            func.count(Comment.id).label('total'),
            func.sum(Comment.likes_count).label('total_likes'),
            func.count(case((Comment.is_solution == True, 1))).label('solutions')
        ).filter(Comment.student_id == current_user.id).first()
        
        # Thread participation
        thread_stats = db.session.query(
            func.count(ThreadMember.id).label('joined'),
            func.sum(ThreadMember.messages_sent).label('messages_sent')
        ).filter(ThreadMember.student_id == current_user.id).first()
        
        threads_created = Thread.query.filter_by(creator_id=current_user.id).count()
        
        # Calculate engagement rate
        engagement_rate = calculate_engagement_rate(
            post_stats.total_views or 0,
            post_stats.total_likes or 0,
            post_stats.total_comments or 0
        )
        
        return jsonify({
            "status": "success",
            "data": {
                "posts": {
                    "total_created": post_stats.total or 0,
                    "total_views": post_stats.total_views or 0,
                    "total_likes": post_stats.total_likes or 0,
                    "total_comments": post_stats.total_comments or 0,
                    "avg_likes_per_post": round(post_stats.avg_likes or 0, 1),
                    "avg_views_per_post": round(post_stats.avg_views or 0, 1),
                    "engagement_rate": engagement_rate,
                    "best_post": {
                        "id": best_post.id,
                        "title": best_post.title,
                        "likes": best_post.likes_count,
                        "comments": best_post.comments_count,
                        "views": best_post.views
                    } if best_post else None
                },
                "comments": {
                    "total_created": comment_stats.total or 0,
                    "total_likes": comment_stats.total_likes or 0,
                    "marked_helpful": current_user.total_helpful,
                    "marked_solution": comment_stats.solutions or 0
                },
                "threads": {
                    "created": threads_created,
                    "joined": thread_stats.joined or 0,
                    "messages_sent": thread_stats.messages_sent or 0
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Engagement stats error: {str(e)}")
        return error_response("Failed to load engagement stats")


@analytics_bp.route("/analytics/impact", methods=["GET"])
@token_required
def get_impact_metrics(current_user):
    """
    Shows how many people the user has helped
    People reached, questions answered, resources shared
    """
    try:
        # Unique users who viewed your posts
        people_reached = db.session.query(
            func.count(func.distinct(PostView.viewer_id))
        ).join(Post, PostView.post_id == Post.id).filter(
            Post.student_id == current_user.id,
            PostView.viewer_id != current_user.id
        ).scalar() or 0
        
        # Questions you answered
        questions_answered = Comment.query.join(Post).filter(
            Comment.student_id == current_user.id,
            Post.post_type.in_(["question", "problem"])
        ).count()
        
        # Questions you solved
        questions_solved = Comment.query.filter_by(
            student_id=current_user.id,
            is_solution=True
        ).count()
        
        # Resources shared
        resources_shared = Post.query.filter_by(
            student_id=current_user.id,
            post_type="resource"
        ).count()
        
        # Times bookmarked by others
        times_bookmarked = Bookmark.query.join(Post).filter(
            Post.student_id == current_user.id,
            Bookmark.student_id != current_user.id
        ).count()
        
        # Active connections
        connections_count = Connection.query.filter(
            or_(
                Connection.requester_id == current_user.id,
                Connection.receiver_id == current_user.id
            ),
            Connection.status == "accepted"
        ).count()
        
        # Study buddies helped (future feature - placeholder)
        study_buddies = 0
        
        return jsonify({
            "status": "success",
            "data": {
                "impact": {
                    "people_reached": people_reached,
                    "questions_answered": questions_answered,
                    "questions_solved": questions_solved,
                    "resources_shared": resources_shared,
                    "times_bookmarked": times_bookmarked,
                    "active_connections": connections_count,
                    "study_buddies_helped": study_buddies,
                    "total_helpful": current_user.total_helpful
                },
                "impact_score": (
                    people_reached * 1 +
                    questions_solved * 10 +
                    current_user.total_helpful * 5 +
                    resources_shared * 3
                )
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Impact metrics error: {str(e)}")
        return error_response("Failed to load impact metrics")


@analytics_bp.route("/analytics/insights", methods=["GET"])
@token_required
def get_insights(current_user):
    """
    AI-like insights and personalized suggestions
    """
    try:
        insights = generate_insights(current_user.id)
        
        return jsonify({
            "status": "success",
            "data": {
                "insights": insights,
                "generated_at": datetime.datetime.utcnow().isoformat()
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Insights error: {str(e)}")
        return error_response("Failed to generate insights")


@analytics_bp.route("/analytics/comparison", methods=["GET"])
@token_required
def get_comparison_stats(current_user):
    """
    Compare user's stats with platform averages
    """
    try:
        avg_stats = get_average_user_stats()
        
        # Calculate multipliers
        posts_multiplier = (current_user.total_posts / avg_stats["avg_posts"]) if avg_stats["avg_posts"] > 0 else 0
        rep_multiplier = (current_user.reputation / avg_stats["avg_reputation"]) if avg_stats["avg_reputation"] > 0 else 0
        helpful_multiplier = (current_user.total_helpful / avg_stats["avg_helpful"]) if avg_stats["avg_helpful"] > 0 else 0
        
        connections_count = Connection.query.filter(
            or_(
                Connection.requester_id == current_user.id,
                Connection.receiver_id == current_user.id
            ),
            Connection.status == "accepted"
        ).count()
        
        connections_multiplier = (connections_count / avg_stats["avg_connections"]) if avg_stats["avg_connections"] > 0 else 0
        
        return jsonify({
            "status": "success",
            "data": {
                "your_stats": {
                    "posts": current_user.total_posts,
                    "reputation": current_user.reputation,
                    "helpful": current_user.total_helpful,
                    "connections": connections_count
                },
                "average_stats": {
                    "posts": round(avg_stats["avg_posts"], 1),
                    "reputation": round(avg_stats["avg_reputation"], 1),
                    "helpful": round(avg_stats["avg_helpful"], 1),
                    "connections": round(avg_stats["avg_connections"], 1)
                },
                "comparison": {
                    "posts": {
                        "multiplier": round(posts_multiplier, 1),
                        "status": "above" if posts_multiplier > 1 else "below"
                    },
                    "reputation": {
                        "multiplier": round(rep_multiplier, 1),
                        "status": "above" if rep_multiplier > 1 else "below"
                    },
                    "helpful": {
                        "multiplier": round(helpful_multiplier, 1),
                        "status": "above" if helpful_multiplier > 1 else "below"
                    },
                    "connections": {
                        "multiplier": round(connections_multiplier, 1),
                        "status": "above" if connections_multiplier > 1 else "below"
                    }
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Comparison stats error: {str(e)}")
        return error_response("Failed to load comparison")


@analytics_bp.route("/analytics/post/<int:post_id>", methods=["GET"])
@token_required
def get_post_analytics(current_user, post_id):
    """
    Detailed analytics for a specific post
    """
    try:
        post = Post.query.get(post_id)
        
        if not post:
            return error_response("Post not found", 404)
        
        if post.student_id != current_user.id:
            return error_response("Can only view analytics for your own posts", 403)
        
        # View timeline (last 30 days)
        thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)
        
        views_by_day = db.session.query(
            PostView.view_date,
            func.count(PostView.id).label('views')
        ).filter(
            PostView.post_id == post_id,
            PostView.view_date >= thirty_days_ago
        ).group_by(PostView.view_date).order_by(PostView.view_date.asc()).all()
        
        timeline = [{
            "date": v.view_date.isoformat(),
            "views": v.views
        } for v in views_by_day]
        
        # Reaction breakdown
        reactions = db.session.query(
            PostReaction.reaction_type,
            func.count(PostReaction.id).label('count')
        ).filter(PostReaction.post_id == post_id).group_by(
            PostReaction.reaction_type
        ).all()
        
        reaction_breakdown = {r.reaction_type: r.count for r in reactions}
        
        # Engagement rate
        engagement_rate = calculate_engagement_rate(
            post.views,
            post.likes_count,
            post.comments_count
        )
        
        return jsonify({
            "status": "success",
            "data": {
                "post": {
                    "id": post.id,
                    "title": post.title,
                    "posted_at": post.posted_at.isoformat()
                },
                "metrics": {
                    "views": post.views,
                    "likes": post.likes_count,
                    "dislikes": post.dislikes_count,
                    "comments": post.comments_count,
                    "bookmarks": post.bookmarks,
                    "engagement_rate": engagement_rate
                },
                "reactions": reaction_breakdown,
                "timeline": timeline
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Post analytics error: {str(e)}")
        return error_response("Failed to load post analytics")


@analytics_bp.route("/analytics/weekly-summary", methods=["GET"])
@token_required
def get_weekly_summary(current_user):
    """
    Weekly digest data (for email/notification)
    """
    try:
        week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        
        # New reputation earned
        rep_change = db.session.query(
            func.sum(ReputationHistory.points_change)
        ).filter(
            ReputationHistory.user_id == current_user.id,
            ReputationHistory.created_at >= week_ago
        ).scalar() or 0
        
        # New badges earned
        new_badges = UserBadge.query.filter(
            UserBadge.user_id == current_user.id,
            UserBadge.earned_at >= week_ago
        ).count()
        
        # Posts created this week
        posts_created = Post.query.filter(
            Post.student_id == current_user.id,
            Post.posted_at >= week_ago
        ).count()
        
        # People helped
        helpful_this_week = db.session.query(func.count(PostReaction.id)).join(
            Post, PostReaction.post_id == Post.id
        ).filter(
            Post.student_id == current_user.id,
            PostReaction.reaction_type == "helpful",
            PostReaction.reacted_at >= week_ago
        ).scalar() or 0
        
        # New connections
        new_connections = Connection.query.filter(
            or_(
                Connection.requester_id == current_user.id,
                Connection.receiver_id == current_user.id
            ),
            Connection.status == "accepted",
            Connection.responded_at >= week_ago
        ).count()
        
        return jsonify({
            "status": "success",
            "data": {
                "period": "last_7_days",
                "summary": {
                    "reputation_earned": int(rep_change),
                    "badges_earned": new_badges,
                    "posts_created": posts_created,
                    "people_helped": helpful_this_week,
                    "new_connections": new_connections
                },
                "message": f"Great week! You earned {rep_change} reputation and helped {helpful_this_week} people! 🎉"
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Weekly summary error: {str(e)}")
        return error_response("Failed to load weekly summary")


@analytics_bp.route("/analytics/export", methods=["GET"])
@token_required
def export_analytics(current_user):
    """
    Export analytics data as CSV
    Returns JSON that frontend can convert to CSV
    """
    try:
        export_type = request.args.get("type", "overview")
        
        if export_type == "activity":
            # Export activity heatmap
            ninety_days_ago = datetime.date.today() - datetime.timedelta(days=90)
            activities = UserActivity.query.filter(
                UserActivity.user_id == current_user.id,
                UserActivity.activity_date >= ninety_days_ago
            ).order_by(UserActivity.activity_date.asc()).all()
            
            export_data = [{
                "date": a.activity_date.isoformat(),
                "posts_created": a.posts_created,
                "comments_created": a.comments_created,
                "messages_sent": a.messages_sent,
                "helpful_count": a.helpful_count,
                "activity_score": a.activity_score
            } for a in activities]
            
        elif export_type == "reputation":
            # Export reputation history
            history = ReputationHistory.query.filter_by(
                user_id=current_user.id
            ).order_by(ReputationHistory.created_at.desc()).all()
            
            export_data = [{
                "date": h.created_at.isoformat(),
                "action": h.action,
                "points_change": h.points_change,
                "reputation_before": h.reputation_before,
                "reputation_after": h.reputation_after
            } for h in history]
            
        elif export_type == "posts":
            # Export post performance
            posts = Post.query.filter_by(student_id=current_user.id).all()
            
            export_data = [{
                "id": p.id,
                "title": p.title,
                "post_type": p.post_type,
                "posted_at": p.posted_at.isoformat(),
                "views": p.views,
                "likes": p.likes_count,
                "comments": p.comments_count,
                "bookmarks": p.bookmarks,
                "is_solved": p.is_solved
            } for p in posts]
            
        else:
            # Overview export
            export_data = [{
                "metric": "Total Posts",
                "value": current_user.total_posts
            }, {
                "metric": "Total Reputation",
                "value": current_user.reputation
            }, {
                "metric": "Reputation Level",
                "value": current_user.reputation_level
            }, {
                "metric": "Total Helpful",
                "value": current_user.total_helpful
            }, {
                "metric": "Login Streak",
                "value": current_user.login_streak
            }]
        
        return jsonify({
            "status": "success",
            "data": {
                "export_type": export_type,
                "records": export_data,
                "generated_at": datetime.datetime.utcnow().isoformat()
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Export analytics error: {str(e)}")
        return error_response("Failed to export analytics")    