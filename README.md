StudyHub - Complete Student Collaboration Platform 🎓
A full-featured academic social network built with Flask, designed to revolutionize how students learn, collaborate, and grow together.
🌟 Features Overview
🔐 Authentication & Profiles
Email Verification System - Secure registration with JWT tokens
Rich User Profiles - Customizable avatars, bio, skills, and learning goals
Privacy Controls - Granular settings for profile visibility
Activity Tracking - GitHub-style contribution heatmap
Smart Analytics - Personalized insights and statistics
📝 Content Creation
Dynamic Posts - Questions, discussions, announcements, resources, problems
Rich Media Support - Images, videos, documents
Smart Tagging - Organized by department and custom tags
@Mentions - Tag users in posts and comments
Nested Comments - Threaded discussions with replies
Bookmarking - Save posts in custom folders
🤝 Social Features
Connection System - Friend requests before messaging (spam prevention)
Private Messaging - Real-time chat with read receipts
Typing Indicators - See when someone is typing
Message Actions - Edit, delete, archive, pin conversations
Mutual Connections - Find common friends
🧵 Study Threads
Private Groups - Create collaboration spaces
Join Requests - Approval system or direct invites
Real-time Chat - Thread messaging with @mentions
Member Management - Roles (creator, moderator, member)
Thread Analytics - Activity stats and member engagement
🎯 Study Buddy System
Smart Matching - Algorithm-based partner suggestions
Preference System - Match by subjects, availability, goals
Request Workflow - Send/accept study partnership requests
Auto-Thread Creation - Dedicated study space on match
Session Tracking - Log completed study sessions
🏆 Gamification
Reputation System - Earn points for helpful contributions
Post gets likes: +5 to +50 points
Comment marked as solution: +15 points
Helpful reactions: +5 points
5-Tier Levels - Newbie → Learner → Contributor → Expert → Master
Badges System - 15+ achievement badges
Engagement, Quality, Consistency, Social, Milestone
Leaderboards - Global and department rankings
🔍 Advanced Search
Multi-Type Search - Users, posts, threads in one query
Smart Filters - Department, class level, tags, date range
Autocomplete - Suggestions as you type
Trending Posts - Algorithm-ranked hot content
Popular Tags - Discover trending topics
📊 Analytics & Insights
Personal Dashboard - Weekly stats and activity overview
Engagement Breakdown - Posts, comments, threads metrics
Impact Metrics - People reached, questions solved
AI-like Insights - Pattern-based recommendations
Comparison Stats - How you rank vs average users
Export Data - CSV export of your activity
🔔 Notifications
Real-time Alerts - Mentions, likes, comments, badges
Grouped Notifications - Organized by category
Smart Filtering - Mark all read, delete, archive
Push-Ready - Architecture supports push notifications
🛠️ Tech Stack
Backend
Framework: Flask 3.0+
Database: SQLAlchemy ORM (SQLite/PostgreSQL)
Authentication: Flask-Login + JWT tokens
Email: Flask-Mail with Brevo SMTP
Security: Werkzeug password hashing
Frontend (Your Integration)
API-First Design - Complete REST API
JSON Responses - Consistent response format
Polling Support - Real-time-feel without WebSockets
File Upload - Multipart form-data support
CORS-Ready - Easy frontend integration
📁 Project Structure
StudyHub/
├── app.py                          # Application factory
├── extensions.py                   # Flask extensions (db, login_manager, mail)
├── models.py                       # Database models (30+ tables)
├── utils.py                        # Email & token utilities
├── requirements.txt                # Python dependencies
│
├── routes/student/                 # Student routes package
│   ├── __init__.py                # Blueprint registration
│   ├── helpers.py                 # Shared utilities & decorators
│   │
│   ├── auth.py                    # 🔐 Registration, login, verification
│   ├── profile.py                 # 👤 View/edit profiles, skills, goals
│   ├── posts.py                   # 📝 CRUD posts, comments, reactions
│   ├── connections.py             # 🤝 Friend requests, suggestions
│   ├── messages.py                # 💬 Private messaging system
│   ├── threads.py                 # 🧵 Study group collaboration
│   ├── study_buddy.py             # 🎯 Smart partner matching
│   ├── badges.py                  # 🏆 Achievement system
│   ├── reputation.py              # ⭐ Points & leaderboards
│   ├── analytics.py               # 📊 Stats & insights
│   └── search.py                  # 🔍 Advanced search engine
│
├── static/                         # Static files
│   └── upload/                    # User uploads
│       ├── avatars/
│       ├── post_images/
│       └── message_attachments/
│
└── templates/                      # HTML templates (for API docs/demos)
🚀 Getting Started
Prerequisites
Python 3.8+
pip
Virtual environment (recommended)
Installation
Clone the repository
git clone https://github.com/yourusername/studyhub.git
cd studyhub
Create virtual environment
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
Install dependencies
pip install -r requirements.txt
Configure environment variables
# Create .env file (optional)
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:///school.db
MAIL_USERNAME=your-email@gmail.com
MAIL_PASSWORD=your-app-password
BREVO_API_KEY=your-brevo-key
Initialize database
python
>>> from app import create_app
>>> from extensions import db
>>> app = create_app()
>>> with app.app_context():
...     db.create_all()
>>> exit()
Seed badges (optional)
python
>>> from app import create_app
>>> from routes.student.badges import seed_badges
>>> app = create_app()
>>> with app.app_context():
...     seed_badges()
>>> exit()
Run the application
python app.py
