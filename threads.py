"""
StudyHub - Complete Thread System
Private collaboration groups for studying together
Includes: creation, invites, join requests, chat, member management
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_, and_, func, desc
import datetime

from models import (
    User, StudentProfile, Thread, ThreadMember, ThreadJoinRequest,
    ThreadMessage, Post, Notification, Connection
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response
)

# Import mention detection from posts
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

threads_bp = Blueprint("student_threads", __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def detect_mentions_in_thread(text_content, sender_id, thread_id, message_id):
    """
    Detect @username mentions in thread messages
    Same logic as posts, but for thread context
    """
    if not text_content:
        return []
    
    import re
    from models import Mention, Notification, User
    
    mention_pattern = r'@([a-zA-Z0-9_]{3,20})'
    matches = re.finditer(mention_pattern, text_content)
    
    mentioned_users = []
    sender = User.query.get(sender_id)
    
    for match in matches:
        username = match.group(1).lower()
        mentioned_user = User.query.filter_by(username=username).first()
        
        if mentioned_user and mentioned_user.id != sender_id:
            # Verify mentioned user is a thread member
            is_member = ThreadMember.query.filter_by(
                thread_id=thread_id,
                student_id=mentioned_user.id
            ).first()
            
            if is_member:
                existing = Mention.query.filter_by(
                    mentioned_in_type="thread_message",
                    mentioned_in_id=message_id,
                    mentioned_user_id=mentioned_user.id,
                    mentioned_by_user_id=sender_id
                ).first()
                
                if not existing:
                    mention = Mention(
                        mentioned_in_type="thread_message",
                        mentioned_in_id=message_id,
                        mentioned_user_id=mentioned_user.id,
                        mentioned_by_user_id=sender_id
                    )
                    db.session.add(mention)
                    
                    notification = Notification(
                        user_id=mentioned_user.id,
                        title=f"{sender.name} mentioned you in a thread",
                        body="",
                        notification_type="mention",
                        related_type="thread",
                        related_id=thread_id
                    )
                    db.session.add(notification)
                    
                    mentioned_users.append(mentioned_user.id)
    
    return mentioned_users


# ============================================================================
# THREAD CREATION
# ============================================================================

@threads_bp.route("/threads/create", methods=["POST"])
@token_required
def create_thread(current_user):
    """
    Create thread from a post
    
    Body: {
        "post_id": 123,
        "title": "Thread title",
        "description": "What we'll study",
        "max_members": 10,
        "requires_approval": true
    }
    """
    try:
        data = request.get_json()
        post_id = data.get("post_id")
        
        if not post_id:
            return error_response("post_id is required")
        
        # Verify post exists and allows threads
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        if not post.thread_enabled:
            return error_response("This post does not allow thread creation", 403)
        
        # Validate input
        title = data.get("title", "").strip()
        if not title:
            return error_response("Thread title is required")
        
        if len(title) < 5:
            return error_response("Title too short (minimum 5 characters)")
        
        description = data.get("description", "").strip()
        max_members = data.get("max_members", 10)
        requires_approval = data.get("requires_approval", True)
        
        if max_members < 2:
            return error_response("Thread must allow at least 2 members")
        if max_members > 50:
            return error_response("Thread cannot exceed 50 members")
        
        # Get department from user profile
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        # Create thread
        new_thread = Thread(
            post_id=post_id,
            creator_id=current_user.id,
            title=title,
            description=description,
            max_members=max_members,
            requires_approval=requires_approval,
            department=profile.department if profile else None,
            tags=post.tags,
            member_count=1
        )
        
        db.session.add(new_thread)
        db.session.flush()
        
        # Auto-add creator as first member
        creator_member = ThreadMember(
            thread_id=new_thread.id,
            student_id=current_user.id,
            role="creator"
        )
        db.session.add(creator_member)
        
        db.session.commit()
        
        return success_response(
            "Thread created successfully!",
            data={
                "thread": {
                    "id": new_thread.id,
                    "title": new_thread.title,
                    "max_members": new_thread.max_members,
                    "created_at": new_thread.created_at.isoformat()
                }
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create thread error: {str(e)}")
        return error_response("Failed to create thread")


@threads_bp.route("/threads/create-standalone", methods=["POST"])
@token_required
def create_standalone_thread(current_user):
    """
    Create thread WITHOUT a post (standalone study group)
    
    Body: {
        "title": "React Study Group",
        "description": "Learning React hooks",
        "max_members": 8,
        "requires_approval": true,
        "tags": ["react", "javascript"]
    }
    """
    try:
        data = request.get_json()
        
        title = data.get("title", "").strip()
        if not title:
            return error_response("Thread title is required")
        
        if len(title) < 5:
            return error_response("Title too short (minimum 5 characters)")
        
        description = data.get("description", "").strip()
        max_members = data.get("max_members", 10)
        requires_approval = data.get("requires_approval", True)
        tags = data.get("tags", [])
        
        if max_members < 2 or max_members > 50:
            return error_response("Max members must be between 2 and 50")
        
        # Rate limit: max 3 threads per week
        week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
        recent_threads = Thread.query.filter(
            Thread.creator_id == current_user.id,
            Thread.created_at >= week_ago
        ).count()
        
        if recent_threads >= 3:
            return error_response("You can only create 3 threads per week", 429)
        
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        # Create thread (no post_id)
        new_thread = Thread(
            post_id=None,  # Standalone thread
            creator_id=current_user.id,
            title=title,
            description=description,
            max_members=max_members,
            requires_approval=requires_approval,
            department=profile.department if profile else None,
            tags=tags[:5] if tags else [],
            member_count=1
        )
        
        db.session.add(new_thread)
        db.session.flush()
        
        # Auto-add creator
        creator_member = ThreadMember(
            thread_id=new_thread.id,
            student_id=current_user.id,
            role="creator"
        )
        db.session.add(creator_member)
        
        db.session.commit()
        
        return success_response(
            "Standalone thread created!",
            data={
                "thread": {
                    "id": new_thread.id,
                    "title": new_thread.title,
                    "is_standalone": True,
                    "created_at": new_thread.created_at.isoformat()
                }
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create standalone thread error: {str(e)}")
        return error_response("Failed to create thread")


# ============================================================================
# THREAD VIEWING
# ============================================================================
@threads_bp.route("/threads/<int:thread_id>/leave", methods=["POST"])
@token_required
def leave_thread(current_user, thread_id):
    """Leave a thread you're a member of"""
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        # Check if user is creator
        if thread.creator_id == current_user.id:
            return error_response("Creator cannot leave thread. Transfer ownership or delete thread.", 403)
        
        # Find membership
        membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if not membership:
            return error_response("You are not a member of this thread", 404)
        
        # Remove membership
        db.session.delete(membership)
        
        # Update thread
        thread.member_count = max(1, thread.member_count - 1)
        thread.last_activity = datetime.datetime.utcnow()
        
        # Notify creator
        notification = Notification(
            user_id=thread.creator_id,
            title=f"{current_user.name} left your thread",
            body=f'Thread: "{thread.title}"',
            notification_type="thread_member_left",
            related_type="thread",
            related_id=thread_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response("You left the thread")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Leave thread error: {str(e)}")
        return error_response("Failed to leave thread")


@threads_bp.route("/threads/<int:thread_id>/remove/<int:user_id>", methods=["DELETE"])
@token_required
def remove_member(current_user, thread_id, user_id):
    """
    Remove a member from thread (creator/moderator only)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        # Verify user has permission
        current_membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if not current_membership or current_membership.role not in ["creator", "moderator"]:
            return error_response("Only creator/moderators can remove members", 403)
        
        # Cannot remove creator
        if user_id == thread.creator_id:
            return error_response("Cannot remove thread creator", 403)
        
        # Find member to remove
        member = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=user_id
        ).first()
        
        if not member:
            return error_response("User is not a member", 404)
        
        # Remove member
        db.session.delete(member)
        
        thread.member_count = max(1, thread.member_count - 1)
        thread.last_activity = datetime.datetime.utcnow()
        
        # Notify removed user
        notification = Notification(
            user_id=user_id,
            title="You were removed from a thread",
            body=f'Thread: "{thread.title}"',
            notification_type="thread_removed",
            related_type="thread",
            related_id=thread_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response("Member removed from thread")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Remove member error: {str(e)}")
        return error_response("Failed to remove member")


# ============================================================================
# THREAD MANAGEMENT
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/close", methods=["POST"])
@token_required
def close_thread(current_user, thread_id):
    """
    Close thread - no more join requests accepted (creator only)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can close thread", 403)
        
        if not thread.is_open:
            return error_response("Thread is already closed", 409)
        
        thread.is_open = False
        db.session.commit()
        
        return success_response("Thread closed - no more join requests will be accepted")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Close thread error: {str(e)}")
        return error_response("Failed to close thread")


@threads_bp.route("/threads/<int:thread_id>/reopen", methods=["POST"])
@token_required
def reopen_thread(current_user, thread_id):
    """
    Reopen thread - allow join requests again (creator only)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can reopen thread", 403)
        
        if thread.is_open:
            return error_response("Thread is already open", 409)
        
        thread.is_open = True
        db.session.commit()
        
        return success_response("Thread reopened - now accepting join requests")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Reopen thread error: {str(e)}")
        return error_response("Failed to reopen thread")


@threads_bp.route("/threads/<int:thread_id>", methods=["PATCH"])
@token_required
def update_thread(current_user, thread_id):
    """
    Update thread details (creator only)
    
    Body: {
        "title": "New title",
        "description": "New description",
        "max_members": 15
    }
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can update thread", 403)
        
        data = request.get_json()
        changes = []
        
        if "title" in data:
            new_title = data["title"].strip()
            if len(new_title) >= 5:
                thread.title = new_title
                changes.append("title")
        
        if "description" in data:
            thread.description = data["description"].strip()
            changes.append("description")
        
        if "max_members" in data:
            new_max = data["max_members"]
            # Cannot reduce below current member count
            if new_max >= thread.member_count and new_max <= 50:
                thread.max_members = new_max
                changes.append("max_members")
        
        if changes:
            db.session.commit()
            return success_response(
                "Thread updated",
                data={"changes": changes}
            )
        else:
            return success_response("No changes made")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update thread error: {str(e)}")
        return error_response("Failed to update thread")


@threads_bp.route("/threads/<int:thread_id>", methods=["DELETE"])
@token_required
def delete_thread(current_user, thread_id):
    """
    Delete thread (creator only)
    Cascade deletes all members, messages, requests
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can delete thread", 403)
        
        # Notify all members
        members = ThreadMember.query.filter_by(thread_id=thread_id).all()
        for member in members:
            if member.student_id != current_user.id:
                notification = Notification(
                    user_id=member.student_id,
                    title="Thread deleted",
                    body=f'The thread "{thread.title}" has been deleted',
                    notification_type="thread_deleted",
                    related_type="thread",
                    related_id=thread_id
                )
                db.session.add(notification)
        
        # Delete thread (cascade handles related records)
        db.session.delete(thread)
        db.session.commit()
        
        return success_response("Thread deleted successfully")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Delete thread error: {str(e)}")
        return error_response("Failed to delete thread")


# ============================================================================
# THREAD CHAT/MESSAGES
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/messages", methods=["GET"])
@token_required
def get_thread_messages(current_user, thread_id):
    """
    Get messages in thread (polling endpoint)
    
    Query params:
    - since: ISO timestamp - only return messages after this time
    - limit: Max messages to return (default 50)
    """
    try:
        # Verify membership
        membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if not membership:
            return error_response("You must be a member to view messages", 403)
        
        # Get messages
        query = ThreadMessage.query.filter_by(
            thread_id=thread_id,
            is_deleted=False
        )
        
        # Polling: only get messages after timestamp
        since = request.args.get("since")
        if since:
            try:
                since_dt = datetime.datetime.fromisoformat(since.replace('Z', '+00:00'))
                query = query.filter(ThreadMessage.sent_at > since_dt)
            except ValueError:
                pass
        
        limit = min(request.args.get("limit", 50, type=int), 100)
        
        messages = query.order_by(ThreadMessage.sent_at.asc()).limit(limit).all()
        
        messages_data = []
        for msg in messages:
            sender = User.query.get(msg.sender_id)
            messages_data.append({
                "id": msg.id,
                "text_content": msg.text_content,
                "attachment": msg.attachment,
                "attachment_type": msg.attachment_type,
                "is_edited": msg.is_edited,
                "sent_at": msg.sent_at.isoformat(),
                "edited_at": msg.edited_at.isoformat() if msg.edited_at else None,
                "sender": {
                    "id": sender.id,
                    "username": sender.username,
                    "name": sender.name,
                    "avatar": sender.avatar
                } if sender else None,
                "is_own_message": msg.sender_id == current_user.id
            })
        
        # Update last read timestamp
        membership.last_read_at = datetime.datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "data": {
                "messages": messages_data,
                "count": len(messages_data),
                "has_more": len(messages_data) == limit
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Get thread messages error: {str(e)}")
        return error_response("Failed to load messages")


@threads_bp.route("/threads/<int:thread_id>/messages", methods=["POST"])
@token_required
def send_thread_message(current_user, thread_id):
    """
    Send message in thread
    
    Body: {
        "text_content": "Message text"
    }
    """
    try:
        # Verify membership
        membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if not membership:
            return error_response("You must be a member to send messages", 403)
        
        data = request.get_json()
        text_content = data.get("text_content", "").strip()
        
        if not text_content:
            return error_response("Message text is required")
        
        if len(text_content) > 5000:
            return error_response("Message too long (max 5000 characters)")
        
        # Create message
        new_message = ThreadMessage(
            thread_id=thread_id,
            sender_id=current_user.id,
            text_content=text_content
        )
        
        db.session.add(new_message)
        db.session.flush()
        
        # Detect mentions
        mentioned_users = detect_mentions_in_thread(
            text_content,
            current_user.id,
            thread_id,
            new_message.id
        )
        
        # Update thread activity
        thread = Thread.query.get(thread_id)
        if thread:
            thread.message_count += 1
            thread.last_activity = datetime.datetime.utcnow()
        
        # Update member message count
        membership.messages_sent += 1
        
        db.session.commit()
        
        return success_response(
            "Message sent",
            data={
                "message_id": new_message.id,
                "sent_at": new_message.sent_at.isoformat(),
                "mentioned_users": mentioned_users
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Send message error: {str(e)}")
        return error_response("Failed to send message")


@threads_bp.route("/threads/<int:thread_id>/messages/<int:message_id>", methods=["PATCH"])
@token_required
def edit_thread_message(current_user, thread_id, message_id):
    """
    Edit your own message
    """
    try:
        message = ThreadMessage.query.get(message_id)
        
        if not message:
            return error_response("Message not found", 404)
        
        if message.sender_id != current_user.id:
            return error_response("You can only edit your own messages", 403)
        
        if message.thread_id != thread_id:
            return error_response("Message does not belong to this thread", 400)
        
        data = request.get_json()
        new_text = data.get("text_content", "").strip()
        
        if not new_text:
            return error_response("Message text is required")
        
        message.text_content = new_text
        message.is_edited = True
        message.edited_at = datetime.datetime.utcnow()
        
        # Re-detect mentions
        from models import Mention
        Mention.query.filter_by(
            mentioned_in_type="thread_message",
            mentioned_in_id=message_id
        ).delete()
        
        detect_mentions_in_thread(
            new_text,
            current_user.id,
            thread_id,
            message_id
        )
        
        db.session.commit()
        
        return success_response(
            "Message updated",
            data={"edited_at": message.edited_at.isoformat()}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Edit message error: {str(e)}")
        return error_response("Failed to edit message")


@threads_bp.route("/threads/<int:thread_id>/messages/<int:message_id>", methods=["DELETE"])
@token_required
def delete_thread_message(current_user, thread_id, message_id):
    """
    Delete your own message (soft delete)
    """
    try:
        message = ThreadMessage.query.get(message_id)
        
        if not message:
            return error_response("Message not found", 404)
        
        # Check permission (sender or creator can delete)
        thread = Thread.query.get(thread_id)
        if message.sender_id != current_user.id and thread.creator_id != current_user.id:
            return error_response("You can only delete your own messages", 403)
        
        message.is_deleted = True
        message.text_content = "[deleted]"
        
        thread.message_count = max(0, thread.message_count - 1)
        
        db.session.commit()
        
        return success_response("Message deleted")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Delete message error: {str(e)}")
        return error_response("Failed to delete message")


# ============================================================================
# MY THREADS
# ============================================================================

@threads_bp.route("/threads/my-threads", methods=["GET"])
@token_required
def get_my_threads(current_user):
    """
    Get all threads user is a member of
    """
    try:
        memberships = ThreadMember.query.filter_by(
            student_id=current_user.id
        ).all()
        
        threads_data = []
        for membership in memberships:
            thread = Thread.query.get(membership.thread_id)
            if thread:
                # Count unread messages
                unread_count = 0
                if membership.last_read_at:
                    unread_count = ThreadMessage.query.filter(
                        ThreadMessage.thread_id == thread.id,
                        ThreadMessage.sent_at > membership.last_read_at,
                        ThreadMessage.sender_id != current_user.id,
                        ThreadMessage.is_deleted == False
                    ).count()
                
                threads_data.append({
                    "id": thread.id,
                    "title": thread.title,
                    "member_count": thread.member_count,
                    "message_count": thread.message_count,
                    "is_open": thread.is_open,
                    "is_creator": thread.creator_id == current_user.id,
                    "last_activity": thread.last_activity.isoformat(),
                    "unread_count": unread_count,
                    "your_role": membership.role
                })
        
        # Sort by last activity
        threads_data.sort(key=lambda x: x["last_activity"], reverse=True)
        
        return jsonify({
            "status": "success",
            "data": {
                "threads": threads_data,
                "total": len(threads_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get my threads error: {str(e)}")
        return error_response("Failed to load your threads")


@threads_bp.route("/threads/pending-requests", methods=["GET"])
@token_required
def get_pending_requests(current_user):
    """
    Get all pending join requests for threads you created
    """
    try:
        # Get threads created by user
        created_threads = Thread.query.filter_by(creator_id=current_user.id).all()
        thread_ids = [t.id for t in created_threads]
        
        # Get pending requests for those threads
        requests = ThreadJoinRequest.query.filter(
            ThreadJoinRequest.thread_id.in_(thread_ids),
            ThreadJoinRequest.status == "pending"
        ).all()
        
        requests_data = []
        for req in requests:
            thread = Thread.query.get(req.thread_id)
            requester = User.query.get(req.requester_id)
            
            if thread and requester:
                requests_data.append({
                    "request_id": req.id,
                    "thread": {
                        "id": thread.id,
                        "title": thread.title,
                        "member_count": thread.member_count,
                        "max_members": thread.max_members
                    },
                    "requester": {
                        "id": requester.id,
                        "username": requester.username,
                        "name": requester.name,
                        "avatar": requester.avatar
                    },
                    "message": req.message,
                    "requested_at": req.requested_at.isoformat()
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "pending_requests": requests_data,
                "total": len(requests_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get pending requests error: {str(e)}")
        return error_response("Failed to load pending requests")


@threads_bp.route("/threads/my-requests", methods=["GET"])
@token_required
def get_my_join_requests(current_user):
    """
    Get all join requests YOU sent that are still pending
    """
    try:
        requests = ThreadJoinRequest.query.filter_by(
            requester_id=current_user.id,
            status="pending"
        ).all()
        
        requests_data = []
        for req in requests:
            thread = Thread.query.get(req.thread_id)
            if thread:
                requests_data.append({
                    "request_id": req.id,
                    "thread": {
                        "id": thread.id,
                        "title": thread.title,
                        "member_count": thread.member_count,
                        "max_members": thread.max_members,
                        "is_full": thread.member_count >= thread.max_members
                    },
                    "requested_at": req.requested_at.isoformat()
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "my_requests": requests_data,
                "total": len(requests_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get my requests error: {str(e)}")
        return error_response("Failed to load your requests")


# ============================================================================
# MEMBER ROLE MANAGEMENT
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/members/<int:user_id>/role", methods=["PATCH"])
@token_required
def update_member_role(current_user, thread_id, user_id):
    """
    Update member's role (creator only)
    
    Body: {"role": "moderator"}
    
    Roles: member, moderator
    (creator role cannot be changed)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can change member roles", 403)
        
        member = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=user_id
        ).first()
        
        if not member:
            return error_response("User is not a member", 404)
        
        if member.role == "creator":
            return error_response("Cannot change creator role", 403)
        
        data = request.get_json()
        new_role = data.get("role", "").strip().lower()
        
        if new_role not in ["member", "moderator"]:
            return error_response("Role must be 'member' or 'moderator'")
        
        if member.role == new_role:
            return success_response("No change needed")
        
        member.role = new_role
        db.session.commit()
        
        # Notify user
        user = User.query.get(user_id)
        if user:
            notification = Notification(
                user_id=user_id,
                title=f"You are now a {new_role} in a thread",
                body=f'Thread: "{thread.title}"',
                notification_type="thread_role_updated",
                related_type="thread",
                related_id=thread_id
            )
            db.session.add(notification)
            db.session.commit()
        
        return success_response(
            f"Member role updated to {new_role}",
            data={
                "user_id": user_id,
                "new_role": new_role
            }
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update member role error: {str(e)}")
        return error_response("Failed to update role")


# ============================================================================
# THREAD STATISTICS
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/stats", methods=["GET"])
@token_required
def get_thread_stats(current_user, thread_id):
    """
    Get thread statistics (members only)
    
    Returns:
    - Member activity breakdown
    - Message frequency
    - Most active members
    """
    try:
        # Verify membership
        membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if not membership:
            return error_response("You must be a member to view stats", 403)
        
        thread = Thread.query.get(thread_id)
        if not thread:
            return error_response("Thread not found", 404)
        
        # Get all members with their stats
        members = ThreadMember.query.filter_by(thread_id=thread_id).all()
        
        members_stats = []
        for member in members:
            user = User.query.get(member.student_id)
            if user:
                members_stats.append({
                    "user": {
                        "id": user.id,
                        "username": user.username,
                        "name": user.name,
                        "avatar": user.avatar
                    },
                    "role": member.role,
                    "messages_sent": member.messages_sent,
                    "joined_at": member.joined_at.isoformat()
                })
        
        # Sort by most active
        members_stats.sort(key=lambda x: x["messages_sent"], reverse=True)
        
        # Calculate thread age
        thread_age = (datetime.datetime.utcnow() - thread.created_at).days
        
        # Average messages per day
        avg_messages_per_day = thread.message_count / max(thread_age, 1)
        
        return jsonify({
            "status": "success",
            "data": {
                "thread": {
                    "id": thread.id,
                    "title": thread.title,
                    "created_at": thread.created_at.isoformat(),
                    "age_days": thread_age
                },
                "stats": {
                    "total_members": thread.member_count,
                    "total_messages": thread.message_count,
                    "avg_messages_per_day": round(avg_messages_per_day, 2),
                    "last_activity": thread.last_activity.isoformat()
                },
                "members": members_stats,
                "most_active": members_stats[0] if members_stats else None
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get thread stats error: {str(e)}")
        return error_response("Failed to load stats")


# ============================================================================
# THREAD SETTINGS
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/settings", methods=["GET"])
@token_required
def get_thread_settings(current_user, thread_id):
    """
    Get thread settings (creator only)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can view settings", 403)
        
        return jsonify({
            "status": "success",
            "data": {
                "settings": {
                    "is_open": thread.is_open,
                    "max_members": thread.max_members,
                    "requires_approval": thread.requires_approval,
                    "current_members": thread.member_count
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get thread settings error: {str(e)}")
        return error_response("Failed to load settings")


@threads_bp.route("/threads/<int:thread_id>/settings", methods=["PATCH"])
@token_required
def update_thread_settings(current_user, thread_id):
    """
    Update thread settings (creator only)
    
    Body: {
        "requires_approval": false,
        "max_members": 20
    }
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only creator can update settings", 403)
        
        data = request.get_json()
        changes = []
        
        if "requires_approval" in data:
            thread.requires_approval = bool(data["requires_approval"])
            changes.append("requires_approval")
        
        if "max_members" in data:
            new_max = data["max_members"]
            if new_max >= thread.member_count and new_max <= 50:
                thread.max_members = new_max
                changes.append("max_members")
            else:
                return error_response("Invalid max_members value")
        
        if changes:
            db.session.commit()
            return success_response(
                "Settings updated",
                data={"changes": changes}
            )
        else:
            return success_response("No changes made")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Update settings error: {str(e)}")
        return error_response("Failed to update settings")


# ============================================================================
# CANCEL JOIN REQUEST
# ============================================================================

@threads_bp.route("/threads/requests/<int:request_id>/cancel", methods=["DELETE"])
@token_required
def cancel_join_request(current_user, request_id):
    """
    Cancel your own pending join request
    """
    try:
        request_obj = ThreadJoinRequest.query.get(request_id)
        
        if not request_obj:
            return error_response("Request not found", 404)
        
        if request_obj.requester_id != current_user.id:
            return error_response("You can only cancel your own requests", 403)
        
        if request_obj.status != "pending":
            return error_response("Request is no longer pending", 400)
        
        db.session.delete(request_obj)
        db.session.commit()
        
        return success_response("Join request cancelled")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Cancel request error: {str(e)}")
        return error_response("Failed to cancel request")
        
        # Check if user is a member
        membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        is_member = bool(membership)
        is_creator = thread.creator_id == current_user.id
        
        # Check if user has pending request
        pending_request = ThreadJoinRequest.query.filter_by(
            thread_id=thread_id,
            requester_id=current_user.id,
            status="pending"
        ).first()
        
        # Get creator info
        creator = User.query.get(thread.creator_id)
        
        # Get post info if exists
        post = None
        if thread.post_id:
            post_obj = Post.query.get(thread.post_id)
            if post_obj:
                post = {
                    "id": post_obj.id,
                    "title": post_obj.title,
                    "post_type": post_obj.post_type
                }
        
        # Basic thread info (visible to all)
        thread_data = {
            "id": thread.id,
            "title": thread.title,
            "description": thread.description,
            "department": thread.department,
            "tags": thread.tags,
            "is_open": thread.is_open,
            "member_count": thread.member_count,
            "max_members": thread.max_members,
            "is_full": thread.member_count >= thread.max_members,
            "requires_approval": thread.requires_approval,
            "created_at": thread.created_at.isoformat(),
            "last_activity": thread.last_activity.isoformat(),
            "creator": {
                "id": creator.id,
                "username": creator.username,
                "name": creator.name,
                "avatar": creator.avatar
            } if creator else None,
            "post": post,
            "is_standalone": thread.post_id is None
        }
        
        # User's status
        user_status = {
            "is_member": is_member,
            "is_creator": is_creator,
            "has_pending_request": bool(pending_request),
            "can_join": not is_member and thread.is_open and thread.member_count < thread.max_members
        }
        
        # If user is member, show full details
        if is_member:
            # Get all members
            members = ThreadMember.query.filter_by(thread_id=thread_id).all()
            members_data = []
            
            for member in members:
                user = User.query.get(member.student_id)
                if user:
                    members_data.append({
                        "id": user.id,
                        "username": user.username,
                        "name": user.name,
                        "avatar": user.avatar,
                        "role": member.role,
                        "joined_at": member.joined_at.isoformat(),
                        "messages_sent": member.messages_sent
                    })
            
            thread_data["members"] = members_data
            thread_data["message_count"] = thread.message_count
            
            # If creator, show pending requests
            if is_creator:
                pending_requests = ThreadJoinRequest.query.filter_by(
                    thread_id=thread_id,
                    status="pending"
                ).all()
                
                requests_data = []
                for req in pending_requests:
                    requester = User.query.get(req.requester_id)
                    if requester:
                        requests_data.append({
                            "request_id": req.id,
                            "user": {
                                "id": requester.id,
                                "username": requester.username,
                                "name": requester.name,
                                "avatar": requester.avatar
                            },
                            "message": req.message,
                            "requested_at": req.requested_at.isoformat()
                        })
                
                thread_data["pending_requests"] = requests_data
        
        return jsonify({
            "status": "success",
            "data": {
                "thread": thread_data,
                "user_status": user_status
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get thread error: {str(e)}")
        return error_response("Failed to load thread")


# ============================================================================
# JOIN REQUESTS
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/join", methods=["POST"])
@token_required
def request_join_thread(current_user, thread_id):
    """
    Request to join a thread
    
    Body (optional): {"message": "Why I want to join"}
    
    Includes re-request logic with cooldown
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        # Check if thread is open
        if not thread.is_open:
            return error_response("This thread is closed", 403)
        
        # Check if thread is full
        if thread.member_count >= thread.max_members:
            return error_response("This thread is full", 403)
        
        # Check if already a member
        existing_member = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if existing_member:
            return error_response("You are already a member of this thread", 409)
        
        # Check existing request
        existing_request = ThreadJoinRequest.query.filter_by(
            thread_id=thread_id,
            requester_id=current_user.id
        ).first()
        
        if existing_request:
            if existing_request.status == "pending":
                return error_response("You already have a pending request", 409)
            
            elif existing_request.status == "rejected":
                # Re-request logic with 24-hour cooldown
                cooldown_period = datetime.timedelta(hours=24)
                time_since_rejection = datetime.datetime.utcnow() - existing_request.reviewed_at
                
                if time_since_rejection < cooldown_period:
                    remaining_hours = int((cooldown_period - time_since_rejection).total_seconds() / 3600)
                    return error_response(
                        f"Please wait {remaining_hours} hours before requesting again",
                        429
                    )
                
                # Allow re-request after cooldown
                existing_request.status = "pending"
                existing_request.requested_at = datetime.datetime.utcnow()
                existing_request.reviewed_at = None
                existing_request.reviewed_by = None
                
                data = request.get_json(silent=True) or {}
                existing_request.message = data.get("message", "").strip()
                
                # Notify creator
                notification = Notification(
                    user_id=thread.creator_id,
                    title=f"{current_user.name} wants to join your thread again",
                    body=f'Thread: "{thread.title}"',
                    notification_type="thread_join_request",
                    related_type="thread",
                    related_id=thread_id
                )
                db.session.add(notification)
                
                db.session.commit()
                
                return success_response(
                    "Re-request submitted",
                    data={"request_id": existing_request.id}
                ), 201
            
            elif existing_request.status == "approved":
                return error_response("Your request was already approved", 409)
        
        # Create new join request
        data = request.get_json(silent=True) or {}
        message = data.get("message", "").strip()
        
        join_request = ThreadJoinRequest(
            thread_id=thread_id,
            requester_id=current_user.id,
            message=message if message else None,
            status="pending"
        )
        
        db.session.add(join_request)
        
        # Notify creator
        notification = Notification(
            user_id=thread.creator_id,
            title=f"{current_user.name} wants to join your thread",
            body=f'Thread: "{thread.title}"',
            notification_type="thread_join_request",
            related_type="thread",
            related_id=thread_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Join request sent",
            data={"request_id": join_request.id}
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Join thread error: {str(e)}")
        return error_response("Failed to send join request")

@threads_bp.route("/threads/<int:thread_id>/approve/<int:user_id>", methods=["POST"])
@token_required
def approve_join_request(current_user, thread_id, user_id):
    """
    Approve a join request (creator only)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        # Verify user is creator
        if thread.creator_id != current_user.id:
            return error_response("Only thread creator can approve requests", 403)
        
        # Check if thread is full
        if thread.member_count >= thread.max_members:
            return error_response("Thread is full", 403)
        
        # Find request
        join_request = ThreadJoinRequest.query.filter_by(
            thread_id=thread_id,
            requester_id=user_id,
            status="pending"
        ).first()
        
        if not join_request:
            return error_response("Join request not found", 404)
        
        # Approve request
        join_request.status = "approved"
        join_request.reviewed_at = datetime.datetime.utcnow()
        join_request.reviewed_by = current_user.id
        
        # Add user as member
        new_member = ThreadMember(
            thread_id=thread_id,
            student_id=user_id,
            role="member"
        )
        db.session.add(new_member)
        
        # Update thread member count
        thread.member_count += 1
        thread.last_activity = datetime.datetime.utcnow()
        
        # Notify requester
        notification = Notification(
            user_id=user_id,
            title="Join request approved!",
            body=f'You can now participate in "{thread.title}"',
            notification_type="thread_join_approved",
            related_type="thread",
            related_id=thread_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        requester = User.query.get(user_id)
        
        return success_response(
            "Join request approved",
            data={
                "new_member": {
                    "id": requester.id,
                    "username": requester.username,
                    "name": requester.name
                } if requester else None
            }
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Approve join error: {str(e)}")
        return error_response("Failed to approve request")


@threads_bp.route("/threads/<int:thread_id>/reject/<int:user_id>", methods=["POST"])
@token_required
def reject_join_request(current_user, thread_id, user_id):
    """
    Reject a join request (creator only)
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        if thread.creator_id != current_user.id:
            return error_response("Only thread creator can reject requests", 403)
        
        join_request = ThreadJoinRequest.query.filter_by(
            thread_id=thread_id,
            requester_id=user_id,
            status="pending"
        ).first()
        
        if not join_request:
            return error_response("Join request not found", 404)
        
        join_request.status = "rejected"
        join_request.reviewed_at = datetime.datetime.utcnow()
        join_request.reviewed_by = current_user.id
        
        db.session.commit()
        
        return success_response("Join request rejected")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Reject join error: {str(e)}")
        return error_response("Failed to reject request")


# ============================================================================
# MANUAL INVITES (Creator can invite users directly)
# ============================================================================

@threads_bp.route("/threads/<int:thread_id>/invite/<int:user_id>", methods=["POST"])
@token_required
def invite_to_thread(current_user, thread_id, user_id):
    """
    Manually invite a user to thread (creator only)
    Bypasses approval process
    
    Body (optional): {"message": "Join us!"}
    """
    try:
        thread = Thread.query.get(thread_id)
        
        if not thread:
            return error_response("Thread not found", 404)
        
        # Verify user is creator or moderator
        membership = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=current_user.id
        ).first()
        
        if not membership or membership.role not in ["creator", "moderator"]:
            return error_response("Only thread creator/moderators can invite users", 403)
        
        # Check if thread is full
        if thread.member_count >= thread.max_members:
            return error_response("Thread is full", 403)
        
        # Check if user exists
        invited_user = User.query.get(user_id)
        if not invited_user:
            return error_response("User not found", 404)
        
        # Check if already a member
        existing_member = ThreadMember.query.filter_by(
            thread_id=thread_id,
            student_id=user_id
        ).first()
        
        if existing_member:
            return error_response("User is already a member", 409)
        
        # Check if already has pending invite/request
        existing_request = ThreadJoinRequest.query.filter_by(
            thread_id=thread_id,
            requester_id=user_id,
            status="pending"
        ).first()
        
        if existing_request:
            return error_response("User already has a pending request", 409)
        
        # Create special "invited" join request
        data = request.get_json(silent=True) or {}
        invite_message = data.get("message", "").strip()
        
        invite_request = ThreadJoinRequest(
            thread_id=thread_id,
            requester_id=user_id,  # The invited user
            message=f"[INVITE] {invite_message}" if invite_message else "[INVITED BY CREATOR]",
            status="invited",  # Special status for invites
            reviewed_by=current_user.id
        )
        
        db.session.add(invite_request)
        
        # Notify invited user
        notification = Notification(
            user_id=user_id,
            title=f"{current_user.name} invited you to a thread",
            body=f'Thread: "{thread.title}"',
            notification_type="thread_invite",
            related_type="thread",
            related_id=thread_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Invitation sent",
            data={
                "invited_user": {
                    "id": invited_user.id,
                    "username": invited_user.username,
                    "name": invited_user.name
                }
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Invite to thread error: {str(e)}")
        return error_response("Failed to send invitation")


@threads_bp.route("/threads/invites", methods=["GET"])
@token_required
def get_my_invites(current_user):
    """
    Get all thread invites for current user
    """
    try:
        invites = ThreadJoinRequest.query.filter_by(
            requester_id=current_user.id,
            status="invited"
        ).all()
        
        invites_data = []
        for invite in invites:
            thread = Thread.query.get(invite.thread_id)
            if thread:
                creator = User.query.get(thread.creator_id)
                invites_data.append({
                    "invite_id": invite.id,
                    "thread": {
                        "id": thread.id,
                        "title": thread.title,
                        "description": thread.description,
                        "member_count": thread.member_count,
                        "max_members": thread.max_members
                    },
                    "invited_by": {
                        "id": creator.id,
                        "username": creator.username,
                        "name": creator.name
                    } if creator else None,
                    "message": invite.message,
                    "requested_at": invite.requested_at.isoformat()
                })
        
        return jsonify({
            "status": "success",
            "data": {
                "invites": invites_data,
                "total": len(invites_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get invites error: {str(e)}")
        return error_response("Failed to load invites")


@threads_bp.route("/threads/invites/<int:invite_id>/accept", methods=["POST"])
@token_required
def accept_thread_invite(current_user, invite_id):
    """
    Accept a thread invitation
    """
    try:
        invite = ThreadJoinRequest.query.get(invite_id)
        
        if not invite:
            return error_response("Invite not found", 404)
        
        if invite.requester_id != current_user.id:
            return error_response("This invite is not for you", 403)
        
        if invite.status != "invited":
            return error_response("Invite is no longer valid", 400)
        
        thread = Thread.query.get(invite.thread_id)
        if not thread:
            return error_response("Thread not found", 404)
        
        # Check if thread is full
        if thread.member_count >= thread.max_members:
            return error_response("Thread is now full", 403)
        
        # Accept invite
        invite.status = "approved"
        invite.reviewed_at = datetime.datetime.utcnow()
        
        # Add as member
        new_member = ThreadMember(
            thread_id=thread.id,
            student_id=current_user.id,
            role="member"
        )
        db.session.add(new_member)
        
        thread.member_count += 1
        thread.last_activity = datetime.datetime.utcnow()
        
        # Notify creator
        notification = Notification(
            user_id=thread.creator_id,
            title=f"{current_user.name} accepted your invitation",
            body=f'Thread: "{thread.title}"',
            notification_type="thread_invite_accepted",
            related_type="thread",
            related_id=thread.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Invitation accepted! You're now a member.",
            data={"thread_id": thread.id}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Accept invite error: {str(e)}")
        return error_response("Failed to accept invitation")


@threads_bp.route("/threads/invites/<int:invite_id>/decline", methods=["POST"])
@token_required
def decline_thread_invite(current_user, invite_id):
    """
    Decline a thread invitation
    """
    try:
        invite = ThreadJoinRequest.query.get(invite_id)
        
        if not invite:
            return error_response("Invite not found", 404)
        
        if invite.requester_id != current_user.id:
            return error_response("This invite is not for you", 403)
        
        if invite.status != "invited":
            return error_response("Invite is no longer valid", 400)
        
        invite.status = "rejected"
        invite.reviewed_at = datetime.datetime.utcnow()
        
        db.session.commit()
        
        return success_response("Invitation declined")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Decline invite error: {str(e)}")
        return error_response("Failed to decline invitation")
        
        
       
      

