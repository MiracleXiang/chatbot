# app.py - 支持流式回复的后端
from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import requests
import os
import json
import time
from dotenv import load_dotenv

load_dotenv()  # 加载环境变量

app = Flask(__name__)

# Coze API 配置
COZE_API_URL = os.getenv('COZE_API_URL', 'https://api.coze.com/v1/chat')
COZE_API_KEY = os.getenv('COZE_API_KEY')
BOT_ID = os.getenv('BOT_ID')

@app.route('/')
def home():
    return render_template('chat.html')

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message', '').strip()
    conversation_id = request.json.get('conversation_id', '')
    
    if not user_message:
        return jsonify({
            'error': '消息不能为空',
            'reply': '请输入有效内容'
        }), 400
    
    headers = {
        'Authorization': f'Bearer {COZE_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    payload = {
        "bot_id": BOT_ID,
        "user_id": "user_"+str(int(time.time())),  # 唯一用户ID
        "query": user_message,
        "conversation_id": conversation_id,
        "stream": False  # 非流式模式
    }
    
    try:
        response = requests.post(
            COZE_API_URL,
            headers=headers,
            json=payload,
            timeout=(3.05, 15)
        )
        response.raise_for_status()
        
        coze_data = response.json()
        
        # 解析响应
        reply = ""
        if 'messages' in coze_data:
            for msg in coze_data['messages']:
                if msg['type'] == 'answer':
                    reply = msg['content']
                    break
        
        # 更新会话ID
        new_conversation_id = coze_data.get('conversation_id', conversation_id)
        
        return jsonify({
            'reply': reply,
            'conversation_id': new_conversation_id,
            'timestamp': int(time.time())
        })
        
    except requests.exceptions.Timeout:
        return jsonify({
            'error': '请求超时',
            'reply': '响应时间过长，请稍后再试'
        }), 504
    except requests.exceptions.RequestException as e:
        return jsonify({
            'error': str(e),
            'reply': '服务暂时不可用，请稍后再试'
        }), 500
    except Exception as e:
        return jsonify({
            'error': '处理错误',
            'reply': f'系统错误: {str(e)}'
        }), 500

# 新增流式回复端点
@app.route('/stream_chat', methods=['POST'])
def stream_chat():
    user_message = request.json.get('message', '').strip()
    conversation_id = request.json.get('conversation_id', '')
    
    if not user_message:
        return jsonify({
            'error': '消息不能为空',
            'reply': '请输入有效内容'
        }), 400
    
    headers = {
        'Authorization': f'Bearer {COZE_API_KEY}',
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream'  # 重要：设置流式响应头
    }
    
    payload = {
        "bot_id": BOT_ID,
        "user_id": "user_"+str(int(time.time())),
        "query": user_message,
        "conversation_id": conversation_id,
        "stream": True  # 开启流式模式
    }
    
    try:
        # 向Coze API发起流式请求
        coze_response = requests.post(
            COZE_API_URL,
            headers=headers,
            json=payload,
            stream=True,  # 启用流式接收
            timeout=(3.05, 30)  # 延长超时时间
        )
        coze_response.raise_for_status()
        
        # 创建生成器函数处理流式响应
        def generate():
            full_content = ""
            new_conversation_id = conversation_id
            
            # 处理流式响应
            for line in coze_response.iter_lines():
                if line:
                    # 解码并处理SSE格式
                    decoded_line = line.decode('utf-8').strip()
                    if decoded_line.startswith('data:'):
                        event_data = decoded_line[5:].strip()
                        try:
                            data = json.loads(event_data)
                            # 处理消息事件
                            if data.get('event') == 'message':
                                message = data.get('message', {})
                                if message.get('type') == 'answer':
                                    content = message.get('content', '')
                                    full_content += content
                                    # 将内容作为SSE事件发送
                                    yield f"data: {json.dumps({'content': content})}\n\n"
                            
                            # 更新会话ID
                            if 'conversation_id' in data:
                                new_conversation_id = data['conversation_id']
                            
                        except json.JSONDecodeError:
                            # 忽略非JSON行
                            continue
            
            # 流结束时发送完整消息和会话ID
            yield f"data: {json.dumps({'done': True, 'full_content': full_content, 'conversation_id': new_conversation_id})}\n\n"
        
        # 返回流式响应
        return Response(stream_with_context(generate()), content_type='text/event-stream')
    
    except requests.exceptions.RequestException as e:
        # 错误处理（流式响应）
        def error_generate():
            yield f"data: {json.dumps({'error': str(e), 'message': '请求Coze API失败'})}\n\n"
        return Response(error_generate(), content_type='text/event-stream')

if __name__ == '__main__':
    app.run(debug=os.getenv('FLASK_DEBUG', 'False') == 'True', 
            host='0.0.0.0', 
            port=int(os.getenv('PORT', 5000)))