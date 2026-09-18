import uuid
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

    # Week 6 additions: Profiles & Privacy Controls
    bio = db.Column(db.String(500), nullable=True)
    profile_pic = db.Column(db.String(255), nullable=True)
    contact_email = db.Column(db.String(120), nullable=True)
    github_url = db.Column(db.String(200), nullable=True)
    linkedin_url = db.Column(db.String(200), nullable=True)
    website_url = db.Column(db.String(200), nullable=True)
    require_follow_approval = db.Column(db.Boolean, default=False, nullable=False)
    contact_email_privacy = db.Column(db.String(20), default='private', nullable=False)  # 'all', 'followers', 'private'
    social_links_privacy = db.Column(db.String(20), default='all', nullable=False)      # 'all', 'followers', 'private'

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __init__(self, username=None, email=None, role='Student', faculty=FACULTY_CODES[0], verification_code=None, is_verified=False, bio=None, profile_pic=None, contact_email=None, github_url=None, linkedin_url=None, website_url=None, require_follow_approval=False, contact_email_privacy='private', social_links_privacy='all', **kwargs):
        super().__init__(**kwargs)
        if username:
            self.username = username
        if email:
            self.email = email
        self.role = role
        self.faculty = faculty
        self.verification_code = verification_code
        self.is_verified = is_verified
        self.bio = bio
        self.profile_pic = profile_pic
        self.contact_email = contact_email
        self.github_url = github_url
        self.linkedin_url = linkedin_url
        self.website_url = website_url
        self.require_follow_approval = require_follow_approval
        self.contact_email_privacy = contact_email_privacy
        self.social_links_privacy = social_links_privacy

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def is_student(self):
        return bool(self.role and self.role.strip().lower() == 'student')

    def is_professor(self):
        return bool(self.role and self.role.strip().lower() == 'professor')

    def is_moderator(self):
        return bool(self.role and self.role.strip().lower() in ('community moderator', 'moderator'))

    def is_admin(self):
        return bool(self.role and self.role.strip().lower() == 'admin')

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

    @property
    def avatar_url(self):
        if self.profile_pic:
            return f'/uploads/avatars/{self.profile_pic}'
        return None

    def is_following(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return UserFollow.query.filter_by(
            follower_id=self.id,
            followed_id=target_user.id,
            status='accepted'
        ).first() is not None

    def has_pending_follow(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return UserFollow.query.filter_by(
            follower_id=self.id,
            followed_id=target_user.id,
            status='pending'
        ).first() is not None

    def is_followed_by(self, follower_user):
        if not follower_user or not getattr(follower_user, 'id', None):
            return False
        return follower_user.is_following(self)

    def can_view_contact(self, viewer):
        if not self.contact_email:
            return False
        if viewer and viewer.is_authenticated:
            if viewer.id == self.id or viewer.is_admin():
                return True
            if self.contact_email_privacy == 'all':
                return True
            if self.contact_email_privacy == 'followers':
                return viewer.is_following(self)
        return False

    def can_view_social(self, viewer):
        has_social = bool(self.github_url or self.linkedin_url or self.website_url)
        if not has_social:
            return False
        if viewer and viewer.is_authenticated:
            if viewer.id == self.id or viewer.is_admin():
                return True
            if self.social_links_privacy == 'all':
                return True
            if self.social_links_privacy == 'followers':
                return viewer.is_following(self)
        return False

    @property
    def follower_count(self):
        return UserFollow.query.filter_by(followed_id=self.id, status='accepted').count()

    @property
    def following_count(self):
        return UserFollow.query.filter_by(follower_id=self.id, status='accepted').count()

    @property
    def pending_follow_requests_count(self):
        return UserFollow.query.filter_by(followed_id=self.id, status='pending').count()

    def has_saved_question(self, question_id):
        return SavedQuestion.query.filter_by(user_id=self.id, question_id=question_id).first() is not None

    def has_saved_answer(self, answer_id):
        return SavedAnswer.query.filter_by(user_id=self.id, answer_id=answer_id).first() is not None

    def save_answer(self, answer_id):
        if not self.has_saved_answer(answer_id):
            sa = SavedAnswer(user_id=self.id, answer_id=answer_id)
            db.session.add(sa)
            return sa
        return None

    def unsave_answer(self, answer_id):
        sa = SavedAnswer.query.filter_by(user_id=self.id, answer_id=answer_id).first()
        if sa:
            db.session.delete(sa)
            return True
        return False

    @property
    def unread_notifications_count(self):
        return Notification.query.filter_by(user_id=self.id, is_read=False).count()

    def has_blocked_chat(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return ChatBlock.query.filter_by(blocker_id=self.id, blocked_id=target_user.id).first() is not None

    def is_chat_blocked_by(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return ChatBlock.query.filter_by(blocker_id=target_user.id, blocked_id=self.id).first() is not None

    def has_blocked_platform(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return ChatBlock.query.filter_by(blocker_id=self.id, blocked_id=target_user.id, block_scope='platform').first() is not None

    def is_platform_blocked_by(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return ChatBlock.query.filter_by(blocker_id=target_user.id, blocked_id=self.id, block_scope='platform').first() is not None

    def has_any_platform_block_with(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return self.has_blocked_platform(target_user) or self.is_platform_blocked_by(target_user)

    def is_chat_mutually_available(self, target_user):
        if not target_user or not getattr(target_user, 'id', None):
            return False
        return not (self.has_blocked_chat(target_user) or self.is_chat_blocked_by(target_user))

    def unread_chat_count_from(self, peer_user):
        if not peer_user or not getattr(peer_user, 'id', None):
            return 0
        return ChatMessage.query.filter_by(sender_id=peer_user.id, recipient_id=self.id, is_read=False).count()

    @property
    def total_unread_chats_count(self):
        return ChatMessage.query.filter_by(recipient_id=self.id, is_read=False).count()

    @property
    def has_pending_username_request(self):
        return any(r.status == 'pending' for r in self.username_requests)

    @property
    def pending_username_request(self):
        for r in self.username_requests:
            if r.status == 'pending':
                return r
        return None

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
    visibility = db.Column(db.String(20), default='public', nullable=False)  # 'public', 'friends'
    is_draft = db.Column(db.Boolean, default=False, nullable=False)
    
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

    def can_view(self, viewer):
        if viewer and viewer.is_authenticated:
            if self.author and (self.author.has_blocked_platform(viewer) or viewer.has_blocked_platform(self.author)):
                return False
        if self.is_draft:
            return bool(viewer and viewer.is_authenticated and viewer.id == self.author_id)
        if self.visibility == 'public':
            return True
        if viewer and viewer.is_authenticated:
            if viewer.id == self.author_id:
                return True
            if viewer.is_professor() or viewer.is_moderator() or viewer.is_admin():
                return True
            if viewer.is_following(self.author):
                return True
        return False

    def __init__(self, title=None, content=None, category='General', faculty=FACULTY_CODES[0], author_id=None, best_answer_id=None, views=0, visibility='public', is_draft=False, **kwargs):
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
        self.visibility = visibility
        self.is_draft = is_draft

    def __repr__(self):
        return f'<Question {self.id}: {self.title[:30]}>'


class Answer(db.Model):
    __tablename__ = 'answers'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    is_best_answer = db.Column(db.Boolean, default=False)
    visibility = db.Column(db.String(20), default='public', nullable=False)  # 'public', 'friends'
    
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

    # Screenshot attachments (Habib)
    attachments = db.relationship(
        'QAAttachment',
        foreign_keys='QAAttachment.answer_id',
        back_populates='answer',
        cascade='all, delete-orphan',
        lazy=True
    )

    def can_view(self, viewer):
        if viewer and viewer.is_authenticated:
            if self.author and (self.author.has_blocked_platform(viewer) or viewer.has_blocked_platform(self.author)):
                return False
        if self.visibility == 'public':
            return True
        if viewer and viewer.is_authenticated:
            if viewer.id == self.author_id:
                return True
            if viewer.is_professor() or viewer.is_moderator() or viewer.is_admin():
                return True
            if viewer.is_following(self.author):
                return True
        return False

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

    def __init__(self, content=None, question_id=None, author_id=None, is_best_answer=False, parent_answer_id=None, visibility='public', **kwargs):
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
        self.visibility = visibility

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

class ResourceRating(db.Model):
    __tablename__ = 'resource_ratings'
    __table_args__ = (
        db.CheckConstraint('rating >= 1 AND rating <= 5', name='ck_rating_range'),
        db.UniqueConstraint('user_id', 'resource_id', name='uq_resource_user_rating'),
    )

    id = db.Column(db.Integer, primary_key=True)
    rating = db.Column(db.Integer, nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resources.id', name='fk_resource_ratings_resource_id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_resource_ratings_user_id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    resource = db.relationship('Resource', backref=db.backref('ratings', cascade='all, delete-orphan', lazy=True))
    user = db.relationship('User', backref=db.backref('resource_ratings', lazy=True))

    def __init__(self, rating=None, resource_id=None, user_id=None, **kwargs):
        super().__init__(**kwargs)
        if rating is not None:
            self.rating = rating
        if resource_id:
            self.resource_id = resource_id
        if user_id:
            self.user_id = user_id

    def __repr__(self):
        return f'<ResourceRating user={self.user_id} resource={self.resource_id} rating={self.rating}>'


class ResourceReview(db.Model):
    """Endorsement / review by verified faculty (Professors)."""
    __tablename__ = 'resource_reviews'
    __table_args__ = (
        db.UniqueConstraint('resource_id', 'professor_id', name='uq_resource_professor_review'),
    )

    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('resources.id', name='fk_resource_reviews_resource_id', ondelete='CASCADE'), nullable=False)
    professor_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_resource_reviews_professor_id', ondelete='CASCADE'), nullable=False)
    review_note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    resource = db.relationship('Resource', backref=db.backref('reviews', cascade='all, delete-orphan', lazy=True))
    professor = db.relationship('User', backref=db.backref('professor_reviews', lazy=True))

    def __init__(self, resource_id=None, professor_id=None, review_note=None, **kwargs):
        super().__init__(**kwargs)
        if resource_id:
            self.resource_id = resource_id
        if professor_id:
            self.professor_id = professor_id
        if review_note:
            self.review_note = review_note

    def __repr__(self):
        return f'<ResourceReview prof={self.professor_id} resource={self.resource_id}>'


class ResourceCollection(db.Model):
    """Collection for complete folder uploads (Notes Collections)."""
    __tablename__ = 'resource_collections'
    __table_args__ = (
        db.CheckConstraint(f"faculty IN {tuple(FACULTY_CODES)}", name='ck_collection_faculty_valid'),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=False, default='Lecture Notes')
    faculty = db.Column(db.String(10), nullable=False, default=FACULTY_CODES[0])
    course_code = db.Column(db.String(20), nullable=True)
    course_name = db.Column(db.String(150), nullable=True)
    academic_year = db.Column(db.String(20), nullable=True)
    semester = db.Column(db.String(20), nullable=True)
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_collections_uploader_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    uploader = db.relationship('User', backref=db.backref('resource_collections', lazy=True))
    resources = db.relationship(
        'Resource',
        backref=db.backref('collection', lazy=True),
        cascade='all, delete-orphan',
        lazy=True,
        order_by='Resource.relative_path'
    )

    def __init__(self, title=None, description=None, category='Lecture Notes', faculty=FACULTY_CODES[0], uploader_id=None, course_code=None, course_name=None, academic_year=None, semester=None, **kwargs):
        super().__init__(**kwargs)
        if title:
            self.title = title
        if description:
            self.description = description
        self.category = category
        self.faculty = faculty
        if uploader_id:
            self.uploader_id = uploader_id
        self.course_code = course_code
        self.course_name = course_name
        self.academic_year = academic_year
        self.semester = semester

    @property
    def download_count(self):
        """Total downloads across all member resources."""
        return sum(r.download_count or 0 for r in self.resources)

    @property
    def rating_count(self):
        """Total number of ratings across all member resources."""
        return sum(r.rating_count for r in self.resources)

    @property
    def average_rating(self):
        """Average rating derived from all member resources."""
        all_ratings = [rating.rating for r in self.resources for rating in r.ratings]
        if not all_ratings:
            return 0.0
        return round(sum(all_ratings) / len(all_ratings), 1)

    @property
    def file_count(self):
        return len(self.resources)

    @property
    def files_count(self):
        return len(self.resources)

    @property
    def professor_reviewed_count(self):
        """Count of files in this collection that have at least one professor review."""
        return sum(1 for r in self.resources if r.is_reviewed_by_professor)

    @property
    def total_size_bytes(self):
        return sum(r.file_size or 0 for r in self.resources)

    @property
    def total_size(self):
        return self.total_size_bytes

    @property
    def formatted_total_size(self):
        size = self.total_size_bytes
        if not size:
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{int(size)} B"
            size /= 1024.0
        return f"{size:.1f} TB"

    @property
    def formatted_size(self):
        return self.formatted_total_size

    @property
    def is_collection(self):
        return True

    def __repr__(self):
        return f'<ResourceCollection #{self.id}: {self.title} ({len(self.resources)} files)>'


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

    # Academic Metadata Fields
    course_code = db.Column(db.String(20), nullable=True)
    course_name = db.Column(db.String(150), nullable=True)
    academic_year = db.Column(db.String(20), nullable=True)
    semester = db.Column(db.String(20), nullable=True)

    # Download count & Collection membership
    download_count = db.Column(db.Integer, nullable=False, default=0)
    collection_id = db.Column(db.Integer, db.ForeignKey('resource_collections.id', name='fk_resources_collection_id', ondelete='CASCADE'), nullable=True)
    relative_path = db.Column(db.String(500), nullable=True)

    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_resources_uploader_id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    uploader = db.relationship('User', backref=db.backref('resources', lazy=True))

    def __init__(self, title=None, description=None, filename=None, stored_filename=None, file_size=0, file_type=None, category='Lecture Notes', faculty=FACULTY_CODES[0], uploader_id=None, download_count=0, collection_id=None, relative_path=None, course_code=None, course_name=None, academic_year=None, semester=None, **kwargs):
        super().__init__(**kwargs)
        if title:
            self.title = title
        if description:
            self.description = description
        self.filename = filename or f"{title or 'file'}.{file_type or 'dat'}"
        self.stored_filename = stored_filename or f"{uuid.uuid4().hex}_{self.filename}"
        self.file_size = file_size
        if file_type:
            self.file_type = file_type
        self.category = category
        self.faculty = faculty
        if uploader_id:
            self.uploader_id = uploader_id
        self.download_count = download_count
        self.collection_id = collection_id
        self.relative_path = relative_path
        self.course_code = course_code
        self.course_name = course_name
        self.academic_year = academic_year
        self.semester = semester

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

    @property
    def average_rating(self):
        """Returns average star rating rounded to 1 decimal place, or 0.0 if not rated."""
        if not self.ratings:
            return 0.0
        return round(sum(r.rating for r in self.ratings) / len(self.ratings), 1)

    @property
    def rating_count(self):
        """Returns number of ratings submitted for this resource."""
        return len(self.ratings)

    @property
    def is_reviewed_by_professor(self):
        """Returns True if at least one professor has reviewed/endorsed this resource."""
        return len(self.reviews) > 0

    @property
    def professor_reviews_count(self):
        """Total number of professor reviews."""
        return len(self.reviews)

    def is_reviewed_by(self, user):
        """Returns True if the given user has reviewed this resource."""
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return any(rev.professor_id == user.id for rev in self.reviews)

    def user_rating(self, user_or_id):
        """Returns the rating value (1-5) submitted by user or user_id, or None."""
        if not user_or_id:
            return None
        uid = getattr(user_or_id, 'id', user_or_id)
        for r in self.ratings:
            if r.user_id == uid:
                return r.rating
        return None

    def is_bookmarked_by(self, user):
        """Returns True if the given user has bookmarked this resource."""
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        return any(b.user_id == user.id for b in self.user_bookmarks)

    @property
    def is_collection(self):
        return False

    def __repr__(self):
        return f'<Resource {self.id}: {self.title} ({self.filename})>'


class ResourceBookmark(db.Model):
    __tablename__ = 'resource_bookmarks'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'resource_id', name='uq_user_resource_bookmark'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_resource_bookmarks_user_id', ondelete='CASCADE'), nullable=False)
    resource_id = db.Column(db.Integer, db.ForeignKey('resources.id', name='fk_resource_bookmarks_resource_id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('resource_bookmarks', lazy=True, cascade='all, delete-orphan'))
    resource = db.relationship('Resource', backref=db.backref('user_bookmarks', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, user_id=None, resource_id=None, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if resource_id:
            self.resource_id = resource_id

    def __repr__(self):
        return f'<ResourceBookmark User #{self.user_id} -> Resource #{self.resource_id}>'


# -------------------------------
# REPORTING & MODERATION MODULE 
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
        elif self.content_type == 'resource_collection':
            return db.session.get(ResourceCollection, self.content_id)
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


# =====================================================================
# WEEK 6: PROFILES, PRIVACY & SAVED QUESTIONS (MOHAMMAD KHAN)
# =====================================================================

class UserFollow(db.Model):
    __tablename__ = 'user_follows'
    __table_args__ = (
        db.UniqueConstraint('follower_id', 'followed_id', name='uq_follower_followed'),
    )

    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_user_follows_follower_id', ondelete='CASCADE'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_user_follows_followed_id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(20), default='accepted', nullable=False)  # 'accepted' or 'pending'
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    follower = db.relationship('User', foreign_keys=[follower_id], backref=db.backref('following_relations', lazy=True, cascade='all, delete-orphan'))
    followed = db.relationship('User', foreign_keys=[followed_id], backref=db.backref('follower_relations', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, follower_id=None, followed_id=None, status='accepted', **kwargs):
        super().__init__(**kwargs)
        if follower_id:
            self.follower_id = follower_id
        if followed_id:
            self.followed_id = followed_id
        self.status = status

    def __repr__(self):
        return f'<UserFollow {self.follower_id} -> {self.followed_id} ({self.status})>'


class SavedQuestionFolder(db.Model):
    __tablename__ = 'saved_question_folders'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'name', name='uq_user_folder_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_saved_question_folders_user_id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('saved_question_folders', lazy=True, cascade='all, delete-orphan'))
    saved_questions = db.relationship('SavedQuestion', backref='folder', lazy=True)

    def __init__(self, user_id=None, name=None, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if name:
            self.name = name

    @property
    def question_count(self):
        return len(self.saved_questions)

    def __repr__(self):
        return f'<SavedQuestionFolder #{self.id}: {self.name} (User #{self.user_id})>'


class SavedQuestion(db.Model):
    __tablename__ = 'saved_questions'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'question_id', name='uq_user_saved_question'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_saved_questions_user_id', ondelete='CASCADE'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id', name='fk_saved_questions_question_id', ondelete='CASCADE'), nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('saved_question_folders.id', name='fk_saved_questions_folder_id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('saved_questions', lazy=True, cascade='all, delete-orphan'))
    question = db.relationship('Question', backref=db.backref('saved_by_users', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, user_id=None, question_id=None, folder_id=None, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if question_id:
            self.question_id = question_id
        self.folder_id = folder_id

    def __repr__(self):
        return f'<SavedQuestion User #{self.user_id} -> Question #{self.question_id}>'


class UsernameChangeRequest(db.Model):
    __tablename__ = 'username_change_requests'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_username_requests_user_id', ondelete='CASCADE'), nullable=False)
    current_username = db.Column(db.String(50), nullable=False)
    new_username = db.Column(db.String(50), nullable=False)
    reason = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'approved', 'rejected', 'cancelled'
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_username_requests_reviewed_by_id', ondelete='SET NULL'), nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewer_note = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('username_requests', lazy=True, cascade='all, delete-orphan'))
    reviewer = db.relationship('User', foreign_keys=[reviewed_by_id])

    def __init__(self, user_id=None, current_username=None, new_username=None, reason=None, status='pending', **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if current_username:
            self.current_username = current_username
        if new_username:
            self.new_username = new_username
        self.reason = reason
        self.status = status

    def __repr__(self):
        return f'<UsernameChangeRequest User #{self.user_id} (@{self.current_username} -> @{self.new_username}) [{self.status}]>'


# =====================================================================
# WEEK 7: VISIBILITY, CHAT, DRAFTS, NOTIFICATIONS & FAVOURITES (HABIB)
# =====================================================================

class SavedAnswer(db.Model):
    __tablename__ = 'saved_answers'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'answer_id', name='uq_user_saved_answer'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_saved_answers_user_id', ondelete='CASCADE'), nullable=False)
    answer_id = db.Column(db.Integer, db.ForeignKey('answers.id', name='fk_saved_answers_answer_id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('saved_answers', lazy=True, cascade='all, delete-orphan'))
    answer = db.relationship('Answer', backref=db.backref('saved_by_users', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, user_id=None, answer_id=None, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if answer_id:
            self.answer_id = answer_id

    def __repr__(self):
        return f'<SavedAnswer User #{self.user_id} -> Answer #{self.answer_id}>'


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_notifications_user_id', ondelete='CASCADE'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_notifications_sender_id', ondelete='CASCADE'), nullable=True)
    notification_type = db.Column(db.String(30), nullable=False, default='mention')  # 'mention', 'chat', 'system'
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    link_url = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan', order_by='Notification.created_at.desc()'))
    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('sent_notifications', lazy=True))

    def __init__(self, user_id=None, sender_id=None, notification_type='mention', title='New Notification', message=None, link_url=None, is_read=False, **kwargs):
        super().__init__(**kwargs)
        if user_id:
            self.user_id = user_id
        if sender_id:
            self.sender_id = sender_id
        self.notification_type = notification_type
        self.title = title
        if message:
            self.message = message
        if link_url:
            self.link_url = link_url
        self.is_read = is_read

    def __repr__(self):
        return f'<Notification #{self.id} to User #{self.user_id} ({self.notification_type})>'


class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_chat_messages_sender_id', ondelete='CASCADE'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_chat_messages_recipient_id', ondelete='CASCADE'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False)
    is_edited = db.Column(db.Boolean, default=False, nullable=False)
    edited_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    sender = db.relationship('User', foreign_keys=[sender_id], backref=db.backref('sent_chats', lazy=True))
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref=db.backref('received_chats', lazy=True))

    def __init__(self, sender_id=None, recipient_id=None, message=None, is_read=False, is_edited=False, edited_at=None, **kwargs):
        super().__init__(**kwargs)
        if sender_id:
            self.sender_id = sender_id
        if recipient_id:
            self.recipient_id = recipient_id
        if message:
            self.message = message
        self.is_read = is_read
        self.is_edited = is_edited
        self.edited_at = edited_at

    def __repr__(self):
        return f'<ChatMessage #{self.id}: {self.sender_id} -> {self.recipient_id}>'


class ChatBlock(db.Model):
    __tablename__ = 'chat_blocks'
    __table_args__ = (
        db.UniqueConstraint('blocker_id', 'blocked_id', name='uq_chat_blocker_blocked'),
    )

    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_chat_blocks_blocker_id', ondelete='CASCADE'), nullable=False)
    blocked_id = db.Column(db.Integer, db.ForeignKey('users.id', name='fk_chat_blocks_blocked_id', ondelete='CASCADE'), nullable=False)
    block_scope = db.Column(db.String(20), default='chat', nullable=False)
    reason = db.Column(db.String(100), nullable=True)
    details = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    blocker = db.relationship('User', foreign_keys=[blocker_id], backref=db.backref('chat_blocks_given', lazy=True, cascade='all, delete-orphan'))
    blocked = db.relationship('User', foreign_keys=[blocked_id], backref=db.backref('chat_blocks_received', lazy=True, cascade='all, delete-orphan'))

    def __init__(self, blocker_id=None, blocked_id=None, block_scope='chat', reason=None, details=None, **kwargs):
        super().__init__(**kwargs)
        if blocker_id:
            self.blocker_id = blocker_id
        if blocked_id:
            self.blocked_id = blocked_id
        self.block_scope = block_scope or 'chat'
        self.reason = reason
        self.details = details

    def __repr__(self):
        return f'<ChatBlock User #{self.blocker_id} blocked #{self.blocked_id} scope={self.block_scope}>'


# -------------------------------
# DATABASE INITIALIZATION & MIGRATION
# -------------------------------

def migrate_database(db_path=None):
    """
    Safely inspects the SQLite database and ensures all tables and columns
    across all features and modules exist without data loss.
    """
    import os
    import sqlite3

    if db_path is None:
        possible_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'codenest.db'),
            os.path.join(os.getcwd(), 'instance', 'codenest.db'),
            'instance/codenest.db'
        ]
        for p in possible_paths:
            if os.path.exists(p):
                db_path = p
                break
        if db_path is None:
            db_path = possible_paths[0]

    if not os.path.exists(db_path):
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    def ensure_column(table, column, col_type, default_val=None):
        try:
            cursor.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in cursor.fetchall()]
            if cols and column not in cols:
                default_clause = f" DEFAULT {default_val}" if default_val is not None else ""
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}{default_clause}")
                if default_val is not None:
                    cursor.execute(f"UPDATE {table} SET {column} = {default_val} WHERE {column} IS NULL")
        except sqlite3.OperationalError:
            pass

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
    # Week 6 additions
    ensure_column('users', 'bio', 'VARCHAR(500)', None)
    ensure_column('users', 'profile_pic', 'VARCHAR(255)', None)
    ensure_column('users', 'contact_email', 'VARCHAR(120)', None)
    ensure_column('users', 'github_url', 'VARCHAR(200)', None)
    ensure_column('users', 'linkedin_url', 'VARCHAR(200)', None)
    ensure_column('users', 'website_url', 'VARCHAR(200)', None)
    ensure_column('users', 'require_follow_approval', 'BOOLEAN', 0)
    ensure_column('users', 'contact_email_privacy', "VARCHAR(20)", "'private'")
    ensure_column('users', 'social_links_privacy', "VARCHAR(20)", "'all'")

    # 2. QUESTIONS table columns
    ensure_column('questions', 'views', 'INTEGER', 0)

    # 3. ANSWERS table columns
    ensure_column('answers', 'parent_answer_id', 'INTEGER REFERENCES answers(id)', None)

    # 4. RESOURCES table columns (Week 4 Resource Hub)
    ensure_column('resources', 'download_count', 'INTEGER NOT NULL', 0)
    ensure_column('resources', 'collection_id', 'INTEGER REFERENCES resource_collections(id) ON DELETE CASCADE', None)
    ensure_column('resources', 'relative_path', 'VARCHAR(500)', None)
    ensure_column('resources', 'course_code', 'VARCHAR(20)', None)
    ensure_column('resources', 'course_name', 'VARCHAR(150)', None)
    ensure_column('resources', 'academic_year', 'VARCHAR(20)', None)
    ensure_column('resources', 'semester', 'VARCHAR(20)', None)

    # 4b. RESOURCE_COLLECTIONS table columns
    ensure_column('resource_collections', 'course_code', 'VARCHAR(20)', None)
    ensure_column('resource_collections', 'course_name', 'VARCHAR(150)', None)
    ensure_column('resource_collections', 'academic_year', 'VARCHAR(20)', None)
    ensure_column('resource_collections', 'semester', 'VARCHAR(20)', None)

    # 4c. RESOURCE_BOOKMARKS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resource_bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        resource_id INTEGER NOT NULL,
        created_at DATETIME,
        CONSTRAINT uq_user_resource_bookmark UNIQUE (user_id, resource_id),
        CONSTRAINT fk_resource_bookmarks_user_id FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
        CONSTRAINT fk_resource_bookmarks_resource_id FOREIGN KEY (resource_id) REFERENCES resources (id) ON DELETE CASCADE
    )
    """)

    # 5. CHAT_BLOCKS table columns
    ensure_column('chat_blocks', 'block_scope', "VARCHAR(20)", "'chat'")
    ensure_column('chat_blocks', 'reason', "VARCHAR(100)", None)
    ensure_column('chat_blocks', 'details', "VARCHAR(500)", None)

    # 6. CHAT_MESSAGES table columns
    ensure_column('chat_messages', 'is_edited', 'BOOLEAN', 0)
    ensure_column('chat_messages', 'edited_at', 'DATETIME', None)

    conn.commit()
    conn.close()


def init_db(app=None, db_path=None):
    """Initializes all tables and runs schema migration checks."""
    if app:
        with app.app_context():
            db.create_all()
    else:
        db.create_all()
    migrate_database(db_path=db_path)


if __name__ == '__main__':
    import os
    from flask import Flask
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///codenest.db')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    instance_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    db_path = os.path.join(instance_dir, 'codenest.db')
    db.init_app(app)
    with app.app_context():
        init_db(app, db_path=db_path)
    print(f"[Database] Schema initialized and migrated successfully at {db_path}.")






