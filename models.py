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


class Question(db.Model):
    __tablename__ = 'questions'
    __table_args__ = (
        db.CheckConstraint(f"faculty IN {tuple(FACULTY_CODES)}", name='ck_question_faculty_valid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False, default='General')
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])
    
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_questions_author_id'), nullable=False)
    best_answer_id = db.Column(
        db.Integer,
        db.ForeignKey('answers.id', name='fk_questions_best_answer_id', use_alter=True),
        nullable=True
    )
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    author = db.relationship('User', backref=db.backref('questions', lazy=True))
    answers = db.relationship(
        'Answer',
        foreign_keys='Answer.question_id',
        back_populates='question',
        cascade='all, delete-orphan',
        lazy=True
    )
    best_answer = db.relationship('Answer', foreign_keys=[best_answer_id], post_update=True)

    def __init__(self, title=None, content=None, category='General', faculty=FACULTY_CODES[0], author_id=None, best_answer_id=None, **kwargs):
        super().__init__(**kwargs)
        if title:
            self.title = title
        if content:
            self.content = content
        self.category = category
        self.faculty = faculty
        if author_id:
            self.author_id = author_id
        if best_answer_id:
            self.best_answer_id = best_answer_id

    def __repr__(self):
        return f'<Question {self.id}: {self.title[:30]}>'


class Answer(db.Model):
    __tablename__ = 'answers'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    is_best_answer = db.Column(db.Boolean, default=False)
    
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', name='fk_answers_question_id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_answers_author_id'), nullable=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    author = db.relationship('User', backref=db.backref('answers', lazy=True))
    question = db.relationship('Question', foreign_keys=[question_id], back_populates='answers')

    def __init__(self, content=None, question_id=None, author_id=None, is_best_answer=False, **kwargs):
        super().__init__(**kwargs)
        if content:
            self.content = content
        if question_id:
            self.question_id = question_id
        if author_id:
            self.author_id = author_id
        self.is_best_answer = is_best_answer

    def __repr__(self):
        return f'<Answer {self.id} for Question {self.question_id}>'


# -------------------------------
# RESOURCE HUB MODULE 
# -------------------------------

class Resource(db.Model):
    __tablename__ = 'resources'
    __table_args__ = (
        db.CheckConstraint(f"faculty IN {tuple(FACULTY_CODES)}", name='ck_resource_faculty_valid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    file_size = db.Column(db.Integer, nullable=False)  # size in bytes
    file_type = db.Column(db.String(20), nullable=False)  # file extension, e.g. pdf, docx
    category = db.Column(db.String(50), nullable=False, default='Lecture Notes')
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])

    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_resources_uploader_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    uploader = db.relationship('User', backref=db.backref('resources', lazy=True))

    def __init__(self, title=None, description=None, filename=None, stored_filename=None, file_size=0, file_type=None, category='Lecture Notes', faculty=FACULTY_CODES[0], uploader_id=None, **kwargs):
        super().__init__(**kwargs)
        if title:
            self.title = title
        if description:
            self.description = description
        if filename:
            self.filename = filename
        if stored_filename:
            self.stored_filename = stored_filename
        self.file_size = file_size
        if file_type:
            self.file_type = file_type
        self.category = category
        self.faculty = faculty
        if uploader_id:
            self.uploader_id = uploader_id

    @property
    def formatted_size(self):
        """Returns human-readable file size."""
        size = self.file_size
        if not size:
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
            size /= 1024.0
        return f"{size:.1f} TB"

    def __repr__(self):
        return f'<Resource {self.id}: {self.title} ({self.filename})>'
