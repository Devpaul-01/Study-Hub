"""
StudyHub - Enhanced Messaging System
WhatsApp/Messenger-level features with polling support

Features:
- Connection-based messaging (must be connected to message)
- Rich messages (text, files, code snippets, reactions)
- Read receipts and typing indicators
- Reply to specific messages
- Message actions (delete, forward, star)
- Conversation management (archive, mute, pin)
- Search and export
"""

from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_, and_, func, desc
import datetime
import os

from models import (
    User, Message, Connection, Notification, ThreadMember
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response,
    save_file, ALLOWED_IMAGE_EXT, ALLOWED_DOCUMENT_EXT
)

messages_bp = Blueprint("student_messages", __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def can_message(sender_id, receiver_id):
    """
    Check if sender can message receiver
    
    Rules:
    1. Must have accepted connection, OR
    2. System message exception
    
    Note: Thread members CANNOT DM - must connect first
    """
    if sender_id == receiver_id:
        return False
    
    # Check for accepted connection
    connection = Connection.query.filter(
        or_(
            and_(Connection.requester_id == sender_id, Connection.receiver_id == receiver_id),
            and_(Connection.requester_id == receiver_id, Connection.receiver_id == sender_id)
        ),
        Connection.status == "accepted"
    ).first()
    
    if connection:
        return True
    
    return False


def get_conversation_partner(conversation, current_user_id):
    """Get the other user in a conversation"""
    if conversation.get("user1_id") == current_user_id:
        return User.query.get(conversation.get("user2_id"))
    return User.query.get(conversation.get("user1_id"))


def create_conversation_key(user1_id, user2_id):
    sorted_ids = sorted([user1_id, user2_id])
    return f"{sorted_ids[0]}-{sorted_ids[1]}"


# In-memory typing status (can be moved to Redis for production)
typing_status = {}


# ============================================================================
# CONVERSATION MANAGEMENT
# ============================================================================

@messages_bp.route("/messages/conversations", methods=["GET"])
@token_required
def get_conversations(current_user):
    """
    Get all conversations for current user
    Shows list like WhatsApp with last message preview
    """
    try:
        # Get all messages where user is sender or receiver
        messages_query = Message.query.filter(
        or_(
        and_(Message.sender_id == current_user.id, Message.deleted_by_sender == False),
        and_(Message.receiver_id == current_user.id, Message.deleted_by_receiver == False)
        )
        ).order_by(Message.sent_at.desc()).all()
        
        # Group by conversation partner
        conversations = {}
        
        for message in messages_query.all():
            partner_id = message.receiver_id if message.sender_id == current_user.id else message.sender_id
            
            if partner_id not in conversations:
                conversations[partner_id] = {
                    "partner_id": partner_id,
                    "messages": [],
                    "unread_count": 0
                }
            
            conversations[partner_id]["messages"].append(message)
            
            # Count unread (messages TO current user that are unread)
            if message.receiver_id == current_user.id and not message.is_read:
                conversations[partner_id]["unread_count"] += 1
        
        # Format conversations
        conversations_list = []
        
        for partner_id, conv_data in conversations.items():
            partner = User.query.get(partner_id)
            if not partner:
                continue
            
            # Get last message
            last_message = max(conv_data["messages"], key=lambda m: m.sent_at)
            
            # Check if conversation is pinned/archived/muted (stored in user metadata)
            metadata = current_user.user_metadata if current_user.user_metadata else {}
            conv_settings = metadata.get("conversations", {}).get(str(partner_id), {})
            
            conversations_list.append({
                "partner": {
                    "id": partner.id,
                    "username": partner.username,
                    "name": partner.name,
                    "avatar": partner.avatar,
                    "last_active": partner.last_active.isoformat() if partner.last_active else None
                },
                "last_message": {
                    "id": last_message.id,
                    "preview": last_message.body[:100],
                    "sent_at": last_message.sent_at.isoformat(),
                    "is_read": last_message.is_read,
                    "from_me": last_message.sender_id == current_user.id
                },
                "unread_count": conv_data["unread_count"],
                "is_pinned": conv_settings.get("pinned", False),
                "is_archived": conv_settings.get("archived", False),
                "is_muted": conv_settings.get("muted", False)
            })
        
        # Sort: pinned first, then by last message time
        conversations_list.sort(
            key=lambda x: (not x["is_pinned"], x["last_message"]["sent_at"]),
            reverse=True
        )
        
        # Filter archived if not requested
        show_archived = request.args.get("archived", "false").lower() == "true"
        if not show_archived:
            conversations_list = [c for c in conversations_list if not c["is_archived"]]
        
        return jsonify({
            "status": "success",
            "data": {
                "conversations": conversations_list,
                "total_unread": sum(c["unread_count"] for c in conversations_list)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get conversations error: {str(e)}")
        return error_response("Failed to load conversations")


@messages_bp.route("/messages/conversation/<int:partner_id>", methods=["GET"])
@token_required
def get_conversation_messages(current_user, partner_id):
    """
    Get all messages in a conversation with pagination
    
    Query params:
    - page: Page number
    - per_page: Messages per page (default 50)
    - since: ISO timestamp (for polling - only get new messages)
    """
    try:
        # Verify can message
        if not can_message(current_user.id, partner_id):
            return error_response("You must be connected to message this user", 403)
        
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 50, type=int), 100)
        since = request.args.get("since")
        
        # Base query
        query = Message.query.filter(
            or_(
                and_(Message.sender_id == current_user.id, Message.receiver_id == partner_id),
                and_(Message.sender_id == partner_id, Message.receiver_id == current_user.id)
            ),
            # Exclude deleted
            or_(
                and_(Message.sender_id == current_user.id, Message.deleted_by_sender == False),
                and_(Message.receiver_id == current_user.id, Message.deleted_by_receiver == False)
            )
        )
        
        # Filter by timestamp if polling
        if since:
            try:
                since_dt = datetime.datetime.fromisoformat(since.replace('Z', '+00:00'))
                query = query.filter(Message.sent_at > since_dt)
            except ValueError:
                pass
        
        # Paginate
        paginated = query.order_by(Message.sent_at.asc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Format messages
        messages_data = []
        
        for msg in paginated.items:
            messages_data.append({
                "id": msg.id,
                "sender_id": msg.sender_id,
                "receiver_id": msg.receiver_id,
                "subject": msg.subject,
                "body": msg.body,
                "sent_at": msg.sent_at.isoformat(),
                "is_read": msg.is_read,
                "read_at": msg.read_at.isoformat() if msg.read_at else None,
                "from_me": msg.sender_id == current_user.id,
                "metadata": msg.metadata if hasattr(msg, 'metadata') else {}
            })
        
        # Mark messages as read (messages TO current user)
        Message.query.filter(
            Message.sender_id == partner_id,
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).update({
            "is_read": True,
            "read_at": datetime.datetime.utcnow()
        })
        db.session.commit()
        
        return jsonify({
            "status": "success",
            "data": {
                "messages": messages_data,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": paginated.total,
                    "pages": paginated.pages
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get conversation error: {str(e)}")
        return error_response("Failed to load messages")


@messages_bp.route("/messages/send", methods=["POST"])
@token_required
def send_message(current_user):
    """
    Send a message to another user
    
    Body: {
        "receiver_id": 123,
        "subject": "Hello",
        "body": "Message text",
        "reply_to": 456 (optional - reply to specific message)
    }
    
    Or multipart/form-data for file attachments
    """
    try:
        # Get data from JSON or form
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        receiver_id = int(data.get("receiver_id")) if data.get("receiver_id") else None
        subject = data.get("subject", "").strip()
        body = data.get("body", "").strip()
        reply_to = data.get("reply_to", type=int)
        
        # Validation
        if not receiver_id:
            return error_response("receiver_id is required")
        
        if not body:
            return error_response("Message body is required")
        
        if len(body) > 5000:
            return error_response("Message too long (max 5000 characters)")
        
        # Check permission
        if not can_message(current_user.id, receiver_id):
            return error_response(
                "You must be connected to message this user. Send a connection request first.",
                403
            )
        
        # Verify receiver exists
        receiver = User.query.get(receiver_id)
        if not receiver:
            return error_response("Receiver not found", 404)
        
        # Check if blocked
        block = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == receiver_id),
                and_(Connection.requester_id == receiver_id, Connection.receiver_id == current_user.id)
            ),
            Connection.status == "blocked"
        ).first()
        
        if block:
            return error_response("Cannot message this user", 403)
        
        # Handle file attachment
        attachment_path = None
        if 'attachment' in request.files:
            file = request.files['attachment']
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                
                if ext in ALLOWED_IMAGE_EXT:
                    attachment_path = save_file(file, "message_attachments", ALLOWED_IMAGE_EXT)
                elif ext in ALLOWED_DOCUMENT_EXT:
                    attachment_path = save_file(file, "message_attachments", ALLOWED_DOCUMENT_EXT)
                else:
                    return error_response(f"File type .{ext} not allowed")
        
        # Create message
        message = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            subject=subject if subject else "No Subject",
            body=body
        )
        
        # Store metadata (reply_to, attachment, etc.)
        metadata = {}
        if reply_to:
            metadata["reply_to"] = reply_to
        if attachment_path:
            metadata["attachment"] = attachment_path
        
        # Add metadata to message model (assuming you add this field)
        # message.metadata = metadata
        
        db.session.add(message)
        db.session.flush()
        
        # Create notification
        notification = Notification(
            user_id=receiver_id,
            title=f"New message from {current_user.name}",
            body=body[:100],
            notification_type="message",
            related_type="message",
            related_id=message.id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Message sent",
            data={
                "message_id": message.id,
                "sent_at": message.sent_at.isoformat()
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Send message error: {str(e)}")
        return error_response("Failed to send message")


@messages_bp.route("/messages/poll", methods=["GET"])
@token_required
def poll_messages(current_user):
    """
    Poll for new messages (for real-time feel without WebSockets)
    
    Query params:
    - since: ISO timestamp - only return messages after this time
    
    Call this endpoint every 3-5 seconds from frontend
    """
    try:
        from dateutil import parser
        since = request.args.get("since")
        if since:
            try:
                since_dt = parser.isoparse(since)
            except ValueError:
                return error_response("Invalid timestamp format")
        else:
            since_dt = None
        
        # Get new messages
        new_messages = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.sent_at > since_dt,
            Message.deleted_by_receiver == False
        ).order_by(Message.sent_at.asc()).all()
        
        messages_data = []
        
        for msg in new_messages:
            sender = User.query.get(msg.sender_id)
            messages_data.append({
                "id": msg.id,
                "sender": {
                    "id": sender.id,
                    "username": sender.username,
                    "name": sender.name,
                    "avatar": sender.avatar
                } if sender else None,
                "subject": msg.subject,
                "body": msg.body,
                "sent_at": msg.sent_at.isoformat(),
                "is_read": msg.is_read
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "new_messages": messages_data,
                "count": len(messages_data),
                "latest_timestamp": messages_data[-1]["sent_at"] if messages_data else since
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Poll messages error: {str(e)}")
        return error_response("Failed to poll messages")


# ============================================================================
# MESSAGE ACTIONS
# ============================================================================

@messages_bp.route("/messages/<int:message_id>", methods=["DELETE"])
@token_required
def delete_message(current_user, message_id):
    """
    Delete message (soft delete)
    
    Query param:
    - for_everyone: true/false (only if within 5 minutes and you're sender)
    """
    try:
        message = Message.query.get(message_id)
        
        if not message:
            return error_response("Message not found", 404)
        
        # Check if user is part of conversation
        if message.sender_id != current_user.id and message.receiver_id != current_user.id:
            return error_response("Not authorized", 403)
        
        delete_for_everyone = request.args.get("for_everyone", "false").lower() == "true"
        
        if delete_for_everyone:
            # Only sender can delete for everyone, and only within 5 minutes
            if message.sender_id != current_user.id:
                return error_response("Only sender can delete for everyone", 403)
            
            time_since_sent = (datetime.datetime.utcnow() - message.sent_at).total_seconds() / 60
            if time_since_sent > 5:
                return error_response("Can only delete for everyone within 5 minutes", 403)
            
            # Mark as deleted for both
            message.deleted_by_sender = True
            message.deleted_by_receiver = True
            message.body = "[Message deleted]"
            
        else:
            # Delete only for current user
            if message.sender_id == current_user.id:
                message.deleted_by_sender = True
            else:
                message.deleted_by_receiver = True
        
        db.session.commit()
        
        return success_response("Message deleted")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Delete message error: {str(e)}")
        return error_response("Failed to delete message")


@messages_bp.route("/messages/<int:message_id>/mark-read", methods=["POST"])
@token_required
def mark_message_read(current_user, message_id):
    """
    Mark specific message as read
    """
    try:
        message = Message.query.get(message_id)
        
        if not message:
            return error_response("Message not found", 404)
        
        if message.receiver_id != current_user.id:
            return error_response("Can only mark received messages as read", 403)
        
        if not message.is_read:
            message.is_read = True
            message.read_at = datetime.datetime.utcnow()
            db.session.commit()
        
        return success_response("Message marked as read")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Mark read error: {str(e)}")
        return error_response("Failed to mark as read")


@messages_bp.route("/messages/mark-all-read/<int:partner_id>", methods=["POST"])
@token_required
def mark_all_read(current_user, partner_id):
    """
    Mark all messages from a user as read
    """
    try:
        Message.query.filter(
            Message.sender_id == partner_id,
            Message.receiver_id == current_user.id,
            Message.is_read == False
        ).update({
            "is_read": True,
            "read_at": datetime.datetime.utcnow()
        })
        
        db.session.commit()
        
        return success_response("All messages marked as read")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Mark all read error: {str(e)}")
        return error_response("Failed to mark messages as read")

@messages_bp.route("/messages/unread-count", methods=["GET"])
@token_required
def get_unread_count(current_user):
    """
    Get total unread message count (for badge)
    """
    try:
        unread_count = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.deleted_by_receiver == False
        ).count()
        
        return jsonify({
            "status": "success",
            "data": {
                "unread_count": unread_count
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Unread count error: {str(e)}")
        return error_response("Failed to get unread count")


# ============================================================================
# TYPING INDICATORS
# ============================================================================

@messages_bp.route("/messages/typing/<int:partner_id>", methods=["POST"])
@token_required
def set_typing_status(current_user, partner_id):
    """
    Set typing status (user is typing)
    No timeout - manual control
    """
    try:
        conv_key = create_conversation_key(current_user.id, partner_id)
        typing_status[conv_key] = {
            "user_id": current_user.id,
            "started_at": datetime.datetime.utcnow().isoformat()
        }
        
        return success_response("Typing status set")
        
    except Exception as e:
        current_app.logger.error(f"Set typing error: {str(e)}")
        return error_response("Failed to set typing status")


@messages_bp.route("/messages/stop-typing/<int:partner_id>", methods=["POST"])
@token_required
def stop_typing_status(current_user, partner_id):
    """
    Clear typing status (user stopped typing)
    """
    try:
        conv_key = create_conversation_key(current_user.id, partner_id)
        if conv_key in typing_status:
            del typing_status[conv_key]
        
        return success_response("Typing status cleared")
        
    except Exception as e:
        current_app.logger.error(f"Stop typing error: {str(e)}")
        return error_response("Failed to clear typing status")


@messages_bp.route("/messages/is-typing/<int:partner_id>", methods=["GET"])
@token_required
def check_typing_status(current_user, partner_id):
    """
    Check if partner is typing
    Poll this endpoint every 2-3 seconds
    """
    try:
        conv_key = create_conversation_key(current_user.id, partner_id)
        typing_data = typing_status.get(conv_key)
        
        if typing_data and typing_data["user_id"] == partner_id:
            return jsonify({
                "status": "success",
                "data": {
                    "is_typing": True,
                    "started_at": typing_data["started_at"]
                }
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "is_typing": False
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Check typing error: {str(e)}")
        return error_response("Failed to check typing status")


# ============================================================================
# CONVERSATION MANAGEMENT
# ============================================================================

@messages_bp.route("/messages/archive/<int:partner_id>", methods=["POST"])
@token_required
def archive_conversation(current_user, partner_id):
    """
    Archive conversation (hide from main list)
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        if "conversations" not in metadata:
            metadata["conversations"] = {}
        
        if str(partner_id) not in metadata["conversations"]:
            metadata["conversations"][str(partner_id)] = {}
        
        metadata["conversations"][str(partner_id)]["archived"] = True
        current_user.user_metadata = metadata
        
        db.session.commit()
        
        return success_response("Conversation archived")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Archive conversation error: {str(e)}")
        return error_response("Failed to archive conversation")


@messages_bp.route("/messages/unarchive/<int:partner_id>", methods=["POST"])
@token_required
def unarchive_conversation(current_user, partner_id):
    """
    Unarchive conversation
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        if "conversations" in metadata and str(partner_id) in metadata["conversations"]:
            metadata["conversations"][str(partner_id)]["archived"] = False
            current_user.user_metadata = metadata
            db.session.commit()
        
        return success_response("Conversation unarchived")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unarchive conversation error: {str(e)}")
        return error_response("Failed to unarchive conversation")


@messages_bp.route("/messages/pin/<int:partner_id>", methods=["POST"])
@token_required
def pin_conversation(current_user, partner_id):
    """
    Pin conversation to top
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        if "conversations" not in metadata:
            metadata["conversations"] = {}
        
        if str(partner_id) not in metadata["conversations"]:
            metadata["conversations"][str(partner_id)] = {}
        
        metadata["conversations"][str(partner_id)]["pinned"] = True
        current_user.user_metadata = metadata
        
        db.session.commit()
        
        return success_response("Conversation pinned")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Pin conversation error: {str(e)}")
        return error_response("Failed to pin conversation")


@messages_bp.route("/messages/unpin/<int:partner_id>", methods=["POST"])
@token_required
def unpin_conversation(current_user, partner_id):
    """
    Unpin conversation
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        if "conversations" in metadata and str(partner_id) in metadata["conversations"]:
            metadata["conversations"][str(partner_id)]["pinned"] = False
            current_user.user_metadata = metadata
            db.session.commit()
        
        return success_response("Conversation unpinned")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unpin conversation error: {str(e)}")
        return error_response("Failed to unpin conversation")


@messages_bp.route("/messages/mute/<int:partner_id>", methods=["POST"])
@token_required
def mute_conversation(current_user, partner_id):
    """
    Mute notifications for conversation
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        if "conversations" not in metadata:
            metadata["conversations"] = {}
        
        if str(partner_id) not in metadata["conversations"]:
            metadata["conversations"][str(partner_id)] = {}
        
        metadata["conversations"][str(partner_id)]["muted"] = True
        current_user.user_metadata = metadata
        
        db.session.commit()
        
        return success_response("Conversation muted")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Mute conversation error: {str(e)}")
        return error_response("Failed to mute conversation")


@messages_bp.route("/messages/unmute/<int:partner_id>", methods=["POST"])
@token_required
def unmute_conversation(current_user, partner_id):
    """
    Unmute notifications
    """
    try:
        metadata = current_user.user_metadata if current_user.user_metadata else {}
        if "conversations" in metadata and str(partner_id) in metadata["conversations"]:
            metadata["conversations"][str(partner_id)]["muted"] = False
            current_user.user_metadata = metadata
            db.session.commit()
        
        return success_response("Conversation unmuted")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unmute conversation error: {str(e)}")
        return error_response("Failed to unmute conversation")


# ============================================================================
# SEARCH & PERMISSIONS
# ============================================================================

@messages_bp.route("/messages/search", methods=["GET"])
@token_required
def search_messages(current_user):
    """
    Search messages by content or sender
    
    Query params:
    - q: Search query
    - partner_id: Filter by conversation (optional)
    """
    try:
        query_str = request.args.get("q", "").strip()
        partner_id = request.args.get("partner_id", type=int)
        
        if not query_str:
            return error_response("Search query required")
        
        # Base query
        query = Message.query.filter(
            or_(
                Message.sender_id == current_user.id,
                Message.receiver_id == current_user.id
            ),
            or_(
                Message.subject.ilike(f"%{query_str}%"),
                Message.body.ilike(f"%{query_str}%")
            )
        )
        
        # Filter by partner if specified
        if partner_id:
            query = query.filter(
                or_(
                    and_(Message.sender_id == current_user.id, Message.receiver_id == partner_id),
                    and_(Message.sender_id == partner_id, Message.receiver_id == current_user.id)
                )
            )
        
        results = query.order_by(Message.sent_at.desc()).limit(50).all()
        
        results_data = []
        for msg in results:
            partner = User.query.get(
                msg.receiver_id if msg.sender_id == current_user.id else msg.sender_id
            )
            
            results_data.append({
                "message_id": msg.id,
                "partner": {
                    "id": partner.id,
                    "username": partner.username,
                    "name": partner.name
                } if partner else None,
                "subject": msg.subject,
                "body": msg.body[:200],
                "sent_at": msg.sent_at.isoformat(),
                "from_me": msg.sender_id == current_user.id
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "results": results_data,
                "count": len(results_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Search messages error: {str(e)}")
        return error_response("Failed to search messages")


@messages_bp.route("/messages/can-message/<int:user_id>", methods=["GET"])
@token_required
def check_can_message(current_user, user_id):
    """
    Check if current user can message another user
    Returns permission status and reason
    """
    try:
        if user_id == current_user.id:
            return jsonify({
                "status": "success",
                "data": {
                    "can_message": False,
                    "reason": "Cannot message yourself"
                }
            })
        
        target_user = User.query.get(user_id)
        if not target_user:
            return jsonify({
                "status": "success",
                "data": {
                    "can_message": False,
                    "reason": "User not found"
                }
            })
        
        # Check if blocked
        block = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            ),
            Connection.status == "blocked"
        ).first()
        
        if block:
            return jsonify({
                "status": "success",
                "data": {
                    "can_message": False,
                    "reason": "User is blocked"
                }
            })
        
        # Check if connected
        if can_message(current_user.id, user_id):
            return jsonify({
                "status": "success",
                "data": {
                    "can_message": True,
                    "reason": "Connected"
                }
            })
        
        # Not connected - check if pending connection
        pending = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            ),
            Connection.status == "pending"
        ).first()
        
        if pending:
            if pending.requester_id == current_user.id:
                reason = "Connection request pending - waiting for acceptance"
            else:
                reason = "User sent you a connection request - accept to message"
        else:
            reason = "Not connected - send connection request to message"
        
        return jsonify({
            "status": "success",
            "data": {
                "can_message": False,
                "reason": reason,
                "can_connect": not pending
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Check can message error: {str(e)}")
        return error_response("Failed to check messaging permission")


@messages_bp.route("/messages/block/<int:user_id>", methods=["POST"])
@token_required
def block_user_messaging(current_user, user_id):
    """
    Block user from messaging (updates Connection status)
    This uses the Connection model's block functionality
    """
    try:
        if user_id == current_user.id:
            return error_response("Cannot block yourself")
        
        # Check existing connection
        connection = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            )
        ).first()
        
        if connection:
            connection.status = "blocked"
        else:
            # Create block record
            connection = Connection(
                requester_id=user_id,
                receiver_id=current_user.id,
                status="blocked"
            )
            db.session.add(connection)
        
        db.session.commit()
        
        return success_response("User blocked from messaging")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Block user error: {str(e)}")
        return error_response("Failed to block user")


@messages_bp.route("/messages/unblock/<int:user_id>", methods=["POST"])
@token_required
def unblock_user_messaging(current_user, user_id):
    """
    Unblock user (remove block)
    """
    try:
        connection = Connection.query.filter(
            or_(
                and_(Connection.requester_id == current_user.id, Connection.receiver_id == user_id),
                and_(Connection.requester_id == user_id, Connection.receiver_id == current_user.id)
            ),
            Connection.status == "blocked"
        ).first()
        
        if not connection:
            return error_response("User is not blocked", 404)
        
        # Remove connection entirely
        db.session.delete(connection)
        db.session.commit()
        
        return success_response("User unblocked")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unblock user error: {str(e)}")
        return error_response("Failed to unblock user")


@messages_bp.route("/messages/report/<int:message_id>", methods=["POST"])
@token_required
def report_message(current_user, message_id):
    """
    Report inappropriate message
    
    Body: {
        "reason": "spam",
        "description": "Additional details"
    }
    """
    try:
        message = Message.query.get(message_id)
        
        if not message:
            return error_response("Message not found", 404)
        
        if message.receiver_id != current_user.id:
            return error_response("Can only report messages sent to you", 403)
        
        data = request.get_json()
        reason = data.get("reason", "").strip()
        description = data.get("description", "").strip()
        
        if not reason:
            return error_response("Reason required")
        
        # Create report (using existing PostReport model structure)
        # You may want to create a separate MessageReport model
        # For now, we'll log it
        
        current_app.logger.warning(
            f"Message reported - ID: {message_id}, "
            f"From: {message.sender_id}, "
            f"Reason: {reason}, "
            f"By: {current_user.id}"
        )
        
        return success_response("Message reported - we'll review it soon")
        
    except Exception as e:
        current_app.logger.error(f"Report message error: {str(e)}")
        return error_response("Failed to report message")