"""
StudyHub - Complete Database Models (FIXED)
Added MutableDict and MutableList for proper JSON field tracking
"""

import datetime
from flask_login import UserMixin
from sqlalchemy.ext.mutable import MutableDict, MutableList
from extensions import db
# ============================================================================
# CORE USER MODELS
# ============================================================================

class User(UserMixin, db.Model):
    """Main user account - handles authentication and basic identity"""
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    
    # Auth
    username = db.Column(db.String(50), unique=True, nullable=True, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    pin = db.Column(db.String(200), nullable=False)
    
    # Profile basics
    name = db.Column(db.String(100), nullable=False)
    bio = db.Column(db.String(500))
    avatar = db.Column(db.String(200))
    
    # Role & status
    role = db.Column(db.String(20), default="student")
    status = db.Column(db.String(30), default="pending_verification")
    email_verified = db.Column(db.Boolean, default=False)
    
    # Gamification
    reputation = db.Column(db.Integer, default=0, index=True)
    reputation_level = db.Column(db.String(20), default="Newbie")
    
    # Activity tracking
    last_active = db.Column(db.DateTime)
    login_streak = db.Column(db.Integer, default=0)
    total_posts = db.Column(db.Integer, default=0)
    total_helpful = db.Column(db.Integer, default=0)
    
    # Profile customization - FIXED: Using MutableList and MutableDict
    # Profile customization - stored as JSON for flexibility
    featured_post_id = db.Column(db.Integer, nullable=True)
    skills = db.Column(db.JSON, default=list)
    learning_goals = db.Column(db.JSON, default=list)
    study_schedule = db.Column(db.JSON, default=dict)
    
    # Privacy controls - JSON so we can add settings without migrations
    privacy_settings = db.Column(db.JSON, default=dict)
    
    # Metadata - catch-all for future features
    # IMPORTANT: Use 'user_metadata' as attribute name to avoid conflict with SQLAlchemy's metadata
    user_metadata = db.Column('metadata', db.JSON, default=dict)  # ← THIS IS THE KEY LINE
    
    # Timestamps
    joined_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_login = db.Column(db.DateTime)
    # Relationships
    student_profile = db.relationship('StudentProfile', backref='user', uselist=False, cascade="all, delete-orphan")
    posts = db.relationship("Post", backref="author", lazy="dynamic", cascade="all, delete-orphan")
    comments = db.relationship("Comment", backref="author", lazy="dynamic", cascade="all, delete-orphan")
    threads_created = db.relationship("Thread", foreign_keys="Thread.creator_id", backref="creator", lazy="dynamic")
    badges = db.relationship("UserBadge", backref="user", lazy="dynamic", cascade="all, delete-orphan")
    
    @property
    def is_active(self):
        return (
            self.email_verified and 
            self.status == "approved" and 
            self.username is not None and
            self.pin != "PENDING_VERIFICATION"
        )

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)
    
    def update_reputation_level(self):
        """Calculate and update reputation level"""
        if self.reputation < 51:
            self.reputation_level = "Newbie"
        elif self.reputation < 201:
            self.reputation_level = "Learner"
        elif self.reputation < 501:
            self.reputation_level = "Contributor"
        elif self.reputation < 1000:
            self.reputation_level = "Expert"
        else:
            self.reputation_level = "Master"

    def __repr__(self):
        return f"<User @{self.username or self.email}>"


class StudentProfile(db.Model):
    """Extended profile info specific to students"""
    __tablename__ = "student_profiles"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    pin = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=True, index=True)
    
    # Academic info
    full_name = db.Column(db.String(120), nullable=False)
    department = db.Column(db.String(100), nullable=False, index=True)
    class_name = db.Column(db.String(50), nullable=False, index=True)
    
    # Optional info
    date_of_birth = db.Column(db.Date, nullable=True)
    guardian_name = db.Column(db.String(120))
    guardian_contact = db.Column(db.String(50))
    pin = db.Column(db.String(200))  # Added for compatibility
    username = db.Column(db.String(50))  # Added for compatibility
    
    # Status
    status = db.Column(db.String(50), default="active")
    registered_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Student @{self.user.username if self.user else 'Unknown'} - {self.department}>"


# ============================================================================
# CONTENT MODELS
# ============================================================================

class Post(db.Model):
    """Main content type - questions, discussions, resources"""
    __tablename__ = "posts"

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    # Content
    title = db.Column(db.String(200), nullable=False)
    text_content = db.Column(db.Text)
    post_type = db.Column(db.String(50), nullable=False, default="discussion", index=True)
    
    # Media
    resource = db.Column(db.String(255))
    resource_type = db.Column(db.String(50))
    
    # Organization - FIXED
    department = db.Column(db.String(100), index=True)
    tags = db.Column(MutableList.as_mutable(db.JSON), default=list)
    
    # Engagement metrics
    likes_count = db.Column(db.Integer, default=0)
    dislikes_count = db.Column(db.Integer, default=0)
    views = db.Column(db.Integer, default=0)
    comments_count = db.Column(db.Integer, default=0)
    bookmarks = db.Column(db.Integer, default=0)  # Added missing field
    
    # Thread system
    thread_enabled = db.Column(db.Boolean, default=False)
    
    # Status flags
    is_solved = db.Column(db.Boolean, default=False)
    is_pinned = db.Column(db.Boolean, default=False)
    is_locked = db.Column(db.Boolean, default=False)
    
    # Timestamps
    posted_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime)
    solved_at = db.Column(db.DateTime)
    
    # Relationships
    comments = db.relationship("Comment", backref="post", lazy="dynamic", cascade="all, delete-orphan")
    threads = db.relationship("Thread", backref="post", lazy="dynamic", cascade="all, delete-orphan")
    likes = db.relationship("PostLike", backref="post", lazy="dynamic", cascade="all, delete-orphan")
    reactions = db.relationship("PostReaction", backref="post", lazy="dynamic", cascade="all, delete-orphan")
    bookmarks = db.relationship("Bookmark", backref="post", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Post {self.id}: {self.title[:30]}>"


class Comment(db.Model):
    """Comments on posts - supports nested replies"""
    __tablename__ = "comments"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("comments.id"), nullable=True)

    # Content
    text_content = db.Column(db.Text, nullable=False)
    resource = db.Column(db.String(255))
    resource_type = db.Column(db.String(50))
    
    # Engagement
    likes_count = db.Column(db.Integer, default=0)
    
    # Status
    is_solution = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)

    # Timestamps
    posted_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    edited_at = db.Column(db.DateTime)
    
    # Relationships
    replies = db.relationship(
        "Comment",
        backref=db.backref("parent", remote_side=[id]),
        cascade="all, delete-orphan",
        lazy="dynamic"
    )
    likes = db.relationship("CommentLike", backref="comment", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Comment {self.id} on Post {self.post_id}>"


class Thread(db.Model):
    """Private collaboration groups"""
    __tablename__ = "threads"

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=True, index=True)  # Made nullable for standalone threads
    creator_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # Thread info
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    
    # Settings
    is_open = db.Column(db.Boolean, default=True)
    max_members = db.Column(db.Integer, default=10)
    requires_approval = db.Column(db.Boolean, default=True)
    
    # Metadata - FIXED
    department = db.Column(db.String(100), index=True)
    tags = db.Column(MutableList.as_mutable(db.JSON), default=list)
    
    # Stats
    member_count = db.Column(db.Integer, default=1)
    message_count = db.Column(db.Integer, default=0)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    # Relationships
    members = db.relationship("ThreadMember", backref="thread", lazy="dynamic", cascade="all, delete-orphan")
    join_requests = db.relationship("ThreadJoinRequest", backref="thread", lazy="dynamic", cascade="all, delete-orphan")
    messages = db.relationship("ThreadMessage", backref="thread", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Thread {self.id}: {self.title}>"


class ThreadMember(db.Model):
    """Approved members of a thread"""
    __tablename__ = "thread_members"
    
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("threads.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    role = db.Column(db.String(20), default="member")
    
    # Activity
    joined_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_read_at = db.Column(db.DateTime)
    messages_sent = db.Column(db.Integer, default=0)
    
    __table_args__ = (db.UniqueConstraint('thread_id', 'student_id', name='unique_thread_member'),)

    def __repr__(self):
        return f"<ThreadMember: User {self.student_id} in Thread {self.thread_id}>"


class ThreadJoinRequest(db.Model):
    """Pending requests to join threads"""
    __tablename__ = "thread_join_requests"
    
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("threads.id"), nullable=False, index=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default="pending", index=True)
    
    requested_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    
    __table_args__ = (db.UniqueConstraint('thread_id', 'requester_id', name='unique_join_request'),)

    def __repr__(self):
        return f"<JoinRequest: User {self.requester_id} → Thread {self.thread_id} [{self.status}]>"


class ThreadMessage(db.Model):
    """Chat messages inside threads"""
    __tablename__ = "thread_messages"
    
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("threads.id"), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    text_content = db.Column(db.Text, nullable=False)
    attachment = db.Column(db.String(255))
    attachment_type = db.Column(db.String(50))
    
    is_edited = db.Column(db.Boolean, default=False)
    is_deleted = db.Column(db.Boolean, default=False)
    
    sent_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    edited_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<ThreadMessage {self.id} in Thread {self.thread_id}>"


# ============================================================================
# SOCIAL FEATURES
# ============================================================================

class Connection(db.Model):
    """Friend/connection system"""
    __tablename__ = "connections"
    
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    status = db.Column(db.String(20), default="pending", index=True)
    
    requested_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    responded_at = db.Column(db.DateTime)
    
    connection_type = db.Column(db.String(30), default="connection")
    notes = db.Column(db.Text)
    
    __table_args__ = (
        db.UniqueConstraint('requester_id', 'receiver_id', name='unique_connection'),
        db.CheckConstraint('requester_id != receiver_id', name='no_self_connection')
    )

    def __repr__(self):
        return f"<Connection: {self.requester_id} → {self.receiver_id} [{self.status}]>"


class Mention(db.Model):
    """Track @username mentions"""
    __tablename__ = "mentions"
    
    id = db.Column(db.Integer, primary_key=True)
    
    mentioned_in_type = db.Column(db.String(20), nullable=False, index=True)
    mentioned_in_id = db.Column(db.Integer, nullable=False, index=True)
    
    mentioned_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    mentioned_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    
    is_read = db.Column(db.Boolean, default=False)
    mentioned_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Mention: @User{self.mentioned_user_id} in {self.mentioned_in_type} {self.mentioned_in_id}>"


class PostFollow(db.Model):
    """Follow posts for notifications"""
    __tablename__ = "post_follows"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    followed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    notify_on_comment = db.Column(db.Boolean, default=True)
    notify_on_solution = db.Column(db.Boolean, default=True)
    
    __table_args__ = (db.UniqueConstraint('post_id', 'student_id', name='unique_post_follow'),)

    def __repr__(self):
        return f"<Follow: User {self.student_id} → Post {self.post_id}>"


# ============================================================================
# ENGAGEMENT MODELS
# ============================================================================

class PostLike(db.Model):
    """Like/dislike tracking for posts"""
    __tablename__ = "post_likes"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    like_type = db.Column(db.String(10), default="like")
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('post_id', 'student_id', name='unique_post_like'),)

    def __repr__(self):
        return f"<PostLike: User {self.student_id} {self.like_type}d Post {self.post_id}>"


class CommentLike(db.Model):
    """Like tracking for comments"""
    __tablename__ = "comment_likes"
    
    id = db.Column(db.Integer, primary_key=True)
    comment_id = db.Column(db.Integer, db.ForeignKey("comments.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    liked_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('comment_id', 'student_id', name='unique_comment_like'),)

    def __repr__(self):
        return f"<CommentLike: User {self.student_id} → Comment {self.comment_id}>"


class PostReaction(db.Model):
    """Emoji reactions for posts"""
    __tablename__ = "post_reactions"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    reaction_type = db.Column(db.String(20), nullable=False)
    reacted_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('post_id', 'student_id', name='unique_post_reaction'),)

    def __repr__(self):
        return f"<Reaction: {self.reaction_type} on Post {self.post_id}>"


class Bookmark(db.Model):
    """Save posts for later"""
    __tablename__ = "bookmarks"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    folder = db.Column(db.String(100), default="Saved", index=True)
    notes = db.Column(db.Text)
    
    bookmarked_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('post_id', 'student_id', name='unique_bookmark'),)

    def __repr__(self):
        return f"<Bookmark: User {self.student_id} → Post {self.post_id} [{self.folder}]>"


# ============================================================================
# GAMIFICATION
# ============================================================================

class Badge(db.Model):
    """Achievable badges"""
    __tablename__ = "badges"
    
    id = db.Column(db.Integer, primary_key=True)
    
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    icon = db.Column(db.String(100))
    category = db.Column(db.String(50), index=True)
    
    # FIXED: MutableDict for criteria
    criteria = db.Column(MutableDict.as_mutable(db.JSON))
    
    rarity = db.Column(db.String(20), default="common")
    awarded_count = db.Column(db.Integer, default=0)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Badge: {self.name} [{self.rarity}]>"


class UserBadge(db.Model):
    """Badges earned by users"""
    __tablename__ = "user_badges"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), nullable=False, index=True)
    
    earned_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    is_featured = db.Column(db.Boolean, default=False)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'badge_id', name='unique_user_badge'),)
    
    badge = db.relationship("Badge", backref="user_badges")

    def __repr__(self):
        return f"<UserBadge: User {self.user_id} earned Badge {self.badge_id}>"

class ReputationHistory(db.Model):
    """Log of all reputation changes"""
    __tablename__ = "reputation_history"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    action = db.Column(db.String(100), nullable=False)
    points_change = db.Column(db.Integer, nullable=False)
    
    related_type = db.Column(db.String(20))
    related_id = db.Column(db.Integer)
    
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    
    reputation_before = db.Column(db.Integer)
    reputation_after = db.Column(db.Integer)

    def __repr__(self):
        return f"<RepHistory: User {self.user_id} {self.points_change:+d} pts for {self.action}>"


# ============================================================================
# UTILITY MODELS
# ============================================================================

class Notification(db.Model):
    """In-app notifications"""
    __tablename__ = "notifications"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    
    notification_type = db.Column(db.String(50), index=True)
    
    related_type = db.Column(db.String(20))
    related_id = db.Column(db.Integer)
    
    is_read = db.Column(db.Boolean, default=False, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    read_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<Notification {self.id}: {self.notification_type} for User {self.user_id}>"


class PostReport(db.Model):
    """Content moderation"""
    __tablename__ = "post_reports"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    reported_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    reason = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    
    status = db.Column(db.String(20), default="pending", index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    review_notes = db.Column(db.Text)
    action_taken = db.Column(db.String(100))
    
    reported_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)

    def __repr__(self):
        return f"<Report {self.id}: Post {self.post_id} - {self.reason} [{self.status}]>"


class ProfileChangeHistory(db.Model):
    """Audit trail for profile changes"""
    __tablename__ = "profile_change_history"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.String(500))
    new_value = db.Column(db.String(500))
    
    change_type = db.Column(db.String(50), index=True)
    ip_address = db.Column(db.String(50))
    user_agent = db.Column(db.String(200))
    
    changed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    
    def __repr__(self):
        return f"<ProfileChange: User {self.user_id} - {self.field_changed} [{self.change_type}]>"


class PasswordResetToken(db.Model):
    """Secure password reset tokens"""
    __tablename__ = "password_reset_tokens"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    token = db.Column(db.String(500), unique=True, nullable=False, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    
    used = db.Column(db.Boolean, default=False)
    used_at = db.Column(db.DateTime)
    
    def is_valid(self):
        return not self.used and datetime.datetime.utcnow() < self.expires_at

    def __repr__(self):
        return f"<PasswordResetToken for User {self.user_id}>"



class Message(db.Model):
    """Private messaging between connected users"""
    __tablename__ = "messages"
    
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    subject = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    
    sent_at = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    is_read = db.Column(db.Boolean, default=False, index=True)
    read_at = db.Column(db.DateTime)
    
    deleted_by_sender = db.Column(db.Boolean, default=False)
    deleted_by_receiver = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Message {self.id}: {self.sender_id} → {self.receiver_id}>"


# ============================================================================
# STUDY BUDDY SYSTEM
# ============================================================================

class StudyBuddyRequest(db.Model):
    """Study partnership requests with matching criteria"""
    __tablename__ = "study_buddy_requests"
    
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    receiver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # FIXED: Using Mutable types
    subjects = db.Column(MutableList.as_mutable(db.JSON), default=list)
    availability = db.Column(MutableDict.as_mutable(db.JSON), default=dict)
    message = db.Column(db.Text)
    
    status = db.Column(db.String(20), default="pending", index=True)
    thread_id = db.Column(db.Integer, db.ForeignKey("threads.id"), nullable=True)
    
    requested_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    responded_at = db.Column(db.DateTime)
    
    __table_args__ = (db.UniqueConstraint('requester_id', 'receiver_id', name='unique_study_buddy_request'),)

    def __repr__(self):
        return f"<StudyBuddy: {self.requester_id} → {self.receiver_id} [{self.status}]>"


class StudyBuddyMatch(db.Model):
    """Active study buddy partnerships"""
    __tablename__ = "study_buddy_matches"
    
    id = db.Column(db.Integer, primary_key=True)
    user1_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    user2_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    # FIXED: MutableList for subjects
    subjects = db.Column(MutableList.as_mutable(db.JSON), default=list)
    thread_id = db.Column(db.Integer, db.ForeignKey("threads.id"))
    
    sessions_count = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    
    matched_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    last_activity = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    
    __table_args__ = (db.UniqueConstraint('user1_id', 'user2_id', name='unique_study_match'),)

    def __repr__(self):
        return f"<StudyMatch: {self.user1_id} ↔ {self.user2_id}>"


# ============================================================================
# ANALYTICS & TRACKING
# ============================================================================

class PostView(db.Model):
    """Track post views for analytics and trending"""
    __tablename__ = "post_views"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, index=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    
    viewed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    view_date = db.Column(db.Date, default=datetime.date.today, index=True)
    
    __table_args__ = (
        db.UniqueConstraint('post_id', 'viewer_id', 'view_date', name='unique_daily_view'),
    )

    def __repr__(self):
        return f"<PostView: User {self.viewer_id} → Post {self.post_id}>"


class UserActivity(db.Model):
    """Track daily user activity for heatmap and streaks"""
    __tablename__ = "user_activity"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    activity_date = db.Column(db.Date, default=datetime.date.today, nullable=False, index=True)
    
    # Daily counts
    posts_created = db.Column(db.Integer, default=0)
    comments_created = db.Column(db.Integer, default=0)
    threads_joined = db.Column(db.Integer, default=0)
    messages_sent = db.Column(db.Integer, default=0)
    helpful_count = db.Column(db.Integer, default=0)
    
    # Total score for the day
    activity_score = db.Column(db.Integer, default=0)
    
    __table_args__ = (db.UniqueConstraint('user_id', 'activity_date', name='unique_daily_activity'),)

    def __repr__(self):
        return f"<Activity: User {self.user_id} on {self.activity_date}>"


class TrendingPost(db.Model):
    """Cached trending posts - recalculated periodically"""
    __tablename__ = "trending_posts"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, unique=True, index=True)
    
    trending_score = db.Column(db.Float, default=0.0, index=True)
    department = db.Column(db.String(100), index=True)
    
    calculated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    rank = db.Column(db.Integer)

    def __repr__(self):
        return f"<Trending: Post {self.post_id} - Score {self.trending_score:.2f}>"


# ============================================================================
# SEARCH OPTIMIZATION
# ============================================================================

class SearchIndex(db.Model):
    """Full-text search index for faster queries"""
    __tablename__ = "search_index"
    
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey("posts.id"), nullable=False, unique=True, index=True)
    
    searchable_text = db.Column(db.Text)
    
    department = db.Column(db.String(100), index=True)
    post_type = db.Column(db.String(50), index=True)
    tags_text = db.Column(db.String(500), index=True)
    
    indexed_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<SearchIndex: Post {self.post_id}>"


# ============================================================================
# MODERATION & COMMUNITY HEALTH
# ============================================================================

class UserWarning(db.Model):
    """Track warnings for policy violations - Three strikes system"""
    __tablename__ = "user_warnings"
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    
    reason = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(20), default="low")  # low, medium, high, critical
    
    issued_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    
    related_type = db.Column(db.String(20))
    related_id = db.Column(db.Integer)
    
    is_active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime)
    
    issued_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

    def __repr__(self):
        return f"<Warning: User {self.user_id} - {self.severity} [{self.reason}]>"


 
# END OF MODELS
# ============================================================================