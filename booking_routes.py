from flask import Blueprint, request, jsonify
import sqlite3
from datetime import datetime, timedelta

# Create a Blueprint for booking routes
booking_bp = Blueprint('booking', __name__)

def init_booking_db():
    conn = sqlite3.connect('home_service.db')
    c = conn.cursor()
    
    # Create bookings table
    c.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            service_id INTEGER NOT NULL,
            provider_id INTEGER NOT NULL,
            booking_date DATE NOT NULL,
            booking_time TIME NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',  -- pending, approved, rejected, completed, cancelled
            total_amount DECIMAL(10,2) NOT NULL,
            booking_notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (service_id) REFERENCES services (id),
            FOREIGN KEY (provider_id) REFERENCES service_providers (id)
        )
    ''')
    
    # Create index for better query performance
    c.execute('''CREATE INDEX IF NOT EXISTS idx_bookings_provider 
                 ON bookings (provider_id)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_bookings_service 
                 ON bookings (service_id)''')
    c.execute('''CREATE INDEX IF NOT EXISTS idx_bookings_user 
                 ON bookings (user_id)''')
    
    conn.commit()
    conn.close()

# Initialize booking table
init_booking_db()

@booking_bp.route('/create', methods=['POST'])
def create_booking():
    try:
        data = request.get_json()
        required_fields = ['user_id', 'service_id', 'booking_date', 'booking_time']
        
        # Validate required fields
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        # Validate date and time format
        try:
            booking_date = datetime.strptime(data['booking_date'], '%Y-%m-%d').date()
            booking_time = datetime.strptime(data['booking_time'], '%H:%M').time()
            
            # Check if booking date is in the past
            if booking_date < datetime.now().date():
                return jsonify({'error': 'Cannot book for past dates'}), 400
                
            # Check if booking time is within allowed range (12:00 AM to 11:00 PM)
            booking_datetime = datetime.combine(booking_date, booking_time)
            if booking_datetime < datetime.now():
                return jsonify({'error': 'Cannot book for past time slots'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid date or time format'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get service details
        c.execute('SELECT provider_id, price FROM services WHERE id = ?', (data['service_id'],))
        service = c.fetchone()
        
        if not service:
            conn.close()
            return jsonify({'error': 'Service not found'}), 404
        
        provider_id, service_price = service
        
        # Check if the time slot is available
        c.execute('''
            SELECT COUNT(*) FROM bookings 
            WHERE service_id = ? 
            AND booking_date = ? 
            AND booking_time = ?
            AND status IN ('pending', 'approved', 'paid_deposit')
        ''', (data['service_id'], data['booking_date'], data['booking_time']))
        
        if c.fetchone()[0] > 0:
            conn.close()
            return jsonify({'error': 'This time slot is already booked'}), 409

        # Create booking
        c.execute('''
            INSERT INTO bookings (
                user_id, service_id, provider_id, booking_date, booking_time,
                total_amount, booking_notes, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')
        ''', (
            data['user_id'],
            data['service_id'],
            provider_id,
            data['booking_date'],
            data['booking_time'],
            service_price,
            data.get('booking_notes')
        ))
        
        conn.commit()
        booking_id = c.lastrowid
        
        # Get booking details
        c.execute('''
            SELECT b.*, s.service_title, s.service_image,
                   u.name as user_name, u.mobile as user_mobile,
                   p.business_name as provider_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN users u ON b.user_id = u.id
            JOIN service_providers p ON b.provider_id = p.id
            WHERE b.id = ?
        ''', (booking_id,))
        
        booking = c.fetchone()
        conn.close()

        return jsonify({
            'message': 'Booking created successfully',
            'booking': {
                'id': booking[0],
                'user_id': booking[1],
                'service_id': booking[2],
                'provider_id': booking[3],
                'booking_date': booking[4],
                'booking_time': booking[5],
                'status': booking[6],
                'total_amount': booking[7],
                'booking_notes': booking[8],
                'created_at': booking[9],
                'service_title': booking[11],
                'service_image': booking[12],
                'user_name': booking[13],
                'user_mobile': booking[14],
                'provider_name': booking[15]
            }
        }), 201

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@booking_bp.route('/provider/<int:provider_id>/bookings', methods=['GET'])
def get_provider_bookings(provider_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get query parameters
        status = request.args.get('status')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        query = '''
            SELECT b.*, s.service_title, s.service_image,
                   u.name as user_name, u.mobile as user_mobile
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN users u ON b.user_id = u.id
            WHERE b.provider_id = ?
        '''
        params = [provider_id]
        
        if status:
            query += ' AND b.status = ?'
            params.append(status)
            
        if start_date:
            query += ' AND b.booking_date >= ?'
            params.append(start_date)
            
        if end_date:
            query += ' AND b.booking_date <= ?'
            params.append(end_date)
            
        query += ' ORDER BY b.booking_date DESC, b.booking_time DESC'
        
        c.execute(query, params)
        bookings = c.fetchall()
        conn.close()

        bookings_list = [{
            'id': booking[0],
            'user_id': booking[1],
            'service_id': booking[2],
            'booking_date': booking[4],
            'booking_time': booking[5],
            'status': booking[6],
            'total_amount': booking[7],
            'booking_notes': booking[8],
            'created_at': booking[9],
            'service_title': booking[11],
            'service_image': booking[12],
            'user_name': booking[13],
            'user_mobile': booking[14]
        } for booking in bookings]

        return jsonify({
            'total_bookings': len(bookings_list),
            'bookings': bookings_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@booking_bp.route('/user/<int:user_id>/bookings', methods=['GET'])
def get_user_bookings(user_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get query parameters
        status = request.args.get('status')
        
        query = '''
            SELECT b.*, s.service_title, s.service_image,
                   p.business_name as provider_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN service_providers p ON b.provider_id = p.id
            WHERE b.user_id = ?
        '''
        params = [user_id]
        
        if status:
            query += ' AND b.status = ?'
            params.append(status)
            
        query += ' ORDER BY b.booking_date DESC, b.booking_time DESC'
        
        c.execute(query, params)
        bookings = c.fetchall()
        conn.close()

        bookings_list = [{
            'id': booking[0],
            'service_id': booking[2],
            'provider_id': booking[3],
            'booking_date': booking[4],
            'booking_time': booking[5],
            'status': booking[6],
            'total_amount': booking[7],
            'booking_notes': booking[8],
            'created_at': booking[9],
            'service_title': booking[11],
            'service_image': booking[12],
            'provider_name': booking[13]
        } for booking in bookings]

        return jsonify({
            'total_bookings': len(bookings_list),
            'bookings': bookings_list
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@booking_bp.route('/<int:booking_id>/status', methods=['PUT'])
def update_booking_status(booking_id):
    try:
        data = request.get_json()
        if 'status' not in data:
            return jsonify({'error': 'Status is required'}), 400
            
        # Validate status
        valid_statuses = ['pending', 'approved', 'rejected', 'completed', 'cancelled', 'paid_deposit']
        if data['status'] not in valid_statuses:
            return jsonify({'error': f"Invalid status. Must be one of: {', '.join(valid_statuses)}"}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Check if booking exists
        c.execute('SELECT status FROM bookings WHERE id = ?', (booking_id,))
        booking = c.fetchone()
        
        if not booking:
            conn.close()
            return jsonify({'error': 'Booking not found'}), 404
            
        # Update status
        c.execute('''
            UPDATE bookings 
            SET status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (data['status'], booking_id))
        
        conn.commit()
        conn.close()

        return jsonify({
            'message': 'Booking status updated successfully',
            'booking_id': booking_id,
            'status': data['status']
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@booking_bp.route('/timeslots', methods=['GET'])
def get_available_timeslots():
    try:
        # Get query parameters
        service_id = request.args.get('service_id')
        date = request.args.get('date')
        
        if not service_id or not date:
            return jsonify({'error': 'Service ID and date are required'}), 400
            
        try:
            # Validate date
            booking_date = datetime.strptime(date, '%Y-%m-%d').date()
            if booking_date < datetime.now().date():
                return jsonify({'error': 'Cannot check availability for past dates'}), 400
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400

        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get all booked slots for the service on the specified date
        c.execute('''
            SELECT booking_time 
            FROM bookings 
            WHERE service_id = ? 
            AND booking_date = ?
            AND status IN ('pending', 'approved')
        ''', (service_id, date))
        
        booked_slots = {row[0] for row in c.fetchall()}
        conn.close()

        # Generate all possible time slots (12:00 AM to 11:00 PM)
        all_slots = []
        current_time = datetime.strptime('00:00', '%H:%M').time()
        end_time = datetime.strptime('23:00', '%H:%M').time()
        
        while current_time <= end_time:
            slot = current_time.strftime('%H:%M')
            
            # Check if slot is in the past for today
            if booking_date == datetime.now().date():
                slot_datetime = datetime.combine(booking_date, current_time)
                if slot_datetime <= datetime.now():
                    current_time = (datetime.combine(datetime.min, current_time) + 
                                  timedelta(hours=1)).time()
                    continue
            
            all_slots.append({
                'time': slot,
                'available': slot not in booked_slots
            })
            
            current_time = (datetime.combine(datetime.min, current_time) + 
                          timedelta(hours=1)).time()

        return jsonify({
            'date': date,
            'service_id': service_id,
            'time_slots': all_slots
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@booking_bp.route('/<int:booking_id>', methods=['GET'])
def get_booking_details(booking_id):
    try:
        conn = sqlite3.connect('home_service.db')
        c = conn.cursor()
        
        # Get booking details with related information
        c.execute('''
            SELECT b.*, s.service_title, s.service_image,
                   u.name as user_name, u.mobile as user_mobile,
                   p.business_name as provider_name
            FROM bookings b
            JOIN services s ON b.service_id = s.id
            JOIN users u ON b.user_id = u.id
            JOIN service_providers p ON b.provider_id = p.id
            WHERE b.id = ?
        ''', (booking_id,))
        
        booking = c.fetchone()
        conn.close()

        if not booking:
            return jsonify({'error': 'Booking not found'}), 404

        return jsonify({
            'booking': {
                'id': booking[0],
                'user_id': booking[1],
                'service_id': booking[2],
                'provider_id': booking[3],
                'booking_date': booking[4],
                'booking_time': booking[5],
                'status': booking[6],
                'total_amount': booking[7],
                'booking_notes': booking[8],
                'created_at': booking[9],
                'updated_at': booking[10],
                'service_title': booking[11],
                'service_image': booking[12],
                'user_name': booking[13],
                'user_mobile': booking[14],
                'provider_name': booking[15]
            }
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500