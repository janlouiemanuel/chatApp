from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime
import os
from werkzeug.utils import secure_filename

# 1. Initialize Flask app first
app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///chat.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10 MB limit

# 2. Initialize database
db = SQLAlchemy(app)

# 3. Setup migration AFTER app and db
migrate = Migrate(app, db)

# 4. Initialize SocketIO
socketio = SocketIO(app, cors_allowed_origins="*")

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'docx'}

users = {
    "joy": {"password": "joy", "avatar": "/static/avatars/joy.png"},
    "louie": {"password": "louie", "avatar": "/static/avatars/louie.png"}
}


# 5. Define your database model
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50))
    message = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.String(50))
    seen = db.Column(db.Boolean, default=False)

with app.app_context():
    db.create_all()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    if 'username' in session:
        return redirect(url_for('chat'))
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username in users and users[username]['password'] == password:
            session['username'] = username
            return redirect(url_for('chat'))
        else:
            return render_template('login.html', error="Invalid username or password.", username=username)
    return render_template('login.html', error=None, username=None)


@app.route('/chat')
def chat():
    if 'username' not in session:
        return redirect(url_for('home'))
    messages = Message.query.all()
    return render_template('chat.html', username=session['username'], messages=messages, users=users)

@app.route('/logout')
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))



@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return "No file uploaded", 400

    file = request.files['file']
    if file.filename == '':
        return "No selected file", 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

        # Save file in static/uploads
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)

        # Create a URL for the file
        file_url = url_for('static', filename=f"uploads/{filename}")

        username = session.get('username', 'Unknown')
        timestamp = datetime.now().strftime("%I:%M %p")

        # Save message in database
        new_msg = Message(username=username, file_path=file_url, timestamp=timestamp)
        db.session.add(new_msg)
        db.session.commit()

        # Broadcast message
        socketio.emit('receive_message', {
            'id': new_msg.id,
            'username': username,
            'file_path': file_url,
            'timestamp': new_msg.timestamp,
            'seen': False
        }, broadcast=True)

        return "File uploaded", 200

    return "Invalid file type", 400


@socketio.on('send_message')
def handle_message(data):
    username = data.get('username', 'Unknown')
    message = data.get('message', '')
    timestamp = datetime.now().strftime("%I:%M %p")
    
    new_msg = Message(username=username, message=message, timestamp=timestamp)
    db.session.add(new_msg)
    db.session.commit()

    emit('receive_message', {
        'id': new_msg.id,
        'username': username,
        'message': message,
        'timestamp': timestamp,
        'seen': False
    }, broadcast=True)



@socketio.on('send_file')
def handle_file(data):
    username = data.get('username', 'Unknown')
    filename = secure_filename(data['filename'])

    if not allowed_file(filename):
        return

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

    import base64
    with open(file_path, "wb") as f:
        f.write(base64.b64decode(data['file_data']))

    file_url = url_for('static', filename=f"uploads/{filename}")
    timestamp = datetime.now().strftime("%I:%M %p")

    new_msg = Message(username=username, file_path=file_url, timestamp=timestamp)
    db.session.add(new_msg)
    db.session.commit()

    emit('receive_message', {
        'id': new_msg.id,
        'username': username,
        'file_path': file_url,
        'timestamp': timestamp,
        'seen': False
    }, broadcast=True)

    

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {'username': session.get('username')}, broadcast=True, include_self=False)

@socketio.on('mark_seen')
def mark_seen(data):
    msg = Message.query.get(data['message_id'])
    if msg:
        msg.seen = True
        db.session.commit()
        emit('message_seen', {'message_id': msg.id}, broadcast=True)

if __name__ == '__main__':
    from eventlet import wsgi
    import eventlet
    eventlet.monkey_patch()  # Ensures compatibility for Socket.IO in production
    socketio.run(app, host='0.0.0.0', port=5000)

