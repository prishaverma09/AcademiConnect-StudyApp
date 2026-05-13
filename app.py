from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from models import db, User, Course, LibraryQuestion, LibrarySolution, StudySession, FileResource, Skill, Report
import os
import re
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from collections import defaultdict
import time

app = Flask(__name__)

# ============================================================
# 🔒 SECURITY CONFIGURATION
# ============================================================
# Secret key: Use environment variable in production, fallback for dev
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(32))

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///academi_connect.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max upload (reduced from 16MB)

# Secure Session Cookies
app.config['SESSION_COOKIE_HTTPONLY'] = True   # JS cannot read the cookie
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # Prevents CSRF from other sites
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)  # Auto-expire sessions

# Allowed file types for upload (whitelist approach)
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'txt', 'docx'}

def allowed_file(filename):
    """Only allow safe file extensions."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================================================
# 🛡️ RATE LIMITING (Brute-force protection)
# ============================================================
login_attempts = defaultdict(list)
MAX_ATTEMPTS = 5       # Max 5 attempts
WINDOW_SECONDS = 300   # Per 5 minutes

def is_rate_limited(ip):
    """Check if IP has exceeded login attempt limits."""
    now = time.time()
    attempts = login_attempts[ip]
    # Clear old attempts outside the window
    login_attempts[ip] = [t for t in attempts if now - t < WINDOW_SECONDS]
    if len(login_attempts[ip]) >= MAX_ATTEMPTS:
        return True
    login_attempts[ip].append(now)
    return False

# ============================================================
# 🛡️ INPUT VALIDATION HELPERS
# ============================================================
def sanitize_text(text, max_len=200):
    """Strip leading/trailing whitespace and enforce max length."""
    if not text:
        return ''
    return str(text).strip()[:max_len]

def is_valid_email(email):
    """Basic email format validation."""
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w{2,}$'
    return re.match(pattern, email) is not None

# ============================================================

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db.init_app(app)
# Only restrict CORS origin in production
socketio = SocketIO(app, cors_allowed_origins="http://localhost:5000")

with app.app_context():
    db.create_all()

# ============================================================
# 🔒 SECURITY HEADERS (Applied to every response)
# ============================================================
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'         # Prevent Clickjacking
    response.headers['X-Content-Type-Options'] = 'nosniff'     # Prevent MIME sniffing
    response.headers['X-XSS-Protection'] = '1; mode=block'     # Block reflected XSS
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/signup', methods=['POST'])
def signup():
    ip = request.remote_addr

    # 🛡️ Rate limit check
    if is_rate_limited(ip):
        flash('⛔ Too many attempts. Please wait 5 minutes before trying again.')
        return redirect(url_for('login_page'))

    # 🛡️ Sanitize all inputs
    name    = sanitize_text(request.form.get('name', ''), max_len=80)
    email   = sanitize_text(request.form.get('email', ''), max_len=120)
    age     = sanitize_text(request.form.get('age', ''), max_len=3)
    college = sanitize_text(request.form.get('college', ''), max_len=120)
    year    = sanitize_text(request.form.get('year', ''), max_len=10)

    # 🛡️ Validate required fields
    if not name or not email:
        flash('⚠️ Name and email are required.')
        return redirect(url_for('login_page'))

    # 🛡️ Validate email format
    if not is_valid_email(email):
        flash('⚠️ Please enter a valid email address.')
        return redirect(url_for('login_page'))

    is_verified = email.endswith('.edu') or 'uni' in email.lower()

    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(name=name, email=email, age=age, college=college, year=year, is_verified=is_verified, streak_count=1)
        db.session.add(user)
    else:
        # Update streak on login
        today = datetime.utcnow().date()
        last_seen_date = user.last_seen.date()
        if (today - last_seen_date).days == 1:
            user.streak_count += 1
        elif (today - last_seen_date).days > 1:
            user.streak_count = 1
        user.last_seen = datetime.utcnow()

    db.session.commit()
    session['user_id'] = user.id
    session['user'] = {'name': user.name, 'college': user.college, 'year': user.year}
    session.permanent = True   # Apply 12-hour expiry
    return redirect(url_for('dashboard'))

@app.before_request
def update_presence():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.last_seen = datetime.utcnow()
            db.session.commit()

@app.route('/logout')
def logout():
    session.pop('user', None)
    session.pop('user_id', None)
    return redirect(url_for('login_page'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    user = User.query.get(session['user_id'])
    # Fetch scheduled sessions
    sessions = StudySession.query.order_by(StudySession.start_time.desc()).all()
    # Suggested partners (simple match by college for now)
    suggestions = User.query.filter(User.college == user.college, User.id != user.id).limit(3).all()
    recent_questions = LibraryQuestion.query.order_by(LibraryQuestion.created_at.desc()).limit(3).all()
    return render_template('dashboard.html', user=user, suggestions=suggestions, recent_questions=recent_questions, sessions=sessions)

@app.route('/games')
def games():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('games.html')

@app.route('/library')
def library():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    search_query = request.args.get('search', '')
    query = LibraryQuestion.query
    
    if search_query:
        query = query.filter(
            (LibraryQuestion.title.ilike(f'%{search_query}%')) | 
            (LibraryQuestion.content.ilike(f'%{search_query}%')) |
            (LibraryQuestion.course_code.ilike(f'%{search_query}%'))
        )
        
    questions = query.order_by(LibraryQuestion.created_at.desc()).all()
    return render_template('library.html', questions=questions, search_query=search_query)

@app.route('/library/ask', methods=['POST'])
def library_ask():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    title = request.form.get('title')
    content = request.form.get('content')
    course_code = request.form.get('course_code', 'GENERAL').upper()
    
    q = LibraryQuestion(title=title, content=content, course_code=course_code, user_id=session['user_id'])
    db.session.add(q)
    db.session.commit()
    flash('Question posted successfully! 📚')
    return redirect(url_for('library'))

@app.route('/library/question/<int:q_id>')
def question_detail(q_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    question = LibraryQuestion.query.get_or_404(q_id)
    return render_template('question_detail.html', question=question)

@app.route('/library/question/<int:q_id>/solve', methods=['POST'])
def solve_question(q_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    content = request.form.get('content')
    
    solution = LibrarySolution(content=content, question_id=q_id, user_id=session['user_id'])
    db.session.add(solution)
    db.session.commit()
    flash('Solution posted! You earned +10 Reputation. 🌟')
    return redirect(url_for('question_detail', q_id=q_id))

@app.route('/ai/summarize/<int:file_id>')
def ai_summarize(file_id):
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    file_record = FileResource.query.get_or_404(file_id)
    # Placeholder for LLM API integration
    summary = {
        "title": f"Summary: {file_record.filename}",
        "flashcards": [
            {"front": "Key Term 1", "back": "Definition of key term from the document."},
            {"front": "Process A", "back": "Steps to complete Process A."},
            {"front": "Formula B", "back": "Mathematical representation of B."}
        ],
        "recap": "This document covers the fundamental principles of " + file_record.course_code + "."
    }
    return jsonify(summary)

@app.route('/whiteboard')
def whiteboard():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    return render_template('whiteboard.html')

@app.route('/mentor-search')
def mentor_search():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    skill_filter = request.args.get('skill')
    college_filter = request.args.get('college')
    
    query = User.query.filter(User.mentor_status == True)
    
    if skill_filter:
        query = query.join(User.skills).filter(Skill.name.ilike(f'%{skill_filter}%'))
    if college_filter:
        query = query.filter(User.college.ilike(f'%{college_filter}%'))
        
    mentors = query.distinct().all()
    return render_template('mentors.html', mentors=mentors)

@app.route('/become-mentor', methods=['POST'])
def become_mentor():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    user = User.query.get(session['user_id'])
    skills_text = request.form.get('skills')
    
    if skills_text:
        user.mentor_status = True
        # Clear old skills and add new ones
        Skill.query.filter_by(user_id=user.id).delete()
        for s in skills_text.split(','):
            skill = Skill(name=s.strip(), user_id=user.id)
            db.session.add(skill)
        db.session.commit()
        flash('You are now a verified mentor! 🎓')
    
    return redirect(url_for('mentor_search'))

@app.route('/repository')
def repository():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    search_query = request.args.get('search', '')
    course_code = request.args.get('course', '')
    
    query = FileResource.query
    
    if search_query:
        query = query.filter(FileResource.filename.ilike(f'%{search_query}%'))
    if course_code:
        query = query.filter(FileResource.course_code.ilike(f'%{course_code}%'))
        
    files = query.order_by(FileResource.created_at.desc()).all()
    return render_template('repository.html', files=files, course_code=course_code, search_query=search_query)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
        
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('repository'))

    file = request.files['file']
    course_code = sanitize_text(request.form.get('course_code', 'GENERAL'), max_len=20).upper()

    if file.filename == '':
        flash('No file selected.')
        return redirect(url_for('repository'))

    # 🛡️ Validate file extension against whitelist
    if not allowed_file(file.filename):
        flash('⛔ File type not allowed. Please upload PDF, image, or document files only.')
        return redirect(url_for('repository'))

    if file:
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique_filename = f"{timestamp}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(file_path)

        new_file = FileResource(
            filename=filename,
            file_path=unique_filename,
            course_code=course_code,
            uploaded_by=session['user_id']
        )
        db.session.add(new_file)
        db.session.commit()
        flash('File uploaded successfully! 📁')

    return redirect(url_for('repository', course=course_code))

@app.route('/download/<int:file_id>')
def download_file(file_id):
    file_record = FileResource.query.get_or_404(file_id)
    return send_from_directory(app.config['UPLOAD_FOLDER'], file_record.file_path, as_attachment=True, download_name=file_record.filename)

@app.route('/rate-session', methods=['POST'])
def rate_session():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    target_user_id = request.form.get('user_id')
    rating = float(request.form.get('rating', 5))
    
    user = User.query.get(target_user_id)
    if user:
        # Simple moving average for trust score
        user.trust_score = (user.trust_score + rating) / 2
        db.session.commit()
        flash(f'Feedback submitted for {user.name}!')
    
    return redirect(url_for('dashboard'))

@app.route('/report', methods=['POST'])
def report_content():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    content_type = request.form.get('type')
    content_id = request.form.get('id')
    reason = request.form.get('reason')
    
    report = Report(content_type=content_type, content_id=content_id, reason=reason, reporter_id=session['user_id'])
    db.session.add(report)
    db.session.commit()
    flash('Thank you. Content has been flagged for admin review.')
    
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/index')
def index():
    return redirect(url_for('dashboard'))

@app.route('/match', methods=['GET', 'POST'])
def match_users():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
        
    if request.method == 'POST':
        data = request.json
        target_course_code = data.get('course_code')
        target_vibe = data.get('study_vibe')
        
        users = User.query.join(User.courses).filter(Course.code == target_course_code).all()
        matches = []
        for user in users:
            if (not target_vibe) or (target_vibe.lower() == user.study_vibe.lower()):
                matches.append({
                    "name": user.name, 
                    "study_vibe": user.study_vibe, 
                    "id": user.id,
                    "matched_courses": [target_course_code]
                })
        return jsonify({"matches": matches})
        
    user = User.query.get(session['user_id'])
    return render_template('index.html', user=user)

# SocketIO Events for Real-time Chat
@socketio.on('join')
def on_join(data):
    username = data.get('username')
    room = data.get('room')
    join_room(room)
    print(f"{username} has joined room: {room}")

@app.route('/schedule', methods=['POST'])
def schedule_session():
    if 'user_id' not in session:
        return redirect(url_for('login_page'))
    
    course_code = request.form.get('course_code')
    room_id = request.form.get('room_id', 'GLOBAL')
    
    session_obj = StudySession(course_code=course_code, room_id=room_id)
    db.session.add(session_obj)
    db.session.commit()
    flash('Study session scheduled successfully! 📅')
    return redirect(url_for('dashboard'))

@socketio.on('send_buddy_msg')
def handle_buddy_msg(data):
    room = data.get('room')
    msg = data.get('message')
    sender = data.get('sender')
    emit('receive_buddy_msg', {'message': msg, 'sender': sender}, room=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', debug=True, port=port)
