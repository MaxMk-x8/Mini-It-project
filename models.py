from datetime import datetime, timezone, timedelta
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

    is_banned = db.Column(db.Boolean, default=False, nullable=False)
    suspended_until = db.Column(db.DateTime, nullable=True)
    suspension_reason = db.Column(db.String(255), nullable=True)

    # Verification OTP security
    verification_code_created_at = db.Column(db.DateTime, nullable=True)
    verification_attempts = db.Column(db.Integer, default=0, nullable=False)
    verification_resend_available_at = db.Column(db.DateTime, nullable=True)

    # Login Lockout
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)

    # Password Reset OTP
    reset_code = db.Column(db.String(6), nullable=True)
    reset_code_created_at = db.Column(db.DateTime, nullable=True)
    reset_attempts = db.Column(db.Integer, default=0, nullable=False)
    reset_resend_available_at = db.Column(db.DateTime, nullable=True)

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

    @property
    def reputation_points(self):
        """Sum of points earned across all answers authored by this user (50 pts per Prof mark, 5 pts per Student mark)."""
        return sum(ans.total_points for ans in self.answers)

    @property
    def professor_endorsements_count(self):
        """Total number of professor marks received on answers."""
        return sum(ans.professor_marks_count for ans in self.answers)

    @property
    def has_pending_moderator_application(self):
        return any(app.status == 'pending' for app in self.moderator_applications)

    @property
    def latest_moderator_application(self):
        if not self.moderator_applications:
            return None
        return sorted(self.moderator_applications, key=lambda a: a.created_at, reverse=True)[0]

    def is_locked_out(self):
        if self.locked_until:
            now = datetime.now(timezone.utc)
            locked_until = self.locked_until
            if locked_until.tzinfo is None:
                locked_until = locked_until.replace(tzinfo=timezone.utc)
            if now < locked_until:
                remaining = int((locked_until - now).total_seconds())
                return True, max(1, remaining)
            else:
                self.locked_until = None
                self.failed_login_attempts = 0
                db.session.commit()
        return False, 0

    def record_failed_login(self, max_attempts=5, lockout_seconds=60):
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.now(timezone.utc) + timedelta(seconds=lockout_seconds)
            db.session.commit()
            return True, lockout_seconds
        db.session.commit()
        return False, max_attempts - self.failed_login_attempts

    def reset_login_lockout(self):
        self.failed_login_attempts = 0
        self.locked_until = None
        db.session.commit()

    def is_suspended(self):
        if self.suspended_until:
            now = datetime.now(timezone.utc)
            suspended_until = self.suspended_until
            if suspended_until.tzinfo is None:
                suspended_until = suspended_until.replace(tzinfo=timezone.utc)
            if now < suspended_until:
                return True
            else:
                self.suspended_until = None
                self.suspension_reason = None
                db.session.commit()
        return False

    def get_suspension_status(self):
        if self.is_suspended():
            return True, self.suspended_until, self.suspension_reason
        return False, None, None

    @property
    def unread_warnings_count(self):
        return sum(1 for w in self.warnings_received if not w.is_read)

    def is_verification_code_valid(self, code):
        if not self.verification_code:
            return False, "No verification code has been requested."
        if (self.verification_attempts or 0) >= 5:
            return False, "Maximum verification attempts exceeded (5/5). Please request a new code."

        now = datetime.now(timezone.utc)
        if self.verification_code_created_at:
            created_at = self.verification_code_created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (now - created_at).total_seconds() > 300:
                return False, "Verification code has expired (5-minute limit). Please request a new code."

        if str(code).strip() == str(self.verification_code).strip():
            return True, None

        self.verification_attempts = (self.verification_attempts or 0) + 1
        db.session.commit()
        remaining = 5 - self.verification_attempts
        if remaining <= 0:
            return False, "Invalid code. Maximum attempts exceeded (5/5). Please request a new code."
        return False, f"Invalid verification code. Attempts remaining: {remaining}/5."

    def is_reset_code_valid(self, code):
        if not self.reset_code:
            return False, "No password reset code has been requested."
        if (self.reset_attempts or 0) >= 5:
            return False, "Maximum reset attempts exceeded (5/5). Please request a new reset code."

        now = datetime.now(timezone.utc)
        if self.reset_code_created_at:
            created_at = self.reset_code_created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if (now - created_at).total_seconds() > 300:
                return False, "Password reset code has expired (5-minute limit). Please request a new code."

        if str(code).strip() == str(self.reset_code).strip():
            return True, None

        self.reset_attempts = (self.reset_attempts or 0) + 1
        db.session.commit()
        remaining = 5 - self.reset_attempts
        if remaining <= 0:
            return False, "Invalid code. Maximum attempts exceeded (5/5). Please request a new reset code."
        return False, f"Invalid reset code. Attempts remaining: {remaining}/5."

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
    views = db.Column(db.Integer, nullable=False, default=0)
    
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
    attachments = db.relationship(
        'QAAttachment',
        foreign_keys='QAAttachment.question_id',
        back_populates='question',
        cascade='all, delete-orphan',
        lazy=True
    )

    def __init__(self, title=None, content=None, category='General', faculty=FACULTY_CODES[0], author_id=None, best_answer_id=None, views=0, **kwargs):
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
        self.views = views

    def __repr__(self):
        return f'<Question {self.id}: {self.title[:30]}>'


class Answer(db.Model):
    __tablename__ = 'answers'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    is_best_answer = db.Column(db.Boolean, default=False)
    
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', name='fk_answers_question_id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_answers_author_id'), nullable=False)
    
    # --- Reply-to-answer feature (Habib) ---
    parent_answer_id = db.Column(db.Integer, db.ForeignKey('answers.id', name='fk_answers_parent_answer_id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    author = db.relationship('User', backref=db.backref('answers', lazy=True))
    question = db.relationship('Question', foreign_keys=[question_id], back_populates='answers')

    # --- Reply-to-answer feature (Habib) ---
    parent_answer = db.relationship('Answer', remote_side=[id], backref=db.backref('replies', lazy=True, cascade='all, delete-orphan'))

    # Best answer marks (community voting)
    best_marks = db.relationship('AnswerBestMark', backref='answer', lazy=True, cascade='all, delete-orphan')

    # Screenshot attachments (Habib - Week 4)
    attachments = db.relationship(
        'QAAttachment',
        foreign_keys='QAAttachment.answer_id',
        back_populates='answer',
        cascade='all, delete-orphan',
        lazy=True
    )

    @property
    def best_marks_count(self):
        return len(self.best_marks)

    @property
    def professor_marks(self):
        return [m for m in self.best_marks if m.user and m.user.is_professor()]

    @property
    def student_marks(self):
        return [m for m in self.best_marks if m.user and not m.user.is_professor()]

    @property
    def professor_marks_count(self):
        return len(self.professor_marks)

    @property
    def student_marks_count(self):
        return len(self.student_marks)

    @property
    def has_professor_endorsement(self):
        return self.professor_marks_count > 0

    @property
    def total_points(self):
        # 50 points per Professor endorsement, 5 points per Student mark
        return (self.professor_marks_count * 50) + (self.student_marks_count * 5)

    def is_marked_by(self, user):
        if not user or not user.is_authenticated:
            return False
        return any(m.user_id == user.id for m in self.best_marks)

    def __init__(self, content=None, question_id=None, author_id=None, is_best_answer=False, parent_answer_id=None, **kwargs):
        super().__init__(**kwargs)
        if content:
            self.content = content
        if question_id:
            self.question_id = question_id
        if author_id:
            self.author_id = author_id
        self.is_best_answer = is_best_answer
        # --- Reply-to-answer feature (Habib) ---
        self.parent_answer_id = parent_answer_id

    def __repr__(self):
        return f'<Answer {self.id} for Question {self.question_id}>'


class QAAttachment(db.Model):
    """Screenshot attachment for Questions, Answers, and Replies (Habib - Week 4)."""
    __tablename__ = 'qa_attachments'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)  # Original uploaded name
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    file_type = db.Column(db.String(20), nullable=False)  # png, jpg, jpeg, webp

    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', name='fk_qa_attachments_question_id'), nullable=True)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id', name='fk_qa_attachments_answer_id'), nullable=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_qa_attachments_uploader_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    question = db.relationship('Question', foreign_keys=[question_id], back_populates='attachments')
    answer = db.relationship('Answer', foreign_keys=[answer_id], back_populates='attachments')
    uploader = db.relationship('User', backref=db.backref('qa_attachments', lazy=True))

    def __init__(self, filename=None, stored_filename=None, file_size=0, file_type=None, question_id=None, answer_id=None, uploader_id=None, **kwargs):
        super().__init__(**kwargs)
        if filename:
            self.filename = filename
        if stored_filename:
            self.stored_filename = stored_filename
        self.file_size = file_size
        if file_type:
            self.file_type = file_type
        self.question_id = question_id
        self.answer_id = answer_id
        if uploader_id:
            self.uploader_id = uploader_id

    def __repr__(self):
        return f'<QAAttachment {self.id}: {self.filename} ({self.stored_filename})>'


class AnswerBestMark(db.Model):
    __tablename__ = 'answer_best_marks'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'answer_id', name='uq_user_answer_best_mark'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_answer_best_marks_user_id'), nullable=False)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id', name='fk_answer_best_marks_answer_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    user = db.relationship('User', backref=db.backref('best_marks', lazy=True))

    def __init__(self, user_id=None, answer_id=None, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if answer_id:
            self.answer_id = answer_id

    def __repr__(self):
        return f'<AnswerBestMark user={self.user_id} answer={self.answer_id}>'



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


# -------------------------------
# REPORTING & MODERATION MODULE (MOHAMMAD - WEEK 4)
# -------------------------------

class Report(db.Model):
    __tablename__ = 'reports'
    __table_args__ = (
        db.CheckConstraint(f"faculty IN {tuple(FACULTY_CODES)}", name='ck_report_faculty_valid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_reports_reporter_id'), nullable=False)
    content_type = db.Column(db.String(20), nullable=False)  # 'question', 'answer', 'reply', 'resource'
    content_id = db.Column(db.Integer, nullable=False)
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])
    reason = db.Column(db.String(50), nullable=False)
    details = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'resolved', 'dismissed', 'content_removed'
    content_snippet = db.Column(db.Text, nullable=True)  # Snapshot of title/text in case content is deleted

    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_reports_reviewed_by_id'), nullable=True)
    action_taken = db.Column(db.String(50), nullable=True)  # 'dismissed', 'resolved', 'content_removed'
    reviewed_at = db.Column(db.DateTime, nullable=True)
    decision_note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    reporter = db.relationship('User', foreign_keys=[reporter_id], backref=db.backref('submitted_reports', lazy=True))
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id], backref=db.backref('reviewed_reports', lazy=True))

    def __init__(self, reporter_id=None, content_type=None, content_id=None, faculty=FACULTY_CODES[0], reason=None, details=None, content_snippet=None, status='pending', **kwargs):
        super().__init__(**kwargs)
        if reporter_id:
            self.reporter_id = reporter_id
        if content_type:
            self.content_type = content_type
        if content_id:
            self.content_id = content_id
        self.faculty = faculty
        if reason:
            self.reason = reason
        self.details = details
        self.content_snippet = content_snippet
        self.status = status

    def get_target_content(self):
        """Returns the content object if it still exists in the database, otherwise None."""
        if self.content_type == 'question':
            return db.session.get(Question, self.content_id)
        elif self.content_type in ('answer', 'reply'):
            return db.session.get(Answer, self.content_id)
        elif self.content_type == 'resource':
            return db.session.get(Resource, self.content_id)
        return None

    def __repr__(self):
        return f'<Report {self.id} ({self.content_type} #{self.content_id}) - {self.faculty} - {self.status}>'


# -------------------------------
# MODERATOR APPLICATION MODULE
# -------------------------------

class ModeratorApplication(db.Model):
    __tablename__ = 'moderator_applications'
    __table_args__ = (
        db.CheckConstraint(f"faculty IN {tuple(FACULTY_CODES)}", name='ck_mod_app_faculty_valid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_mod_apps_user_id'), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    matric_number = db.Column(db.String(30), nullable=False)
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='pending')  # 'pending', 'approved', 'rejected'
    admin_note = db.Column(db.Text, nullable=True)

    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_mod_apps_reviewed_by_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reviewed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    applicant = db.relationship('User', foreign_keys=[user_id], backref=db.backref('moderator_applications', lazy=True))
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id], backref=db.backref('reviewed_applications', lazy=True))

    def __init__(self, user_id=None, full_name=None, matric_number=None, faculty=FACULTY_CODES[0], reason=None, status='pending', admin_note=None, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if full_name:
            self.full_name = full_name
        if matric_number:
            self.matric_number = matric_number
        self.faculty = faculty
        if reason:
            self.reason = reason
        self.status = status
        self.admin_note = admin_note

    def __repr__(self):
        return f'<ModeratorApplication #{self.id} for User #{self.user_id} ({self.faculty}) - {self.status}>'


# -------------------------------
# USER DISCIPLINE & INBOX MODELS
# -------------------------------

class BannedEmail(db.Model):
    __tablename__ = 'banned_emails'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    username_snapshot = db.Column(db.String(50), nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    banned_by_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_banned_emails_admin_id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    banned_by_admin = db.relationship('User', foreign_keys=[banned_by_id])

    def __init__(self, email=None, username_snapshot=None, reason=None, banned_by_id=None, **kwargs):
        super().__init__(**kwargs)
        if email:
            self.email = email
        if username_snapshot:
            self.username_snapshot = username_snapshot
        if reason:
            self.reason = reason
        if banned_by_id:
            self.banned_by_id = banned_by_id

    def __repr__(self):
        return f'<BannedEmail {self.email} (Reason: {self.reason})>'


class UserWarning(db.Model):
    __tablename__ = 'user_warnings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_user_warnings_user_id'), nullable=False)
    issued_by_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_user_warnings_issuer_id'), nullable=False)
    sender_role = db.Column(db.String(30), nullable=False, default='Admin')
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])
    title = db.Column(db.String(150), nullable=False, default='Official Account Warning')
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    recipient = db.relationship('User', foreign_keys=[user_id], backref=db.backref('warnings_received', lazy=True, order_by='UserWarning.created_at.desc()'))
    issuer = db.relationship('User', foreign_keys=[issued_by_id], backref=db.backref('warnings_issued', lazy=True))

    def __init__(self, user_id=None, issued_by_id=None, sender_role='Admin', faculty=FACULTY_CODES[0], title='Official Account Warning', message=None, is_read=False, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if issued_by_id:
            self.issued_by_id = issued_by_id
        self.sender_role = sender_role
        self.faculty = faculty
        self.title = title
        if message:
            self.message = message
        self.is_read = is_read

    def __repr__(self):
        return f'<UserWarning #{self.id} to User #{self.user_id} by User #{self.issued_by_id}>'


