from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3


# Create a Blueprint for user routes
user_bp = Blueprint('user', __name__)

def init_user_db():
    conn = sqlite3.connect('home_service.db')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            mobile TEXT NOT NULL,
            password TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (service_id) REFERENCES services (id),
            UNIQUE (user_id, service_id)  -- Ensure a user can only favorite a service once
        )
    ''')
    
    conn.commit()
    conn.close()

# Initialize user table
init_user_db()

@user_bp.route('/register', methods=['POST'])
def register_user():
    try:
        data = request.get_json()
        required_fields = ['name', 'email', 'mobile', 'password']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        # Hash password
        hashed_password = generate_password_hash(data['password'])

        # Store in database
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO users (name, email, mobile, password)
            VALUES (?, ?, ?, ?)
        ''', (
            data['name'],
            data['email'],
            data['mobile'],
            hashed_password
        ))
        
        conn.commit()
        user_id = c.lastrowid
        conn.close()

        return jsonify({
            'message': 'User registered successfully',
            'user_id': user_id
        }), 201

    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already exists'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@user_bp.route('/login', methods=['POST'])
def login_user():
    try:
        data = request.get_json()
        
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({'error': 'Email and password are required'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('SELECT * FROM users WHERE email = ?', (data['email'],))
        user = c.fetchone()
        conn.close()

        if not user:
            return jsonify({'error': 'Invalid email or password'}), 401

        # Check password
        if not check_password_hash(user[4], data['password']):
            return jsonify({'error': 'Invalid email or password'}), 401

        return jsonify({
            'message': 'Login successful',
            'user_id': user[0],
            'name': user[1],
            'email': user[2],
            'mobile': user[3]
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@user_bp.route('/users', methods=['GET'])
def get_all_users():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT id, name, email, mobile, created_at 
            FROM users
            ORDER BY created_at DESC
        ''')
        
        users = c.fetchall()
        conn.close()

        users_list = [{
            'id': user[0],
            'name': user[1],
            'email': user[2],
            'mobile': user[3],
            'created_at': user[4]
        } for user in users]

        return jsonify({
            'total_users': len(users_list),
            'users': users_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@user_bp.route('/favorites', methods=['POST'])
def add_favorite():
    try:
        data = request.get_json()
        required_fields = ['user_id', 'service_id']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if the service exists
        c.execute('SELECT id FROM services WHERE id = ?', (data['service_id'],))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Service not found'}), 404

        # Add favorite
        c.execute('''
            INSERT INTO favorites (user_id, service_id)
            VALUES (?, ?)
        ''', (data['user_id'], data['service_id']))
        
        conn.commit()
        conn.close()

        return jsonify({'message': 'Service added to favorites successfully'}), 201

    except sqlite3.IntegrityError:
        return jsonify({'error': 'This service is already in your favorites'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@user_bp.route('/favorites', methods=['DELETE'])
def unfavorite_service():
    try:
        data = request.get_json()
        required_fields = ['user_id', 'service_id']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if the favorite exists
        c.execute('SELECT id FROM favorites WHERE user_id = ? AND service_id = ?', (data['user_id'], data['service_id']))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Favorite not found'}), 404

        # Remove favorite
        c.execute('DELETE FROM favorites WHERE user_id = ? AND service_id = ?', (data['user_id'], data['service_id']))
        
        conn.commit()
        conn.close()

        return jsonify({'message': 'Service removed from favorites successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500