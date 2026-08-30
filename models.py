from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from constants import FACULTY_CODES

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """
    Role is NOT chosen by the user - it is decided automatically
    at registration based on email domain:
        @student.mmu.edu.my -> Student
        @mmu.edu.my          -> Professor
    Moderator / Admin roles can only be granted separately
    (moderator application + approval, or the seed_admin.py script)
    - never through public registration.
    """

    
    __tablename__ = 'users'
    __table_args__ = (
        db.CheckConstraint(f"faculty IN {tuple(FACULTY_CODES)}", name='ck_user_faculty_valid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    role = db.Column(db.String(30), nullable=False, default='Student')
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])
    verification_code = db.Column(db.String(6), nullable=True)
    is_verified = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __init__(self, username=None, email=None, role='Student', faculty=FACULTY_CODES[0], verification_code=None, is_verified=False, **kwargs):
        super().__init__(**kwargs)
        if username:
            self.username = username
        if email:
            self.email = email
        self.role = role
        self.faculty = faculty
        self.verification_code = verification_code
        self.is_verified = is_verified

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_student(self):
        return self.role == 'Student'

    def is_professor(self):
        return self.role == 'Professor'

    def is_moderator(self):
        return self.role == 'Community Moderator'

    def is_admin(self):
        return self.role == 'Admin'

    def __repr__(self):
        return f'<User {self.username} ({self.role} - {self.faculty})>'


