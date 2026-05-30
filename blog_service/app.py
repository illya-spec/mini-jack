import os
import sqlite3
import re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'mini_jack_super_secret_key'

UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BAD_WORDS = [
    'залупа', 'пізда', 'хуй', 'блять', 'сука', 'піздец', 'піздєц', 
    'наркотики', 'кокаїн', 'сигарети', 'вейп', 'нікотин', 'сижки'
]

def moderate_text(text):
    if not text:
        return text
    modified_text = text
    weed_context = r'(курит[иаіь]|курив|хапат[иь]|палит[иь]|курильн[аиі])\s+(це|цю|всю)?\s*трав[ауиоюеі]'
    matches = re.finditer(weed_context, modified_text, re.IGNORECASE)
    for match in matches:
        full_phrase = match.group(0)
        censored_phrase = re.sub(r'трав[ауиоюеі]', '#####', full_phrase, flags=re.IGNORECASE)
        modified_text = modified_text.replace(full_phrase, censored_phrase)

    for word in BAD_WORDS:
        matches = re.findall(re.escape(word), modified_text, re.IGNORECASE)
        for match in set(matches):
            censored = '#' * len(match)
            modified_text = modified_text.replace(match, censored)
    return modified_text

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.execute('PRAGMA foreign_keys = ON;')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            image_filename TEXT,
            likes INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0,
            deleted_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL,
            user_id INTEGER,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
        )
    ''')
    conn.commit()
    conn.close()

def clean_old_trash():
    conn = get_db_connection()
    now = datetime.now()
    trash_posts = conn.execute('SELECT id, deleted_at, image_filename FROM posts WHERE is_deleted = 1').fetchall()
    
    for post in trash_posts:
        if post['deleted_at']:
            try:
                del_time = datetime.strptime(post['deleted_at'], '%Y-%m-%d %H:%M:%S')
                if now - del_time > timedelta(days=1):
                    if post['image_filename']:
                        img_path = os.path.join(app.config['UPLOAD_FOLDER'], post['image_filename'])
                        if os.path.exists(img_path):
                            os.remove(img_path)
                    conn.execute('DELETE FROM posts WHERE id = ?', (post['id'],))
            except ValueError:
                pass
    conn.commit()
    conn.close()

@app.route('/register', methods=['GET', 'POST'])
def register():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        if not username or not password:
            error = "Введіть логін та пароль."
        else:
            conn = get_db_connection()
            user_exists = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
            if user_exists:
                error = "Такий користувач вже існує."
            else:
                hashed_pw = generate_password_hash(password)
                cursor = conn.execute('INSERT INTO users (username, password) VALUES (?, ?)', (username, hashed_pw))
                conn.commit()
                session['user_id'] = cursor.lastrowid
                session['username'] = username
                conn.close()
                return redirect(url_for('index'))
            conn.close()
    return render_template('register.html', error=error)

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('index'))
        else:
            error = "Невірний логін або пароль."
            
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.context_processor
def inject_user():
    return dict(current_user_id=session.get('user_id'), current_username=session.get('username'))

@app.route('/')
def index():
    clean_old_trash()
    limit = request.args.get('limit', 5, type=int)
    conn = get_db_connection()
    
    # Завантажуємо на 1 пост більше, щоб дізнатися, чи є наступна сторінка
    posts_rows = conn.execute('''
        SELECT p.*, u.username 
        FROM posts p 
        LEFT JOIN users u ON p.user_id = u.id 
        WHERE p.is_deleted = 0 
        ORDER BY p.id DESC
        LIMIT ?
    ''', (limit + 1,)).fetchall()
    
    has_more = len(posts_rows) > limit
    display_posts = posts_rows[:limit]
    
    posts = []
    for row in display_posts:
        post_data = dict(row)
        comments_rows = conn.execute('''
            SELECT c.*, u.username 
            FROM comments c 
            LEFT JOIN users u ON c.user_id = u.id 
            WHERE c.post_id = ? 
            ORDER BY c.id ASC
        ''', (post_data['id'],)).fetchall()
        post_data['comments'] = [dict(c) for c in comments_rows]
        post_data['comments_count'] = len(post_data['comments'])
        posts.append(post_data)
        
    conn.close()
    return render_template('index.html', posts=posts, limit=limit, has_more=has_more)

@app.route('/create', methods=('GET', 'POST'))
def create():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content']
        
        censored_title = moderate_text(title)
        censored_content = moderate_text(content)

        image_filename = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_filename = filename

        if censored_title and censored_content:
            conn = get_db_connection()
            cursor = conn.cursor()
            user_id = session.get('user_id')
            
            cursor.execute('INSERT INTO posts (user_id, title, content, image_filename) VALUES (?, ?, ?, ?)',
                           (user_id, censored_title, censored_content, image_filename))
            new_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return redirect(url_for('index', created_id=new_id))

    return render_template('create.html')

@app.route('/comment/add/<int:post_id>', methods=['POST'])
def add_comment(post_id):
    comment_text = request.form.get('comment_text', '').strip()
    redirect_target = request.args.get('redirect', 'index')
    
    if comment_text:
        censored_comment = moderate_text(comment_text)
        now_str = datetime.now().strftime('%H:%M')
        user_id = session.get('user_id')
        
        conn = get_db_connection()
        conn.execute('INSERT INTO comments (post_id, user_id, content, created_at) VALUES (?, ?, ?, ?)',
                     (post_id, user_id, censored_comment, now_str))
        conn.commit()
        conn.close()
    
    if redirect_target == 'post':
        return redirect(url_for('post', post_id=post_id))
    
    return redirect(url_for('index', comment_post_id=post_id))

@app.route('/trash')
def trash():
    clean_old_trash()
    conn = get_db_connection()
    posts = conn.execute('SELECT * FROM posts WHERE is_deleted = 1 ORDER BY id DESC').fetchall()
    conn.close()
    return render_template('trash.html', posts=posts)

@app.route('/post/<int:post_id>')
def post(post_id):
    conn = get_db_connection()
    post_row = conn.execute('''
        SELECT p.*, u.username 
        FROM posts p 
        LEFT JOIN users u ON p.user_id = u.id 
        WHERE p.id = ?
    ''', (post_id,)).fetchone()
    
    if post_row is None or post_row['is_deleted'] == 1:
        conn.close()
        return "Пост не знайдено або він у кошику!", 404
        
    post_data = dict(post_row)
    comments_rows = conn.execute('''
        SELECT c.*, u.username 
        FROM comments c 
        LEFT JOIN users u ON c.user_id = u.id 
        WHERE c.post_id = ? 
        ORDER BY c.id ASC
    ''', (post_id,)).fetchall()
    post_data['comments'] = [dict(c) for c in comments_rows]
    post_data['comments_count'] = len(post_data['comments'])
    
    conn.close()
    return render_template('post.html', post=post_data)

@app.route('/like/<int:post_id>', methods=['POST'])
def like_post(post_id):
    conn = get_db_connection()
    conn.execute('UPDATE posts SET likes = likes + 1 WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('index'))

@app.route('/delete/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    conn = get_db_connection()
    post_row = conn.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
    
    if post_row and post_row['user_id'] is not None:
        if post_row['user_id'] != session.get('user_id'):
            conn.close()
            return redirect(url_for('index'))
            
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn.execute('UPDATE posts SET is_deleted = 1, deleted_at = ? WHERE id = ?', (now_str, post_id))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/restore/<int:post_id>', methods=['POST'])
def restore_post(post_id):
    conn = get_db_connection()
    post_row = conn.execute('SELECT user_id FROM posts WHERE id = ?', (post_id,)).fetchone()
    
    if post_row and post_row['user_id'] is not None:
        if post_row['user_id'] != session.get('user_id'):
            conn.close()
            return redirect(url_for('trash'))
            
    conn.execute('UPDATE posts SET is_deleted = 0, deleted_at = NULL WHERE id = ?', (post_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)