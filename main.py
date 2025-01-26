from flask import Flask, request, jsonify, send_file, url_for, make_response
from flask_cors import CORS
import sqlite3
import base64
from werkzeug.security import generate_password_hash, check_password_hash
from user_routes import user_bp
from booking_routes import booking_bp
import os
from werkzeug.utils import secure_filename
from datetime import datetime


app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {  # This will cover all /api/ routes including blueprints
        "origins": "*",  # Allow all origins
        "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
        "allow_headers": ["Content-Type", "Authorization"],
        "supports_credentials": True
    }
})

# Add explicit CORS handling for preflight requests
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")  # Allow all origins
        response.headers.add('Access-Control-Allow-Headers', "Content-Type, Authorization")
        response.headers.add('Access-Control-Allow-Methods', "GET, POST, PUT, DELETE, OPTIONS, PATCH")
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response

# Register blueprints after CORS configuration
app.register_blueprint(user_bp, url_prefix='/api/user')
app.register_blueprint(booking_bp, url_prefix='/api/booking')

# Configure upload settings
UPLOAD_FOLDER = 'uploads'
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'mov', 'avi', 'mkv'}
MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100MB

# Create upload directory if it doesn't exist
os.makedirs(os.path.join(UPLOAD_FOLDER, 'reports'), exist_ok=True)

def allowed_video_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS

# Updated database initialization
def init_db():
    conn = sqlite3.connect('home_service.db')
    c = conn.cursor()
    
    # Existing Service Providers table with added verification status
    c.execute('''
        CREATE TABLE IF NOT EXISTS service_providers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            business_photo TEXT NOT NULL,
            business_name TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            service_category TEXT NOT NULL,
            custom_category TEXT,
            email TEXT UNIQUE NOT NULL,
            phone_number TEXT NOT NULL,
            password TEXT NOT NULL,
            verification_status TEXT DEFAULT 'pending',  -- pending, approved, rejected
            verification_notes TEXT,
            total_rating DECIMAL(3,2) DEFAULT NULL,
            rating_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Existing Services table with added rating fields
    c.execute('''
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id INTEGER NOT NULL,
            service_image TEXT NOT NULL,
            service_title TEXT NOT NULL,
            category TEXT NOT NULL,
            custom_category TEXT,
            price DECIMAL(10,2) NOT NULL,
            duration TEXT NOT NULL,
            service_areas TEXT NOT NULL,
            description TEXT NOT NULL,
            customer_requirements TEXT NOT NULL,
            cancellation_policy TEXT NOT NULL,
            status BOOLEAN NOT NULL DEFAULT 1,
            total_rating DECIMAL(3,2) DEFAULT NULL,
            rating_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES service_providers (id)
        )
    ''')
    
    # New table for Provider Ratings
    c.execute('''
        CREATE TABLE IF NOT EXISTS provider_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            review_text TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES service_providers (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            UNIQUE (provider_id, user_id)
        )
    ''')
    
    # New table for Service Reviews
    c.execute('''
        CREATE TABLE IF NOT EXISTS service_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            booking_id INTEGER,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            review_text TEXT,
            review_response TEXT,
            response_date TIMESTAMP,
            images TEXT,  -- Comma-separated base64 images
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (service_id) REFERENCES services (id),
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (booking_id) REFERENCES bookings (id),
            UNIQUE (service_id, user_id, booking_id)
        )
    ''')
    
    # New table for Provider Reports
    c.execute('''
        CREATE TABLE IF NOT EXISTS provider_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            description TEXT,
            video_path TEXT,  -- Store file path instead of base64
            status TEXT DEFAULT 'pending',  -- pending, reviewed, resolved, dismissed
            admin_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (provider_id) REFERENCES service_providers (id),
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Create indexes for better query performance
    c.execute('''CREATE INDEX IF NOT EXISTS idx_provider_ratings_provider 
                 ON provider_ratings (provider_id)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_service_reviews_service 
                 ON service_reviews (service_id)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_service_reviews_user 
                 ON service_reviews (user_id)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_provider_reports_provider 
                 ON provider_reports (provider_id)''')
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

def validate_base64_image(base64_string):
    try:
        # Check if the string starts with data:image
        if not base64_string.startswith('data:image'):
            return False
        # Extract the actual base64 data after the comma
        image_data = base64_string.split(',')[1]
        # Try to decode it
        base64.b64decode(image_data)
        return True
    except Exception:
        return False

# Updated provider registration endpoint
@app.route('/api/provider/register', methods=['POST'])
def register_provider():
    try:
        data = request.get_json()
        required_fields = ['business_photo', 'business_name', 'owner_name', 
                         'service_category', 'email', 'phone_number', 'password']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        # Validate base64 image
        if not validate_base64_image(data['business_photo']):
            return jsonify({'error': 'Invalid image format'}), 400

        # Check if custom category is provided when category is "Other"
        custom_category = None
        if data['service_category'] == 'Other':
            custom_category = data.get('custom_category')
            if not custom_category:
                return jsonify({'error': 'Custom category is required when selecting Other'}), 400

        # Hash password
        hashed_password = generate_password_hash(data['password'])

        # Store in database
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO service_providers 
            (business_photo, business_name, owner_name, service_category, 
             custom_category, email, phone_number, password)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['business_photo'],
            data['business_name'],
            data['owner_name'],
            data['service_category'],
            custom_category,
            data['email'],
            data['phone_number'],
            hashed_password
        ))
        
        conn.commit()
        provider_id = c.lastrowid
        conn.close()

        return jsonify({
            'message': 'Service provider registered successfully',
            'provider_id': provider_id
        }), 201

    except sqlite3.IntegrityError:
        return jsonify({'error': 'Email already exists'}), 409
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/login', methods=['POST'])
def provider_login():
    try:
        data = request.get_json()
        
        if not data or 'email' not in data or 'password' not in data:
            return jsonify({'error': 'Email and password are required'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get provider with verification status
        c.execute('''
            SELECT id, business_name, business_photo, email, password, 
                   verification_status, verification_notes
            FROM service_providers 
            WHERE email = ?
        ''', (data['email'],))
        
        provider = c.fetchone()
        conn.close()
        
        if not provider:
            return jsonify({'error': 'Provider not found'}), 404
            
        # Verify password
        if not check_password_hash(provider[4], data['password']):
            return jsonify({'error': 'Invalid password'}), 401
            
        # Check verification status
        verification_status = provider[5]
        verification_message = None
        
        if verification_status == 'pending':
            verification_message = 'Your account is pending verification. Please wait for admin approval.'
        elif verification_status == 'rejected':
            verification_message = f'Your account verification was rejected. Reason: {provider[6]}'
            
        return jsonify({
            'provider': {
                'id': provider[0],
                'business_name': provider[1],
                'business_photo': provider[2],
                'email': provider[3],
                'verification_status': verification_status,
                'verification_message': verification_message
            },
            'can_create_services': verification_status == 'approved'
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/profile/<int:provider_id>', methods=['GET'])
def get_provider_profile(provider_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('SELECT * FROM service_providers WHERE id = ?', (provider_id,))
        provider = c.fetchone()
        conn.close()

        if not provider:
            return jsonify({'error': 'Provider not found'}), 404

        category_display = provider[4]  # Default to main category
        if provider[4] == 'Other' and provider[5]:  # If category is "Other" and custom_category exists
            category_display = provider[5]

        return jsonify({
            'id': provider[0],
            'business_photo': provider[1],
            'business_name': provider[2],
            'owner_name': provider[3],
            'service_category': provider[4],
            'custom_category': provider[5],
            'category_display': category_display,
            'email': provider[6],
            'phone_number': provider[7]
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/update/<int:provider_id>', methods=['PUT'])
def update_provider(provider_id):
    try:
        data = request.get_json()
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if provider exists
        c.execute('SELECT * FROM service_providers WHERE id = ?', (provider_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Provider not found'}), 404

        update_fields = {}
        field_mapping = {
            'business_name': str,
            'owner_name': str,
            'service_category': str,
            'phone_number': str
        }

        for field, type_conv in field_mapping.items():
            if field in data:
                update_fields[field] = type_conv(data[field])

        # Handle custom category
        if 'service_category' in data:
            if data['service_category'] == 'Other':
                if 'custom_category' not in data or not data['custom_category']:
                    return jsonify({'error': 'Custom category is required when selecting Other'}), 400
                update_fields['custom_category'] = str(data['custom_category'])
            else:
                update_fields['custom_category'] = None

        if 'business_photo' in data:
            if not validate_base64_image(data['business_photo']):
                return jsonify({'error': 'Invalid image format'}), 400
            update_fields['business_photo'] = data['business_photo']

        if update_fields:
            query = 'UPDATE service_providers SET '
            query += ', '.join(f'{key} = ?' for key in update_fields.keys())
            query += ' WHERE id = ?'
            
            c.execute(query, (*update_fields.values(), provider_id))
            conn.commit()

        conn.close()
        return jsonify({'message': 'Provider updated successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/providers', methods=['GET'])
def get_all_providers():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Optional query parameters for filtering
        category = request.args.get('category')
        
        if category:
            if category == 'Other':
                c.execute('''
                    SELECT id, business_photo, business_name, owner_name, 
                           service_category, custom_category, email, phone_number 
                    FROM service_providers 
                    WHERE service_category = ?
                    ORDER BY business_name
                ''', (category,))
            else:
                c.execute('''
                    SELECT id, business_photo, business_name, owner_name, 
                           service_category, custom_category, email, phone_number 
                    FROM service_providers 
                    WHERE service_category = ? OR custom_category = ?
                    ORDER BY business_name
                ''', (category, category))
        else:
            c.execute('''
                SELECT id, business_photo, business_name, owner_name, 
                       service_category, custom_category, email, phone_number 
                FROM service_providers
                ORDER BY business_name
            ''')
            
        providers = c.fetchall()
        conn.close()

        providers_list = []
        for provider in providers:
            category_display = provider[4]  # Default to main category
            if provider[4] == 'Other' and provider[5]:  # If category is "Other" and custom_category exists
                category_display = provider[5]

            providers_list.append({
                'id': provider[0],
                'business_photo': provider[1],
                'business_name': provider[2],
                'owner_name': provider[3],
                'service_category': provider[4],
                'custom_category': provider[5],
                'category_display': category_display,
                'email': provider[6],
                'phone_number': provider[7]
            })

        return jsonify({
            'total_providers': len(providers_list),
            'providers': providers_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Updated service creation endpoint
@app.route('/api/services/create', methods=['POST'])
def create_service():
    try:
        data = request.get_json()
        
        # First check if provider is verified
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT verification_status 
            FROM service_providers 
            WHERE id = ?
        ''', (data['provider_id'],))
        
        provider = c.fetchone()
        
        if not provider:
            conn.close()
            return jsonify({'error': 'Provider not found'}), 404            
        if provider[0] != 'approved':
            conn.close()
            return jsonify({
                'error': 'Provider not verified',
                'verification_status': provider[0]
            }), 403

        required_fields = [
            'provider_id', 'service_image', 'service_title', 'category', 
            'price', 'duration', 'service_areas', 'description', 
            'customer_requirements', 'cancellation_policy'
        ]
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        # Check if custom category is provided when category is "Other"
        custom_category = None
        if data['category'] == 'Other':
            custom_category = data.get('custom_category')
            if not custom_category:
                return jsonify({'error': 'Custom category is required when selecting Other'}), 400

        # Validate base64 image
        if not validate_base64_image(data['service_image']):
            return jsonify({'error': 'Invalid image format'}), 400

        # Validate service areas
        if not isinstance(data['service_areas'], list) or not data['service_areas']:
            return jsonify({'error': 'At least one service area is required'}), 400

        # Get status with default True (active)
        status = data.get('status', True)
        if status not in [True, 'pending', 'approved', 'completed', 'cancelled', 'paid_deposit']:
            return jsonify({'error': 'Invalid status'}), 400

        # Store in database
        c.execute('''
            INSERT INTO services 
            (provider_id, service_image, service_title, category, custom_category,
             price, duration, service_areas, description, customer_requirements, 
             cancellation_policy, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            data['provider_id'],
            data['service_image'],
            data['service_title'],
            data['category'],
            custom_category,
            float(data['price']),
            data['duration'],
            ','.join(data['service_areas']),
            data['description'],
            data['customer_requirements'],
            data['cancellation_policy'],
            status
        ))
        
        conn.commit()
        service_id = c.lastrowid
        conn.close()

        return jsonify({
            'message': 'Service created successfully',
            'service_id': service_id,
            'status': status
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Get provider services with status
@app.route('/api/services/provider/<int:provider_id>', methods=['GET'])
def get_provider_services(provider_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Optional status filter
        status = request.args.get('status')
        
        query = '''
            SELECT * FROM services 
            WHERE provider_id = ?
        '''
        params = [provider_id]

        if status is not None:
            query += ' AND status = ?'
            params.append(int(status))

        query += ' ORDER BY created_at DESC'
        
        c.execute(query, params)
        services = c.fetchall()
        conn.close()

        services_list = []
        for service in services:
            category_display = service[4]  # Default to main category
            if service[4] == 'Other' and service[5]:  # If category is "Other" and custom_category exists
                category_display = service[5]

            services_list.append({
                'id': service[0],
                'service_image': service[2],
                'service_title': service[3],
                'category': service[4],
                'custom_category': service[5],
                'category_display': category_display,
                'price': service[6],
                'duration': service[7],
                'service_areas': service[8].split(','),
                'description': service[9],
                'customer_requirements': service[10],
                'cancellation_policy': service[11],
                'status': bool(service[12]),
                'created_at': service[13]
            })

        return jsonify({
            'total_services': len(services_list),
            'services': services_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/services/<int:service_id>', methods=['GET'])
def get_service_details(service_id):
    try:
        user_id = request.args.get('user_id', type=int)  # Get user_id from query parameters
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get service details with provider info
        c.execute('''
            SELECT s.*, p.business_name as provider_name, p.business_photo as provider_photo
            FROM services s
            JOIN service_providers p ON s.provider_id = p.id
            WHERE s.id = ?
        ''', (service_id,))
        
        service = c.fetchone()
        
        if not service:
            return jsonify({'error': 'Service not found'}), 404

        # Get user's review status if user_id is provided
        user_review_status = None
        if user_id:
            c.execute('''
                SELECT id, rating, review_text, created_at, images
                FROM service_reviews 
                WHERE service_id = ? AND user_id = ?
            ''', (service_id, user_id))
            user_review = c.fetchone()
            
            if user_review:
                user_review_status = {
                    'has_reviewed': True,
                    'review_details': {
                        'review_id': user_review[0],
                        'rating': user_review[1],
                        'review_text': user_review[2],
                        'created_at': user_review[3],
                        'images': user_review[4].split(',') if user_review[4] else []
                    }
                }
            else:
                user_review_status = {
                    'has_reviewed': False
                }

        # Determine category display
        category_display = service[4]  # Default to main category
        if service[4] == 'Other' and service[5]:  # If category is "Other" and custom_category exists
            category_display = service[5]

        # Build response data
        response_data = {
            'id': service[0],
            'provider_id': service[1],
            'service_image': service[2],
            'service_title': service[3],
            'category': service[4],
            'custom_category': service[5],
            'category_display': category_display,
            'price': service[6],
            'duration': service[7],
            'service_areas': service[8].split(','),
            'description': service[9],
            'customer_requirements': service[10],
            'cancellation_policy': service[11],
            'status': bool(service[12]),
            'total_rating': service[13],
            'rating_count': service[14],
            'created_at': service[15],
            'provider_name': service[16],
            'provider_photo': service[17]
        }
        
        # Add user review status if available
        if user_review_status is not None:
            response_data['user_review_status'] = user_review_status

        return jsonify(response_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
        
@app.route('/api/booking/<int:booking_id>/user/<int:user_id>/review-status', methods=['GET'])
def check_user_review_status(booking_id, user_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # First check if booking exists and belongs to the user
        c.execute('''
            SELECT b.id, b.service_id, b.status, b.user_id 
            FROM bookings b
            WHERE b.id = ? AND b.user_id = ?
        ''', (booking_id, user_id))
        booking = c.fetchone()
        
        if not booking:
            return jsonify({'error': 'Booking not found or unauthorized'}), 404
            
        # Check if booking is completed
        if booking[2] != 'completed':
            return jsonify({
                'has_reviewed': False,
                'can_review': False,
                'message': 'Booking must be completed before reviewing'
            }), 200
        
        # Check if review exists for this booking
        c.execute('''
            SELECT id, rating, review_text, created_at, images 
            FROM service_reviews 
            WHERE booking_id = ?
        ''', (booking_id,))
        
        review = c.fetchone()
        
        if review:
            return jsonify({
                'has_reviewed': True,
                'can_review': False,
                'review_details': {
                    'review_id': review[0],
                    'rating': review[1],
                    'review_text': review[2],
                    'created_at': review[3],
                    'images': review[4].split(',') if review[4] else []
                }
            }), 200
        else:
            return jsonify({
                'has_reviewed': False,
                'can_review': True,
                'booking_id': booking_id,
                'service_id': booking[1]
            }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
        
@app.route('/api/services/update/<int:service_id>', methods=['PUT'])
def update_service(service_id):
    try:
        data = request.get_json()
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if service exists
        c.execute('SELECT * FROM services WHERE id = ?', (service_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Service not found'}), 404

        update_fields = {}
        field_mapping = {
            'service_title': str,
            'category': str,
            'price': float,
            'duration': str,
            'description': str,
            'customer_requirements': str,
            'cancellation_policy': str
        }

        for field, type_conv in field_mapping.items():
            if field in data:
                update_fields[field] = type_conv(data[field])

        # Handle custom category
        if 'category' in data:
            if data['category'] == 'Other':
                if 'custom_category' not in data or not data['custom_category']:
                    return jsonify({'error': 'Custom category is required when selecting Other'}), 400
                update_fields['custom_category'] = str(data['custom_category'])
            else:
                update_fields['custom_category'] = None

        if 'service_image' in data:
            if not validate_base64_image(data['service_image']):
                return jsonify({'error': 'Invalid image format'}), 400
            update_fields['service_image'] = data['service_image']

        if 'service_areas' in data:
            if not isinstance(data['service_areas'], list) or not data['service_areas']:
                return jsonify({'error': 'At least one service area is required'}), 400
            update_fields['service_areas'] = ','.join(data['service_areas'])

        if update_fields:
            query = 'UPDATE services SET '
            query += ', '.join(f'{key} = ?' for key in update_fields.keys())
            query += ' WHERE id = ?'
            
            c.execute(query, (*update_fields.values(), service_id))
            conn.commit()

        conn.close()
        return jsonify({'message': 'Service updated successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/services/delete/<int:service_id>', methods=['DELETE'])
def delete_service(service_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if service exists
        c.execute('SELECT * FROM services WHERE id = ?', (service_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Service not found'}), 404

        # Delete the service
        c.execute('DELETE FROM services WHERE id = ?', (service_id,))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Service deleted successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    

@app.route('/api/services/<int:service_id>/toggle-status', methods=['PUT'])
def toggle_service_status(service_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if service exists and get current status
        c.execute('SELECT status FROM services WHERE id = ?', (service_id,))
        result = c.fetchone()
        
        if not result:
            conn.close()
            return jsonify({'error': 'Service not found'}), 404

        # Toggle the status
        new_status = not bool(result[0])
        
        c.execute('UPDATE services SET status = ? WHERE id = ?', 
                 (new_status, service_id))
        conn.commit()
        conn.close()

        return jsonify({
            'message': 'Service status updated successfully',
            'service_id': service_id,
            'status': new_status
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Modified get all services endpoint to include custom category
@app.route('/api/services', methods=['GET'])
def get_all_services():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        base_query = '''
            SELECT 
                s.id,
                s.provider_id,
                s.service_image,
                s.service_title,
                s.category,
                s.custom_category,
                s.price,
                s.duration,
                s.service_areas,
                s.description,
                s.customer_requirements,
                s.cancellation_policy,
                s.status,
                s.total_rating,
                s.rating_count,
                s.created_at,
                p.business_name,
                p.business_photo
            FROM services s
            LEFT JOIN service_providers p ON s.provider_id = p.id
            WHERE 1=1
        '''
        
        params = []
        
        # Optional filters
        category = request.args.get('category')
        if category:
            if category == 'Other':
                base_query += ' AND s.category = "Other"'
            else:
                base_query += ' AND (s.category = ? OR (s.category = "Other" AND s.custom_category = ?))'
                params.extend([category, category])

        area = request.args.get('area')
        if area:
            base_query += ' AND s.service_areas LIKE ?'
            params.append(f'%{area}%')
        
        min_price = request.args.get('min_price')
        if min_price:
            base_query += ' AND s.price >= ?'
            params.append(float(min_price))
        
        max_price = request.args.get('max_price')
        if max_price:
            base_query += ' AND s.price <= ?'
            params.append(float(max_price))
        
        status = request.args.get('status')
        if status is not None:
            base_query += ' AND s.status = ?'
            params.append(int(status))
        
        # Add sorting
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'DESC')
        
        valid_sort_fields = {
            'created_at': 's.created_at',
            'price': 's.price',
            'service_title': 's.service_title'
        }
        
        valid_sort_orders = ['ASC', 'DESC']
        
        if sort_by in valid_sort_fields and sort_order in valid_sort_orders:
            base_query += f' ORDER BY {valid_sort_fields[sort_by]} {sort_order}'
        else:
            base_query += ' ORDER BY s.created_at DESC'

        # Execute query
        c.execute(base_query, params)
        services = c.fetchall()
        
        # Process results
        services_list = []
        for service in services:
            # Determine category display
            category = service[4]  # category
            custom_category = service[5]  # custom_category
            category_display = custom_category if category == 'Other' and custom_category else category
            
            service_dict = {
                'id': service[0],
                'provider_id': service[1],
                'service_image': service[2],
                'service_title': service[3],
                'category': category,
                'custom_category': custom_category,
                'category_display': category_display,
                'price': service[6],
                'duration': service[7],
                'service_areas': service[8].split(',') if service[8] else [],
                'description': service[9],
                'customer_requirements': service[10],
                'cancellation_policy': service[11],
                'status': bool(service[12]),
                'total_rating': service[13],
                'rating_count': service[14],
                'created_at': service[15],
                'provider_name': service[16],
                'provider_photo': service[17]
            }
            services_list.append(service_dict)

        return jsonify({
            'total_services': len(services_list),
            'services': services_list
        }), 200

    except Exception as e:
        print(f"Error in get_all_services: {str(e)}")  # Debug log
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# Search services
@app.route('/api/services/search', methods=['GET'])
def search_services():
    try:
        search_term = request.args.get('q', '')
        if not search_term:
            return jsonify({'error': 'Search term is required'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        query = '''
            SELECT s.*, p.business_name as provider_name, p.business_photo as provider_photo 
            FROM services s
            JOIN service_providers p ON s.provider_id = p.id
            WHERE s.service_title LIKE ? 
            OR s.description LIKE ? 
            OR s.category LIKE ?
            OR s.custom_category LIKE ?
            ORDER BY s.created_at DESC
        '''
        
        search_pattern = f'%{search_term}%'
        c.execute(query, (search_pattern, search_pattern, search_pattern, search_pattern))
        services = c.fetchall()
        conn.close()

        services_list = []
        for service in services:
            category_display = service[4]  # Default to main category
            if service[4] == 'Other' and service[5]:  # If category is "Other" and custom_category exists
                category_display = service[5]

            services_list.append({
                'id': service[0],
                'provider_id': service[1],
                'service_image': service[2],
                'service_title': service[3],
                'category': service[4],
                'custom_category': service[5],
                'category_display': category_display,
                'price': service[6],
                'duration': service[7],
                'service_areas': service[8].split(','),
                'description': service[9],
                'customer_requirements': service[10],
                'cancellation_policy': service[11],
                'status': bool(service[12]),
                'created_at': service[13],
                'provider_name': service[14],
                'provider_photo': service[15]
            })

        return jsonify({
            'total_results': len(services_list),
            'services': services_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/categories', methods=['GET'])
def get_categories():
    try:
        # Predefined categories
        predefined_categories = [
            'Carpenter', 'Cleaner', 'Painter', 'Electrician', 
            'AC Repair', 'Plumber', "Men's Salon", "Other"
        ]
        
        # Get custom categories from the database
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get unique custom categories from both providers and services
        c.execute('''
            SELECT DISTINCT custom_category 
            FROM (
                SELECT custom_category FROM service_providers 
                WHERE custom_category IS NOT NULL
                UNION
                SELECT custom_category FROM services 
                WHERE custom_category IS NOT NULL
            )
            ORDER BY custom_category
        ''')
        
        custom_categories = [row[0] for row in c.fetchall()]
        conn.close()

        return jsonify({
            'predefined_categories': predefined_categories,
            'custom_categories': custom_categories
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Provider Rating Endpoints

@app.route('/api/provider/<int:provider_id>/rating', methods=['POST'])
def add_provider_rating(provider_id):
    try:
        data = request.get_json()
        required_fields = ['user_id', 'rating']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
                
        # Validate rating range
        rating = int(data['rating'])
        if rating < 1 or rating > 5:
            return jsonify({'error': 'Rating must be between 1 and 5'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if provider exists
        c.execute('SELECT id FROM service_providers WHERE id = ?', (provider_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Provider not found'}), 404

        try:
            # Insert new rating
            c.execute('''
                INSERT INTO provider_ratings (provider_id, user_id, rating, review_text)
                VALUES (?, ?, ?, ?)
            ''', (provider_id, data['user_id'], rating, data.get('review_text')))
            
            # Update provider's total rating and count
            c.execute('''
                UPDATE service_providers 
                SET total_rating = (
                    SELECT AVG(rating) 
                    FROM provider_ratings 
                    WHERE provider_id = ?
                ),
                rating_count = (
                    SELECT COUNT(*) 
                    FROM provider_ratings 
                    WHERE provider_id = ?
                )
                WHERE id = ?
            ''', (provider_id, provider_id, provider_id))
            
            conn.commit()
            
            # Get updated rating info
            c.execute('''
                SELECT total_rating, rating_count 
                FROM service_providers 
                WHERE id = ?
            ''', (provider_id,))
            rating_info = c.fetchone()
            
            return jsonify({
                'message': 'Rating added successfully',
                'total_rating': rating_info[0],
                'rating_count': rating_info[1]
            }), 201
            
        except sqlite3.IntegrityError:
            # Handle case where user has already rated this provider
            return jsonify({'error': 'User has already rated this provider'}), 409
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/provider/<int:provider_id>/rating', methods=['GET'])
def get_provider_rating(provider_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT COALESCE(AVG(r.rating), 0) as average_rating
            FROM service_providers p
            LEFT JOIN services s ON p.id = s.provider_id
            LEFT JOIN service_reviews r ON s.id = r.service_id
            WHERE p.id = ?
        ''', (provider_id,))
        
        average_rating = round(c.fetchone()[0], 1)
        conn.close()

        return jsonify({
            'average_rating': average_rating
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Service Review Endpoints

@app.route('/api/service/<int:service_id>/review', methods=['POST'])
def add_service_review(service_id):
    try:
        data = request.get_json()
        print("Received data:", data)
        # Check if user exists first
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('SELECT id FROM users WHERE id = ?', (data['user_id'],))
        user = c.fetchone()
        if not user:
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        required_fields = ['user_id', 'rating']
        
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
                
        # Validate rating range
        rating = int(data['rating'])
        if rating < 1 or rating > 5:
            return jsonify({'error': 'Rating must be between 1 and 5'}), 400
            
        # Validate images if provided
        images = data.get('images', [])
        if images:
            if not isinstance(images, list):
                return jsonify({'error': 'Images must be a list'}), 400
            for image in images:
                if not validate_base64_image(image):
                    return jsonify({'error': 'Invalid image format'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if service exists
        c.execute('SELECT id FROM services WHERE id = ?', (service_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Service not found'}), 404

        try:
            # Insert new review
            c.execute('''
                INSERT INTO service_reviews 
                (service_id, user_id, booking_id, rating, review_text, images)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                service_id, 
                data['user_id'],
                data.get('booking_id'),
                rating,
                data.get('review_text'),
                ','.join(images) if images else None
            ))
            
            # Update service's total rating and count
            c.execute('''
                UPDATE services 
                SET total_rating = (
                    SELECT AVG(rating) 
                    FROM service_reviews 
                    WHERE service_id = ?
                ),
                rating_count = (
                    SELECT COUNT(*) 
                    FROM service_reviews 
                    WHERE service_id = ?
                )
                WHERE id = ?
            ''', (service_id, service_id, service_id))
            
            conn.commit()
            
            # Get updated rating info
            c.execute('''
                SELECT total_rating, rating_count 
                FROM services 
                WHERE id = ?
            ''', (service_id,))
            rating_info = c.fetchone()
            
            return jsonify({
                'message': 'Review added successfully',
                'total_rating': rating_info[0],
                'rating_count': rating_info[1]
            }), 201
            
        except sqlite3.IntegrityError:
            # Handle case where user has already reviewed this service booking
            return jsonify({'error': 'User has already reviewed this service booking'}), 409
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/service/<int:service_id>/reviews', methods=['GET'])
def get_service_reviews(service_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get service's overall rating
        c.execute('''
            SELECT total_rating, rating_count 
            FROM services 
            WHERE id = ?
        ''', (service_id,))
        rating_info = c.fetchone()
        
        if not rating_info:
            return jsonify({'error': 'Service not found'}), 404
        
        # Get detailed reviews
        c.execute('''
            SELECT sr.rating, sr.review_text, sr.images, 
                   sr.review_response, sr.response_date,
                   sr.created_at, u.name as user_name, 
                   u.profile_photo
            FROM service_reviews sr
            JOIN users u ON sr.user_id = u.id
            WHERE sr.service_id = ?
            ORDER BY sr.created_at DESC
        ''', (service_id,))
        reviews = c.fetchall()
        
        reviews_list = [{
            'rating': review[0],
            'review_text': review[1],
            'images': review[2].split(',') if review[2] else [],
            'review_response': review[3],
            'response_date': review[4],
            'created_at': review[5],
            'user_name': review[6],
            'user_photo': review[7]
        } for review in reviews]
        
        return jsonify({
            'total_rating': rating_info[0],
            'rating_count': rating_info[1],
            'reviews': reviews_list
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/service/review/<int:review_id>/response', methods=['POST'])
def add_review_response(review_id):
    try:
        data = request.get_json()
        if 'response' not in data:
            return jsonify({'error': 'Response text is required'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if review exists and hasn't been responded to
        c.execute('''
            SELECT sr.id, s.provider_id 
            FROM service_reviews sr
            JOIN services s ON sr.service_id = s.id
            WHERE sr.id = ? AND sr.review_response IS NULL
        ''', (review_id,))
        review = c.fetchone()
        
        if not review:
            conn.close()
            return jsonify({'error': 'Review not found or already responded to'}), 404
            
        # Verify the provider owns this service
        provider_id = data.get('provider_id')
        if provider_id != review[1]:
            conn.close()
            return jsonify({'error': 'Unauthorized to respond to this review'}), 403

        # Add response
        c.execute('''
            UPDATE service_reviews 
            SET review_response = ?, 
                response_date = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (data['response'], review_id))
        
        conn.commit()
        
        return jsonify({
            'message': 'Response added successfully'
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# Helper endpoint to get rating statistics
@app.route('/api/service/<int:service_id>/rating-stats', methods=['GET'])
def get_service_rating_stats(service_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get rating distribution
        c.execute('''
            SELECT rating, COUNT(*) as count
            FROM service_reviews
            WHERE service_id = ?
            GROUP BY rating
            ORDER BY rating DESC
        ''', (service_id,))
        
        distribution = {i: 0 for i in range(5, 0, -1)}  # Initialize counts for all ratings
        for row in c.fetchall():
            distribution[row[0]] = row[1]
            
        # Get total reviews count
        total_reviews = sum(distribution.values())
        
        # Calculate percentages
        distribution_percentage = {
            rating: (count / total_reviews * 100 if total_reviews > 0 else 0)
            for rating, count in distribution.items()
        }

        # Calculate total rating and average rating
        c.execute('''
            SELECT SUM(rating), COUNT(*) 
            FROM service_reviews 
            WHERE service_id = ?
        ''', (service_id,))
        total_rating, review_count = c.fetchone()
        average_rating = total_rating / review_count if review_count > 0 else 0

        return jsonify({
            'distribution': distribution,
            'distribution_percentage': distribution_percentage,
            'total_reviews': total_reviews,
            'total_rating': total_rating or 0,
            'average_rating': average_rating
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/dashboard/stats', methods=['GET'])
def get_dashboard_stats():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get total users
        c.execute('SELECT COUNT(*) FROM users')
        total_users = c.fetchone()[0]
        
        # Get total verified service providers
        c.execute('''
            SELECT COUNT(*) 
            FROM service_providers 
            WHERE verification_status = 'approved'
        ''')
        total_providers = c.fetchone()[0]
        
        # Get total active services from verified providers
        c.execute('''
            SELECT COUNT(*) 
            FROM services s
            JOIN service_providers p ON s.provider_id = p.id
            WHERE s.status = 1 
            AND p.verification_status = 'approved'
        ''')
        total_active_services = c.fetchone()[0]
        
        # Get total completed services from verified providers
        c.execute('''
            SELECT COUNT(*) 
            FROM bookings b
            JOIN service_providers p ON b.provider_id = p.id
            WHERE b.status = 'completed'
            AND p.verification_status = 'approved'
        ''')
        total_completed_services = c.fetchone()[0]
        
        conn.close()
        
        return jsonify({
            'total_users': total_users,
            'total_verified_providers': total_providers,
            'total_active_services': total_active_services,
            'total_completed_services': total_completed_services
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/<int:provider_id>/report', methods=['POST'])
def report_provider(provider_id):
    try:
        # Check if the post request has the video file part
        if 'video' not in request.files and not request.form:
            return jsonify({'error': 'No video file or form data provided'}), 400

        # Get form data
        user_id = request.form.get('user_id')
        reason = request.form.get('reason')
        description = request.form.get('description')

        if not user_id or not reason:
            return jsonify({'error': 'User ID and reason are required'}), 400

        video_path = None
        if 'video' in request.files:
            video = request.files['video']
            if video.filename:
                if not allowed_video_file(video.filename):
                    return jsonify({'error': 'Invalid video format'}), 400

                # Check file size
                video.seek(0, os.SEEK_END)
                size = video.tell()
                if size > MAX_VIDEO_SIZE:
                    return jsonify({'error': 'Video file too large'}), 400
                video.seek(0)

                # Generate unique filename
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = secure_filename(f"{timestamp}_{video.filename}")
                video_path = os.path.join('reports', filename)
                
                # Save the video
                video.save(os.path.join(UPLOAD_FOLDER, video_path))

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if provider exists
        c.execute('SELECT id FROM service_providers WHERE id = ?', (provider_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Provider not found'}), 404

        # Create report
        c.execute('''
            INSERT INTO provider_reports (
                provider_id, user_id, reason, description, 
                video_path, status
            )
            VALUES (?, ?, ?, ?, ?, 'pending')
        ''', (
            provider_id,
            user_id,
            reason,
            description,
            video_path
        ))
        
        conn.commit()
        report_id = c.lastrowid
        conn.close()

        return jsonify({
            'message': 'Report submitted successfully',
            'report_id': report_id
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/reports', methods=['GET'])
def get_provider_reports():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get query parameters
        provider_id = request.args.get('provider_id', type=int)
        status = request.args.get('status')
        
        query = '''
            SELECT pr.*, u.name as reporter_name, u.email as reporter_email,
                   sp.business_name as provider_name
            FROM provider_reports pr
            JOIN users u ON pr.user_id = u.id
            JOIN service_providers sp ON pr.provider_id = sp.id
            WHERE 1=1
        '''
        params = []
        
        if provider_id:
            query += ' AND pr.provider_id = ?'
            params.append(provider_id)
            
        if status:
            query += ' AND pr.status = ?'
            params.append(status)
            
        query += ' ORDER BY pr.created_at DESC'
        
        c.execute(query, params)
        reports = c.fetchall()
        
        # Get report counts per provider
        c.execute('''
            SELECT pr.provider_id, sp.business_name,
                   COUNT(*) as total_reports,
                   SUM(CASE WHEN pr.status = 'pending' THEN 1 ELSE 0 END) as pending_reports
            FROM provider_reports pr
            JOIN service_providers sp ON pr.provider_id = sp.id
            GROUP BY pr.provider_id
        ''')
        report_counts = c.fetchall()
        
        conn.close()

        reports_list = [{
            'id': report[0],
            'provider_id': report[1],
            'user_id': report[2],
            'reason': report[3],
            'description': report[4],
            'has_video': bool(report[5]),
            'status': report[6],
            'admin_notes': report[7],
            'created_at': report[8],
            'updated_at': report[9],
            'reporter_name': report[10],
            'reporter_email': report[11],
            'provider_name': report[12]
        } for report in reports]

        provider_stats = [{
            'provider_id': count[0],
            'provider_name': count[1],
            'total_reports': count[2],
            'pending_reports': count[3]
        } for count in report_counts]

        return jsonify({
            'total_reports': len(reports_list),
            'reports': reports_list,
            'provider_statistics': provider_stats
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/report/<int:report_id>/video', methods=['GET'])
def get_report_video(report_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('SELECT video_path FROM provider_reports WHERE id = ?', (report_id,))
        result = c.fetchone()
        conn.close()

        if not result or not result[0]:
            return jsonify({'error': 'Video not found'}), 404

        video_path = os.path.join(UPLOAD_FOLDER, result[0])
        if not os.path.exists(video_path):
            return jsonify({'error': 'Video file not found'}), 404

        return send_file(video_path)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/report/<int:report_id>', methods=['GET'])
def get_report_details(report_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT pr.*, u.name as reporter_name, u.email as reporter_email,
                   sp.business_name as provider_name
            FROM provider_reports pr
            JOIN users u ON pr.user_id = u.id
            JOIN service_providers sp ON pr.provider_id = sp.id
            WHERE pr.id = ?
        ''', (report_id,))
        
        report = c.fetchone()
        conn.close()

        if not report:
            return jsonify({'error': 'Report not found'}), 404

        # Generate video URL if video exists
        video_url = None
        if report[5]:  # video_path
            video_url = url_for('get_report_video', report_id=report_id, _external=True)

        return jsonify({
            'report': {
                'id': report[0],
                'provider_id': report[1],
                'user_id': report[2],
                'reason': report[3],
                'description': report[4],
                'video_url': video_url,
                'status': report[6],
                'admin_notes': report[7],
                'created_at': report[8],
                'updated_at': report[9],
                'reporter_name': report[10],
                'reporter_email': report[11],
                'provider_name': report[12]
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Admin endpoints for provider verification
@app.route('/api/admin/providers/pending', methods=['GET'])
def get_pending_providers():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT id, business_photo, business_name, owner_name, 
                   service_category, custom_category, email, phone_number,
                   verification_status, verification_notes, created_at
            FROM service_providers
            WHERE verification_status = 'pending'
            ORDER BY created_at DESC
        ''')
        
        providers = c.fetchall()
        conn.close()

        providers_list = [{
            'id': p[0],
            'business_photo': p[1],
            'business_name': p[2],
            'owner_name': p[3],
            'service_category': p[4],
            'custom_category': p[5],
            'email': p[6],
            'phone_number': p[7],
            'verification_status': p[8],
            'verification_notes': p[9],
            'created_at': p[10]
        } for p in providers]

        return jsonify({
            'total_pending': len(providers_list),
            'providers': providers_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/provider/<int:provider_id>/verify', methods=['PUT'])
def verify_provider(provider_id):
    try:
        data = request.get_json()
        if 'status' not in data:
            return jsonify({'error': 'Verification status is required'}), 400
            
        if data['status'] not in ['approved', 'rejected']:
            return jsonify({'error': 'Invalid verification status'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            UPDATE service_providers 
            SET verification_status = ?,
                verification_notes = ?
            WHERE id = ?
        ''', (data['status'], data.get('notes'), provider_id))
        
        conn.commit()
        conn.close()

        return jsonify({
            'message': f'Provider {data["status"]} successfully',
            'provider_id': provider_id,
            'status': data['status']
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/provider/<int:provider_id>/verification-status', methods=['GET'])
def get_provider_verification_status(provider_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT verification_status, verification_notes 
            FROM service_providers 
            WHERE id = ?
        ''', (provider_id,))
        
        result = c.fetchone()
        conn.close()

        if not result:
            return jsonify({'error': 'Provider not found'}), 404

        return jsonify({
            'provider_id': provider_id,
            'verification_status': result[0],
            'verification_notes': result[1]
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/verification/counts', methods=['GET'])
def get_verification_counts():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get counts for each verification status
        c.execute('''
            SELECT 
                verification_status,
                COUNT(*) as count,
                COUNT(CASE WHEN created_at >= date('now', '-7 days') THEN 1 END) as last_7_days,
                COUNT(CASE WHEN created_at >= date('now', '-30 days') THEN 1 END) as last_30_days
            FROM service_providers
            GROUP BY verification_status
        ''')
        
        results = c.fetchall()
        
        # Initialize counts dictionary with zeros
        counts = {
            'pending': {'total': 0, 'last_7_days': 0, 'last_30_days': 0},
            'approved': {'total': 0, 'last_7_days': 0, 'last_30_days': 0},
            'rejected': {'total': 0, 'last_7_days': 0, 'last_30_days': 0}
        }
        
        # Update counts from database results
        for status, total, last_7, last_30 in results:
            if status in counts:
                counts[status] = {
                    'total': total,
                    'last_7_days': last_7 or 0,
                    'last_30_days': last_30 or 0
                }
        
        # Calculate totals
        total_providers = sum(status['total'] for status in counts.values())
        
        # Get latest pending providers
        c.execute('''
            SELECT id, business_name, created_at
            FROM service_providers
            WHERE verification_status = 'pending'
            ORDER BY created_at DESC
            LIMIT 5
        ''')
        latest_pending = [{
            'id': row[0],
            'business_name': row[1],
            'created_at': row[2]
        } for row in c.fetchall()]
        
        conn.close()

        return jsonify({
            'total_providers': total_providers,
            'counts': counts,
            'latest_pending': latest_pending,
            'summary': {
                'pending_percentage': (counts['pending']['total'] / total_providers * 100) if total_providers > 0 else 0,
                'approved_percentage': (counts['approved']['total'] / total_providers * 100) if total_providers > 0 else 0,
                'rejected_percentage': (counts['rejected']['total'] / total_providers * 100) if total_providers > 0 else 0
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/provider/<int:provider_id>/details', methods=['GET'])
def get_provider_details_for_admin(provider_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get provider details including verification status
        c.execute('''
            SELECT id, business_photo, business_name, owner_name, 
                   service_category, custom_category, email, phone_number,
                   verification_status, verification_notes, created_at,
                   total_rating, rating_count
            FROM service_providers 
            WHERE id = ?
        ''', (provider_id,))
        
        provider = c.fetchone()
        
        if not provider:
            conn.close()
            return jsonify({'error': 'Provider not found'}), 404

        # Get any reports filed against this provider
        c.execute('''
            SELECT COUNT(*) as report_count,
                   COUNT(CASE WHEN status = 'pending' THEN 1 END) as pending_reports
            FROM provider_reports
            WHERE provider_id = ?
        ''', (provider_id,))
        
        report_stats = c.fetchone()
        
        # Get service count
        c.execute('''
            SELECT COUNT(*) 
            FROM services 
            WHERE provider_id = ?
        ''', (provider_id,))
        
        service_count = c.fetchone()[0]
        
        # Get booking statistics
        c.execute('''
            SELECT 
                COUNT(*) as total_bookings,
                COUNT(CASE WHEN status = 'completed' THEN 1 END) as completed_bookings,
                COUNT(CASE WHEN status = 'cancelled' THEN 1 END) as cancelled_bookings
            FROM bookings
            WHERE provider_id = ?
        ''', (provider_id,))
        
        booking_stats = c.fetchone()
        
        conn.close()

        # Format the response
        category_display = provider[4]  # Default to main category
        if provider[4] == 'Other' and provider[5]:  # If category is "Other" and custom_category exists
            category_display = provider[5]

        return jsonify({
            'provider': {
                'id': provider[0],
                'business_photo': provider[1],
                'business_name': provider[2],
                'owner_name': provider[3],
                'service_category': provider[4],
                'custom_category': provider[5],
                'category_display': category_display,
                'email': provider[6],
                'phone_number': provider[7],
                'verification_status': provider[8],
                'verification_notes': provider[9],
                'created_at': provider[10],
                'rating': {
                    'total_rating': provider[11],
                    'rating_count': provider[12]
                }
            },
            'statistics': {
                'services': {
                    'total': service_count
                },
                'bookings': {
                    'total': booking_stats[0],
                    'completed': booking_stats[1],
                    'cancelled': booking_stats[2],
                    'completion_rate': (booking_stats[1] / booking_stats[0] * 100) if booking_stats[0] > 0 else 0
                },
                'reports': {
                    'total': report_stats[0],
                    'pending': report_stats[1]
                }
            },
            'timestamps': {
                'registered_at': provider[10],
                'days_since_registration': (datetime.now() - datetime.strptime(provider[10], '%Y-%m-%d %H:%M:%S')).days
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/bookings/monthly-completed', methods=['GET'])
def get_monthly_completed_bookings():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Query to get completed bookings count for each month
        c.execute('''
            WITH RECURSIVE months(month_num) AS (
                SELECT 1
                UNION ALL
                SELECT month_num + 1
                FROM months
                WHERE month_num < 6
            )
            SELECT 
                CASE month_num
                    WHEN 1 THEN 'January'
                    WHEN 2 THEN 'February'
                    WHEN 3 THEN 'March'
                    WHEN 4 THEN 'April'
                    WHEN 5 THEN 'May'
                    WHEN 6 THEN 'June'
                END as Month,
                COALESCE(COUNT(b.id), 0) as Count
            FROM months m
            LEFT JOIN bookings b ON 
                strftime('%m', b.booking_date) = printf('%02d', m.month_num)
                AND strftime('%Y', b.booking_date) = strftime('%Y', 'now')
                AND b.status = 'completed'
            GROUP BY month_num
            ORDER BY month_num
        ''')
        
        results = c.fetchall()
        conn.close()

        monthly_counts = [
            {
                "Month": month,
                "Count": count
            }
            for month, count in results
        ]

        return jsonify(monthly_counts), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/reviews/latest', methods=['GET'])
def get_latest_reviews():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT 
                r.id,
                r.rating,
                r.review_text,
                r.created_at,
                s.service_title,
                u.name as user_name,
                p.business_name as provider_name
            FROM service_reviews r
            JOIN services s ON r.service_id = s.id
            JOIN users u ON r.user_id = u.id
            JOIN service_providers p ON s.provider_id = p.id
            ORDER BY r.created_at DESC
            LIMIT 3
        ''')
        
        reviews = c.fetchall()
        conn.close()

        latest_reviews = [{
            'id': review[0],
            'rating': review[1],
            'review_text': review[2],
            'created_at': review[3],
            'service_title': review[4],
            'user_name': review[5],
            'provider_name': review[6]
        } for review in reviews]

        return jsonify(latest_reviews), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/providers/top', methods=['GET'])
def get_top_providers():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT 
                p.id,
                p.business_name,
                p.business_photo,
                p.service_category,
                p.custom_category,
                p.total_rating,
                p.rating_count,
                COUNT(b.id) as total_bookings,
                COUNT(CASE WHEN b.status = 'completed' THEN 1 END) as completed_bookings
            FROM service_providers p
            LEFT JOIN bookings b ON p.id = b.provider_id
            WHERE p.verification_status = 'approved'
            GROUP BY p.id
            ORDER BY p.total_rating DESC, p.rating_count DESC
            LIMIT 3
        ''')
        
        providers = c.fetchall()
        conn.close()

        top_providers = [{
            'rank': idx + 1,  # Add ranking number
            'id': provider[0],
            'business_name': provider[1],
            'business_photo': provider[2],
            'category': provider[3] if provider[3] != 'Other' else provider[4],
            'rating': {
                'average': provider[5],
                'count': provider[6]
            },
            'bookings': {
                'total': provider[7],
                'completed': provider[8]
            }
        } for idx, provider in enumerate(providers)]

        return jsonify(top_providers), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/api/services/top', methods=['GET'])
def get_top_services():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        c.execute('''
            SELECT 
                s.id,
                s.service_title,
                s.service_image,
                s.category,
                s.custom_category,
                s.price,
                s.total_rating,
                s.rating_count,
                p.business_name as provider_name,
                COUNT(b.id) as total_bookings,
                COUNT(CASE WHEN b.status = 'completed' THEN 1 END) as completed_bookings
            FROM services s
            JOIN service_providers p ON s.provider_id = p.id
            LEFT JOIN bookings b ON s.id = b.service_id
            WHERE p.verification_status = 'approved'
            GROUP BY s.id
            ORDER BY total_bookings DESC
            LIMIT 3
        ''')
        
        services = c.fetchall()
        conn.close()

        top_services = [{
            'id': service[0],
            'service_title': service[1],
            'service_image': service[2],
            'category': service[3] if service[3] != 'Other' else service[4],
            'price': service[5],
            'rating': {
                'average': service[6],
                'count': service[7]
            },
            'provider_name': service[8],
            'bookings': {
                'total': service[9],
                'completed': service[10]
            }
        } for service in services]

        return jsonify(top_services), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/activities/recent', methods=['GET'])
def get_recent_activities():
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get recent bookings
        c.execute('''
            SELECT 
                'booking' as type,
                b.id,
                b.status,
                b.booking_date,
                b.booking_time,
                u.name as user_name,
                s.service_title,
                p.business_name as provider_name,
                b.created_at
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN services s ON b.service_id = s.id
            JOIN service_providers p ON b.provider_id = p.id
            ORDER BY b.created_at DESC
            LIMIT 3
        ''')
        
        bookings = [{
            'type': 'booking',
            'id': row[1],
            'status': row[2],
            'booking_date': row[3],
            'booking_time': row[4],
            'user_name': row[5],
            'service_title': row[6],
            'provider_name': row[7],
            'created_at': row[8]
        } for row in c.fetchall()]
        
        # Get recent reviews
        c.execute('''
            SELECT 
                'review' as type,
                r.id,
                r.rating,
                r.review_text,
                u.name as user_name,
                s.service_title,
                p.business_name as provider_name,
                r.created_at
            FROM service_reviews r
            JOIN users u ON r.user_id = u.id
            JOIN services s ON r.service_id = s.id
            JOIN service_providers p ON s.provider_id = p.id
            ORDER BY r.created_at DESC
            LIMIT 3
        ''')
        
        reviews = [{
            'type': 'review',
            'id': row[1],
            'rating': row[2],
            'review_text': row[3],
            'user_name': row[4],
            'service_title': row[5],
            'provider_name': row[6],
            'created_at': row[7]
        } for row in c.fetchall()]
        
        # Combine and sort all activities by created_at
        all_activities = bookings + reviews
        all_activities.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Return only the 3 most recent activities
        return jsonify(all_activities[:3]), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
