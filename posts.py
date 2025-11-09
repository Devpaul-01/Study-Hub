"""
StudyHub - Complete Post System
Create, edit, interact with posts - the core of student collaboration
Includes: CRUD, mentions, reactions, comments, bookmarks, spam prevention
"""

from flask import Blueprint, request, jsonify, current_app
from werkzeug.utils import secure_filename
from sqlalchemy import or_, and_, func, desc
import datetime
import re
import os

from models import (
    User, StudentProfile, Post, Comment, PostLike, PostReaction,
    Bookmark, PostFollow, Mention, Notification, ReputationHistory,
    UserActivity, PostView, Connection, CommentLike
)
from extensions import db
from routes.student.helpers import (
    token_required, success_response, error_response,
    save_file, ALLOWED_IMAGE_EXT, ALLOWED_DOCUMENT_EXT
)

posts_bp = Blueprint("student_posts", __name__)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def detect_and_create_mentions(text_content, created_by_id, content_type, content_id):
    """
    Detect @username mentions in text and create Mention records
    Also creates notifications for mentioned users
    
    Args:
        text_content: Text to scan for mentions
        created_by_id: ID of user who created the content
        content_type: "post", "comment", or "thread_message"
        content_id: ID of the content (post_id, comment_id, etc)
    """
    if not text_content:
        return []
    
    # Regex pattern to match @username (alphanumeric + underscore)
    mention_pattern = r'@([a-zA-Z0-9_]{3,20})'
    matches = re.finditer(mention_pattern, text_content)
    
    mentioned_users = []
    creator = User.query.get(created_by_id)
    
    for match in matches:
        username = match.group(1).lower()
        
        # Find user
        mentioned_user = User.query.filter_by(username=username).first()
        
        if mentioned_user and mentioned_user.id != created_by_id:
            # Check if mention already exists (prevent duplicates)
            existing_mention = Mention.query.filter_by(
                mentioned_in_type=content_type,
                mentioned_in_id=content_id,
                mentioned_user_id=mentioned_user.id,
                mentioned_by_user_id=created_by_id
            ).first()
            
            if not existing_mention:
                # Create mention record
                mention = Mention(
                    mentioned_in_type=content_type,
                    mentioned_in_id=content_id,
                    mentioned_user_id=mentioned_user.id,
                    mentioned_by_user_id=created_by_id
                )
                db.session.add(mention)
                
                # Create notification
                content_link = f"{content_type}/{content_id}"
                notification = Notification(
                    user_id=mentioned_user.id,
                    title=f"{creator.name} mentioned you",
                    body=f"{creator.name} mentioned you in a {content_type}",
                    notification_type="mention",
                    related_type=content_type,
                    related_id=content_id
                )
                db.session.add(notification)
                
                mentioned_users.append(mentioned_user.id)
    
    return mentioned_users


def check_spam(user_id, content_type="post"):
    """
    Simple spam detection - rate limiting
    
    Returns: (is_spam: bool, reason: str)
    """
    now = datetime.datetime.utcnow()
    hour_ago = now - datetime.timedelta(hours=1)
    
    # Check posts in last hour
    if content_type == "post":
        recent_posts = Post.query.filter(
            Post.student_id == user_id,
            Post.posted_at >= hour_ago
        ).count()
        
        if recent_posts >= 10:  # Max 10 posts per hour
            return True, "Too many posts in short time"
    
    # Check comments in last hour
    elif content_type == "comment":
        recent_comments = Comment.query.filter(
            Comment.student_id == user_id,
            Comment.posted_at >= hour_ago
        ).count()
        
        if recent_comments >= 30:  # Max 30 comments per hour
            return True, "Too many comments in short time"
    
    return False, None


def update_user_activity(user_id, activity_type):
    """
    Update or create daily activity record for user
    Used for activity heatmap and streak tracking
    """
    today = datetime.date.today()
    
    activity = UserActivity.query.filter_by(
        user_id=user_id,
        activity_date=today
    ).first()
    
    if not activity:
        activity = UserActivity(
            user_id=user_id,
            activity_date=today
        )
        db.session.add(activity)
    
    # Increment counters
    if activity_type == "post":
        activity.posts_created += 1
        activity.activity_score += 5
    elif activity_type == "comment":
        activity.comments_created += 1
        activity.activity_score += 2
    
    return activity


# ============================================================================
# POST CRUD OPERATIONS
# ============================================================================

@posts_bp.route("/posts/create", methods=["POST"])
@token_required
def create_post(current_user):
    """
    Create a new post
    
    Supports:
    - Text content
    - File attachments (images, videos, documents)
    - Tags for discovery
    - Thread collaboration toggle
    - @mentions detection
    
    Body (multipart/form-data or JSON):
    - title: Post title (required)
    - text_content: Post body
    - post_type: question, discussion, announcement, resource, problem
    - department: Department tag
    - tags: JSON array of tags
    - thread_enabled: Boolean
    - resource: File upload (optional)
    """
    try:
        # Spam check
        is_spam, spam_reason = check_spam(current_user.id, "post")
        if is_spam:
            return error_response(f"Rate limit exceeded: {spam_reason}", 429)
        
        # Get data (support both JSON and form data)
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        # Validation
        title = data.get("title", "").strip()
        if not title:
            return error_response("Title is required")
        
        if len(title) < 5:
            return error_response("Title too short (minimum 5 characters)")
        
        if len(title) > 200:
            return error_response("Title too long (maximum 200 characters)")
        
        text_content = data.get("text_content", "").strip()
        post_type = data.get("post_type", "discussion")
        
        # Validate post type
        valid_types = ["question", "discussion", "announcement", "resource", "problem"]
        if post_type not in valid_types:
            return error_response(f"Invalid post type. Must be one of: {', '.join(valid_types)}")
        
        # Get department from profile
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        department = data.get("department", profile.department if profile else None)
        
        # Parse tags
        tags = data.get("tags")
        if isinstance(tags, str):
            try:
                import json
                tags = json.loads(tags)
            except:
                tags = [t.strip() for t in tags.split(",") if t.strip()]
        elif not isinstance(tags, list):
            tags = []
        
        # Limit tags
        tags = tags[:5] if tags else []
        
        # Thread enabled (announcements cannot have threads)
        thread_enabled = data.get("thread_enabled", "false").lower() in ['true', '1', 'yes']
        if post_type == "announcement":
            thread_enabled = False
        
        # Handle file upload
        resource_path = None
        resource_type = None
        
        if 'resource' in request.files:
            file = request.files['resource']
            if file and file.filename:
                # Determine file type
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                
                if ext in ALLOWED_IMAGE_EXT:
                    resource_path = save_file(file, "post_images", ALLOWED_IMAGE_EXT)
                    resource_type = "image"
                elif ext in ['mp4', 'mov', 'avi', 'webm']:
                    resource_path = save_file(file, "post_videos", ['mp4', 'mov', 'avi', 'webm'])
                    resource_type = "video"
                elif ext in ALLOWED_DOCUMENT_EXT:
                    resource_path = save_file(file, "post_documents", ALLOWED_DOCUMENT_EXT)
                    resource_type = "document"
                else:
                    return error_response(f"Unsupported file type: {ext}")
        
        # Create post
        new_post = Post(
            student_id=current_user.id,
            title=title,
            text_content=text_content,
            post_type=post_type,
            department=department,
            tags=tags,
            thread_enabled=thread_enabled,
            resource=resource_path,
            resource_type=resource_type
        )
        
        db.session.add(new_post)
        db.session.flush()  # Get post ID
        
        # Detect mentions
        mentioned_users = detect_and_create_mentions(
            text_content,
            current_user.id,
            "post",
            new_post.id
        )
        
        # Update user stats
        current_user.total_posts += 1
        
        # Update activity
        update_user_activity(current_user.id, "post")
        
        db.session.commit()
        
        return success_response(
            "Post created successfully!",
            data={
                "post": {
                    "id": new_post.id,
                    "title": new_post.title,
                    "post_type": new_post.post_type,
                    "thread_enabled": new_post.thread_enabled,
                    "posted_at": new_post.posted_at.isoformat()
                },
                "mentioned_users": mentioned_users
            }
        ), 201
        
    except ValueError as e:
        db.session.rollback()
        return error_response(str(e))
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Create post error: {str(e)}")
        return error_response("Failed to create post")


@posts_bp.route("/posts/<int:post_id>", methods=["GET"])
@token_required
def get_post(current_user, post_id):
    """
    Get single post with full details
    
    Includes:
    - Post content
    - Author info
    - Like/dislike/reaction counts
    - Your interaction status
    - Top comments (paginated separately)
    """
    try:
        post = Post.query.get(post_id)
        
        if not post:
            return error_response("Post not found", 404)
        
        # Increment view count (once per user per day)
        today = datetime.date.today()
        existing_view = PostView.query.filter_by(
            post_id=post_id,
            viewer_id=current_user.id,
            view_date=today
        ).first()
        
        if not existing_view:
            view = PostView(
                post_id=post_id,
                viewer_id=current_user.id,
                view_date=today
            )
            db.session.add(view)
            post.views += 1
            db.session.commit()
        
        # Get author info
        author = User.query.get(post.student_id)
        author_profile = StudentProfile.query.filter_by(user_id=author.id).first() if author else None
        
        # Check user's interactions
        user_like = PostLike.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        user_reaction = PostReaction.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        user_bookmark = Bookmark.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        user_following = PostFollow.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        # Get reaction breakdown
        reactions = db.session.query(
            PostReaction.reaction_type,
            func.count(PostReaction.id).label('count')
        ).filter(
            PostReaction.post_id == post_id
        ).group_by(PostReaction.reaction_type).all()
        
        reaction_counts = {r[0]: r[1] for r in reactions}
        
        # Check if user is author
        is_author = post.student_id == current_user.id
        
        # Check connection with author (for privacy)
        connection_status = "none"
        if author and author.id != current_user.id:
            connection = Connection.query.filter(
                or_(
                    and_(Connection.requester_id == current_user.id, Connection.receiver_id == author.id),
                    and_(Connection.requester_id == author.id, Connection.receiver_id == current_user.id)
                ),
                Connection.status == "accepted"
            ).first()
            if connection:
                connection_status = "connected"
        
        return jsonify({
            "status": "success",
            "data": {
                "post": {
                    "id": post.id,
                    "title": post.title,
                    "text_content": post.text_content,
                    "post_type": post.post_type,
                    "department": post.department,
                    "tags": post.tags,
                    "resource": post.resource,
                    "resource_type": post.resource_type,
                    "thread_enabled": post.thread_enabled,
                    "is_solved": post.is_solved,
                    "is_pinned": post.is_pinned,
                    "is_locked": post.is_locked,
                    "posted_at": post.posted_at.isoformat(),
                    "edited_at": post.edited_at.isoformat() if post.edited_at else None,
                    "solved_at": post.solved_at.isoformat() if post.solved_at else None
                },
                "stats": {
                    "likes_count": post.likes_count,
                    "dislikes_count": post.dislikes_count,
                    "comments_count": post.comments_count,
                    "views": post.views,
                    "reactions": reaction_counts
                },
                "author": {
                    "id": author.id,
                    "username": author.username,
                    "name": author.name,
                    "avatar": author.avatar,
                    "reputation": author.reputation,
                    "reputation_level": author.reputation_level,
                    "department": author_profile.department if author_profile else None
                } if author else None,
                "user_interaction": {
                    "liked": user_like.like_type if user_like else None,
                    "reaction": user_reaction.reaction_type if user_reaction else None,
                    "bookmarked": bool(user_bookmark),
                    "following": bool(user_following),
                    "is_author": is_author
                },
                "permissions": {
                    "can_edit": is_author,
                    "can_delete": is_author,
                    "can_mark_solved": is_author and post.post_type in ["question", "problem"],
                    "can_comment": not post.is_locked,
                    "connection_with_author": connection_status
                }
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Get post error: {str(e)}")
        return error_response("Failed to load post")


@posts_bp.route("/posts/<int:post_id>/edit", methods=["PATCH"])
@token_required
def edit_post(current_user, post_id):
    """
    Edit your own post
    
    Can update: title, text_content, tags, thread_enabled
    Cannot change: post_type, department (for integrity)
    """
    try:
        post = Post.query.get(post_id)
        
        if not post:
            return error_response("Post not found", 404)
        
        # Verify ownership
        if post.student_id != current_user.id:
            return error_response("You can only edit your own posts", 403)
        
        data = request.get_json()
        changes = []
        
        # Update title
        if "title" in data:
            new_title = data["title"].strip()
            if len(new_title) < 5:
                return error_response("Title too short")
            if new_title != post.title:
                post.title = new_title
                changes.append("title")
        
        # Update content
        if "text_content" in data:
            new_content = data["text_content"].strip()
            if new_content != post.text_content:
                post.text_content = new_content
                changes.append("content")
                
                # Re-detect mentions (delete old, create new)
                Mention.query.filter_by(
                    mentioned_in_type="post",
                    mentioned_in_id=post_id
                ).delete()
                
                detect_and_create_mentions(
                    new_content,
                    current_user.id,
                    "post",
                    post_id
                )
        
        # Update tags
        if "tags" in data:
            new_tags = data["tags"]
            if isinstance(new_tags, list):
                post.tags = new_tags[:5]
                changes.append("tags")
        
        # Update thread enabled (only if no threads exist yet)
        if "thread_enabled" in data:
            if post.threads.count() == 0:  # No threads created yet
                post.thread_enabled = bool(data["thread_enabled"])
                changes.append("thread_enabled")
        
        if changes:
            post.edited_at = datetime.datetime.utcnow()
            db.session.commit()
            
            return success_response(
                "Post updated successfully",
                data={
                    "changes": changes,
                    "edited_at": post.edited_at.isoformat()
                }
            )
        else:
            return success_response("No changes made")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Edit post error: {str(e)}")
        return error_response("Failed to update post")


@posts_bp.route("/posts/<int:post_id>", methods=["DELETE"])
@token_required
def delete_post(current_user, post_id):
    """
    Delete your own post
    
    Cascade deletes:
    - All comments
    - All reactions/likes
    - All bookmarks
    - Associated threads
    """
    try:
        post = Post.query.get(post_id)
        
        if not post:
            return error_response("Post not found", 404)
        
        # Verify ownership
        if post.student_id != current_user.id:
            return error_response("You can only delete your own posts", 403)
        
        # Delete associated file if exists
        if post.resource:
            try:
                file_path = os.path.join(
                    current_app.config['UPLOAD_FOLDER'],
                    f"post_{post.resource_type}s",
                    post.resource
                )
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                current_app.logger.warning(f"Failed to delete file: {str(e)}")
        
        
        # Delete post (cascade will handle related records)
        db.session.delete(post)
        
        # Update user stats
        if current_user.total_posts > 0:
            current_user.total_posts -= 1
        
        db.session.commit()
        
        return success_response("Post deleted successfully")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Delete post error: {str(e)}")
        return error_response("Failed to delete post")


# ============================================================================
# POST INTERACTIONS - Likes, Reactions, Bookmarks
# ============================================================================

@posts_bp.route("/posts/<int:post_id>/like", methods=["POST"])
@token_required
def like_post(current_user, post_id):
    """
    Like or dislike a post
    
    Body: {"type": "like"} or {"type": "dislike"}
    
    If already liked/disliked with same type → Remove
    If liked/disliked with different type → Switch
    """
    try:
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        data = request.get_json()
        like_type = data.get("type", "like")
        
        if like_type not in ["like", "dislike"]:
            return error_response("Type must be 'like' or 'dislike'")
        
        # Check existing
        existing = PostLike.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        if existing:
            if existing.like_type == like_type:
                # Remove like/dislike
                db.session.delete(existing)
                
                if like_type == "like":
                    post.likes_count = max(0, post.likes_count - 1)
                else:
                    post.dislikes_count = max(0, post.dislikes_count - 1)
                
                db.session.commit()
                return success_response(f"Post {like_type} removed")
            else:
                # Switch like to dislike or vice versa
                old_type = existing.like_type
                existing.like_type = like_type
                existing.created_at = datetime.datetime.utcnow()
                
                if like_type == "like":
                    post.likes_count += 1
                    post.dislikes_count = max(0, post.dislikes_count - 1)
                else:
                    post.dislikes_count += 1
                    post.likes_count = max(0, post.likes_count - 1)
                
                db.session.commit()
                return success_response(f"Changed from {old_type} to {like_type}")
        else:
            # Create new like/dislike
            new_like = PostLike(
                post_id=post_id,
                student_id=current_user.id,
                like_type=like_type
            )
            db.session.add(new_like)
            
            if like_type == "like":
                post.likes_count += 1
                
                # Notify author (if not self-like)
                if post.student_id != current_user.id:
                    notification = Notification(
                        user_id=post.student_id,
                        title=f"{current_user.name} liked your post",
                        body=f'"{post.title}"',
                        notification_type="like",
                        related_type="post",
                        related_id=post_id
                    )
                    db.session.add(notification)
            else:
                post.dislikes_count += 1
            
            db.session.commit()
            return success_response(f"Post {like_type}d successfully"), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Like post error: {str(e)}")
        return error_response("Failed to process like")


@posts_bp.route("/posts/<int:post_id>/react", methods=["POST"])
@token_required
def react_to_post(current_user, post_id):
    """
    Add emoji reaction to post
    
    Body: {"reaction": "helpful"}
    
    Reaction types: like, love, laugh, wow, helpful, fire
    One reaction per user per post (can change)
    """
    try:
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        data = request.get_json()
        reaction_type = data.get("reaction", "").strip().lower()
        
        valid_reactions = ["like", "love", "laugh", "wow", "helpful", "fire"]
        if reaction_type not in valid_reactions:
            return error_response(f"Invalid reaction. Must be one of: {', '.join(valid_reactions)}")
        
        # Check existing
        existing = PostReaction.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        if existing:
            if existing.reaction_type == reaction_type:
                # Remove reaction
                db.session.delete(existing)
                db.session.commit()
                return success_response("Reaction removed")
            else:
                # Change reaction
                old_type = existing.reaction_type
                existing.reaction_type = reaction_type
                existing.reacted_at = datetime.datetime.utcnow()
                db.session.commit()
                return success_response(f"Changed reaction from {old_type} to {reaction_type}")
        else:
            # Add new reaction
            new_reaction = PostReaction(
                post_id=post_id,
                student_id=current_user.id,
                reaction_type=reaction_type
            )
            db.session.add(new_reaction)
            
            # If "helpful" reaction, update author's helpful count
            if reaction_type == "helpful" and post.student_id != current_user.id:
                author = User.query.get(post.student_id)
                if author:
                    author.total_helpful += 1
                    
                    # Add reputation
                    author.reputation += 5
                    author.update_reputation_level()
                    
                    # Log reputation change
                    rep_log = ReputationHistory(
                        user_id=author.id,
                        action="post_marked_helpful",
                        points_change=5,
                        related_type="post",
                        related_id=post_id,
                        reputation_before=author.reputation - 5,
                        reputation_after=author.reputation
                    )
                    db.session.add(rep_log)
                    
                    # Notify author
                    notification = Notification(
                        user_id=author.id,
                        title=f"{current_user.name} found your post helpful!",
                        body=f'"{post.title}" (+5 reputation)',
                        notification_type="helpful",
                        related_type="post",
                        related_id=post_id
                    )
                    db.session.add(notification)
            
            db.session.commit()
            return success_response(f"Reacted with {reaction_type}"), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"React to post error: {str(e)}")
        return error_response("Failed to add reaction")


@posts_bp.route("/posts/<int:post_id>/bookmark", methods=["POST"])
@token_required
def bookmark_post(current_user, post_id):
    """
    Bookmark post for later
    
    Body (optional): {
        "folder": "Exam Prep",
        "notes": "Important for finals"
    }
    """
    try:
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        # Check if already bookmarked
        existing = Bookmark.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        if existing:
            return error_response("Post already bookmarked", 409)
        
        data = request.get_json(silent=True) or {}
        folder = data.get("folder", "Saved").strip()
        notes = data.get("notes", "").strip()
        
        bookmark = Bookmark(
            post_id=post_id,
            student_id=current_user.id,
            folder=folder,
            notes=notes if notes else None
        )
        db.session.add(bookmark)
        
        # Increment bookmark count on post
        post.bookmarks += 1
        
        db.session.commit()
        
        return success_response(
            "Post bookmarked",
            data={
                "bookmark_id": bookmark.id,
                "folder": folder
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Bookmark post error: {str(e)}")
        return error_response("Failed to bookmark post")


@posts_bp.route("/posts/<int:post_id>/bookmark", methods=["DELETE"])
@token_required
def unbookmark_post(current_user, post_id):
    """
    Remove bookmark from post
    """
    try:
        bookmark = Bookmark.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        if not bookmark:
            return error_response("Bookmark not found", 404)
        
        db.session.delete(bookmark)
        
        # Decrement count
        post = Post.query.get(post_id)
        if post and post.bookmarks > 0:
            post.bookmarks -= 1
        
        db.session.commit()
        
        return success_response("Bookmark removed")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unbookmark error: {str(e)}")
        return error_response("Failed to remove bookmark")


@posts_bp.route("/posts/<int:post_id>/follow", methods=["POST"])
@token_required
def follow_post(current_user, post_id):
    """
    Follow post to get notifications of new activity
    """
    try:
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        existing = PostFollow.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        if existing:
            return error_response("Already following this post", 409)
        
        follow = PostFollow(
            post_id=post_id,
            student_id=current_user.id
        )
        db.session.add(follow)
        db.session.commit()
        
        return success_response("Now following post"), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Follow post error: {str(e)}")
        return error_response("Failed to follow post")


@posts_bp.route("/posts/<int:post_id>/follow", methods=["DELETE"])
@token_required
def unfollow_post(current_user, post_id):
    """
    Unfollow post (stop notifications)
    """
    try:
        follow = PostFollow.query.filter_by(
            post_id=post_id,
            student_id=current_user.id
        ).first()
        
        if not follow:
            return error_response("Not following this post", 404)
        
        db.session.delete(follow)
        db.session.commit()
        
        return success_response("Unfollowed post")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unfollow post error: {str(e)}")
        return error_response("Failed to unfollow post")


# ============================================================================
# MARK AS SOLVED (For Questions/Problems)
# ============================================================================

@posts_bp.route("/posts/<int:post_id>/mark-solved", methods=["POST"])
@token_required
def mark_solved(current_user, post_id):
    """
    Mark question/problem as solved
    Only post author can do this
    
    Body (optional): {"comment_id": 123}  # Mark specific comment as solution
    """
    try:
        post = Post.query.get(post_id)
        
        if not post:
            return error_response("Post not found", 404)
        
        if post.student_id != current_user.id:
            return error_response("Only post author can mark as solved", 403)
        
        if post.post_type not in ["question", "problem"]:
            return error_response("Only questions and problems can be marked as solved")
        
        if post.is_solved:
            return error_response("Post already marked as solved", 409)
        
        post.is_solved = True
        post.solved_at = datetime.datetime.utcnow()
        
        # If specific comment marked as solution
        data = request.get_json(silent=True) or {}
        comment_id = data.get("comment_id")
        
        if comment_id:
            comment = Comment.query.get(comment_id)
            if comment and comment.post_id == post_id:
                comment.is_solution = True
                
                # Reward the commenter with reputation
                commenter = User.query.get(comment.student_id)
                if commenter and commenter.id != current_user.id:
                    commenter.reputation += 15  # Big reward for solving!
                    commenter.total_helpful += 1
                    commenter.update_reputation_level()
                    
                    # Log reputation
                    rep_log = ReputationHistory(
                        user_id=commenter.id,
                        action="answer_marked_as_solution",
                        points_change=15,
                        related_type="comment",
                        related_id=comment_id,
                        reputation_before=commenter.reputation - 15,
                        reputation_after=commenter.reputation
                    )
                    db.session.add(rep_log)
                    
                    # Notify commenter
                    notification = Notification(
                        user_id=commenter.id,
                        title="Your answer was marked as the solution!",
                        body=f'"{post.title}" (+15 reputation)',
                        notification_type="solution_accepted",
                        related_type="post",
                        related_id=post_id
                    )
                    db.session.add(notification)
        
        db.session.commit()
        
        return success_response(
            "Post marked as solved",
            data={
                "solved_at": post.solved_at.isoformat(),
                "solution_comment_id": comment_id if comment_id else None
            }
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Mark solved error: {str(e)}")
        return error_response("Failed to mark as solved")


@posts_bp.route("/posts/<int:post_id>/unmark-solved", methods=["POST"])
@token_required
def unmark_solved(current_user, post_id):
    """
    Unmark post as solved (in case of mistake)
    """
    try:
        post = Post.query.get(post_id)
        
        if not post:
            return error_response("Post not found", 404)
        
        if post.student_id != current_user.id:
            return error_response("Only post author can unmark as solved", 403)
        
        if not post.is_solved:
            return error_response("Post is not marked as solved")
        
        post.is_solved = False
        post.solved_at = None
        
        # Unmark solution comment
        Comment.query.filter_by(post_id=post_id, is_solution=True).update(
            {"is_solution": False}
        )
        
        db.session.commit()
        
        return success_response("Post unmarked as solved")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Unmark solved error: {str(e)}")
        return error_response("Failed to unmark as solved")


# ============================================================================
# COMMENTS & REPLIES
# ============================================================================

@posts_bp.route("/posts/<int:post_id>/comments", methods=["GET"])
@token_required
def get_comments(current_user, post_id):
    """
    Get all comments for a post (with pagination)
    
    Query params:
    - page: Page number
    - per_page: Results per page
    - sort: recent, popular, oldest
    """
    try:
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        # Base query - top-level comments only (parent_id is None)
        query = Comment.query.filter_by(
            post_id=post_id,
            parent_id=None,
            is_deleted=False
        )
        
        # Sorting
        sort_by = request.args.get("sort", "recent")
        if sort_by == "popular":
            query = query.order_by(Comment.likes_count.desc())
        elif sort_by == "oldest":
            query = query.order_by(Comment.posted_at.asc())
        else:  # recent
            query = query.order_by(Comment.posted_at.desc())
        
        # Pagination
        page = request.args.get("page", 1, type=int)
        per_page = min(request.args.get("per_page", 20, type=int), 50)
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        comments_data = []
        for comment in paginated.items:
            author = User.query.get(comment.student_id)
            
            # Get replies count
            replies_count = Comment.query.filter_by(
                parent_id=comment.id,
                is_deleted=False
            ).count()
            
            # Check if current user liked this comment
            user_liked = CommentLike.query.filter_by(
                comment_id=comment.id,
                student_id=current_user.id
            ).first()
            
            comments_data.append({
                "id": comment.id,
                "text_content": comment.text_content,
                "resource": comment.resource,
                "resource_type": comment.resource_type,
                "likes_count": comment.likes_count,
                "replies_count": replies_count,
                "is_solution": comment.is_solution,
                "posted_at": comment.posted_at.isoformat(),
                "edited_at": comment.edited_at.isoformat() if comment.edited_at else None,
                "author": {
                    "id": author.id,
                    "username": author.username,
                    "name": author.name,
                    "avatar": author.avatar,
                    "reputation_level": author.reputation_level
                } if author else None,
                "user_liked": bool(user_liked),
                "is_author": comment.student_id == current_user.id
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "comments": comments_data,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": paginated.total,
                    "pages": paginated.pages
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get comments error: {str(e)}")
        return error_response("Failed to load comments")


@posts_bp.route("/posts/<int:post_id>/comments", methods=["POST"])
@token_required
def add_comment(current_user, post_id):
    """
    Add comment to post
    
    Body: {
        "text_content": "Comment text",
        "parent_id": 123  (optional - for replies)
    }
    """
    try:
        post = Post.query.get(post_id)
        if not post:
            return error_response("Post not found", 404)
        
        if post.is_locked:
            return error_response("Post is locked - no more comments allowed", 403)
        
        # Spam check
        is_spam, spam_reason = check_spam(current_user.id, "comment")
        if is_spam:
            return error_response(f"Rate limit exceeded: {spam_reason}", 429)
        data = request.get_json()
        text_content = data.get("text_content", "").strip()
        
        if not text_content:
            return error_response("Comment text is required")
        
        if len(text_content) < 2:
            return error_response("Comment too short")
        
        parent_id = data.get("parent_id")
        
        # If replying to a comment, verify parent exists
        if parent_id:
            parent_comment = Comment.query.get(parent_id)
            if not parent_comment or parent_comment.post_id != post_id:
                return error_response("Invalid parent comment")
        
        # Create comment
        new_comment = Comment(
            post_id=post_id,
            student_id=current_user.id,
            parent_id=parent_id,
            text_content=text_content
        )
        
        db.session.add(new_comment)
        db.session.flush()
        
        # Update post comment count
        post.comments_count += 1
        
        # Detect mentions
        mentioned_users = detect_and_create_mentions(
            text_content,
            current_user.id,
            "comment",
            new_comment.id
        )
        
        # Notify post author (if not self-comment)
        if post.student_id != current_user.id:
            notification = Notification(
                user_id=post.student_id,
                title=f"{current_user.name} commented on your post",
                body=f'"{post.title}"',
                notification_type="comment",
                related_type="post",
                related_id=post_id
            )
            db.session.add(notification)
        
        # Notify followers of the post
        followers = PostFollow.query.filter_by(post_id=post_id).all()
        for follow in followers:
            if follow.student_id != current_user.id and follow.notify_on_comment:
                notification = Notification(
                    user_id=follow.student_id,
                    title=f"New comment on post you're following",
                    body=f'"{post.title}"',
                    notification_type="comment",
                    related_type="post",
                    related_id=post_id
                )
                db.session.add(notification)
        
        # Update activity
        update_user_activity(current_user.id, "comment")
        
        db.session.commit()
        
        return success_response(
            "Comment added",
            data={
                "comment_id": new_comment.id,
                "posted_at": new_comment.posted_at.isoformat(),
                "mentioned_users": mentioned_users
            }
        ), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Add comment error: {str(e)}")
        return error_response("Failed to add comment")


@posts_bp.route("/comments/<int:comment_id>", methods=["GET"])
@token_required
def get_comment_replies(current_user, comment_id):
    """
    Get all replies to a specific comment
    """
    try:
        comment = Comment.query.get(comment_id)
        if not comment:
            return error_response("Comment not found", 404)
        
        # Get all replies
        replies = Comment.query.filter_by(
            parent_id=comment_id,
            is_deleted=False
        ).order_by(Comment.posted_at.asc()).all()
        
        replies_data = []
        for reply in replies:
            author = User.query.get(reply.student_id)
            
            user_liked = CommentLike.query.filter_by(
                comment_id=reply.id,
                student_id=current_user.id
            ).first()
            
            replies_data.append({
                "id": reply.id,
                "text_content": reply.text_content,
                "likes_count": reply.likes_count,
                "posted_at": reply.posted_at.isoformat(),
                "author": {
                    "id": author.id,
                    "username": author.username,
                    "name": author.name,
                    "avatar": author.avatar
                } if author else None,
                "user_liked": bool(user_liked),
                "is_author": reply.student_id == current_user.id
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "replies": replies_data,
                "total": len(replies_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get replies error: {str(e)}")
        return error_response("Failed to load replies")


@posts_bp.route("/comments/<int:comment_id>", methods=["PATCH"])
@token_required
def edit_comment(current_user, comment_id):
    """
    Edit your own comment
    
    Body: {"text_content": "Updated text"}
    """
    try:
        comment = Comment.query.get(comment_id)
        
        if not comment:
            return error_response("Comment not found", 404)
        
        if comment.student_id != current_user.id:
            return error_response("You can only edit your own comments", 403)
        
        data = request.get_json()
        new_text = data.get("text_content", "").strip()
        
        if not new_text:
            return error_response("Comment text is required")
        
        if new_text == comment.text_content:
            return success_response("No changes made")
        
        comment.text_content = new_text
        comment.edited_at = datetime.datetime.utcnow()
        
        # Re-detect mentions
        Mention.query.filter_by(
            mentioned_in_type="comment",
            mentioned_in_id=comment_id
        ).delete()
        
        detect_and_create_mentions(
            new_text,
            current_user.id,
            "comment",
            comment_id
        )
        
        db.session.commit()
        
        return success_response(
            "Comment updated",
            data={"edited_at": comment.edited_at.isoformat()}
        )
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Edit comment error: {str(e)}")
        return error_response("Failed to edit comment")


@posts_bp.route("/comments/<int:comment_id>", methods=["DELETE"])
@token_required
def delete_comment(current_user, comment_id):
    """
    Delete your own comment (soft delete)
    """
    try:
        comment = Comment.query.get(comment_id)
        
        if not comment:
            return error_response("Comment not found", 404)
        
        if comment.student_id != current_user.id:
            return error_response("You can only delete your own comments", 403)
        
        # Soft delete (preserve structure for replies)
        comment.is_deleted = True
        comment.text_content = "[deleted]"
        
        # Update post comment count
        post = Post.query.get(comment.post_id)
        if post and post.comments_count > 0:
            post.comments_count -= 1
        
        db.session.commit()
        
        return success_response("Comment deleted")
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Delete comment error: {str(e)}")
        return error_response("Failed to delete comment")


@posts_bp.route("/comments/<int:comment_id>/like", methods=["POST"])
@token_required
def like_comment(current_user, comment_id):
    """
    Like a comment
    """
    try:
        comment = Comment.query.get(comment_id)
        if not comment:
            return error_response("Comment not found", 404)
        
        existing = CommentLike.query.filter_by(
            comment_id=comment_id,
            student_id=current_user.id
        ).first()
        
        if existing:
            # Unlike
            db.session.delete(existing)
            comment.likes_count = max(0, comment.likes_count - 1)
            db.session.commit()
            return success_response("Comment unliked")
        else:
            # Like
            new_like = CommentLike(
                comment_id=comment_id,
                student_id=current_user.id
            )
            db.session.add(new_like)
            comment.likes_count += 1
            
            # Notify comment author
            if comment.student_id != current_user.id:
                notification = Notification(
                    user_id=comment.student_id,
                    title=f"{current_user.name} liked your comment",
                    body="",
                    notification_type="like",
                    related_type="comment",
                    related_id=comment_id
                )
                db.session.add(notification)
            
            db.session.commit()
            return success_response("Comment liked"), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Like comment error: {str(e)}")
        return error_response("Failed to like comment")


# ============================================================================
# FEED & DISCOVERY
# ============================================================================

@posts_bp.route("/posts/feed", methods=["GET"])
@token_required
def get_feed(current_user):
    """
    Smart feed - personalized posts based on:
    - Your department
    - Your connections' posts
    - Trending in your department
    - Posts you might like
    
    Query params:
    - filter: all, following, department, trending
    - page: Page number
    """
    try:
        filter_type = request.args.get("filter", "all")
        page = request.args.get("page", 1, type=int)
        per_page = 20
        
        profile = StudentProfile.query.filter_by(user_id=current_user.id).first()
        
        if filter_type == "following":
            # Posts from connections only
            connections = Connection.query.filter(
                or_(
                    Connection.requester_id == current_user.id,
                    Connection.receiver_id == current_user.id
                ),
                Connection.status == "accepted"
            ).all()
            
            connection_ids = []
            for conn in connections:
                if conn.requester_id == current_user.id:
                    connection_ids.append(conn.receiver_id)
                else:
                    connection_ids.append(conn.requester_id)
            
            query = Post.query.filter(Post.student_id.in_(connection_ids))
        
        elif filter_type == "department":
            # Posts from your department
            query = Post.query.filter(Post.department == profile.department)
        
        elif filter_type == "trending":
            # Trending posts (last 7 days, high engagement)
            week_ago = datetime.datetime.utcnow() - datetime.timedelta(days=7)
            query = Post.query.filter(Post.posted_at >= week_ago).order_by(
                (Post.likes_count * 2 + Post.comments_count * 1.5 + Post.views / 10).desc()
            )
        
        else:  # all
            # Smart feed - mix of everything
            query = Post.query
        
        # Default sort by recent
        if filter_type != "trending":
            query = query.order_by(Post.posted_at.desc())
        
        paginated = query.paginate(page=page, per_page=per_page, error_out=False)
        
        posts_data = []
        for post in paginated.items:
            author = User.query.get(post.student_id)
            
            # Check user interaction
            user_liked = PostLike.query.filter_by(
                post_id=post.id,
                student_id=current_user.id
            ).first()
            
            user_bookmarked = Bookmark.query.filter_by(
                post_id=post.id,
                student_id=current_user.id
            ).first()
            
            posts_data.append({
                "id": post.id,
                "title": post.title,
                "excerpt": post.text_content[:200] if post.text_content else None,
                "post_type": post.post_type,
                "department": post.department,
                "tags": post.tags,
                "thread_enabled": post.thread_enabled,
                "is_solved": post.is_solved,
                "likes_count": post.likes_count,
                "comments_count": post.comments_count,
                "views": post.views,
                "posted_at": post.posted_at.isoformat(),
                "author": {
                    "id": author.id,
                    "username": author.username,
                    "name": author.name,
                    "avatar": author.avatar,
                    "reputation_level": author.reputation_level
                } if author else None,
                "user_interaction": {
                    "liked": user_liked.like_type if user_liked else None,
                    "bookmarked": bool(user_bookmarked)
                }
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "posts": posts_data,
                "filter": filter_type,
                "pagination": {
                    "page": page,
                    "per_page": per_page,
                    "total": paginated.total,
                    "pages": paginated.pages
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get feed error: {str(e)}")
        return error_response("Failed to load feed")


@posts_bp.route("/posts/my-posts", methods=["GET"])
@token_required
def get_my_posts(current_user):
    """
    Get all posts created by current user
    """
    try:
        page = request.args.get("page", 1, type=int)
        per_page = 20
        
        paginated = Post.query.filter_by(
            student_id=current_user.id
        ).order_by(Post.posted_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        posts_data = []
        for post in paginated.items:
            posts_data.append({
                "id": post.id,
                "title": post.title,
                "post_type": post.post_type,
                "is_solved": post.is_solved,
                "likes_count": post.likes_count,
                "comments_count": post.comments_count,
                "is_featured": post.id == current_user.featured_post_id if current_user.featured_post_id else None
                "is_pinned": post.is_pinned
                "views": post.views,
                "posted_at": post.posted_at.isoformat()
            })
        
        return jsonify({
            "status": "success",
            "data": {
                "posts": posts_data,
                "pagination": {
                    "page": page,
                    "total": paginated.total,
                    "pages": paginated.pages
                }
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get my posts error: {str(e)}")
        return error_response("Failed to load your posts")


@posts_bp.route("/posts/bookmarked", methods=["GET"])
@token_required
def get_bookmarked_posts(current_user):
    """
    Get all bookmarked posts organized by folder
    
    Query params:
    - folder: Filter by folder name
    """
    try:
        folder_filter = request.args.get("folder")
        
        query = Bookmark.query.filter_by(student_id=current_user.id)
        
        if folder_filter:
            query = query.filter_by(folder=folder_filter)
        
        bookmarks = query.order_by(Bookmark.bookmarked_at.desc()).all()
        
        bookmarks_data = []
        for bookmark in bookmarks:
            post = Post.query.get(bookmark.post_id)
            if post:
                author = User.query.get(post.student_id)
                bookmarks_data.append({
                    "bookmark_id": bookmark.id,
                    "folder": bookmark.folder,
                    "notes": bookmark.notes,
                    "bookmarked_at": bookmark.bookmarked_at.isoformat(),
                    "post": {
                        "id": post.id,
                        "title": post.title,
                        "post_type": post.post_type,
                        "posted_at": post.posted_at.isoformat(),
                        "author": {
                            "username": author.username,
                            "name": author.name
                        } if author else None
                    }
                })
        
        # Get all unique folders
        folders = db.session.query(Bookmark.folder, func.count(Bookmark.id)).filter_by(
            student_id=current_user.id
        ).group_by(Bookmark.folder).all()
        
        folders_data = [{"name": f[0], "count": f[1]} for f in folders]
        
        return jsonify({
            "status": "success",
            "data": {
                "bookmarks": bookmarks_data,
                "folders": folders_data,
                "total": len(bookmarks_data)
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"Get bookmarked posts error: {str(e)}")
        return error_response("Failed to load bookmarks")
        
        
        