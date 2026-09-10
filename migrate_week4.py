"""
Comprehensive Database Migration Script for CodeNest (Weeks 1 - 4)
Safely ensures all tables and columns across all team modules exist without data loss.
"""
import sqlite3
import os

def migrate_database(db_path='instance/codenest.db'):
    if not os.path.exists(db_path):
        print(f"[Migration] Database file not found at {db_path}. Will be initialized on app launch.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print(f"[Migration] Inspecting and upgrading database at {db_path}...")

    # Helper to check and add column
    def ensure_column(table, column, col_type, default_val=None):
        cursor.execute(f"PRAGMA table_info({table})")
        cols = [r[1] for r in cursor.fetchall()]
        if column not in cols:
            print(f"[Migration] Adding column '{column}' to table '{table}'...")
            default_clause = f" DEFAULT {default_val}" if default_val is not None else ""
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
            if default_val is not None:
                cursor.execute(f"UPDATE {table} SET {column} = {default_val} WHERE {column} IS NULL")

    # 1. USERS table columns
    ensure_column('users', 'is_banned', 'BOOLEAN', 0)
    ensure_column('users', 'suspended_until', 'DATETIME', None)
    ensure_column('users', 'suspension_reason', 'VARCHAR(255)', None)
    ensure_column('users', 'verification_code_created_at', 'DATETIME', None)
    ensure_column('users', 'verification_attempts', 'INTEGER', 0)
    ensure_column('users', 'verification_resend_available_at', 'DATETIME', None)
    ensure_column('users', 'failed_login_attempts', 'INTEGER', 0)
    ensure_column('users', 'locked_until', 'DATETIME', None)
    ensure_column('users', 'reset_code', 'VARCHAR(6)', None)
    ensure_column('users', 'reset_code_created_at', 'DATETIME', None)
    ensure_column('users', 'reset_attempts', 'INTEGER', 0)
    ensure_column('users', 'reset_resend_available_at', 'DATETIME', None)

    # 2. QUESTIONS table columns
    ensure_column('questions', 'views', 'INTEGER', 0)

    # 3. ANSWERS table columns
    ensure_column('answers', 'parent_answer_id', 'INTEGER REFERENCES answers(id)', None)

    # 4. RESOURCES table columns (Week 4 Resource Hub)
    ensure_column('resources', 'download_count', 'INTEGER NOT NULL', 0)
    ensure_column('resources', 'collection_id', 'INTEGER REFERENCES resource_collections(id) ON DELETE CASCADE', None)
    ensure_column('resources', 'relative_path', 'VARCHAR(500)', None)

    # 5. CREATE ALL REQUIRED TABLES IF NOT EXIST
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resource_collections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title VARCHAR(150) NOT NULL,
        description TEXT,
        category VARCHAR(50) NOT NULL DEFAULT 'Lecture Notes',
        faculty VARCHAR(10) NOT NULL DEFAULT 'FCI',
        uploader_id INTEGER NOT NULL,
        created_at DATETIME,
        CONSTRAINT ck_collection_faculty_valid CHECK (faculty IN ('FCI', 'FOM')),
        CONSTRAINT fk_collections_uploader_id FOREIGN KEY (uploader_id) REFERENCES users (id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resource_ratings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rating INTEGER NOT NULL,
        resource_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        created_at DATETIME,
        updated_at DATETIME,
        CONSTRAINT ck_rating_range CHECK (rating >= 1 AND rating <= 5),
        CONSTRAINT uq_resource_user_rating UNIQUE (user_id, resource_id),
        CONSTRAINT fk_resource_ratings_resource_id FOREIGN KEY (resource_id) REFERENCES resources (id) ON DELETE CASCADE,
        CONSTRAINT fk_resource_ratings_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qa_attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename VARCHAR(255) NOT NULL,
        stored_filename VARCHAR(255) NOT NULL UNIQUE,
        file_size INTEGER NOT NULL,
        file_type VARCHAR(20) NOT NULL,
        question_id INTEGER REFERENCES questions(id),
        answer_id INTEGER REFERENCES answers(id),
        uploader_id INTEGER NOT NULL REFERENCES users(id),
        created_at DATETIME
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS answer_best_marks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        answer_id INTEGER NOT NULL REFERENCES answers(id),
        created_at DATETIME,
        CONSTRAINT uq_user_answer_best_mark UNIQUE (user_id, answer_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_id INTEGER NOT NULL REFERENCES users(id),
        content_type VARCHAR(20) NOT NULL,
        content_id INTEGER NOT NULL,
        faculty VARCHAR(10) NOT NULL DEFAULT 'FCI',
        reason VARCHAR(50) NOT NULL,
        details TEXT,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        content_snippet TEXT,
        reviewed_by_id INTEGER REFERENCES users(id),
        action_taken VARCHAR(50),
        reviewed_at DATETIME,
        decision_note TEXT,
        created_at DATETIME,
        CONSTRAINT ck_report_faculty_valid CHECK (faculty IN ('FCI', 'FOM'))
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS moderator_applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        full_name VARCHAR(100) NOT NULL,
        matric_number VARCHAR(30) NOT NULL,
        faculty VARCHAR(10) NOT NULL DEFAULT 'FCI',
        reason TEXT NOT NULL,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        admin_note TEXT,
        reviewed_by_id INTEGER REFERENCES users(id),
        created_at DATETIME,
        reviewed_at DATETIME,
        CONSTRAINT ck_mod_app_faculty_valid CHECK (faculty IN ('FCI', 'FOM'))
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS banned_emails (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email VARCHAR(120) NOT NULL UNIQUE,
        username_snapshot VARCHAR(50),
        reason VARCHAR(255),
        banned_by_id INTEGER REFERENCES users(id),
        created_at DATETIME
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id),
        issued_by_id INTEGER NOT NULL REFERENCES users(id),
        sender_role VARCHAR(30) NOT NULL DEFAULT 'Admin',
        faculty VARCHAR(10) NOT NULL DEFAULT 'FCI',
        title VARCHAR(150) NOT NULL DEFAULT 'Official Account Warning',
        message TEXT NOT NULL,
        is_read BOOLEAN NOT NULL DEFAULT 0,
        created_at DATETIME
    )
    """)

    conn.commit()
    conn.close()
    print("[Migration] All database tables and columns are fully up to date.")

if __name__ == '__main__':
    migrate_database()
