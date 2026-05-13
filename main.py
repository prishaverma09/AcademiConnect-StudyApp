from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
import os

app = Flask(__name__)
app.secret_key = 'super_secret_gen_z_key'
socketio = SocketIO(app, cors_allowed_origins="*")

# Dummy database for User Models
# User Profile: Course Codes, Study Vibe, Availability, Private Mode
users_db = [
    {
        "id": 1,
        "name": "Alice",
        "course_codes": ["CS101", "MATH202"],
        "study_vibe": "Quiet Library",
        "availability": ["Monday Morning", "Wednesday Afternoon"],
        "private_mode": False
    },
    {
        "id": 2,
        "name": "Bob",
        "course_codes": ["CS101", "PHYS101"],
        "study_vibe": "Loud Cafe",
        "availability": ["Monday Morning", "Friday Evening"],
        "private_mode": False
    },
    {
        "id": 3,
        "name": "Charlie",
        "course_codes": ["MATH202", "HIST101"],
        "study_vibe": "Quiet Library",
        "availability": ["Wednesday Afternoon", "Saturday Morning"],
        "private_mode": True
    }
]

@app.route('/login')
def login_page():
    if 'user' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/signup', methods=['POST'])
def signup():
    # Capture user details from the signup form
    session['user'] = {
        'name': request.form.get('name', 'Student'),
        'age': request.form.get('age', '18'),
        'college': request.form.get('college', 'University'),
        'year': request.form.get('year', 'Freshman')
    }
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login_page'))

@app.route('/')
@app.route('/index')
@app.route('/index.html')
def index():
    if 'user' not in session:
        return redirect(url_for('login_page'))
    return render_template('index.html', user=session['user'])

@app.route('/match', methods=['POST'])
def match_users():
    """
    Matching Function: A Python route that filters users based on 
    matching Course Codes and overlapping availability/vibe.
    """
    data = request.json
    target_course = data.get('course_code')
    target_availability = data.get('availability')
    target_vibe = data.get('study_vibe')
    
    matches = []
    for user in users_db:
        # Check if course code matches
        if target_course and target_course.upper() in [c.upper() for c in user['course_codes']]:
            # Optional: Check for overlapping availability or study vibe
            # In a real application, you'd calculate overlap. Here we do simple matching.
            vibe_match = (not target_vibe) or (target_vibe.lower() == user['study_vibe'].lower())
            
            if vibe_match:
                match_data = {
                    "name": user['name'],
                    "study_vibe": user['study_vibe'],
                    "matched_courses": [c for c in user['course_codes'] if c.upper() == target_course.upper()]
                }
                matches.append(match_data)
                    
    return jsonify({"matches": matches})

# SocketIO Events for Real-time Chat
@socketio.on('join')
def on_join(data):
    username = data.get('username')
    room = data.get('room')
    join_room(room)
    print(f"{username} has joined room: {room}")

@socketio.on('send_buddy_msg')
def handle_buddy_msg(data):
    room = data.get('room')
    msg = data.get('message')
    sender = data.get('sender')
    emit('receive_buddy_msg', {'message': msg, 'sender': sender}, room=room)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', debug=True, port=port)
