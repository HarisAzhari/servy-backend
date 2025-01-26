import sqlite3
import psycopg2
from psycopg2.extras import execute_values

def migrate_data():
    # Connect to SQLite
    sqlite_conn = sqlite3.connect('home_service.db')
    sqlite_cur = sqlite_conn.cursor()
    
    # Connect to PostgreSQL
    pg_conn = psycopg2.connect(
        dbname="dbname",
        user="username",
        password="password",
        host="localhost"
    )
    pg_cur = pg_conn.cursor()
    
    try:
        # Create tables in PostgreSQL
        pg_cur.execute('''
            CREATE TABLE IF NOT EXISTS service_providers (
                id SERIAL PRIMARY KEY,
                business_photo TEXT NOT NULL,
                business_name TEXT NOT NULL,
                owner_name TEXT NOT NULL,
                service_category TEXT NOT NULL,
                custom_category TEXT,
                email TEXT UNIQUE NOT NULL,
                phone_number TEXT NOT NULL,
                password TEXT NOT NULL,
                total_rating DECIMAL(3,2) DEFAULT NULL,
                rating_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Migrate service providers
        sqlite_cur.execute('SELECT * FROM service_providers')
        providers = sqlite_cur.fetchall()
        if providers:
            execute_values(pg_cur,
                'INSERT INTO service_providers (id, business_photo, business_name, owner_name, service_category, custom_category, email, phone_number, password, total_rating, rating_count, created_at) VALUES %s',
                providers
            )
        
        # Create and migrate other tables similarly...
        # (services, users, bookings, reviews, etc.)
        
        pg_conn.commit()
        print("Migration completed successfully!")
        
    except Exception as e:
        pg_conn.rollback()
        print(f"Error during migration: {str(e)}")
        
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == "__main__":
    migrate_data() 