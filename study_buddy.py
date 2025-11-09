"""
StudyHub - Study Buddy Matching System
Smart algorithm to match students for collaborative learning

Features:
- Preference-based matching
- Smart algorithm (subject overlap, availability, activity level)
- Request workflow
- Auto-thread creation on match
- Session tracking
- Success metrics
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import func, desc, and_, or_
import datetime

from models import (
    User, StudentProfile, StudyBuddyRequest, StudyBuddyMatch,
    Thread, ThreadMember, Connection, Notification
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response
)

study_buddy_bp = Blueprint("student_study_buddy", __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def calculate_match_score(user1, user2, user1_prefs, user2_prefs):
    """
    Calculate compatibility score between two users
    
    Score breakdown (out of 100):
    - Subject overlap: 40 points
    - Availability overlap: 30 points
    - Department match: 10 points
    - Activity level: 10 points
    - Success rate: 10 points
    
    Returns: int (0-100)
    """
    score = 0
    
    # 1. Subject overlap (40 points max)
    if user1_prefs and user2_prefs:
        needs1 = set([s.lower() for s in user1_prefs.get("needs_help", [])])
        good_at2 = set([s.lower() for s in user2_prefs.get("good_at", [])])
        
        needs2 = set([s.lower() for s in user2_prefs.get("needs_help", [])])
        good_at1 = set([s.lower() for s in user1_prefs.get("good_at", [])])
        
        # User1 needs help in what User2 is good at
        overlap1 = len(needs1 & good_at2)
        # User2 needs help in what User1 is good at
        overlap2 = len(needs2 & good_at1)
        
        total_overlap = overlap1 + overlap2
        score += min(total_overlap * 10, 40)  # 10 points per subject match, max 40
    
    # 2. Availability overlap (30 points max)
    if user1_prefs and user2_prefs:
        avail1 = set(user1_prefs.get("available_days", []))
        avail2 = set(user2_prefs.get("available_days", []))
        
        day_overlap = len(avail1 & avail2)
        score += min(day_overlap * 5, 30)  # 5 points per shared day, max 30
    
    # 3. Department match (10 points)
    profile1 = StudentProfile.query.filter_by(user_id=user1.id).first()
    profile2 = StudentProfile.query.filter_by(user_id=user2.id).first()
    
    if profile1 and profile2 and profile1.department == profile2.department:
        score += 10
    
    # 4. Activity level (10 points)
    # Both users should be active
    week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
    
    if user1.last_active and user1.last_active >= week_ago:
        score += 5
    if user2.last_active and user2.last_active >= week_ago:
        score += 5
    
    # 5. Success rate (10 points)
    # Check how many successful partnerships user2 has
    successful_matches = StudyBuddyMatch.query.filter(
        or_(
            StudyBuddyMatch.user1_id == user2.id,
            StudyBuddyMatch.user2_id == user2.id
        ),
        StudyBuddyMatch.is_active == False,
        StudyBuddyMatch.sessions_count >= 3  # At least 3 sessions = success
    ).count()
    
    score += min(successful_matches * 2, 10)  # 2 points per success, max 10
    
    return min(score, 100)


# ============================================================================
# PREFERENCES MANAGEMENT
# ============================================================================

@study_buddy_bp.route("/study-buddy/preferences", methods=["POST"])
@token_required
def set_preferences(current_user):
    """
    Set study buddy preferences
    
    Body: {
        "needs_help": ["Calculus", "Physics"],
        "good_at": ["Python", "Web Development"],
        "available_days": ["Monday", "Wednesday", "Friday"],
        "available_times": ["evening", "night"],
        "study_style": ["video_call", "chat", "in_person"],
        "goals": "Prepare for exams, build projects"
    }
    """
    try:
        data = request.get_json()
        
        needs_help = data.get("needs_help", [])
        good_at = data.get("good_at", [])
        available_days = data.get("available_days", [])
        available_times = data.get("available_times", [])
        study_style = data.get("study_style", [])
        goals = data.get("goals", "").strip()
        
        # Validate
        if not isinstance(needs_help, list) or not isinstance(good_at, list):
            return error_response("needs_help and good_at must be arrays")
        
        if len(needs_help) == 0 and len(good_at) == 0:
            return error_response("Must specify at least one subject in needs_help or good_at")
        
        # Store in user metadata
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        metadata["study_buddy_prefs"] = {
            "needs_help": needs_help[:10],  # Max 10
            "good_at": good_at[:10],
            "available_days": available_days,
            "available_times": available_times,
            "study_style": study_style,
            "goals": goals[:500],  # Max 500 chars
            "updated_at": datetime.datetime.utcnow().isoformat()
        }
        
        current_user.user_metadata = metadata
        db.session.commit()
        
        return success_response(
            "Preferences saved! We'll find great matches for you.",
            data={"preferences": metadata["study_buddy_prefs"]}
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Set preferences error: {str(e)}")
        return error_response("Failed to save preferences")


@study_buddy_bp.route("/study-buddy/preferences", methods=["GET"])
@token_required
def get_preferences(current_user):
    """
    Get current study buddy preferences
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        prefs = metadata.get("study_buddy_prefs", {})
        
        return jsonify({
            "status": "success",
            "data": {
                "matches": matches_data,
                "total": len(matches_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get matches error: {str(e)}")
        return error_response("Failed to load matches")


@study_buddy_bp.route("/study-buddy/match/<int:match_id>", methods=["GET"])
@token_required
def get_match_details_partnership(current_user, match_id):
    """
    Get detailed information about a specific partnership
    """
    try:
        match = StudyBuddyMatch.query.get(match_id)
        
        if not match:
            return error_response("Match not found", 404)
        
        # Verify user is part of match
        if match.user1_id != current_user.id and match.user2_id != current_user.id:
            return error_response("Not authorized", 403)
        
        partner_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
        partner = User.query.get(partner_id)
        thread = Thread.query.get(match.thread_id) if match.thread_id else None
        
        return jsonify({
            "status": "success",
            "data": {
                "match": {
                    "id": match.id,
                    "partner": {
                        "id": partner.id,
                        "username": partner.username,
                        "name": partner.name,
                        "avatar": partner.avatar,
                        "bio": partner.bio
                    } if partner else None,
                    "subjects": match.subjects,
                    "sessions_completed": match.sessions_count,
                    "is_active": match.is_active,
                    "matched_at": match.matched_at.isoformat(),
                    "last_activity": match.last_activity.isoformat() if match.last_activity else None,
                    "ended_at": match.ended_at.isoformat() if match.ended_at else None,
                    "thread": {
                        "id": thread.id,
                        "title": thread.title,
                        "message_count": thread.message_count
                    } if thread else None
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get match details error: {str(e)}")
        return error_response("Failed to load match details")


@study_buddy_bp.route("/study-buddy/session", methods=["POST"])
@token_required
def log_study_session(current_user):
    """
    Log a completed study session
    
    Body: {
        "match_id": 123,
        "duration_minutes": 60,
        "subjects_covered": ["Calculus", "Physics"],
        "notes": "Covered derivatives and kinematics"
    }
    """
    try:
        data = request.get_json()
        
        match_id = data.get("match_id")
        duration = data.get("duration_minutes", 60)
        subjects = data.get("subjects_covered", [])
        notes = data.get("notes", "").strip()
        
        if not match_id:
            return error_response("match_id required")
        
        match = StudyBuddyMatch.query.get(match_id)
        
        if not match:
            return error_response("Match not found", 404)
        
        # Verify user is part of match
        if match.user1_id != current_user.id and match.user2_id != current_user.id:
            return error_response("Not authorized", 403)
        
        # Increment session count
        match.sessions_count += 1
        match.last_activity = datetime.datetime.utcnow()
        
        # Store session metadata (if you add a Session model later)
        # For now, just update match
        
        db.session.commit()
        
        return success_response(
            f"Session logged! You've completed {match.sessions_count} sessions together.",
            data={
                "sessions_count": match.sessions_count
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Log session error: {str(e)}")
        return error_response("Failed to log session")


@study_buddy_bp.route("/study-buddy/sessions", methods=["GET"])
@token_required
def get_session_history(current_user):
    """
    Get all study sessions for current user
    Shows session count per match
    """
    try:
        matches = StudyBuddyMatch.query.filter(
            or_(
                StudyBuddyMatch.user1_id == current_user.id,
                StudyBuddyMatch.user2_id == current_user.id
            )
        ).all()
        
        total_sessions = sum(m.sessions_count for m in matches)
        
        sessions_data = []
        for match in matches:
            if match.sessions_count > 0:
                partner_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
                partner = User.query.get(partner_id)
                
                sessions_data.append({
                    "match_id": match.id,
                    "partner": {
                        "username": partner.username,
                        "name": partner.name
                    } if partner else None,
                    "subjects": match.subjects,
                    "sessions_count": match.sessions_count,
                    "last_session": match.last_activity.isoformat() if match.last_activity else None
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "sessions": sessions_data,
                "total_sessions": total_sessions,
                "active_partnerships": len([m for m in matches if m.is_active])
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get session history error: {str(e)}")
        return error_response("Failed to load session history")


@study_buddy_bp.route("/study-buddy/remove/<int:match_id>", methods=["DELETE"])
@token_required
def end_partnership(current_user, match_id):
    """
    End study buddy partnership
    """
    try:
        match = StudyBuddyMatch.query.get(match_id)
        
        if not match:
            return error_response("Match not found", 404)
        
        # Verify user is part of match
        if match.user1_id != current_user.id and match.user2_id != current_user.id:
            return error_response("Not authorized", 403)
        
        # Mark as inactive
        match.is_active = False
        match.ended_at = datetime.datetime.utcnow()
        
        # Notify partner
        partner_id = match.user2_id if match.user1_id == current_user.id else match.user1_id
        notification = Notification(
            user_id=partner_id,
            title="Study partnership ended",
            body=f"{current_user.name} ended your study partnership",
            notification_type="study_buddy_ended",
            related_type="study_buddy_match",
            related_id=match_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response("Partnership ended")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"End partnership error: {str(e)}")
        return error_response("Failed to end partnership")


# ============================================================================
# DISCOVERY & STATS
# ============================================================================

@study_buddy_bp.route("/study-buddy/success-stories", methods=["GET"])
@token_required
def get_success_stories(current_user):
    """
    Get successful study buddy partnerships (testimonials)
    Shows partnerships with 5+ sessions
    """
    try:
        # Get successful matches from user's department
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        if profile:
            # Get users from same department
            dept_users = db.session.query(User.id).join(StudentProfile).filter(
                StudentProfile.department == profile.department
            ).all()
            dept_user_ids = [u[0] for u in dept_users]
            
            successful_matches = StudyBuddyMatch.query.filter(
                or_(
                    StudyBuddyMatch.user1_id.in_(dept_user_ids),
                    StudyBuddyMatch.user2_id.in_(dept_user_ids)
                ),
                StudyBuddyMatch.sessions_count >= 5
            ).order_by(StudyBuddyMatch.sessions_count.desc()).limit(10).all()
        else:
            successful_matches = StudyBuddyMatch.query.filter(
                StudyBuddyMatch.sessions_count >= 5
            ).order_by(StudyBuddyMatch.sessions_count.desc()).limit(10).all()
        
        stories = []
        for match in successful_matches:
            user1 = User.query.get(match.user1_id)
            user2 = User.query.get(match.user2_id)
            
            if user1 and user2:
                stories.append({
                    "users": [
                        {"username": user1.username, "name": user1.name},
                        {"username": user2.username, "name": user2.name}
                    ],
                    "subjects": match.subjects,
                    "sessions_completed": match.sessions_count,
                    "duration_days": (match.ended_at - match.matched_at).days if match.ended_at else (datetime.datetime.utcnow() - match.matched_at).days,
                    "is_active": match.is_active
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "success_stories": stories,
                "total": len(stories)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get success stories error: {str(e)}")
        return error_response("Failed to load success stories")


@study_buddy_bp.route("/study-buddy/stats", methods=["GET"])
@token_required
def get_platform_stats(current_user):
    """
    Get platform-wide study buddy statistics
    Motivational data to encourage participation
    """
    try:
        # Total matches
        total_matches = StudyBuddyMatch.query.count()
        active_matches = StudyBuddyMatch.query.filter_by(is_active=True).count()
        
        # Total sessions
        total_sessions = db.session.query(
            func.sum(StudyBuddyMatch.sessions_count)
        ).scalar() or 0
        
        # Success rate (matches with 3+ sessions)
        successful_matches = StudyBuddyMatch.query.filter(
            StudyBuddyMatch.sessions_count >= 3
        ).count()
        
        success_rate = round((successful_matches / total_matches * 100), 1) if total_matches > 0 else 0
        
        # Most popular subjects
        all_matches = StudyBuddyMatch.query.all()
        subject_counts = {}
        
        for match in all_matches:
            for subject in match.subjects:
                subject_lower = subject.lower()
                subject_counts[subject_lower] = subject_counts.get(subject_lower, 0) + 1
        
        popular_subjects = sorted(
            [{"subject": k, "count": v} for k, v in subject_counts.items()],
            key=lambda x: x["count"],
            reverse=True
        )[:10]
        
        return jsonify({
            "status": "success",
            "data": {
                "platform_stats": {
                    "total_matches": total_matches,
                    "active_partnerships": active_matches,
                    "total_sessions": int(total_sessions),
                    "success_rate": success_rate,
                    "popular_subjects": popular_subjects
                },
                "motivational_message": f"Join {active_matches} active study partnerships! {int(total_sessions)} sessions completed so far! 🎓"
            }
        })
       
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Get preferences error: {str(e)}")
        return error_response("Failed to load preferences")


@study_buddy_bp.route("/study-buddy/preferences", methods=["PATCH"])
@token_required
def update_preferences(current_user):
    """
    Update specific preference fields
    """
    try:
        data = request.get_json()
        
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        prefs = metadata.get("study_buddy_prefs", {})
        
        # Update provided fields
        if "needs_help" in data:
            prefs["needs_help"] = data["needs_help"][:10]
        if "good_at" in data:
            prefs["good_at"] = data["good_at"][:10]
        if "available_days" in data:
            prefs["available_days"] = data["available_days"]
        if "available_times" in data:
            prefs["available_times"] = data["available_times"]
        if "study_style" in data:
            prefs["study_style"] = data["study_style"]
        if "goals" in data:
            prefs["goals"] = data["goals"][:500]
        
        prefs["updated_at"] = datetime.datetime.utcnow().isoformat()
        
        metadata["study_buddy_prefs"] = prefs
        current_user.user_metadata = metadata
        
        db.session.commit()
        
        return success_response(
            "Preferences updated",
            data={"preferences": prefs}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update preferences failed")
        return error_response("Failed to update preferences")


# ============================================================================
# SMART MATCHING
# ============================================================================

@study_buddy_bp.route("/study-buddy/suggestions", methods=["GET"])
@token_required
def get_suggestions(current_user):
    """
    Get smart study buddy suggestions
    Uses matching algorithm to find compatible users
    
    Query params:
    - limit: Number of suggestions (default 10, max 20)
    """
    try:
        limit = min(request.args.get("limit", 10, type=int), 20)
        
        # Get user preferences
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        user_prefs = metadata.get("study_buddy_prefs", {})
        
        if not user_prefs:
            return jsonify({
                "status": "success",
                "data": {
                    "suggestions": [],
                    "message": "Set your preferences first to get matches"
                }
            })
        
        # Get profile
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        # Exclude users we already have connections with
        existing_requests = StudyBuddyRequest.query.filter(
            or_(
                StudyBuddyRequest.requester_id == current_user.id,
                StudyBuddyRequest.receiver_id == current_user.id
            )
        ).all()
        
        existing_matches = StudyBuddyMatch.query.filter(
            or_(
                StudyBuddyMatch.user1_id == current_user.id,
                StudyBuddyMatch.user2_id == current_user.id
            )
        ).all()
        
        excluded_ids = [current_user.id]
        excluded_ids.extend([r.receiver_id if r.requester_id == current_user.id else r.requester_id for r in existing_requests])
        excluded_ids.extend([m.user2_id if m.user1_id == current_user.id else m.user1_id for m in existing_matches])
        
        # Get potential matches (active users, same or related department)
        candidates = User.query.filter(
            User.id.notin_(excluded_ids),
            User.status == "approved",
            User.last_active >= datetime.datetime.utcnow() - datetime.timedelta(days=30)
        ).limit(50).all()  # Get 50 candidates, then rank
        
        # Calculate match scores
        suggestions = []
        
        for candidate in candidates:
            cand_metadata = candidate.metadata if candidate.metadata else {}
            cand_prefs = cand_metadata.get("study_buddy_prefs", {})
            
            if not cand_prefs:
                continue  # Skip users without preferences
            
            score = calculate_match_score(current_user, candidate, user_prefs, cand_prefs)
            
            if score >= 30:  # Minimum 30% match
                cand_profile = StudentProfile.query.filter_by(user_id=candidate.id).first()
                
                suggestions.append({
                    "user": {
                        "id": candidate.id,
                        "username": candidate.username,
                        "name": candidate.name,
                        "avatar": candidate.avatar,
                        "bio": candidate.bio,
                        "department": cand_profile.department if cand_profile else None,
                        "class_level": cand_profile.class_name if cand_profile else None,
                        "reputation": candidate.reputation,
                        "reputation_level": candidate.reputation_level
                    },
                    "match_score": score,
                    "preferences": {
                        "good_at": cand_prefs.get("good_at", []),
                        "needs_help": cand_prefs.get("needs_help", []),
                        "available_days": cand_prefs.get("available_days", []),
                        "study_style": cand_prefs.get("study_style", [])
                    },
                    "compatibility": {
                        "subject_match": True if score >= 40 else False,
                        "availability_match": True if score >= 30 else False,
                        "same_department": profile.department == cand_profile.department if profile and cand_profile else False
                    },
                    "stats": {
                        "successful_partnerships": StudyBuddyMatch.query.filter(
                            or_(
                                StudyBuddyMatch.user1_id == candidate.id,
                                StudyBuddyMatch.user2_id == candidate.id
                            ),
                            StudyBuddyMatch.sessions_count >= 3
                        ).count()
                    }
                })
        
        # Sort by match score
        suggestions.sort(key=lambda x: x["match_score"], reverse=True)
        
        return jsonify({
            "status": "success",
            "data": {
                "suggestions": suggestions[:limit],
                "total_found": len(suggestions)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get suggestions error: {str(e)}")
        return error_response("Failed to load suggestions")


@study_buddy_bp.route("/study-buddy/suggestions/details/<int:user_id>", methods=["GET"])
@token_required
def get_match_details(current_user, user_id):
    """
    Get detailed match breakdown for a specific user
    Shows why they're a good match
    """
    try:
        candidate = User.query.get(user_id)
        
        if not candidate:
            return error_response("User not found", 404)
        
        # Get preferences
        user_metadata = current_user.user_metadata if current_user.user_metadata else {}
        user_prefs = user_metadata.get("study_buddy_prefs", {})
        
        cand_metadata = candidate.metadata if candidate.metadata else {}
        cand_prefs = cand_metadata.get("study_buddy_prefs", {})
        
        if not user_prefs or not cand_prefs:
            return error_response("Both users must have preferences set")
        
        # Calculate detailed breakdown
        score = calculate_match_score(current_user, candidate, user_prefs, cand_prefs)
        
        # Subject overlap details
        needs1 = set([s.lower() for s in user_prefs.get("needs_help", [])])
        good_at2 = set([s.lower() for s in cand_prefs.get("good_at", [])])
        subject_overlap = list(needs1 & good_at2)
        
        # Availability overlap
        avail1 = set(user_prefs.get("available_days", []))
        avail2 = set(cand_prefs.get("available_days", []))
        day_overlap = list(avail1 & avail2)
        
        return jsonify({
            "status": "success",
            "data": {
                "match_score": score,
                "breakdown": {
                    "subject_compatibility": {
                        "score": min(len(subject_overlap) * 10, 40),
                        "details": f"You need help with {', '.join(subject_overlap)} and they're strong in it!" if subject_overlap else "No direct subject overlap"
                    },
                    "availability": {
                        "score": min(len(day_overlap) * 5, 30),
                        "shared_days": day_overlap,
                        "details": f"Both available on {', '.join(day_overlap)}" if day_overlap else "Limited availability overlap"
                    },
                    "activity_level": {
                        "you": "Active" if current_user.last_active and (datetime.datetime.utcnow() - current_user.last_active).days < 7 else "Moderate",
                        "them": "Active" if candidate.last_active and (datetime.datetime.utcnow() - candidate.last_active).days < 7 else "Moderate"
                    }
                },
                "recommendation": "Perfect match!" if score >= 80 else "Great match!" if score >= 60 else "Good match" if score >= 40 else "Moderate match"
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get match details error: {str(e)}")
        return error_response("Failed to load match details")


# ============================================================================
# STUDY BUDDY REQUESTS
# ============================================================================

@study_buddy_bp.route("/study-buddy/request/<int:user_id>", methods=["POST"])
@token_required
def send_request(current_user, user_id):
    """
    Send study buddy request
    
    Body: {
        "message": "Hey! Let's study Calculus together",
        "subjects": ["Calculus", "Physics"]
    }
    """
    try:
        if user_id == current_user.id:
            return error_response("Cannot send request to yourself")
        
        target_user = User.query.get(user_id)
        if not target_user:
            return error_response("User not found", 404)
        
        # Check for existing request
        existing = StudyBuddyRequest.query.filter(
            or_(
                and_(StudyBuddyRequest.requester_id == current_user.id, StudyBuddyRequest.receiver_id == user_id),
                and_(StudyBuddyRequest.requester_id == user_id, StudyBuddyRequest.receiver_id == current_user.id)
            )
        ).first()
        
        if existing:
            if existing.status == "pending":
                return error_response("Request already pending", 409)
            elif existing.status == "accepted":
                return error_response("Already study buddies", 409)
        
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        subjects = data.get("subjects", [])
        
        # Get user preferences for availability
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        prefs = metadata.get("study_buddy_prefs", {})
        
        # Create request
        buddy_request = StudyBuddyRequest(
            requester_id=current_user.id,
            receiver_id=user_id,
            message=message if message else "Let's study together!",
            subjects=subjects,
            availability=prefs.get("available_days", []),
            status="pending"
        )
        
        db.session.add(buddy_request)
        
        # Create notification
        notification = Notification(
            user_id=user_id,
            title=f"{current_user.name} wants to be study buddies!",
            body=message if message else f"Study: {', '.join(subjects[:3])}",
            notification_type="study_buddy_request",
            related_type="study_buddy_request",
            related_id=buddy_request.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Study buddy request sent!",
            data={
                "request_id": buddy_request.id,
                "receiver": {
                    "id": target_user.id,
                    "username": target_user.username,
                    "name": target_user.name
                }
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Send study buddy request error: {str(e)}")
        return error_response("Failed to send request")


@study_buddy_bp.route("/study-buddy/accept/<int:request_id>", methods=["POST"])
@token_required
def accept_request(current_user, request_id):
    """
    Accept study buddy request
    Auto-creates private thread for them
    """
    try:
        buddy_request = StudyBuddyRequest.query.get(request_id)
        
        if not buddy_request:
            return error_response("Request not found", 404)
        
        if buddy_request.receiver_id != current_user.id:
            return error_response("Not authorized", 403)
        
        if buddy_request.status != "pending":
            return error_response("Request is no longer pending", 400)
        
        # Accept request
        buddy_request.status = "accepted"
        buddy_request.responded_at = datetime.datetime.utcnow()
        
        # Create study buddy match
        match = StudyBuddyMatch(
            user1_id=buddy_request.requester_id,
            user2_id=current_user.id,
            subjects=buddy_request.subjects,
            is_active=True
        )
        
        db.session.add(match)
        db.session.flush()
        
        # Auto-create private study thread
        thread = Thread(
            post_id=None,  # Standalone thread
            creator_id=buddy_request.requester_id,
            title=f"Study Partnership: {', '.join(buddy_request.subjects[:2])}",
            description=f"Private study thread for {User.query.get(buddy_request.requester_id).name} and {current_user.name}",
            max_members=2,
            requires_approval=False,
            is_open=False,  # Private - no one else can join
            member_count=2
        )
        
        db.session.add(thread)
        db.session.flush()
        
        # Add both as members
        member1 = ThreadMember(
            thread_id=thread.id,
            student_id=buddy_request.requester_id,
            role="creator"
        )
        member2 = ThreadMember(
            thread_id=thread.id,
            student_id=current_user.id,
            role="member"
        )
        
        db.session.add(member1)
        db.session.add(member2)
        
        # Link thread to match
        match.thread_id = thread.id
        buddy_request.thread_id = thread.id
        
        # Notify requester
        notification = Notification(
            user_id=buddy_request.requester_id,
            title=f"{current_user.name} accepted your study buddy request!",
            body=f"Start studying together in your private thread",
            notification_type="study_buddy_accepted",
            related_type="thread",
            related_id=thread.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Study buddy request accepted! Thread created.",
            data={
                "match_id": match.id,
                "thread_id": thread.id
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Accept study buddy request error: {str(e)}")
        return error_response("Failed to accept request")


@study_buddy_bp.route("/study-buddy/reject/<int:request_id>", methods=["POST"])
@token_required
def reject_request(current_user, request_id):
    """
    Reject study buddy request
    """
    try:
        buddy_request = StudyBuddyRequest.query.get(request_id)
        
        if not buddy_request:
            return error_response("Request not found", 404)
        
        if buddy_request.receiver_id != current_user.id:
            return error_response("Not authorized", 403)
        
        if buddy_request.status != "pending":
            return error_response("Request is no longer pending", 400)
        
        buddy_request.status = "rejected"
        buddy_request.responded_at = datetime.datetime.utcnow()
        
        db.session.commit()
        
        return success_response("Study buddy request rejected")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Reject study buddy request error: {str(e)}")
        return error_response("Failed to reject request")


@study_buddy_bp.route("/study-buddy/cancel/<int:request_id>", methods=["DELETE"])
@token_required
def cancel_request(current_user, request_id):
    """
    Cancel pending request you sent
    """
    try:
        buddy_request = StudyBuddyRequest.query.get(request_id)
        
        if not buddy_request:
            return error_response("Request not found", 404)
        
        if buddy_request.requester_id != current_user.id:
            return error_response("Can only cancel requests you sent", 403)
        
        if buddy_request.status != "pending":
            return error_response("Request is no longer pending", 400)
        
        db.session.delete(buddy_request)
        db.session.commit()
        
        return success_response("Study buddy request cancelled")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Cancel study buddy request error: {str(e)}")
        return error_response("Failed to cancel request")


@study_buddy_bp.route("/study-buddy/requests/sent", methods=["GET"])
@token_required
def get_sent_requests(current_user):
    """
    Get all study buddy requests you sent
    """
    try:
        requests = StudyBuddyRequest.query.filter_by(
            requester_id=current_user.id
        ).order_by(StudyBuddyRequest.requested_at.desc()).all()
        
        requests_data = []
        for req in requests:
            receiver = User.query.get(req.receiver_id)
            if receiver:
                requests_data.append({
                    "request_id": req.id,
                    "user": {
                        "id": receiver.id,
                        "username": receiver.username,
                        "name": receiver.name,
                        "avatar": receiver.avatar
                    },
                    "subjects": req.subjects,
                    "message": req.message,
                    "status": req.status,
                    "requested_at": req.requested_at.isoformat(),
                    "responded_at": req.responded_at.isoformat() if req.responded_at else None
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "sent_requests": requests_data,
                "total": len(requests_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get sent requests error: {str(e)}")
        return error_response("Failed to load sent requests")

@study_buddy_bp.route("/study-buddy/requests/accepted", methods=["GET"])
@token_required
def accepted_requests(current_user):
   try:
       requests_data = []
       requests = StudyBuddyRequest.query.filter_by(receiver_id = current_user.id, status = "accepted").order_by(StudyBuddyRequest.requested_at.desc()).all()
       for req in requests:
                    requests_data.append({
                    "request_id": req.id,
                    "user": {
                        "id": requester.id,
                        "username": requester.username,
                        "name": requester.name,
                        "avatar": requester.avatar,
                        "bio": requester.bio,
                        "reputation_level": requester.reputation_level
                    },
                    "subjects": req.subjects,
                    "message": req.message,
                    "availability": req.availability,
                    "match_score": match_score,
                })
        return jsonify({"status": "success", "data": {"accepted_requests": requests_data, "total": len(requests_data)}})
    except Exception as e:
        return error_response("Failed to load study buddies")
        
@study_buddy_bp.route("/study-buddy/requests/received", methods=["GET"])
@token_required
def get_received_requests(current_user):
    """
    Get all study buddy requests you received
    """
    try:
        requests = StudyBuddyRequest.query.filter_by(
            receiver_id=current_user.id,
            status="pending"
        ).order_by(StudyBuddyRequest.requested_at.desc()).all()
        
        requests_data = []
        for req in requests:
            requester = User.query.get(req.requester_id)
            if requester:
                # Calculate match score
                user_metadata = current_user.user_metadata if current_user.user_metadata else {}
                user_prefs = user_metadata.get("study_buddy_prefs", {})
                
                req_metadata = requester.metadata if requester.metadata else {}
                req_prefs = req_metadata.get("study_buddy_prefs", {})
                
                match_score = calculate_match_score(current_user, requester, user_prefs, req_prefs) if user_prefs and req_prefs else 0
                
                requests_data.append({
                    "request_id": req.id,
                    "user": {
                        "id": requester.id,
                        "username": requester.username,
                        "name": requester.name,
                        "avatar": requester.avatar,
                        "bio": requester.bio,
                        "reputation_level": requester.reputation_level
                    },
                    "subjects": req.subjects,
                    "message": req.message,
                    "availability": req.availability,
                    "match_score": match_score,
                    "requested_at": req.requested_at.isoformat()
                })
        
        return jsonify({"status": "success", "data": {"received_requests": requests_data, "total": len(requests_data)}})
    except Exception as e:
       db.session.rollback()
       current_app.logger.error(f"Get received requests error: {str(e)}")
       return error_response("Failed to load received requests")

