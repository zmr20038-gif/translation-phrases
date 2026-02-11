import os
import re
import json
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename
import PyPDF2
import requests
from datetime import datetime

# ==========================================
# LexiFlow MTI v8.3 - 纯净解析版
# ==========================================
app = Flask(__name__)
CORS(app) # 允许跨域，确保前端能顺利调用

app.config['UPLOAD_FOLDER'] = 'uploads'
# --- 必须填写的配置 ---
AI_API_KEY = "在这里填入你的_SiliconFlow_Key" 
AI_BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"
AI_MODEL = "deepseek-ai/DeepSeek-V3"

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# ==========================================
# 核心逻辑：AI 增强函数
# ==========================================
def fetch_ai_enrichment(word, meaning):
    """同步调用 AI，为 PDF 导入提供即时增强"""
    prompt = f"为单词'{word}'(释义:{meaning})提供：1.核心解析；2.英文例句；3.例句翻译。格式严格遵循：解析：xxx\n例句：xxx\n翻译：xxx"
    
    headers = {
        "Authorization": f"Bearer {AI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": AI_MODEL,
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        response = requests.post(AI_BASE_URL, json=payload, headers=headers, timeout=10)
        res_data = response.json()
        return res_data['choices'][0]['message']['content']
    except:
        return "AI 解析暂时不可用"

# ==========================================
# 核心路由：PDF 解析引擎
# ==========================================
@app.route('/')
def health_check():
    return "LexiFlow AI Parser is Running!"

@app.route('/import_pdf', methods=['POST'])
def import_pdf():
    file = request.files.get('pdf_file')
    mode = request.form.get('mode', 'en_cn') # en_cn 或 cn_en
    
    if not file or not file.filename.endswith('.pdf'):
        return jsonify({"error": "请上传有效的 PDF 文件"}), 400

    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)
    
    parsed_items = []
    
    try:
        reader = PyPDF2.PdfReader(path)
        # 优化后的正则表达式：更强的兼容性
        # 支持：单词 [空格/制表符] 翻译
        pattern = re.compile(r'(.+?)[\s\t]+(.+)') 
        
        # 为了响应速度，PDF 导入建议限制前 20 个单词进行 AI 增强
        count = 0
        for page in reader.pages:
            text = page.extract_text()
            if not text: continue
            
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if not line: continue
                
                match = pattern.match(line)
                if match:
                    col1, col2 = match.group(1).strip(), match.group(2).strip()
                    
                    # 模式判断逻辑
                    en_term = col1 if mode == 'en_cn' else col2
                    zh_term = col2 if mode == 'en_cn' else col1
                    
                    # AI 增强 (前 10 条自动增强，后续仅保留词义以确保速度)
                    ai_content = "点击学习时生成详情"
                    if count < 10:
                        ai_content = fetch_ai_enrichment(en_term, zh_term)
                    
                    parsed_items.append({
                        "id": f"pdf_{datetime.now().timestamp()}_{count}",
                        "en": en_term,
                        "zh": zh_term,
                        "ai": ai_content,
                        "ts": int(datetime.now().timestamp() * 1000)
                    })
                    count += 1

        return jsonify({
            "success": True,
            "book_title": filename.replace('.pdf', ''),
            "items": parsed_items
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(path):
            os.remove(path)

if __name__ == '__main__':
    # 确保在本地 5000 端口运行
    app.run(port=5000, debug=True)
