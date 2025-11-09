"""
StudyHub - Connection Request System
Users must connect before messaging - prevents spam and creates safer community
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_, and_, func
import datetime

from models import (
    User, StudentProfile, Connection, Notification,
    Post, Comment, Thread, ThreadMember
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response
)

connections_bp = Blueprint("student_connections", __name__)


# ============================================================================
# CONNECTION REQUESTS
# ============================================================================

@connections_bp.route("/connections/request/<int:user_id>", methods=["POST"])
@token_required
def send_connection_request(current_user, user_id):
    """
    Send connection request to another user
    
    Body (optional): {
        "message": "Hi! Let's connect and study together"
    }
    """
    try:
        # Validation
        if user_id == current_user.id:
            return error_response("Cannot connect with yourself")
        
        target_user = User.query.get(user_id)
        if not target_user:
            return error_response("User not found", 404)
        
        # Check if connection already exists (either direction)
        existing = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            )
        ).first()
        
        if existing:
            if existing.status == "accepted":
                return error_response("Already connected", 409)
            elif existing.status == "pending":
                return error_response("Connection request already pending", 409)
            elif existing.status == "blocked":
                return error_response("Cannot connect with this user", 403)
            elif existing.status == "rejected":
                # Allow re-request after rejection (but maybe after cooldown?)
                existing.status = "pending"
                existing.requested_at = datetime.datetime.utcnow()
                existing.responded_at = None
                db.session.commit()
                
                # Create notification
                notification = Notification(
                    user_id=user_id,
                    title="New Connection Request",
                    body=f"{current_user.name} sent you a connection request again",
                    notification_type="connection_request",
                    related_type="user",
                    related_id=current_user.id
                )
                db.session.add(notification)
                db.session.commit()
                
                return success_response(
                    "Connection request re-sent",
                    data={"connection_id": existing.id}
                ), 201
        
        # Create new connection request
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        
        connection = Connection(
            requester_id=current_user.id,
            receiver_id=user_id,
            status="pending",
            notes=message if message else None
        )
        db.session.add(connection)
        
        # Create notification
        notification = Notification(
            user_id=user_id,
            title="New Connection Request",
            body=f"{current_user.name} wants to connect with you",
            notification_type="connection_request",
            related_type="user",
            related_id=current_user.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Connection request sent",
            data={
                "connection_id": connection.id,
                "receiver": {
                    "id": target_user.id,
                    "name": target_user.name,
                    "username": target_user.username
                }
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Send connection request error: {str(e)}")
        return error_response("Failed to send connection request")


@connections_bp.route("/connections/accept/<int:request_id>", methods=["POST"])
@token_required
def accept_connection(current_user, request_id):
    """
    Accept a connection request
    """
    try:
        connection = Connection.query.get(request_id)
        
        if not connection:
            return error_response("Connection request not found", 404)
        
        # Verify user is the receiver
        if connection.receiver_id != current_user.id:
            return error_response("Not authorized to accept this request", 403)
        
        if connection.status != "pending":
            return error_response("Request is not pending", 400)
        
        # Accept connection
        connection.status = "accepted"
        connection.responded_at = datetime.datetime.utcnow()
        
        # Create notification for requester
        notification = Notification(
            user_id=connection.requester_id,
            title="Connection Accepted",
            body=f"{current_user.name} accepted your connection request",
            notification_type="connection_accepted",
            related_type="user",
            related_id=current_user.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        # Get requester info
        requester = User.query.get(connection.requester_id)
        
        return success_response(
            "Connection accepted",
            data={
                "connection_id": connection.id,
                "connected_user": {
                    "id": requester.id,
                    "name": requester.name,
                    "username": requester.username,
                    "avatar": requester.avatar
                }
            }
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Accept connection error: {str(e)}")
        return error_response("Failed to accept connection")


@connections_bp.route("/connections/reject/<int:request_id>", methods=["POST"])
@token_required
def reject_connection(current_user, request_id):
    """
    Reject a connection request
    """
    try:
        connection = Connection.query.get(request_id)
        
        if not connection:
            return error_response("Connection request not found", 404)
        
        # Verify user is the receiver
        if connection.receiver_id != current_user.id:
            return error_response("Not authorized to reject this request", 403)
        
        if connection.status != "pending":
            return error_response("Request is not pending", 400)
        
        # Reject connection
        connection.status = "rejected"
        connection.responded_at = datetime.datetime.utcnow()
        
        db.session.commit()
        
        return success_response("Connection request rejected")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Reject connection error: {str(e)}")
        return error_response("Failed to reject connection")


@connections_bp.route("/connections/cancel/<int:request_id>", methods=["DELETE"])
@token_required
def cancel_connection_request(current_user, request_id):
    """
    Cancel a pending connection request you sent
    """
    try:
        connection = Connection.query.get(request_id)
        
        if not connection:
            return error_response("Connection request not found", 404)
        
        # Verify user is the requester
        if connection.requester_id != current_user.id:
            return error_response("Not authorized to cancel this request", 403)
        
        if connection.status != "pending":
            return error_response("Request is not pending", 400)
        
        # Delete the request
        db.session.delete(connection)
        db.session.commit()
        
        return success_response("Connection request cancelled")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Cancel connection error: {str(e)}")
        return error_response("Failed to cancel connection")


@connections_bp.route("/connections/remove/<int:user_id>", methods=["DELETE"])
@token_required
def remove_connection(current_user, user_id):
    """
    Remove/unfriend a connection
    """
    try:
        # Find connection (either direction)
        connection = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            ),
            Connection.status == "accepted"
        ).first()
        
        if not connection:
            return error_response("Connection not found", 404)
        
        # Delete the connection
        db.session.delete(connection)
        db.session.commit()
        
        return success_response("Connection removed")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Remove connection error: {str(e)}")
        return error_response("Failed to remove connection")


# ============================================================================
# VIEW CONNECTIONS
# ============================================================================

@connections_bp.route("/connections/list", methods=["GET"])
@token_required
def list_connections(current_user):
    """
    Get all accepted connections
    
    Query params:
    - search: Search by name/username
    - department: Filter by department
    - page: Page number (default 1)
    - per_page: Items per page (default 20)
    """
    try:
        # Get all accepted connections (both directions)
        connections = Connection.query.filter(
            or_(
                Connection.requester_id == current_user.id,
                Connection.receiver_id == current_user.id
            ),
            Connection.status == "accepted"
        ).all()
        
        # Extract connected user IDs
        connected_user_ids = []
        for conn in connections:
            if conn.requester_id == current_user.id:
                connected_user_ids.append(conn.receiver_id)
            else:
                connected_user_ids.append(conn.requester_id)
        
        # Get user details
        query = User.query.filter(User.id.in_(connected_user_ids))
        
        # Search filter
        search = request.args.get("search", "").strip()
        if search:
            query = query.filter(
                or_(
                    User.name.ilike(f"%{search}%"),
                    User.username.ilike(f"%{search}%")
                )
            )
        
        # Department filter
        department = request.args.get("department", "").strip()
        if department:
            query = query.join(StudentProfile).filter(
                StudentProfile.department == department
            )
        
        # Pagination
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        # Format response
        connections_data = []
        for user in paginated.items:
            profile = StudentProfile.query.filter_by(user_id=user.id).first()
            connections_data.append({
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "avatar": user.avatar,
                "bio": user.bio,
                "department": profile.department if profile else None,
                "class_level": profile.class_name if profile else None,
                "reputation": user.reputation,
                "reputation_level": user.reputation_level
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "connections": connections_data,
                "total": paginated.total,
                "page": page,
                "per_page": per_page,
                "pages": paginated.pages
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"List connections error: {str(e)}")
        return error_response("Failed to load connections")


@connections_bp.route("/connections/pending", methods=["GET"])
@token_required
def pending_requests(current_user):
    """
    Get all pending connection requests
    
    Returns both:
    - Requests sent by you (pending_sent)
    - Requests received by you (pending_received)
    """
    try:
        # Requests you sent
        sent_requests = Connection.query.filter_by(
            requester_id=current_user.id,
            status="pending"
        ).all()
        
        sent_data = []
        for req in sent_requests:
            receiver = User.query.get(req.receiver_id)
            if receiver:
                profile = StudentProfile.query.filter_by(user_id=receiver.id).first()
                sent_data.append({
                    "request_id": req.id,
                    "user": {
                        "id": receiver.id,
                        "username": receiver.username,
                        "name": receiver.name,
                        "avatar": receiver.avatar,
                        "department": profile.department if profile else None
                    },
                    "requested_at": req.requested_at.isoformat(),
                    "message": req.notes
                })
        
        # Requests you received
        received_requests = Connection.query.filter_by(
            receiver_id=current_user.id,
            status="pending"
        ).all()
        
        received_data = []
        for req in received_requests:
            requester = User.query.get(req.requester_id)
            if requester:
                profile = StudentProfile.query.filter_by(user_id=requester.id).first()
                received_data.append({
                    "request_id": req.id,
                    "user": {
                        "id": requester.id,
                        "username": requester.username,
                        "name": requester.name,
                        "avatar": requester.avatar,
                        "department": profile.department if profile else None,
                        "bio": requester.bio
                    },
                    "requested_at": req.requested_at.isoformat(),
                    "message": req.notes
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "sent": sent_data,
                "received": received_data,
                "total_sent": len(sent_data),
                "total_received": len(received_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Pending requests error: {str(e)}")
        return error_response("Failed to load pending requests")


@connections_bp.route("/connections/status/<int:user_id>", methods=["GET"])
@token_required
def connection_status(current_user, user_id):
    """
    Check connection status with a specific user
    
    Returns: none, pending_sent, pending_received, connected, blocked
    """
    try:
        if user_id == current_user.id:
            return jsonify({
                "status": "success",
                "data": {
                    "status": "self",
                    "can_message": False,
                    "can_connect": False
                }
            })
        
        # Check for connection
        connection = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            )
        ).first()
        
        if not connection:
            return jsonify({
                "status": "success",
                "data": {
                    "status": "none",
                    "can_message": False,
                    "can_connect": True
                }
            })
        
        # Determine status
        if connection.status == "accepted":
            conn_status = "connected"
            can_message = True
        elif connection.status == "pending":
            if connection.requester_id == current_user.id:
                conn_status = "pending_sent"
            else:
                conn_status = "pending_received"
            can_message = False
        elif connection.status == "blocked":
            conn_status = "blocked"
            can_message = False
        else:
            conn_status = "rejected"
            can_message = False
        
        return jsonify({
            "status": "success",
            "data": {
                "status": conn_status,
                "can_message": can_message,
                "can_connect": conn_status in ["none", "rejected"],
                "connection_id": connection.id if connection else None,
                "connected_at": connection.responded_at.isoformat() if connection and connection.status == "accepted" else None
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Connection status error: {str(e)}")
        return error_response("Failed to check connection status")


# ============================================================================
# SMART CONNECTION SUGGESTIONS
# ============================================================================

@connections_bp.route("/connections/suggestions", methods=["GET"])
@token_required
def connection_suggestions(current_user):
    """
    Smart connection suggestions based on:
    - Same department
    - Similar skills/learning goals
    - Active in similar threads
    - Mutual connections
    
    Limit: 10 suggestions
    """
    try:
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        # Get existing connections and pending requests
        existing_connections = Connection.query.filter(
            or_(
                Connection.requester_id == current_user.id,
                Connection.receiver_id == current_user.id
            )
        ).all()
        
        excluded_ids = [current_user.id]
        for conn in existing_connections:
            if conn.requester_id == current_user.id:
                excluded_ids.append(conn.receiver_id)
            else:
                excluded_ids.append(conn.requester_id)
        
        suggestions = []
        
        # 1. Same department students
        same_dept_users = User.query.join(StudentProfile).filter(
            StudentProfile.department == profile.department,
            User.id.notin_(excluded_ids),
            User.status == "approved"
        ).limit(5).all()
        
        for user in same_dept_users:
            user_profile = StudentProfile.query.filter_by(user_id=user.id).first()
            
            # Calculate match score
            score = 50  # Base score for same department
            
            # Skill overlap
            if user.skills and current_user.skills:
                common_skills = set(s.lower() for s in user.skills) & set(s.lower() for s in current_user.skills)
                score += len(common_skills) * 10
            
            # Learning goal overlap
            if user.learning_goals and current_user.learning_goals:
                common_goals = set(g.lower() for g in user.learning_goals) & set(g.lower() for g in current_user.learning_goals)
                score += len(common_goals) * 15
            
            suggestions.append({
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "avatar": user.avatar,
                    "bio": user.bio,
                    "department": user_profile.department,
                    "class_level": user_profile.class_name,
                    "reputation": user.reputation,
                    "skills": user.skills[:5] if user.skills else []
                },
                "match_score": min(score, 100),
                "reason": "Same department"
            })
        
        # 2. Users in similar threads
        user_threads = ThreadMember.query.filter_by(student_id=current_user.id).all()
        thread_ids = [tm.thread_id for tm in user_threads]
        
        if thread_ids:
            thread_members = ThreadMember.query.filter(
                ThreadMember.thread_id.in_(thread_ids),
                ThreadMember.student_id.notin_(excluded_ids)
            ).limit(5).all()
            
            for tm in thread_members:
                user = User.query.get(tm.student_id)
                if user and user.id not in [s["user"]["id"] for s in suggestions]:
                    user_profile = StudentProfile.query.filter_by(user_id=user.id).first()
                    suggestions.append({
                        "user": {
                            "id": user.id,
                            "username": user.username,
                            "name": user.name,
                            "avatar": user.avatar,
                            "bio": user.bio,
                            "department": user_profile.department if user_profile else None,
                            "class_level": user_profile.class_name if user_profile else None,
                            "reputation": user.reputation
                        },
                        "match_score": 70,
                        "reason": "Active in similar threads"
                    })
        
        # Sort by match score
        suggestions.sort(key=lambda x: x["match_score"], reverse=True)
        
        return jsonify({
            "status": "success",
            "data": {
                "suggestions": suggestions[:10],  # Top 10
                "total": len(suggestions)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Connection suggestions error: {str(e)}")
        return error_response("Failed to load suggestions")
        


# ============================================================================
# MUTUAL CONNECTIONS
# ============================================================================

@connections_bp.route("/connections/mutual/<int:user_id>", methods=["GET"])
@token_required
def mutual_connections(current_user, user_id):
    """
    Find mutual connections between you and another user
    """
    try:
        # Get your connections
        your_connections = Connection.query.filter(
            or_(
                Connection.requester_id == current_user.id,
                Connection.receiver_id == current_user.id
            ),
            Connection.status == "accepted"
        ).all()
        
        your_connection_ids = set()
        for conn in your_connections:
            if conn.requester_id == current_user.id:
                your_connection_ids.add(conn.receiver_id)
            else:
                your_connection_ids.add(conn.requester_id)
        
        # Get their connections
        their_connections = Connection.query.filter(
            or_(
                Connection.requester_id == user_id,
                Connection.receiver_id == user_id
            ),
            Connection.status == "accepted"
        ).all()
        
        their_connection_ids = set()
        for conn in their_connections:
            if conn.requester_id == user_id:
                their_connection_ids.add(conn.receiver_id)
            else:
                their_connection_ids.add(conn.requester_id)
        
        # Find mutual
        mutual_ids = your_connection_ids & their_connection_ids
        
        if not mutual_ids:
            return jsonify({
                "status": "success",
                "data": {
                    "mutual_connections": [],
                    "count": 0
                }
            })
        
        # Get user details
        mutual_users = User.query.filter(User.id.in_(mutual_ids)).limit(10).all()
        
        mutual_data = []
        for user in mutual_users:
            profile = StudentProfile.query.filter_by(user_id=user.id).first()
            mutual_data.append({
                "id": user.id,
                "username": user.username,
                "name": user.name,
                "avatar": user.avatar,
                "department": profile.department if profile else None
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "mutual_connections": mutual_data,
                "count": len(mutual_ids),
                "showing": len(mutual_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Mutual connections error: {str(e)}")
        return error_response("Failed to find mutual connections")
        
@connections_bp.route("/connections/block/<int:user_id>", methods=["POST"])
@token_required
def block_user(current_user, user_id):
    """
    Block a user - prevents them from:
    - Sending connection requests
    - Viewing your profile (if private)
    - Messaging you
    
    This also removes any existing connection
    """
    try:
        if user_id == current_user.id:
            return error_response("Cannot block yourself")
        
        target_user = User.query.get(user_id)
        if not target_user:
            return error_response("User not found", 404)
        
        # Check if connection exists
        existing = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            )
        ).first()
        
        if existing:
            # Update existing connection to blocked
            existing.status = "blocked"
            existing.responded_at = datetime.datetime.utcnow()
            # Make sure current user is always the blocker
            if existing.receiver_id != current_user.id:
                # Swap to make current user the "receiver" (blocker)
                existing.requester_id, existing.receiver_id = existing.receiver_id, existing.requester_id
        else:
            # Create new block record
            block = Connection(
                requester_id=user_id,  # The blocked user
                receiver_id=current_user.id,  # The blocker
                status="blocked"
            )
            db.session.add(block)
        
        db.session.commit()
        
        return success_response(
            "User blocked successfully",
            data={
                "blocked_user": {
                    "id": target_user.id,
                    "username": target_user.username,
                    "name": target_user.name
                }
            }
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Block user error: {str(e)}")
        return error_response("Failed to block user")


@connections_bp.route("/connections/unblock/<int:user_id>", methods=["POST"])
@token_required
def unblock_user(current_user, user_id):
    """
    Unblock a previously blocked user
    """
    try:
        # Find block record
        block = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            ),
            Connection.status == "blocked"
        ).first()
        
        if not block:
            return error_response("User is not blocked", 404)
        
        # Verify current user is the blocker
        if block.receiver_id != current_user.id and block.requester_id != current_user.id:
            return error_response("Not authorized", 403)
        
        # Remove block
        db.session.delete(block)
        db.session.commit()
        
        return success_response("User unblocked successfully")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unblock user error: {str(e)}")
        return error_response("Failed to unblock user")


@connections_bp.route("/connections/blocked", methods=["GET"])
@token_required
def list_blocked_users(current_user):
    """
    Get list of all blocked users
    """
    try:
        # Find all users blocked by current user    
        blocked = Connection.query.filter(
            Connection.receiver_id == current_user.id,
            Connection.status == "blocked"
        ).all()
        
        blocked_data = []
        for block in blocked:
            user = User.query.get(block.requester_id)
            if user:
                profile = StudentProfile.query.filter_by(user_id=user.id).first()
                blocked_data.append({
                    "id": user.id,
                    "username": user.username,
                    "name": user.name,
                    "avatar": user.avatar,
                    "department": profile.department if profile else None,
                    "blocked_at": block.responded_at.isoformat() if block.responded_at else None
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "blocked_users": blocked_data,
                "total": len(blocked_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"List blocked users error: {str(e)}")
        return error_response("Failed to load blocked users")