import os
import re
import json
import threading
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from datetime import datetime
import PyPDF2
import requests

# ==========================================
# LexiFlow MTI v8.3 核心配置
# ==========================================
app = Flask(__name__)
app.config['SECRET_KEY'] = 'lexiflow_secure_secret_83'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///lexiflow_v83.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'uploads'

# --- AI 配置 (建议使用硅基流动 SiliconFlow 免费额度) ---
AI_API_KEY = "你的_API_KEY_在此" # 请在此处填入你的 API Key
AI_BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"
AI_MODEL = "deepseek-ai/DeepSeek-V3" # 也可以使用其他免费模型

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)

# ==========================================
# 数据库模型 (保持原有逻辑并增量扩展)
# ==========================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    wordbooks = db.relationship('UserWordbook', backref='user', lazy=True)

class Wordbook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    is_free = db.Column(db.Boolean, default=True)
    cover_color = db.Column(db.String(50), default="#3498db")
    words = db.relationship('Word', backref='wordbook', lazy=True, cascade="all, delete-orphan")

class Word(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    wordbook_id = db.Column(db.Integer, db.ForeignKey('wordbook.id'), nullable=False)
    spelling = db.Column(db.String(100), nullable=False) # 英文
    meaning = db.Column(db.String(255), nullable=False)  # 中文基础释义
    # --- v8.3 AI 增强字段 ---
    ai_detail = db.Column(db.Text, nullable=True)        # AI 生成的详细解释
    eg_en = db.Column(db.Text, nullable=True)            # 英文例句
    eg_cn = db.Column(db.Text, nullable=True)            # 例句翻译
    status = db.Column(db.String(20), default="pending") # pending, processing, completed

class UserWordbook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    wordbook_id = db.Column(db.Integer, db.ForeignKey('wordbook.id'), nullable=False)
    book_info = db.relationship('Wordbook')

# ==========================================
# AI 处理引擎 (异步后台)
# ==========================================

def enrich_word_with_ai(word_id):
    """调用 AI 补全单词详情和例句"""
    with app.app_context():
        word = Word.query.get(word_id)
        if not word or not AI_API_KEY.startswith("sk-"): return

        prompt = f"""
        请为单词 '{word.spelling}' (中文释义: {word.meaning}) 生成详细学习资料。
        要求以 JSON 格式返回，包含以下字段：
        - detail: 该词的核心用法简述(30字以内)
        - eg_en: 一句地道的英文例句
        - eg_cn: 该例句的中文翻译
        """
        
        headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": AI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }

        try:
            word.status = "processing"
            db.session.commit()
            
            response = requests.post(AI_BASE_URL, json=payload, headers=headers, timeout=15)
            res_data = response.json()
            content = json.loads(res_data['choices'][0]['message']['content'])
            
            word.ai_detail = content.get('detail')
            word.eg_en = content.get('eg_en')
            word.eg_cn = content.get('eg_cn')
            word.status = "completed"
            db.session.commit()
        except Exception as e:
            word.status = "failed"
            db.session.commit()
            print(f"AI Enrichment Error: {e}")

# ==========================================
# 权限与路由 (继承 v8.2 逻辑)
# ==========================================

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    return redirect(url_for('dashboard')) if 'user_id' in session else redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form.get('username')
        if User.query.filter_by(username=uname).first():
            flash('用户名已存在', 'danger')
        else:
            hashed = generate_password_hash(request.form.get('password'), method='pbkdf2:sha256')
            db.session.add(User(username=uname, password=hashed))
            db.session.commit()
            flash('注册成功', 'success')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('dashboard'))
        flash('登录失败', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    my_books = UserWordbook.query.filter_by(user_id=user_id).all()
    my_book_ids = [ub.wordbook_id for ub in my_books]
    available_books = Wordbook.query.filter(Wordbook.is_free==True, ~Wordbook.id.in_(my_book_ids) if my_book_ids else True).all()
    return render_template('dashboard.html', username=session['username'], my_books=my_books, available_books=available_books)

# --- PDF 导入与逻辑切换 ---
@app.route('/import_pdf', methods=['POST'])
@login_required
def import_pdf():
    file = request.files.get('pdf_file')
    mode = request.form.get('mode') # 'en_cn' (默认) 或 'cn_en'
    title = request.form.get('title', '新词书')
    
    if file and file.filename.endswith('.pdf'):
        filename = secure_filename(file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        
        try:
            reader = PyPDF2.PdfReader(path)
            new_book = Wordbook(title=title, description=f"导入于 {datetime.now().strftime('%Y-%m-%d')}")
            db.session.add(new_book)
            db.session.flush()

            pattern = re.compile(r'([a-zA-Z\s\-]+)\s+(.+)') if mode == 'en_cn' else re.compile(r'([^\x00-\xff]+)\s+([a-zA-Z\s\-]+)')
            
            words_to_enrich = []
            for page in reader.pages:
                lines = page.extract_text().split('\n')
                for line in lines:
                    match = pattern.match(line.strip())
                    if match:
                        col1, col2 = match.group(1).strip(), match.group(2).strip()
                        # 逻辑切换：如果是中-英模式，我们将 col2(英)存入spelling，col1(中)存入meaning
                        spelling = col1 if mode == 'en_cn' else col2
                        meaning = col2 if mode == 'en_cn' else col1
                        
                        w = Word(wordbook_id=new_book.id, spelling=spelling, meaning=meaning)
                        db.session.add(w)
                        words_to_enrich.append(w)
            
            db.session.add(UserWordbook(user_id=session['user_id'], wordbook_id=new_book.id))
            db.session.commit()
            
            # 启动后台线程进行 AI 增强 (为避免超出限制，仅示例前10个单词)
            for w in words_to_enrich[:10]:
                threading.Thread(target=enrich_word_with_ai, args=(w.id,)).start()
                
            flash(f'成功导入，AI 正在后台为您生成例句...', 'success')
        except Exception as e:
            flash(f'解析失败: {e}', 'danger')
        finally:
            if os.path.exists(path): os.remove(path)
            
    return redirect(url_for('dashboard'))

# --- 双向学习路由 ---
@app.route('/study/<int:book_id>')
@login_required
def study(book_id):
    mode = request.args.get('mode', 'en_to_cn') # en_to_cn 或 cn_to_en
    book = Wordbook.query.get_or_404(book_id)
    words = Word.query.filter_by(wordbook_id=book_id).all()
    return render_template('study.html', book=book, words=words, mode=mode)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
