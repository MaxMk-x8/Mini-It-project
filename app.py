import os
import random
import uuid
import io
import zipfile
import re
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory, send_file, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, AnonymousUserMixin
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from markupsafe import Markup, escape
from werkzeug.utils import secure_filename
from PIL import Image

from models import (
    db, User, Question, Answer, Resource, AnswerBestMark, QAAttachment,
    Report, ModeratorApplication, BannedEmail, UserWarning, ResourceRating,
    ResourceCollection, ResourceReview, UserFollow, SavedQuestionFolder, SavedQuestion,
    UsernameChangeRequest, SavedAnswer, Notification, ChatMessage, ChatBlock,
    ResourceBookmark, init_db, migrate_database
)
from forms import (
    RegistrationForm, LoginForm, VerificationForm, QuestionForm, AnswerForm, 
    QUESTION_CATEGORIES, ResourceForm, ResourceEditForm, RESOURCE_CATEGORIES, ALLOWED_EXTENSIONS,
    RatingForm, CollectionForm, CollectionEditForm, CollectionUploadForm, ProfessorReviewForm, AddFilesToCollectionForm, SEMESTER_CHOICES,
    ALLOWED_SCREENSHOT_EXTENSIONS, MAX_SCREENSHOT_SIZE, MAX_SCREENSHOTS_COUNT,
    ChangePasswordForm, LogoutForm, ReportActionForm,
    ModeratorApplicationForm, ModeratorApplicationReviewForm,
    ForgotPasswordForm, ResetPasswordForm, ResetPasswordOTPForm, SetNewPasswordForm,
    BanUserForm, SuspendUserForm, IssueWarningForm,
    ResourceRatingForm,
    MAX_RESOURCE_FILE_SIZE, MAX_COLLECTION_FILES, MAX_COLLECTION_TOTAL_SIZE,
    EditProfileForm, CreateFolderForm, MoveSavedQuestionForm,
    UsernameChangeRequestForm, ReviewUsernameRequestForm,
    POST_VISIBILITY_CHOICES, DraftQuestionForm, ChatMessageForm
)
from constants import FACULTIES, FACULTY_CODES, contains_profanity
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
csrf = CSRFProtect(app)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'codenest-foundation-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///codenest.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads', 'resources')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

SCREENSHOTS_FOLDER = os.path.join(app.root_path, 'uploads', 'screenshots')
os.makedirs(SCREENSHOTS_FOLDER, exist_ok=True)
app.config['SCREENSHOTS_FOLDER'] = SCREENSHOTS_FOLDER

AVATARS_FOLDER = os.path.join(app.root_path, 'uploads', 'avatars')
os.makedirs(AVATARS_FOLDER, exist_ok=True)
app.config['AVATARS_FOLDER'] = AVATARS_FOLDER

# Max request limit set to 60MB to support 50MB collection uploads safely while preserving single-file and screenshot limits
app.config['MAX_CONTENT_LENGTH'] = 60 * 1024 * 1024


app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'False') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

db.init_app(app)
mail = Mail(app)

# Automatically create all tables and sync new columns on startup
with app.app_context():
    try:
        db.create_all()
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)
        existing_tables = set(inspector.get_table_names())
        with db.engine.connect() as conn:
            for table_name, table in db.metadata.tables.items():
                if table_name in existing_tables:
                    existing_cols = set(c['name'] for c in inspector.get_columns(table_name))
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(db.engine.dialect)
                            default_clause = ""
                            if col.default is not None and col.default.is_scalar:
                                val = col.default.arg
                                if isinstance(val, bool):
                                    default_clause = " DEFAULT 1" if val else " DEFAULT 0"
                                elif isinstance(val, str):
                                    default_clause = f" DEFAULT '{val}'"
                                else:
                                    default_clause = f" DEFAULT {val}"
                            elif col.nullable:
                                default_clause = " DEFAULT NULL"
                            
                            stmt = f"ALTER TABLE {table_name} ADD COLUMN {col.name} {col_type}{default_clause}"
                            conn.execute(text(stmt))
            conn.commit()
    except Exception as e:
        app.logger.warning(f"Database startup sync notice: {e}")

class AnonymousUser(AnonymousUserMixin):
    username = 'Anonymous'
    faculty = None
    role = 'Anonymous'

    def is_student(self):
        return False

    def is_professor(self):
        return False

    def is_moderator(self):
        return False

    def is_admin(self):
        return False

    def is_suspended(self):
        return False

    @property
    def unread_warnings_count(self):
        return 0

    @property
    def unread_notifications_count(self):
        return 0

    @property
    def total_unread_chats_count(self):
        return 0

    @property
    def unread_total_inbox_count(self):
        return 0

    def is_following(self, target_user):
        return False

    def has_pending_follow(self, target_user):
        return False

    def has_saved_question(self, question_id):
        return False

    def has_saved_answer(self, answer_id):
        return False

    def has_blocked_chat(self, target_user):
        return False

    def is_chat_blocked_by(self, target_user):
        return False

    def is_chat_mutually_available(self, target_user):
        return False

    def unread_chat_count_from(self, peer_user):
        return 0

    @property
    def has_pending_moderator_application(self):
        return False

    @property
    def moderator_applications(self):
        return []

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.anonymous_user = AnonymousUser
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# =====================================================================
# USER MENTION HELPERS & JINJA FILTERS (HABIB)
# =====================================================================

def process_mentions(content_text, author, content_type, content_id, question_id):
    """
    Finds valid @username mentions in text (excluding emails and code blocks).
    Creates in-app Notification records for mentioned users (deduplicated, excluding author).
    """
    if not content_text or not author:
        return

    # Strip multi-line code blocks and inline code snippets
    cleaned_text = re.sub(r'```.*?```', '', content_text, flags=re.DOTALL)
    cleaned_text = re.sub(r'`.*?`', '', cleaned_text)

    # Regex: Lookbehind to avoid matching email addresses (e.g., name@student.mmu.edu.my)
    mention_pattern = r'(?<![\w@])@([a-zA-Z0-9_]{3,50})\b'
    raw_usernames = re.findall(mention_pattern, cleaned_text)

    seen_user_ids = set()
    for uname in set(raw_usernames):
        target_user = User.query.filter(User.username.ilike(uname), User.is_banned == False).first()
        if target_user and target_user.id != author.id and target_user.id not in seen_user_ids:
            seen_user_ids.add(target_user.id)
            link_url = url_for('qa_detail', question_id=question_id)
            if content_type in ('answer', 'reply'):
                link_url += f'#answer-{content_id}'

            notif = Notification(
                user_id=target_user.id,
                sender_id=author.id,
                notification_type='mention',
                title=f'@{author.username} mentioned you in a {content_type}',
                message=f'@{author.username} mentioned you in a {content_type} on CodeNest Q&A.',
                link_url=link_url
            )
            db.session.add(notif)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.warning(f"Failed to commit mention notifications: {e}")


@app.template_filter('render_mentions')
def render_mentions_filter(text):
    """
    Converts valid @username mentions into rich clickable hover cards and 
    formats markdown code blocks into styled IDE blocks with copy buttons.
    Escapes general HTML content first to prevent XSS.
    """
    if not text:
        return ''

    # Extract code blocks before escaping
    code_blocks = []
    def save_code(match):
        lang = (match.group(1) or 'code').strip().lower()
        code = match.group(2)
        idx = len(code_blocks)
        code_blocks.append((lang, code))
        return f"__CODE_BLOCK_{idx}__"

    text_processed = re.sub(r'```([a-zA-Z0-9_+-]*)\n?(.*?)```', save_code, text, flags=re.DOTALL)
    escaped_text = str(escape(text_processed))

    def replace_mention(match):
        uname = match.group(1)
        user = User.query.filter(User.username.ilike(uname), User.is_banned == False).first()
        if user:
            try:
                from flask import has_request_context
                profile_link = url_for('public_profile', username=user.username) if has_request_context() else f"/user/{user.username}"
            except Exception:
                profile_link = f"/user/{user.username}"

            avatar_html = f'<img src="{escape(user.avatar_url)}" class="qa-avatar qa-avatar-sm">' if user.avatar_url else f'<div class="qa-avatar-default qa-avatar-sm">{escape(user.username[:2])}</div>'
            prof_badge = '<span class="badge badge-professor" style="font-size:0.68rem;padding:1px 5px;">🎓 Prof</span>' if user.is_professor() else ''

            return (
                f'<span class="qa-mention-wrapper">'
                f'<a href="{profile_link}" class="qa-mention-tag">@{escape(user.username)}</a>'
                f'<span class="qa-hover-card">'
                f'<span class="qa-hover-header">'
                f'{avatar_html}'
                f'<span style="display:flex;flex-direction:column;gap:1px;text-align:left;">'
                f'<strong style="color:var(--text-color);font-size:0.88rem;display:flex;align-items:center;gap:4px;">@{escape(user.username)} {prof_badge}</strong>'
                f'<span style="color:var(--text-muted);font-size:0.75rem;">{escape(user.role or "Student")}</span>'
                f'</span>'
                f'</span>'
                f'<span class="qa-hover-footer">'
                f'<span>⭐ {user.reputation_points} pts</span>'
                f'<span>{escape(user.faculty or "")}</span>'
                f'</span>'
                f'</span>'
                f'</span>'
            )
        return match.group(0)

    mention_pattern = r'(?<![\w@])@([a-zA-Z0-9_]{3,50})\b'
    linked_text = re.sub(mention_pattern, replace_mention, escaped_text)

    # Restore code blocks safely escaped
    for idx, (lang, raw_code) in enumerate(code_blocks):
        escaped_code = str(escape(raw_code.strip()))
        block_html = (
            f'<div class="qa-code-wrapper">'
            f'<div class="qa-code-header">'
            f'<span><span class="qa-code-dot red"></span><span class="qa-code-dot yellow"></span><span class="qa-code-dot green"></span> {escape(lang.upper() if lang else "CODE")}</span>'
            f'<button type="button" class="qa-code-copy-btn" onclick="copyCodeBlock(this)">&#128203; Copy</button>'
            f'</div>'
            f'<pre class="language-{escape(lang)}"><code>{escaped_code}</code></pre>'
            f'</div>'
        )
        linked_text = linked_text.replace(f"__CODE_BLOCK_{idx}__", block_html)

    return Markup(linked_text)



@app.route('/')
def home():
    return render_template('index.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = RegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()

        if BannedEmail.query.filter_by(email=email).first():
            flash('This email address has been permanently banned from CodeNest.', 'danger')
            return render_template('register.html', form=form)

        existing_user = User.query.filter(
            (User.email == email) | (User.username == form.username.data.strip())
        ).first()

        if existing_user:
            if not existing_user.is_verified:
                flash('An account with this email/username was already registered but has not been verified yet. Please enter your code or request a new one.', 'warning')
                return redirect(url_for('verify_code', user_id=existing_user.id))

            if existing_user.email == email:
                flash('An account with that email already exists. Please log in.', 'danger')
            else:
                flash('That username is already taken. Please choose another username.', 'danger')
            return render_template('register.html', form=form)

        if email.endswith('@student.mmu.edu.my'):
            role = 'Student'
        elif email.endswith('@mmu.edu.my'):
            role = 'Professor'
        else:
            flash('Registration is restricted to official MMU emails (@student.mmu.edu.my or @mmu.edu.my).', 'danger')
            return render_template('register.html', form=form)

        code = str(random.randint(100000, 999999))
        now = datetime.now(timezone.utc)

        user = User(
            username=form.username.data.strip(),
            email=email,
            faculty=form.faculty.data,
            role=role,
            verification_code=code,
            is_verified=False
        )
        user.verification_code_created_at = now
        user.verification_attempts = 0
        user.verification_resend_available_at = now + timedelta(seconds=30)
        user.set_password(form.password.data)

        db.session.add(user)
        db.session.commit()

        # Log verification code to console for local development
        print(f"\n========================================\n[CodeNest OTP] Verification code for {user.username} ({user.email}): {code}\n========================================\n", flush=True)

        try:
            msg = Message(
                subject='CodeNest - Verify Your Account',
                sender=app.config['MAIL_USERNAME'],
                recipients=[user.email]
            )
            msg.body = f'Hi {user.username},\n\nYour CodeNest verification code is: {code}\n\nEnter this code to activate your account.'
            mail.send(msg)
            flash(f'Account created! Role assigned: {role}. Please check your email for your 6-digit code.', 'info')
        except Exception as e:
            flash(f'Verification email failed to send: {e}. [Dev Mode Code: {code}]', 'warning')

        return redirect(url_for('verify_code', user_id=user.id))

    return render_template('register.html', form=form)


@app.route('/verify-code/<int:user_id>', methods=['GET', 'POST'])
def verify_code(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('register'))

    if user.is_banned:
        flash('This account has been permanently banned from CodeNest.', 'danger')
        return redirect(url_for('login'))

    is_susp, susp_date, susp_reason = user.get_suspension_status()
    if is_susp:
        date_str = susp_date.strftime('%Y-%m-%d %H:%M UTC') if hasattr(susp_date, 'strftime') else str(susp_date)
        reason_str = f" Reason: {susp_reason}" if susp_reason else ""
        flash(f'Your account is temporarily suspended until {date_str}.{reason_str}', 'danger')
        return redirect(url_for('login'))

    if user.is_verified:
        flash('Your account is already verified.', 'info')
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        return redirect(url_for('login'))

    form = VerificationForm()
    if form.validate_on_submit():
        is_valid, err_msg = user.is_verification_code_valid(form.code.data.strip())
        if is_valid:
            if user.is_banned:
                flash('This account has been permanently banned from CodeNest.', 'danger')
                return redirect(url_for('login'))

            is_susp, susp_date, susp_reason = user.get_suspension_status()
            if is_susp:
                date_str = susp_date.strftime('%Y-%m-%d %H:%M UTC') if hasattr(susp_date, 'strftime') else str(susp_date)
                reason_str = f" Reason: {susp_reason}" if susp_reason else ""
                flash(f'Your account is temporarily suspended until {date_str}.{reason_str}', 'danger')
                return redirect(url_for('login'))

            user.is_verified = True
            user.verification_code = None
            user.verification_code_created_at = None
            user.verification_resend_available_at = None
            user.verification_attempts = 0
            user.reset_login_lockout()
            db.session.commit()
            login_user(user)
            flash(f'Account verified successfully! Welcome, {user.username}!', 'success')
            return redirect(url_for('home'))
        else:
            flash(err_msg, 'danger')

    return render_template('verify_code.html', form=form, user=user)


@app.route('/resend-code/<int:user_id>', methods=['GET', 'POST'])
def resend_code(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('register'))

    if user.is_banned:
        flash('This account has been permanently banned from CodeNest.', 'danger')
        return redirect(url_for('login'))

    is_susp, susp_date, susp_reason = user.get_suspension_status()
    if is_susp:
        date_str = susp_date.strftime('%Y-%m-%d %H:%M UTC') if hasattr(susp_date, 'strftime') else str(susp_date)
        reason_str = f" Reason: {susp_reason}" if susp_reason else ""
        flash(f'Your account is temporarily suspended until {date_str}.{reason_str}', 'danger')
        return redirect(url_for('login'))

    if user.is_verified:
        flash('Your account is already verified.', 'info')
        return redirect(url_for('login'))

    now = datetime.now(timezone.utc)
    if user.verification_code and user.verification_resend_available_at:
        avail = user.verification_resend_available_at
        if avail.tzinfo is None:
            avail = avail.replace(tzinfo=timezone.utc)
        if now < avail:
            remaining = int((avail - now).total_seconds())
            flash(f'Please wait {max(1, remaining)} seconds before requesting a new verification code.', 'warning')
            return redirect(url_for('verify_code', user_id=user.id))

    code = str(random.randint(100000, 999999))
    user.verification_code = code
    user.verification_code_created_at = now
    user.verification_attempts = 0
    user.verification_resend_available_at = now + timedelta(seconds=30)
    db.session.commit()

    # Log new verification code to console for local development
    print(f"\n========================================\n[CodeNest OTP] New verification code for {user.username} ({user.email}): {code}\n========================================\n", flush=True)

    try:
        msg = Message(
            subject='CodeNest - Verify Your Account',
            sender=app.config['MAIL_USERNAME'],
            recipients=[user.email]
        )
        msg.body = f'Hi {user.username},\n\nYour new CodeNest verification code is: {code}\n\nEnter this code to activate your account. This code expires in 5 minutes.'
        mail.send(msg)
        flash('A new verification code has been sent to your email (expires in 5 minutes).', 'info')
    except Exception as e:
        flash(f'Failed to send verification email: {e}. [Dev Mode Code: {code}]', 'warning')

    return redirect(url_for('verify_code', user_id=user.id))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = LoginForm()
    if form.validate_on_submit():
        credential = form.email_or_username.data.strip()
        password = form.password.data

        user = User.query.filter(
            (User.email == credential.lower()) | (User.username == credential)
        ).first()

        if user:
            if user.is_banned:
                flash('This account has been permanently banned from CodeNest.', 'danger')
                return render_template('login.html', form=form)

            is_susp, susp_date, susp_reason = user.get_suspension_status()
            if is_susp:
                date_str = susp_date.strftime('%Y-%m-%d %H:%M UTC') if hasattr(susp_date, 'strftime') else str(susp_date)
                reason_str = f" Reason: {susp_reason}" if susp_reason else ""
                flash(f'Your account is temporarily suspended until {date_str}.{reason_str}', 'danger')
                return render_template('login.html', form=form)

            is_locked, remaining_sec = user.is_locked_out()
            if is_locked:
                flash(f'Account temporarily locked due to multiple failed login attempts. Please try again in {remaining_sec} seconds.', 'danger')
                return render_template('login.html', form=form)

            if user.check_password(password):
                user.reset_login_lockout()
                if not user.is_verified:
                    flash('Please verify your account before logging in.', 'warning')
                    return redirect(url_for('verify_code', user_id=user.id))
                login_user(user)
                flash(f'Welcome back, {user.username}!', 'success')
                return redirect(url_for('home'))
            else:
                is_locked, lockout_or_left = user.record_failed_login(max_attempts=5, lockout_seconds=60)
                if is_locked:
                    flash('Account temporarily locked for 60 seconds due to 5 consecutive failed login attempts.', 'danger')
                else:
                    flash(f'Invalid email/username or password. {lockout_or_left} attempts remaining before temporary lockout.', 'danger')
        else:
            flash('Invalid email/username or password.', 'danger')

    return render_template('login.html', form=form)


# -------------------------------
# FORGOT & RESET PASSWORD ROUTES
# -------------------------------

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        credential = form.email_or_username.data.strip().lower()
        user = User.query.filter(
            (User.email == credential) | (User.username == form.email_or_username.data.strip())
        ).first()

        if user:
            if user.is_banned:
                flash('This account has been permanently banned.', 'danger')
                return render_template('forgot_password.html', form=form)

            is_susp, susp_date, susp_reason = user.get_suspension_status()
            if is_susp:
                date_str = susp_date.strftime('%Y-%m-%d %H:%M UTC') if hasattr(susp_date, 'strftime') else str(susp_date)
                reason_str = f" Reason: {susp_reason}" if susp_reason else ""
                flash(f'Your account is temporarily suspended until {date_str}.{reason_str}', 'danger')
                return render_template('forgot_password.html', form=form)

            now = datetime.now(timezone.utc)
            # Check resend cooldown (30s) only if a reset code is currently active
            if user.reset_code and user.reset_resend_available_at:
                avail = user.reset_resend_available_at
                if avail.tzinfo is None:
                    avail = avail.replace(tzinfo=timezone.utc)
                if now < avail:
                    remaining = int((avail - now).total_seconds())
                    flash(f'Please wait {max(1, remaining)} seconds before requesting another reset code.', 'warning')
                    return redirect(url_for('verify_reset_code', user_id=user.id))

            code = str(random.randint(100000, 999999))
            user.reset_code = code
            user.reset_code_created_at = now
            user.reset_attempts = 0
            user.reset_resend_available_at = now + timedelta(seconds=30)
            db.session.commit()

            print(f"\n========================================\n[CodeNest Password Reset OTP] Reset code for {user.username} ({user.email}): {code}\n========================================\n", flush=True)

            try:
                msg = Message(
                    subject='CodeNest - Password Reset Code',
                    sender=app.config['MAIL_USERNAME'],
                    recipients=[user.email]
                )
                msg.body = f'Hi {user.username},\n\nYour CodeNest password reset code is: {code}\n\nThis code expires in 5 minutes. If you did not request this, please ignore this email.'
                mail.send(msg)
                flash('A 6-digit password reset code has been sent to your email.', 'info')
            except Exception as e:
                flash(f'Failed to send reset email: {e}. [Dev Mode Code: {code}]', 'warning')

            return redirect(url_for('verify_reset_code', user_id=user.id))
        else:
            flash('No account found with that email or username.', 'danger')

    return render_template('forgot_password.html', form=form)


@app.route('/reset-password/verify/<int:user_id>', methods=['GET', 'POST'])
def verify_reset_code(user_id):
    """
    Dedicated OTP Verification Page:
    Strictly contains only the 6-digit OTP verification field.
    Upon successful verification, unlocks the separate new password page.
    """
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('forgot_password'))

    form = ResetPasswordOTPForm()
    if form.validate_on_submit():
        is_valid, err_msg = user.is_reset_code_valid(form.code.data.strip())
        if is_valid:
            session['reset_password_verified_user_id'] = user.id
            flash('Reset code verified successfully! Please enter your new password.', 'success')
            return redirect(url_for('reset_password', user_id=user.id))
        else:
            flash(err_msg, 'danger')

    return render_template('verify_reset_code.html', form=form, user=user)


@app.route('/reset-password/<int:user_id>', methods=['GET', 'POST'])
def reset_password(user_id):
    """
    Dedicated Set New Password Page:
    Strictly contains only the new password & confirmation fields with strength meter.
    Requires successful OTP verification in the prior step.
    """
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('forgot_password'))

    # Guard: Require prior successful OTP verification
    if session.get('reset_password_verified_user_id') != user.id:
        flash('Please enter and verify your 6-digit reset code first.', 'warning')
        return redirect(url_for('verify_reset_code', user_id=user.id))

    form = SetNewPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.new_password.data)
        user.reset_code = None
        user.reset_code_created_at = None
        user.reset_resend_available_at = None
        user.reset_attempts = 0
        user.reset_login_lockout()
        session.pop('reset_password_verified_user_id', None)
        db.session.commit()
        flash('Password reset successful! You may now log in with your new password.', 'success')
        return redirect(url_for('login'))

    return render_template('reset_password.html', form=form, user=user)


@app.route('/resend-reset-code/<int:user_id>', methods=['GET', 'POST'])
def resend_reset_code(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('forgot_password'))

    now = datetime.now(timezone.utc)
    if user.reset_resend_available_at:
        avail = user.reset_resend_available_at
        if avail.tzinfo is None:
            avail = avail.replace(tzinfo=timezone.utc)
        if now < avail:
            remaining = int((avail - now).total_seconds())
            flash(f'Please wait {max(1, remaining)} seconds before requesting a new reset code.', 'warning')
            return redirect(url_for('verify_reset_code', user_id=user.id))

    code = str(random.randint(100000, 999999))
    user.reset_code = code
    user.reset_code_created_at = now
    user.reset_attempts = 0
    user.reset_resend_available_at = now + timedelta(seconds=30)
    db.session.commit()

    print(f"\n========================================\n[CodeNest Password Reset OTP] New reset code for {user.username} ({user.email}): {code}\n========================================\n", flush=True)

    try:
        msg = Message(
            subject='CodeNest - Password Reset Code',
            sender=app.config['MAIL_USERNAME'],
            recipients=[user.email]
        )
        msg.body = f'Hi {user.username},\n\nYour new CodeNest password reset code is: {code}\n\nThis code expires in 5 minutes.'
        mail.send(msg)
        flash('A new password reset code has been sent to your email.', 'info')
    except Exception as e:
        flash(f'Failed to send reset email: {e}. [Dev Mode Code: {code}]', 'warning')

    return redirect(url_for('verify_reset_code', user_id=user.id))


# -------------------------------
# SETTINGS & AUTH ROUTES 
# -------------------------------

@app.route('/settings')
@login_required
def settings():
    logout_form = LogoutForm()
    return render_template('settings.html', logout_form=logout_form)


@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        current_pw = form.current_password.data
        new_pw = form.new_password.data

        if not current_user.check_password(current_pw):
            flash('Current password is incorrect.', 'danger')
            return render_template('change_password.html', form=form)

        if current_pw == new_pw:
            flash('New password must be different from current password.', 'danger')
            return render_template('change_password.html', form=form)

        current_user.set_password(new_pw)
        db.session.commit()
        flash('Your password has been changed successfully.', 'success')
        return redirect(url_for('settings'))

    return render_template('change_password.html', form=form)


@app.route('/logout', methods=['GET', 'POST'])
@login_required
def logout():
    if request.method == 'GET':
        flash('Logout must be performed via Settings.', 'warning')
        return redirect(url_for('settings'))

    form = LogoutForm()
    if not form.validate_on_submit():
        flash('Invalid logout request or expired CSRF token.', 'danger')
        return redirect(url_for('settings'))

    logout_user()
    session.clear()
    flash('You have been logged out.', 'info')
    resp = redirect(url_for('home'))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "-1"
    return resp


# =====================================================================
# WEEK 6: PROFILES, PRIVACY, FOLLOWS & SAVED QUESTIONS (MOHAMMAD KHAN)
# =====================================================================

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(obj=current_user)

    if form.validate_on_submit():
        # Handle avatar file upload if provided
        photo_file = form.profile_photo.data
        if photo_file and getattr(photo_file, 'filename', None):
            filename_raw = secure_filename(photo_file.filename)
            ext = os.path.splitext(filename_raw)[1].lower().lstrip('.')
            if ext not in ['png', 'jpg', 'jpeg', 'webp']:
                flash('Invalid image format. Allowed formats: PNG, JPG, JPEG, WEBP.', 'danger')
                return render_template('edit_profile.html', form=form)

            try:
                photo_file.seek(0)
                img = Image.open(photo_file)
                img.verify()
                photo_file.seek(0)
            except Exception:
                flash('The uploaded file is not a valid or readable image.', 'danger')
                return render_template('edit_profile.html', form=form)

            unique_name = f"{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}_{filename_raw}"
            save_path = os.path.join(app.config['AVATARS_FOLDER'], unique_name)
            photo_file.save(save_path)

            # Remove previous custom avatar if exists
            if current_user.profile_pic:
                old_path = os.path.join(app.config['AVATARS_FOLDER'], current_user.profile_pic)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except Exception as e:
                        app.logger.warning(f"Failed to remove old avatar {old_path}: {e}")

            current_user.profile_pic = unique_name

        current_user.bio = form.bio.data.strip() if form.bio.data and form.bio.data.strip() else None
        current_user.contact_email = form.contact_email.data.strip() if form.contact_email.data and form.contact_email.data.strip() else None
        current_user.github_url = form.github_url.data.strip() if form.github_url.data and form.github_url.data.strip() else None
        current_user.linkedin_url = form.linkedin_url.data.strip() if form.linkedin_url.data and form.linkedin_url.data.strip() else None
        current_user.website_url = form.website_url.data.strip() if form.website_url.data and form.website_url.data.strip() else None
        current_user.require_follow_approval = bool(form.require_follow_approval.data)
        current_user.contact_email_privacy = form.contact_email_privacy.data
        current_user.social_links_privacy = form.social_links_privacy.data

        db.session.commit()
        flash('Your profile has been updated successfully!', 'success')
        return redirect(url_for('public_profile', username=current_user.username))

    return render_template('edit_profile.html', form=form)


@app.route('/profile/remove-photo', methods=['POST'])
@login_required
def remove_profile_photo():
    if current_user.profile_pic:
        old_path = os.path.join(app.config['AVATARS_FOLDER'], current_user.profile_pic)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except Exception as e:
                app.logger.warning(f"Failed to remove avatar {old_path}: {e}")
        current_user.profile_pic = None
        db.session.commit()
        flash('Profile photo removed. Your avatar has reverted to default initials.', 'info')
    else:
        flash('You do not have a custom profile photo to remove.', 'warning')
    return redirect(url_for('edit_profile'))


@app.route('/profile/request-username-change', methods=['GET', 'POST'])
@login_required
def request_username_change():
    form = UsernameChangeRequestForm()
    pending_request = current_user.pending_username_request
    request_history = UsernameChangeRequest.query.filter_by(
        user_id=current_user.id
    ).order_by(UsernameChangeRequest.created_at.desc()).all()

    if form.validate_on_submit():
        if pending_request and not current_user.is_admin():
            flash('You already have an active username change request pending review.', 'warning')
            return redirect(url_for('request_username_change'))

        new_name = form.new_username.data.strip()

        # Cannot be identical to current username
        if new_name.lower() == current_user.username.lower():
            flash('The requested username is already your current username.', 'danger')
            return render_template(
                'username_change_request.html',
                form=form,
                pending_request=pending_request,
                request_history=request_history
            )

        # Cannot be taken by an existing user
        existing_user = User.query.filter(db.func.lower(User.username) == new_name.lower()).first()
        if existing_user:
            flash(f'The username "@{new_name}" is already taken by another member. Please choose a different username.', 'danger')
            return render_template(
                'username_change_request.html',
                form=form,
                pending_request=pending_request,
                request_history=request_history
            )

        # Cannot conflict with another user's pending request
        conflicting_request = UsernameChangeRequest.query.filter(
            UsernameChangeRequest.status == 'pending',
            db.func.lower(UsernameChangeRequest.new_username) == new_name.lower(),
            UsernameChangeRequest.user_id != current_user.id
        ).first()
        if conflicting_request:
            flash(f'The username "@{new_name}" is currently reserved by another member\'s pending request. Please choose a different username.', 'warning')
            return render_template(
                'username_change_request.html',
                form=form,
                pending_request=pending_request,
                request_history=request_history
            )

        # ADMIN PRIVILEGE: Administrators update username directly without queuing
        if current_user.is_admin():
            old_name = current_user.username
            current_user.username = new_name
            audit_req = UsernameChangeRequest(
                user_id=current_user.id,
                current_username=old_name,
                new_username=new_name,
                reason=form.reason.data.strip() if form.reason.data else "Direct administrator update",
                status='approved',
                reviewed_by_id=current_user.id,
                reviewed_at=datetime.now(timezone.utc),
                reviewer_note="Direct Administrator update applied immediately."
            )
            db.session.add(audit_req)
            db.session.commit()
            flash(f'Administrator Privilege: Your username was updated directly to "@{new_name}"!', 'success')
            return redirect(url_for('edit_profile'))

        req = UsernameChangeRequest(
            user_id=current_user.id,
            current_username=current_user.username,
            new_username=new_name,
            reason=form.reason.data.strip() if form.reason.data else None
        )
        db.session.add(req)
        db.session.commit()
        flash(f'Your request to change username to "@{new_name}" has been submitted for review!', 'success')
        return redirect(url_for('request_username_change'))

    return render_template(
        'username_change_request.html',
        form=form,
        pending_request=pending_request,
        request_history=request_history
    )


@app.route('/profile/cancel-username-request/<int:request_id>', methods=['POST'])
@login_required
def cancel_username_request(request_id):
    req = UsernameChangeRequest.query.filter_by(
        id=request_id,
        user_id=current_user.id,
        status='pending'
    ).first_or_404()

    req.status = 'cancelled'
    db.session.commit()
    flash(f'Your username change request to "@{req.new_username}" has been cancelled.', 'info')
    return redirect(url_for('request_username_change'))


@app.route('/user/<username>')
@login_required
def public_profile(username):
    user = User.query.filter_by(username=username).first_or_404()

    is_own_profile = (current_user.id == user.id)

    # If the user has blocked current_user platform-wide, profile is completely unavailable
    if not is_own_profile and current_user.is_platform_blocked_by(user):
        return render_template('profile_unavailable.html'), 403

    is_platform_blocked_by_me = False
    if not is_own_profile:
        is_platform_blocked_by_me = current_user.has_blocked_platform(user)

    is_following = current_user.is_following(user)
    has_pending_follow = current_user.has_pending_follow(user)

    can_see_contact = user.can_view_contact(current_user)
    can_see_social = user.can_view_social(current_user)
    contact_restricted = bool(user.contact_email and not can_see_contact and user.contact_email_privacy == 'followers')
    social_restricted = bool((user.github_url or user.linkedin_url or user.website_url) and not can_see_social and user.social_links_privacy == 'followers')

    # Contributions with visibility and draft enforcement (hidden if current_user blocked them platform-wide)
    if is_platform_blocked_by_me:
        questions = []
        answers = []
        resources = []
    else:
        all_user_questions = Question.query.filter_by(author_id=user.id, is_draft=False).order_by(Question.created_at.desc()).all()
        questions = [q for q in all_user_questions if q.can_view(current_user)]

        all_user_answers = Answer.query.filter_by(author_id=user.id).order_by(Answer.created_at.desc()).all()
        answers = [a for a in all_user_answers if a.can_view(current_user)]

        resources = Resource.query.filter_by(uploader_id=user.id).order_by(Resource.created_at.desc()).all()

    active_tab = request.args.get('tab', 'questions')
    if active_tab not in ['questions', 'answers', 'resources']:
        active_tab = 'questions'

    return render_template(
        'profile.html',
        user=user,
        is_own_profile=is_own_profile,
        is_platform_blocked_by_me=is_platform_blocked_by_me,
        is_following=is_following,
        has_pending_follow=has_pending_follow,
        can_see_contact=can_see_contact,
        can_see_social=can_see_social,
        contact_restricted=contact_restricted,
        social_restricted=social_restricted,
        questions=questions,
        answers=answers,
        resources=resources,
        active_tab=active_tab
    )


@app.route('/user/<username>/followers')
@login_required
def user_followers(username):
    user = User.query.filter_by(username=username).first_or_404()
    if current_user.id != user.id and current_user.is_platform_blocked_by(user):
        return render_template('profile_unavailable.html'), 403

    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1

    follows_query = UserFollow.query.filter_by(followed_id=user.id, status='accepted').order_by(UserFollow.created_at.desc())
    pagination = follows_query.paginate(page=page, per_page=20, error_out=False)
    followers = pagination.items

    return render_template('user_followers.html', user=user, pagination=pagination, followers=followers)


@app.route('/user/<username>/following')
@login_required
def user_following(username):
    user = User.query.filter_by(username=username).first_or_404()
    if current_user.id != user.id and current_user.is_platform_blocked_by(user):
        return render_template('profile_unavailable.html'), 403

    page = request.args.get('page', 1, type=int)
    if page < 1:
        page = 1

    follows_query = UserFollow.query.filter_by(follower_id=user.id, status='accepted').order_by(UserFollow.created_at.desc())
    pagination = follows_query.paginate(page=page, per_page=20, error_out=False)
    following_users = pagination.items

    return render_template('user_following.html', user=user, pagination=pagination, following_users=following_users)


@app.route('/users/search')
@app.route('/user/search')
def search_users():
    query_text = request.args.get('q', '').strip()
    is_json = request.headers.get('Accept') == 'application/json' or request.args.get('format') == 'json'

    users = []
    if query_text:
        search_term = query_text.lstrip('@').strip()
        if search_term:
            users = User.query.filter(
                User.username.ilike(f"%{search_term}%"),
                User.is_banned == False,
                User.is_verified == True
            ).order_by(User.username.asc()).limit(50).all()

            if current_user.is_authenticated:
                users = [u for u in users if not current_user.has_any_platform_block_with(u)]

    if is_json:
        return jsonify({
            'query': query_text,
            'users': [
                {
                    'id': u.id,
                    'username': u.username,
                    'role': u.role,
                    'faculty': u.faculty,
                    'avatar_url': u.avatar_url,
                    'profile_url': url_for('public_profile', username=u.username)
                } for u in users
            ]
        })

    return render_template('user_search.html', users=users, query_text=query_text)


@app.route('/user/<username>/follow', methods=['POST'])
@login_required
def follow_user(username):
    target_user = User.query.filter_by(username=username).first_or_404()

    if target_user.id == current_user.id:
        flash('You cannot follow yourself.', 'warning')
        return redirect(url_for('public_profile', username=username))

    if current_user.has_any_platform_block_with(target_user):
        flash('Unable to follow this user due to block restrictions.', 'danger')
        return redirect(url_for('student_dashboard'))

    existing = UserFollow.query.filter_by(
        follower_id=current_user.id,
        followed_id=target_user.id
    ).first()

    if existing:
        if existing.status == 'accepted':
            flash(f'You are already following @{target_user.username}.', 'info')
        else:
            flash(f'Follow request to @{target_user.username} is already pending approval.', 'info')
        return redirect(url_for('public_profile', username=username))

    if target_user.require_follow_approval:
        follow_rel = UserFollow(
            follower_id=current_user.id,
            followed_id=target_user.id,
            status='pending'
        )
        db.session.add(follow_rel)
        db.session.commit()
        flash(f'Follow request sent to @{target_user.username}. Waiting for approval.', 'info')
    else:
        follow_rel = UserFollow(
            follower_id=current_user.id,
            followed_id=target_user.id,
            status='accepted'
        )
        db.session.add(follow_rel)
        db.session.commit()
        flash(f'You are now following @{target_user.username}!', 'success')

    return redirect(url_for('public_profile', username=username))


@app.route('/user/<username>/unfollow', methods=['POST'])
@login_required
def unfollow_user(username):
    target_user = User.query.filter_by(username=username).first_or_404()

    follow_rel = UserFollow.query.filter_by(
        follower_id=current_user.id,
        followed_id=target_user.id
    ).first()

    if follow_rel:
        was_pending = (follow_rel.status == 'pending')
        db.session.delete(follow_rel)
        db.session.commit()
        if was_pending:
            flash(f'Follow request to @{target_user.username} cancelled.', 'info')
        else:
            flash(f'You have unfollowed @{target_user.username}.', 'info')
    else:
        flash(f'You are not following @{target_user.username}.', 'warning')

    return redirect(url_for('public_profile', username=username))


@app.route('/follow-requests')
@login_required
def follow_requests():
    requests = UserFollow.query.filter_by(
        followed_id=current_user.id,
        status='pending'
    ).order_by(UserFollow.created_at.desc()).all()
    return render_template('follow_requests.html', follow_requests=requests)


@app.route('/follow-requests/<int:request_id>/accept', methods=['POST'])
@login_required
def accept_follow_request(request_id):
    req = UserFollow.query.filter_by(
        id=request_id,
        followed_id=current_user.id,
        status='pending'
    ).first_or_404()

    req.status = 'accepted'
    db.session.commit()
    flash(f'Accepted follow request from @{req.follower.username}. They are now following you.', 'success')
    return redirect(url_for('follow_requests'))


@app.route('/follow-requests/<int:request_id>/decline', methods=['POST'])
@login_required
def decline_follow_request(request_id):
    req = UserFollow.query.filter_by(
        id=request_id,
        followed_id=current_user.id,
        status='pending'
    ).first_or_404()

    follower_name = req.follower.username
    db.session.delete(req)
    db.session.commit()
    flash(f'Declined follow request from @{follower_name}.', 'info')
    return redirect(url_for('follow_requests'))


@app.route('/qa/questions/<int:question_id>/save', methods=['POST'])
@login_required
def toggle_save_question(question_id):
    question = db.session.get(Question, question_id)
    if not question:
        abort(404)

    saved = SavedQuestion.query.filter_by(
        user_id=current_user.id,
        question_id=question.id
    ).first()

    if saved:
        db.session.delete(saved)
        db.session.commit()
        flash('Question removed from bookmarks.', 'info')
    else:
        new_saved = SavedQuestion(user_id=current_user.id, question_id=question.id)
        db.session.add(new_saved)
        db.session.commit()
        flash('Question added to your bookmarks!', 'success')

    next_url = request.form.get('next') or request.referrer or url_for('qa_detail', question_id=question.id)
    return redirect(next_url)


@app.route('/qa/answers/<int:answer_id>/favourite', methods=['POST'])
@app.route('/qa/answer/<int:answer_id>/favourite', methods=['POST'])
@login_required
def toggle_favourite_answer(answer_id):
    answer = db.session.get(Answer, answer_id)
    if not answer:
        abort(404)

    saved = SavedAnswer.query.filter_by(
        user_id=current_user.id,
        answer_id=answer.id
    ).first()

    if saved:
        db.session.delete(saved)
        db.session.commit()
        flash('Answer removed from your favourites.', 'info')
    else:
        new_saved = SavedAnswer(user_id=current_user.id, answer_id=answer.id)
        db.session.add(new_saved)
        db.session.commit()
        flash('Answer added to your favourites!', 'success')

    next_url = request.form.get('next') or request.referrer or (url_for('qa_detail', question_id=answer.question_id) + f'#answer-{answer.id}')
    return redirect(next_url)


@app.route('/bookmarks')
@app.route('/saved-questions')
@app.route('/favourites')
@login_required
def saved_questions():
    main_tab = request.args.get('tab', 'questions')
    if main_tab not in ['questions', 'answers', 'resources']:
        main_tab = 'questions'

    folder_filter = request.args.get('folder', 'all')
    user_folders = SavedQuestionFolder.query.filter_by(
        user_id=current_user.id
    ).order_by(SavedQuestionFolder.name.asc()).all()

    query = SavedQuestion.query.filter_by(user_id=current_user.id)

    active_folder = None
    if folder_filter == 'uncategorized':
        query = query.filter(SavedQuestion.folder_id.is_(None))
    elif folder_filter != 'all':
        try:
            folder_id_int = int(folder_filter)
            active_folder = SavedQuestionFolder.query.filter_by(
                id=folder_id_int,
                user_id=current_user.id
            ).first()
            if active_folder:
                query = query.filter_by(folder_id=active_folder.id)
            else:
                folder_filter = 'all'
        except (ValueError, TypeError):
            folder_filter = 'all'

    saved_items = query.order_by(SavedQuestion.created_at.desc()).all()

    total_saved_count = SavedQuestion.query.filter_by(user_id=current_user.id).count()
    uncategorized_count = SavedQuestion.query.filter_by(user_id=current_user.id, folder_id=None).count()

    # Query favorited answers for current user
    saved_answers = SavedAnswer.query.filter_by(user_id=current_user.id).order_by(SavedAnswer.created_at.desc()).all()
    total_favourited_answers_count = len(saved_answers)

    # Query bookmarked resources for current user
    saved_resources = ResourceBookmark.query.filter_by(user_id=current_user.id).order_by(ResourceBookmark.created_at.desc()).all()
    total_bookmarked_resources_count = len(saved_resources)

    create_folder_form = CreateFolderForm()
    move_form = MoveSavedQuestionForm()
    move_form.folder_id.choices = [(0, 'Uncategorized')] + [(f.id, f.name) for f in user_folders]

    return render_template(
        'saved_questions.html',
        main_tab=main_tab,
        saved_items=saved_items,
        saved_answers=saved_answers,
        saved_resources=saved_resources,
        user_folders=user_folders,
        folder_filter=folder_filter,
        active_folder=active_folder,
        total_saved_count=total_saved_count,
        uncategorized_count=uncategorized_count,
        total_favourited_answers_count=total_favourited_answers_count,
        total_bookmarked_resources_count=total_bookmarked_resources_count,
        create_folder_form=create_folder_form,
        move_form=move_form
    )



@app.route('/saved-questions/folders/create', methods=['POST'])
@login_required
def create_saved_folder():
    form = CreateFolderForm()
    if form.validate_on_submit():
        folder_name = form.name.data.strip()
        existing = SavedQuestionFolder.query.filter_by(
            user_id=current_user.id,
            name=folder_name
        ).first()
        if existing:
            flash(f"A folder named '{folder_name}' already exists.", 'danger')
        else:
            folder = SavedQuestionFolder(user_id=current_user.id, name=folder_name)
            db.session.add(folder)
            db.session.commit()
            flash(f"Folder '{folder_name}' created successfully.", 'success')
            return redirect(url_for('saved_questions', folder=folder.id))
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(error, 'danger')

    return redirect(url_for('saved_questions'))


@app.route('/saved-questions/folders/<int:folder_id>/delete', methods=['POST'])
@login_required
def delete_saved_folder(folder_id):
    folder = SavedQuestionFolder.query.filter_by(
        id=folder_id,
        user_id=current_user.id
    ).first_or_404()

    folder_name = folder.name
    SavedQuestion.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    db.session.delete(folder)
    db.session.commit()

    flash(f"Folder '{folder_name}' deleted. Bookmarks moved to Uncategorized.", 'info')
    return redirect(url_for('saved_questions', folder='all'))


@app.route('/saved-questions/<int:saved_id>/move', methods=['POST'])
@login_required
def move_saved_question(saved_id):
    saved = SavedQuestion.query.filter_by(
        id=saved_id,
        user_id=current_user.id
    ).first_or_404()

    target_folder_id = request.form.get('folder_id', type=int)

    if not target_folder_id or target_folder_id == 0:
        saved.folder_id = None
        db.session.commit()
        flash('Question moved to Uncategorized.', 'success')
    else:
        folder = SavedQuestionFolder.query.filter_by(
            id=target_folder_id,
            user_id=current_user.id
        ).first_or_404()
        saved.folder_id = folder.id
        db.session.commit()
        flash(f"Question moved to '{folder.name}'.", 'success')

    next_folder = request.args.get('folder', 'all')
    return redirect(url_for('saved_questions', folder=next_folder))


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin():
        return redirect(url_for('admin_dashboard'))
    elif current_user.is_moderator():
        return redirect(url_for('moderator_dashboard'))
    else:
        flash('Dashboards are reserved for Community Moderators and Administrators. Your account details and activity are available on your Profile.', 'info')
        return redirect(url_for('public_profile', username=current_user.username))


@app.route('/dashboard/student')
@login_required
def student_dashboard():
    return redirect(url_for('public_profile', username=current_user.username))


@app.route('/dashboard/professor')
@login_required
def professor_dashboard():
    return redirect(url_for('public_profile', username=current_user.username))


@app.route('/dashboard/moderator')
@login_required
def moderator_dashboard():
    if not current_user.is_moderator():
        flash('Not authorized to view the moderator dashboard.', 'danger')
        return redirect(url_for('home'))

    assigned_faculty = current_user.faculty
    pending_reports = Report.query.filter_by(faculty=assigned_faculty, status='pending').order_by(Report.created_at.desc()).all()
    resolved_reports = Report.query.filter(
        Report.faculty == assigned_faculty,
        Report.status != 'pending'
    ).order_by(Report.reviewed_at.desc()).limit(30).all()

    pending_username_requests = UsernameChangeRequest.query.join(
        User, UsernameChangeRequest.user_id == User.id
    ).filter(
        User.faculty == assigned_faculty,
        UsernameChangeRequest.status == 'pending'
    ).order_by(UsernameChangeRequest.created_at.desc()).all()

    resolved_username_requests = UsernameChangeRequest.query.join(
        User, UsernameChangeRequest.user_id == User.id
    ).filter(
        User.faculty == assigned_faculty,
        UsernameChangeRequest.status.in_(['approved', 'rejected'])
    ).order_by(UsernameChangeRequest.reviewed_at.desc()).limit(20).all()

    review_form = ReviewUsernameRequestForm()

    return render_template(
        'moderator_dashboard.html',
        user=current_user,
        assigned_faculty=assigned_faculty,
        pending_reports=pending_reports,
        resolved_reports=resolved_reports,
        pending_username_requests=pending_username_requests,
        resolved_username_requests=resolved_username_requests,
        review_form=review_form
    )


@app.route('/dashboard/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin():
        flash('Not authorized to view the admin dashboard.', 'danger')
        return redirect(url_for('home'))

    total_users = User.query.count()
    all_users = User.query.all()

    selected_faculty = request.args.get('faculty', '').strip()
    status_filter = request.args.get('status', 'pending').strip()

    reports_query = Report.query
    if selected_faculty in FACULTY_CODES:
        reports_query = reports_query.filter(Report.faculty == selected_faculty)

    if status_filter == 'pending':
        reports = reports_query.filter_by(status='pending').order_by(Report.created_at.desc()).all()
    elif status_filter == 'handled':
        reports = reports_query.filter(Report.status != 'pending').order_by(Report.reviewed_at.desc()).all()
    else:
        status_filter = 'all'
        reports = reports_query.order_by(Report.created_at.desc()).all()

    app_status_filter = request.args.get('app_status', 'pending').strip()
    apps_query = ModeratorApplication.query
    if selected_faculty in FACULTY_CODES:
        apps_query = apps_query.filter(ModeratorApplication.faculty == selected_faculty)

    if app_status_filter == 'pending':
        moderator_applications = apps_query.filter_by(status='pending').order_by(ModeratorApplication.created_at.desc()).all()
    elif app_status_filter == 'handled':
        moderator_applications = apps_query.filter(ModeratorApplication.status != 'pending').order_by(ModeratorApplication.reviewed_at.desc()).all()
    else:
        app_status_filter = 'all'
        moderator_applications = apps_query.order_by(ModeratorApplication.created_at.desc()).all()

    username_status_filter = request.args.get('username_status', 'pending').strip()
    u_req_query = UsernameChangeRequest.query.join(User, UsernameChangeRequest.user_id == User.id)
    if selected_faculty in FACULTY_CODES:
        u_req_query = u_req_query.filter(User.faculty == selected_faculty)

    if username_status_filter == 'pending':
        username_requests = u_req_query.filter(UsernameChangeRequest.status == 'pending').order_by(UsernameChangeRequest.created_at.desc()).all()
    elif username_status_filter == 'handled':
        username_requests = u_req_query.filter(UsernameChangeRequest.status.in_(['approved', 'rejected'])).order_by(UsernameChangeRequest.reviewed_at.desc()).all()
    else:
        username_status_filter = 'all'
        username_requests = u_req_query.order_by(UsernameChangeRequest.created_at.desc()).all()

    banned_emails = BannedEmail.query.order_by(BannedEmail.created_at.desc()).all()
    ban_form = BanUserForm()
    suspend_form = SuspendUserForm()
    warn_form = IssueWarningForm()
    review_form = ReviewUsernameRequestForm()

    return render_template(
        'admin_dashboard.html',
        user=current_user,
        total_users=total_users,
        all_users=all_users,
        reports=reports,
        moderator_applications=moderator_applications,
        app_status_filter=app_status_filter,
        username_requests=username_requests,
        username_status_filter=username_status_filter,
        selected_faculty=selected_faculty,
        status_filter=status_filter,
        faculties=FACULTIES,
        banned_emails=banned_emails,
        ban_form=ban_form,
        suspend_form=suspend_form,
        warn_form=warn_form,
        review_form=review_form
    )


@app.route('/dashboard/username-requests')
@login_required
def username_requests_queue():
    if not (current_user.is_admin() or current_user.is_moderator()):
        flash('Access restricted to Administrators and Community Moderators.', 'danger')
        return redirect(url_for('home'))

    status_filter = request.args.get('status', 'pending').strip()
    selected_faculty = request.args.get('faculty', '').strip()

    query = UsernameChangeRequest.query.join(User, UsernameChangeRequest.user_id == User.id)

    # If community moderator, default to their assigned faculty unless they specify or are admin
    if current_user.is_moderator() and not current_user.is_admin():
        if not selected_faculty:
            selected_faculty = current_user.faculty
        query = query.filter(User.faculty == selected_faculty)
    elif selected_faculty in FACULTY_CODES:
        query = query.filter(User.faculty == selected_faculty)

    if status_filter == 'pending':
        query = query.filter(UsernameChangeRequest.status == 'pending').order_by(UsernameChangeRequest.created_at.desc())
    elif status_filter == 'handled':
        query = query.filter(UsernameChangeRequest.status.in_(['approved', 'rejected'])).order_by(UsernameChangeRequest.reviewed_at.desc())
    elif status_filter in ['approved', 'rejected', 'cancelled']:
        query = query.filter(UsernameChangeRequest.status == status_filter).order_by(UsernameChangeRequest.created_at.desc())
    else:
        status_filter = 'all'
        query = query.order_by(UsernameChangeRequest.created_at.desc())

    username_requests = query.all()
    review_form = ReviewUsernameRequestForm()

    return render_template(
        'username_requests_queue.html',
        username_requests=username_requests,
        status_filter=status_filter,
        selected_faculty=selected_faculty,
        faculties=FACULTIES,
        review_form=review_form
    )


@app.route('/dashboard/username-requests/<int:request_id>/approve', methods=['POST'])
@login_required
def approve_username_request(request_id):
    if not (current_user.is_admin() or current_user.is_moderator()):
        flash('Not authorized to review username requests.', 'danger')
        return redirect(url_for('home'))

    req = UsernameChangeRequest.query.filter_by(id=request_id, status='pending').first_or_404()

    # Rule: If requester is a Community Moderator, ONLY Administrators can approve
    if req.user.is_moderator() and not current_user.is_admin():
        flash('Only Administrators can approve username change requests submitted by Community Moderators.', 'danger')
        return redirect(request.referrer or url_for('username_requests_queue'))

    # If moderator, ensure request user is within their faculty
    if current_user.is_moderator() and not current_user.is_admin():
        if req.user.faculty != current_user.faculty:
            flash(f'You are only authorized to moderate users in {current_user.faculty}.', 'danger')
            return redirect(request.referrer or url_for('username_requests_queue'))

    form = ReviewUsernameRequestForm()
    reviewer_note = form.reviewer_note.data.strip() if form.reviewer_note.data and form.reviewer_note.data.strip() else None

    # Re-verify uniqueness
    existing = User.query.filter(
        db.func.lower(User.username) == req.new_username.lower(),
        User.id != req.user_id
    ).first()
    if existing:
        flash(f'Cannot approve: Username "@{req.new_username}" is already in use by another user.', 'danger')
        return redirect(request.referrer or url_for('username_requests_queue'))

    old_username = req.user.username
    req.user.username = req.new_username
    req.status = 'approved'
    req.reviewed_by_id = current_user.id
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewer_note = reviewer_note or ('Approved by Administrator' if current_user.is_admin() else 'Approved by Moderator')
    db.session.commit()

    flash(f'Approved! Username for {old_username} has been changed to "@{req.new_username}".', 'success')
    return redirect(request.referrer or url_for('username_requests_queue'))


@app.route('/dashboard/username-requests/<int:request_id>/reject', methods=['POST'])
@login_required
def reject_username_request(request_id):
    if not (current_user.is_admin() or current_user.is_moderator()):
        flash('Not authorized to review username requests.', 'danger')
        return redirect(url_for('home'))

    req = UsernameChangeRequest.query.filter_by(id=request_id, status='pending').first_or_404()

    # Rule: If requester is a Community Moderator, ONLY Administrators can review/disapprove
    if req.user.is_moderator() and not current_user.is_admin():
        flash('Only Administrators can review username change requests submitted by Community Moderators.', 'danger')
        return redirect(request.referrer or url_for('username_requests_queue'))

    # If moderator, ensure request user is within their faculty
    if current_user.is_moderator() and not current_user.is_admin():
        if req.user.faculty != current_user.faculty:
            flash(f'You are only authorized to moderate users in {current_user.faculty}.', 'danger')
            return redirect(request.referrer or url_for('username_requests_queue'))

    form = ReviewUsernameRequestForm()
    reviewer_note = form.reviewer_note.data.strip() if form.reviewer_note.data and form.reviewer_note.data.strip() else None

    req.status = 'rejected'
    req.reviewed_by_id = current_user.id
    req.reviewed_at = datetime.now(timezone.utc)
    req.reviewer_note = reviewer_note or ('Disapproved by Administrator' if current_user.is_admin() else 'Disapproved by Moderator')
    db.session.commit()

    flash(f'Username change request for @{req.current_username} (requested "@{req.new_username}") has been disapproved.', 'info')
    return redirect(request.referrer or url_for('username_requests_queue'))



# -------------------------------
# REPORTING & MODERATION ROUTES 
# -------------------------------

@app.route('/report', methods=['POST'])
@login_required
def submit_report():
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.is_json

    content_type = (request.form.get('content_type') or '').strip().lower()
    content_id_raw = request.form.get('content_id')
    reason = (request.form.get('reason') or '').strip()
    details = (request.form.get('details') or '').strip()

    if not content_type or not content_id_raw or not reason:
        msg = 'Missing required report parameters.'
        if is_ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'danger')
        return redirect(request.referrer or url_for('home'))

    try:
        content_id = int(content_id_raw)
    except ValueError:
        msg = 'Invalid content ID.'
        if is_ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'danger')
        return redirect(request.referrer or url_for('home'))

    # Validate content exists and determine faculty strictly on the server
    target_faculty = None
    content_snippet = None

    if content_type == 'question':
        question = db.session.get(Question, content_id)
        if not question:
            msg = 'The question being reported does not exist.'
            if is_ajax:
                return jsonify({'success': False, 'error': msg}), 404
            flash(msg, 'danger')
            return redirect(request.referrer or url_for('home'))
        target_faculty = question.faculty
        content_snippet = f"Question: {question.title}"

    elif content_type in ('answer', 'reply'):
        answer = db.session.get(Answer, content_id)
        if not answer or not answer.question:
            msg = 'The answer/reply being reported does not exist.'
            if is_ajax:
                return jsonify({'success': False, 'error': msg}), 404
            flash(msg, 'danger')
            return redirect(request.referrer or url_for('home'))
        target_faculty = answer.question.faculty
        prefix = "Reply" if answer.parent_answer_id else "Answer"
        content_snippet = f"{prefix} on '{answer.question.title}': {answer.content[:80]}"

    elif content_type == 'resource':
        resource = db.session.get(Resource, content_id)
        if not resource:
            msg = 'The resource being reported does not exist.'
            if is_ajax:
                return jsonify({'success': False, 'error': msg}), 404
            flash(msg, 'danger')
            return redirect(request.referrer or url_for('home'))
        target_faculty = resource.faculty
        content_snippet = f"Resource: {resource.title}"

    elif content_type in ('user', 'account'):
        target_user = db.session.get(User, content_id)
        if not target_user:
            msg = 'The user being reported does not exist.'
            if is_ajax:
                return jsonify({'success': False, 'error': msg}), 404
            flash(msg, 'danger')
            return redirect(request.referrer or url_for('home'))
        target_faculty = target_user.faculty
        content_snippet = f"User Account: @{target_user.username} ({target_user.role})"

    else:
        msg = 'Unsupported content type for reporting.'
        if is_ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'danger')
        return redirect(request.referrer or url_for('home'))

    # Check for duplicate pending report by the same user
    existing = Report.query.filter_by(
        reporter_id=current_user.id,
        content_type=content_type,
        content_id=content_id,
        status='pending'
    ).first()
    if existing:
        msg = 'You already have a pending report for this item. Our moderation team is reviewing it.'
        if is_ajax:
            return jsonify({'success': False, 'error': msg}), 400
        flash(msg, 'warning')
        return redirect(request.referrer or url_for('home'))

    report = Report(
        reporter_id=current_user.id,
        content_type=content_type,
        content_id=content_id,
        faculty=target_faculty,
        reason=reason,
        details=details,
        content_snippet=content_snippet,
        status='pending'
    )
    db.session.add(report)
    db.session.commit()

    success_msg = f'Report submitted successfully for {content_type} #{content_id}. Routed to {target_faculty} moderation.'
    if is_ajax:
        return jsonify({'success': True, 'message': success_msg})
    flash(success_msg, 'success')
    return redirect(request.referrer or url_for('home'))


@app.route('/reports/<int:report_id>')
@login_required
def report_detail(report_id):
    report = db.session.get(Report, report_id)
    if not report:
        flash('Report not found.', 'danger')
        if current_user.is_admin():
            return redirect(url_for('admin_dashboard'))
        elif current_user.is_moderator():
            return redirect(url_for('moderator_dashboard'))
        return redirect(url_for('home'))

    # Authorization Check:
    # Admin can access any report.
    # Moderator can access ONLY if report.faculty == current_user.faculty.
    # Others: Forbidden (403).
    if not (current_user.is_admin() or (current_user.is_moderator() and report.faculty == current_user.faculty)):
        abort(403)

    target_content = report.get_target_content()
    form = ReportActionForm()

    return render_template(
        'report_detail.html',
        report=report,
        target_content=target_content,
        form=form
    )


@app.route('/reports/<int:report_id>/action', methods=['POST'])
@login_required
def report_action(report_id):
    report = db.session.get(Report, report_id)
    if not report:
        flash('Report not found.', 'danger')
        return redirect(url_for('home'))

    # Authorization Check:
    if not (current_user.is_admin() or (current_user.is_moderator() and report.faculty == current_user.faculty)):
        abort(403)

    # Prevent conflicting actions if report has already been handled
    if report.status != 'pending':
        flash('This report has already been handled and cannot be modified.', 'warning')
        return redirect(url_for('report_detail', report_id=report.id))

    form = ReportActionForm()
    if not form.validate_on_submit():
        flash('Invalid action submission or missing CSRF token.', 'danger')
        return redirect(url_for('report_detail', report_id=report.id))

    action = form.action.data
    decision_note = form.decision_note.data.strip() if form.decision_note.data else ''

    if action not in ('resolve', 'dismiss', 'remove_content'):
        flash('Invalid moderation action selected.', 'danger')
        return redirect(url_for('report_detail', report_id=report.id))

    now_utc = datetime.now(timezone.utc)

    if action == 'resolve':
        report.status = 'resolved'
        report.action_taken = 'resolved'
    elif action == 'dismiss':
        report.status = 'dismissed'
        report.action_taken = 'dismissed'
    elif action == 'remove_content':
        report.status = 'content_removed'
        report.action_taken = 'content_removed'

        # Execute content removal using existing helpers & attachment cleanup
        if report.content_type == 'question':
            q = db.session.get(Question, report.content_id)
            if q:
                attachments = list(q.attachments)
                for ans in q.answers:
                    attachments.extend(ans.attachments)
                delete_attachment_files(attachments)
                q.best_answer_id = None
                db.session.delete(q)

        elif report.content_type in ('answer', 'reply'):
            ans = db.session.get(Answer, report.content_id)
            if ans:
                if ans.is_best_answer or (ans.question and ans.question.best_answer_id == ans.id):
                    ans.question.best_answer_id = None
                attachments = list(ans.attachments)
                for r in ans.replies:
                    attachments.extend(r.attachments)
                delete_attachment_files(attachments)
                db.session.delete(ans)

        elif report.content_type == 'resource':
            res = db.session.get(Resource, report.content_id)
            if res:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], res.stored_filename)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        app.logger.warning(f"Failed to remove resource file: {e}")
                db.session.delete(res)

        # Update any other pending reports for the exact same content to prevent conflicting actions
        other_reports = Report.query.filter(
            Report.content_type == report.content_type,
            Report.content_id == report.content_id,
            Report.id != report.id,
            Report.status == 'pending'
        ).all()
        for other in other_reports:
            other.status = 'content_removed'
            other.action_taken = 'content_removed'
            other.reviewed_by_id = current_user.id
            other.reviewed_at = now_utc
            other.decision_note = f"Content was removed when handling Report #{report.id}: {decision_note}"

    report.reviewed_by_id = current_user.id
    report.reviewed_at = now_utc
    report.decision_note = decision_note

    db.session.commit()
    flash(f'Report #{report.id} successfully updated (Action: {report.action_taken}).', 'success')

    if current_user.is_admin():
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('moderator_dashboard'))


# -------------------------------
# MODERATOR APPLICATION MODULE ROUTES
# -------------------------------

@app.route('/moderator/apply', methods=['GET', 'POST'])
@login_required
def moderator_apply():
    if not current_user.is_student():
        flash('Only students can apply to become a Community Moderator.', 'warning')
        return redirect(url_for('dashboard'))

    if current_user.has_pending_moderator_application:
        flash('You already have a pending moderator application. Please wait for an administrator to review it.', 'info')
        return redirect(url_for('moderator_status'))

    form = ModeratorApplicationForm()
    if request.method == 'GET':
        form.faculty.data = current_user.faculty

    if form.validate_on_submit():
        application = ModeratorApplication(
            user_id=current_user.id,
            full_name=form.full_name.data.strip(),
            matric_number=form.matric_number.data.strip(),
            faculty=form.faculty.data,
            reason=form.reason.data.strip(),
            status='pending'
        )
        db.session.add(application)
        db.session.commit()
        flash('Your application has been submitted successfully! An administrator will review it.', 'success')
        return redirect(url_for('moderator_status'))

    return render_template('moderator_apply.html', form=form)


@app.route('/moderator/application-status')
@login_required
def moderator_status():
    applications = ModeratorApplication.query.filter_by(user_id=current_user.id).order_by(ModeratorApplication.created_at.desc()).all()
    latest_app = applications[0] if applications else None
    return render_template('moderator_status.html', applications=applications, latest_app=latest_app)


@app.route('/dashboard/admin/application/<int:app_id>')
@login_required
def moderator_application_detail(app_id):
    if not current_user.is_admin():
        flash('Not authorized to view moderator applications.', 'danger')
        return redirect(url_for('home'))

    application = db.session.get(ModeratorApplication, app_id)
    if not application:
        flash('Application not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    review_form = ModeratorApplicationReviewForm()
    return render_template(
        'moderator_application_detail.html',
        application=application,
        applicant=application.applicant,
        form=review_form
    )


@app.route('/dashboard/admin/application/<int:app_id>/action', methods=['POST'])
@login_required
def moderator_application_action(app_id):
    if not current_user.is_admin():
        flash('Not authorized to perform this action.', 'danger')
        return redirect(url_for('home'))

    application = db.session.get(ModeratorApplication, app_id)
    if not application:
        flash('Application not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if application.status != 'pending':
        flash('This application has already been reviewed.', 'warning')
        return redirect(url_for('moderator_application_detail', app_id=app_id))

    form = ModeratorApplicationReviewForm()
    if form.validate_on_submit():
        decision = form.action.data
        admin_note = (form.admin_note.data or '').strip()

        application.reviewed_by_id = current_user.id
        application.reviewed_at = datetime.now(timezone.utc)
        application.admin_note = admin_note

        applicant_user = application.applicant
        if not applicant_user:
            flash('Applicant user account no longer exists.', 'danger')
            return redirect(url_for('admin_dashboard'))

        if decision == 'approve':
            application.status = 'approved'
            applicant_user.role = 'Community Moderator'
            applicant_user.faculty = application.faculty
            flash(f"Application approved! '{applicant_user.username}' is now a Community Moderator for {application.faculty}.", 'success')
        else:
            application.status = 'rejected'
            flash(f"Application for '{applicant_user.username}' has been rejected.", 'info')

        db.session.commit()
        return redirect(url_for('admin_dashboard'))

    flash('Invalid review form submission.', 'danger')
    return redirect(url_for('moderator_application_detail', app_id=app_id))


# -------------------------------
# USER DISCIPLINE & INBOX ROUTES
# -------------------------------

@app.route('/dashboard/admin/user/<int:user_id>/ban', methods=['POST'])
@login_required
def admin_ban_user(user_id):
    if not current_user.is_admin():
        abort(403)

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if target_user.is_admin():
        flash('Cannot ban an Administrator.', 'danger')
        return redirect(url_for('admin_dashboard'))

    form = BanUserForm()
    reason = form.reason.data.strip() if (form.validate_on_submit() and form.reason.data) else (request.form.get('reason', '').strip() or 'Violation of platform policies')

    target_user.is_banned = True

    existing_ban = BannedEmail.query.filter_by(email=target_user.email.lower()).first()
    if not existing_ban:
        banned_record = BannedEmail(
            email=target_user.email.lower(),
            username_snapshot=target_user.username,
            reason=reason,
            banned_by_id=current_user.id
        )
        db.session.add(banned_record)

    db.session.commit()
    flash(f"User '{target_user.username}' ({target_user.email}) has been permanently banned and their email blacklisted.", 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/user/<int:user_id>/unban', methods=['POST'])
@login_required
def admin_unban_user(user_id):
    if not current_user.is_admin():
        abort(403)

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    target_user.is_banned = False

    banned_record = BannedEmail.query.filter_by(email=target_user.email.lower()).first()
    if banned_record:
        db.session.delete(banned_record)

    db.session.commit()
    flash(f"User '{target_user.username}' has been unbanned. Account access and email registration restored.", 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/banned-email/<int:banned_id>/unban', methods=['POST'])
@login_required
def admin_unban_email(banned_id):
    if not current_user.is_admin():
        abort(403)

    banned_record = db.session.get(BannedEmail, banned_id)
    if not banned_record:
        flash('Banned email record not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    user = User.query.filter_by(email=banned_record.email.lower()).first()
    if user:
        user.is_banned = False

    email_str = banned_record.email
    db.session.delete(banned_record)
    db.session.commit()
    flash(f"Email '{email_str}' has been unbanned and removed from the blacklist.", 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/user/<int:user_id>/suspend', methods=['POST'])
@login_required
def admin_suspend_user(user_id):
    if not current_user.is_admin():
        abort(403)

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    if target_user.is_admin():
        flash('Cannot suspend an Administrator.', 'danger')
        return redirect(url_for('admin_dashboard'))

    form = SuspendUserForm()
    if form.validate_on_submit():
        days = form.days.data or 30
        reason = form.reason.data.strip() if form.reason.data else 'Account temporarily suspended by administration'
    else:
        try:
            days = int(request.form.get('days', 30))
        except (ValueError, TypeError):
            days = 30
        reason = request.form.get('reason', '').strip() or 'Account temporarily suspended by administration'

    target_user.suspended_until = datetime.now(timezone.utc) + timedelta(days=days)
    target_user.suspension_reason = reason
    db.session.commit()

    flash(f"User '{target_user.username}' has been suspended for {days} days.", 'warning')
    return redirect(url_for('admin_dashboard'))


@app.route('/dashboard/admin/user/<int:user_id>/unsuspend', methods=['POST'])
@login_required
def admin_unsuspend_user(user_id):
    if not current_user.is_admin():
        abort(403)

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin_dashboard'))

    target_user.suspended_until = None
    target_user.suspension_reason = None
    db.session.commit()

    flash(f"Suspension for user '{target_user.username}' has been lifted.", 'success')
    return redirect(url_for('admin_dashboard'))


@app.route('/user/<int:user_id>/warn', methods=['POST'])
@login_required
def issue_warning(user_id):
    if not (current_user.is_admin() or current_user.is_moderator()):
        abort(403)

    target_user = db.session.get(User, user_id)
    if not target_user:
        flash('User not found.', 'danger')
        return redirect(request.referrer or url_for('home'))

    if target_user.is_admin():
        flash('Cannot issue disciplinary warnings to an Administrator.', 'danger')
        return redirect(request.referrer or url_for('admin_dashboard'))

    if current_user.is_moderator() and not current_user.is_admin():
        if target_user.faculty != current_user.faculty:
            flash(f"Moderators can only issue warnings to users in their own faculty ({current_user.faculty}).", 'danger')
            return redirect(request.referrer or url_for('moderator_dashboard'))

    message = request.form.get('message', '').strip()
    if not message or len(message) < 5:
        flash('Warning message must be at least 5 characters long.', 'danger')
        return redirect(request.referrer or url_for('home'))

    sender_role = 'Administrator' if current_user.is_admin() else f'{current_user.faculty} Community Moderator'
    warning = UserWarning(
        user_id=target_user.id,
        issued_by_id=current_user.id,
        sender_role=sender_role,
        faculty=current_user.faculty,
        title='Official Account Warning',
        message=message
    )
    db.session.add(warning)
    db.session.commit()

    flash(f"Official warning sent to '{target_user.username}'. It will appear in their Inbox.", 'success')
    return redirect(request.referrer or url_for('home'))


@app.route('/inbox')
@login_required
def inbox():
    warnings = UserWarning.query.filter_by(user_id=current_user.id).order_by(UserWarning.created_at.desc()).all()
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template('inbox.html', warnings=warnings, notifications=notifications)


@app.route('/inbox/<int:warning_id>/read', methods=['POST'])
@login_required
def mark_warning_read(warning_id):
    warning = db.session.get(UserWarning, warning_id)
    if not warning or warning.user_id != current_user.id:
        abort(404)

    warning.is_read = True
    db.session.commit()
    flash('Warning marked as acknowledged.', 'info')
    return redirect(url_for('inbox'))


@app.route('/notifications/<int:notif_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notif_id):
    notif = db.session.get(Notification, notif_id)
    if not notif or notif.user_id != current_user.id:
        abort(404)

    notif.is_read = True
    db.session.commit()
    redirect_target = request.form.get('next') or notif.link_url or url_for('inbox')
    return redirect(redirect_target)


@app.route('/notifications/mark-all-read', methods=['POST'])
@login_required
def mark_all_notifications_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('All notifications marked as read.', 'info')
    return redirect(url_for('inbox'))



#-------------------------------
# Q&A MODULE HELPERS & ROUTES 
#-------------------------------

def validate_and_save_screenshots(files, uploader_id, question_id=None, answer_id=None):
    """
    Validates and saves up to 3 screenshots.
    - Validates format (PNG, JPG/JPEG, WebP)
    - Validates max 5MB per file
    - Validates actual image content using Pillow to reject spoofed or corrupted images
    - Generates safe unique stored filenames
    - Cleans up newly saved files if validation fails
    Returns (attachments_list, error_message)
    """
    valid_files = [f for f in files if f and hasattr(f, 'filename') and f.filename and f.filename.strip() != '']
    if not valid_files:
        return [], None

    if len(valid_files) > MAX_SCREENSHOTS_COUNT:
        return None, f"You can upload a maximum of {MAX_SCREENSHOTS_COUNT} screenshots per submission."

    saved_attachments = []
    created_filepaths = []

    try:
        for file in valid_files:
            orig_name = secure_filename(file.filename)
            if not orig_name:
                orig_name = "screenshot.png"

            ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else ''
            if ext not in ALLOWED_SCREENSHOT_EXTENSIONS:
                raise ValueError(f"Invalid image type '.{ext}'. Allowed formats: PNG, JPG, JPEG, WebP.")

            # Check file size (5 MB limit)
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)

            if size > MAX_SCREENSHOT_SIZE:
                raise ValueError(f"File '{orig_name}' exceeds the 5 MB limit per image.")

            if size == 0:
                raise ValueError(f"File '{orig_name}' is empty.")

            # Validate actual image content using Pillow
            try:
                img = Image.open(file.stream)
                img.verify()  # Validates image format and structure
                if img.format.lower() not in ['png', 'jpeg', 'webp']:
                    raise ValueError(f"File '{orig_name}' contains invalid image data ({img.format}).")
            except Exception as img_err:
                raise ValueError(f"File '{orig_name}' is corrupted or not a valid image: {img_err}")

            # Reset stream after verify()
            file.seek(0)

            # Generate unique safe stored filename
            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
            unique_token = uuid.uuid4().hex[:8]
            stored_filename = f"{timestamp}_{unique_token}_{orig_name}"
            file_path = os.path.join(app.config['SCREENSHOTS_FOLDER'], stored_filename)

            # Save to disk
            file.save(file_path)
            created_filepaths.append(file_path)

            attachment = QAAttachment(
                filename=orig_name,
                stored_filename=stored_filename,
                file_size=size,
                file_type=ext,
                question_id=question_id,
                answer_id=answer_id,
                uploader_id=uploader_id
            )
            saved_attachments.append(attachment)

        return saved_attachments, None

    except Exception as e:
        # Clean up any newly created files on disk if an error occurs
        for path in created_filepaths:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        return None, str(e)


def delete_attachment_files(attachments):
    """Deletes physical screenshot files from disk for given QAAttachment records."""
    for att in attachments:
        if att and att.stored_filename:
            file_path = os.path.join(app.config['SCREENSHOTS_FOLDER'], att.stored_filename)
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    app.logger.warning(f"Failed to remove screenshot file {file_path}: {e}")


@app.route('/uploads/screenshots/<filename>')
def serve_screenshot(filename):
    """Serves uploaded screenshot attachments."""
    return send_from_directory(app.config['SCREENSHOTS_FOLDER'], filename)


@app.route('/qa/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_qa_attachment(attachment_id):
    """Deletes a specific attached screenshot from disk and database."""
    att = db.session.get(QAAttachment, attachment_id)
    if not att:
        flash('Attachment not found.', 'danger')
        return redirect(request.referrer or url_for('qa_list'))

    if att.uploader_id != current_user.id and not current_user.is_admin():
        flash('You are not authorized to delete this attachment.', 'danger')
        return redirect(request.referrer or url_for('qa_list'))

    delete_attachment_files([att])
    db.session.delete(att)
    db.session.commit()
    flash('Attached photo removed successfully.', 'info')
    return redirect(request.referrer or url_for('qa_list'))


@app.route('/uploads/avatars/<filename>')
def serve_avatar(filename):
    """Serves uploaded user avatar profile photos."""
    return send_from_directory(app.config['AVATARS_FOLDER'], filename)


@app.route('/qa')
def qa_list():
    query_text = request.args.get('q', '').strip()
    selected_faculty = request.args.get('faculty', '').strip()
    selected_category = request.args.get('category', '').strip()
    sort_by = request.args.get('sort', 'newest').strip()
    show_unanswered = request.args.get('unanswered', '').strip() == '1'

    page = request.args.get('page', 1, type=int)
    if not isinstance(page, int) or page < 1:
        page = 1

    query = Question.query

    # Privacy and Visibility Enforcement (Habib)
    if current_user.is_authenticated:
        # Exclude questions by users with platform-wide block restrictions in either direction
        blocked_user_ids = [
            b.blocked_id for b in ChatBlock.query.filter_by(blocker_id=current_user.id, block_scope='platform').all()
        ] + [
            b.blocker_id for b in ChatBlock.query.filter_by(blocked_id=current_user.id, block_scope='platform').all()
        ]
        if blocked_user_ids:
            query = query.filter(~Question.author_id.in_(blocked_user_ids))

        if current_user.is_admin() or current_user.is_moderator() or current_user.is_professor():
            # Special roles override: can view all non-draft questions across faculties
            query = query.filter(Question.is_draft == False)
        else:
            # Regular students: can view public questions, own questions, and questions from followed users
            followed_ids = [f.followed_id for f in UserFollow.query.filter_by(follower_id=current_user.id, status='accepted').all()]
            if followed_ids:
                visibility_filter = (
                    (Question.visibility == 'public') |
                    (Question.author_id == current_user.id) |
                    (Question.author_id.in_(followed_ids))
                )
            else:
                visibility_filter = (
                    (Question.visibility == 'public') |
                    (Question.author_id == current_user.id)
                )
            query = query.filter((Question.is_draft == False) & visibility_filter)
    else:
        query = query.filter((Question.is_draft == False) & (Question.visibility == 'public'))

    if query_text:
        search_filter = f"%{query_text}%"
        query = query.filter((Question.title.ilike(search_filter)) | (Question.content.ilike(search_filter)))

    if selected_faculty:
        query = query.filter(Question.faculty == selected_faculty)

    if selected_category:
        query = query.filter(Question.category == selected_category)

    if show_unanswered:
        # Filter for questions with 0 top-level answers (where parent_answer_id is NULL)
        query = query.filter(~Question.answers.any(Answer.parent_answer_id.is_(None)))

    if sort_by == 'views':
        query = query.order_by(Question.views.desc(), Question.created_at.desc())
    else:
        sort_by = 'newest'
        query = query.order_by(Question.created_at.desc())

    # 10 questions per page
    pagination = query.paginate(page=page, per_page=10, error_out=False)
    questions = pagination.items

    return render_template(
        'qa/index.html',
        questions=questions,
        pagination=pagination,
        query_text=query_text,
        selected_faculty=selected_faculty,
        selected_category=selected_category,
        sort_by=sort_by,
        show_unanswered=show_unanswered,
        faculties=FACULTIES,
        categories=QUESTION_CATEGORIES
    )


@app.route('/qa/ask', methods=['GET', 'POST'])
@login_required
def qa_ask():
    form = QuestionForm()
    if request.method == 'GET' and hasattr(current_user, 'faculty') and current_user.faculty:
        form.faculty.data = current_user.faculty

    is_saving_draft = bool(request.form.get('save_draft') or request.form.get('action') == 'draft')

    if request.method == 'POST':
        if is_saving_draft:
            # Relaxed validation for saving incomplete questions as drafts
            title = request.form.get('title', '').strip()
            category = request.form.get('category', 'General')
            faculty = request.form.get('faculty', current_user.faculty or FACULTY_CODES[0])
            visibility = request.form.get('visibility', 'public')
            content = request.form.get('content', '').strip()

            if not title:
                flash('Please enter at least a title to save a draft question.', 'danger')
                return render_template('qa/ask.html', form=form)

            has_prof, p_term = contains_profanity(title)
            if has_prof:
                flash(f"Draft title contains prohibited language ('{p_term}').", 'danger')
                return render_template('qa/ask.html', form=form)

            if content:
                has_prof_c, c_term = contains_profanity(content)
                if has_prof_c:
                    flash(f"Draft content contains prohibited language ('{c_term}').", 'danger')
                    return render_template('qa/ask.html', form=form)

            files = request.files.getlist('screenshots')
            attachments, err = validate_and_save_screenshots(files, current_user.id)
            if err:
                flash(err, 'danger')
                return render_template('qa/ask.html', form=form)

            try:
                question = Question(
                    title=title,
                    content=content,
                    category=category,
                    faculty=faculty,
                    visibility=visibility,
                    author_id=current_user.id,
                    views=0,
                    is_draft=True
                )
                db.session.add(question)
                db.session.flush()

                for att in attachments:
                    att.question_id = question.id
                    db.session.add(att)

                db.session.commit()
                flash('Question saved as a private draft! You can access it anytime under Drafts.', 'info')
                return redirect(url_for('qa_drafts'))

            except Exception as e:
                db.session.rollback()
                delete_attachment_files(attachments)
                flash(f'An error occurred while saving your draft: {e}', 'danger')
                return render_template('qa/ask.html', form=form)

        elif form.validate_on_submit():
            # Standard publish flow with full validation
            files = request.files.getlist('screenshots')
            attachments, err = validate_and_save_screenshots(files, current_user.id)
            if err:
                flash(err, 'danger')
                return render_template('qa/ask.html', form=form)

            try:
                question = Question(
                    title=form.title.data.strip(),
                    content=form.content.data.strip(),
                    category=form.category.data,
                    faculty=form.faculty.data,
                    visibility=form.visibility.data,
                    author_id=current_user.id,
                    views=0,
                    is_draft=False
                )
                db.session.add(question)
                db.session.flush()

                for att in attachments:
                    att.question_id = question.id
                    db.session.add(att)

                db.session.commit()
                # Process mentions in question body
                process_mentions(question.content, current_user, 'question', question.id, question.id)

                flash('Your question has been posted!', 'success')
                return redirect(url_for('qa_detail', question_id=question.id))

            except Exception as e:
                app.logger.error(f"Error saving question: {e}")
                db.session.rollback()
                delete_attachment_files(attachments)
                flash('An error occurred while saving your question. Please try again.', 'danger')
                return render_template('qa/ask.html', form=form)

    return render_template('qa/ask.html', form=form)


@app.route('/qa/drafts')
@login_required
def qa_drafts():
    drafts = Question.query.filter_by(
        author_id=current_user.id,
        is_draft=True
    ).order_by(Question.created_at.desc()).all()
    return render_template('qa/drafts.html', drafts=drafts)


@app.route('/qa/drafts/<int:draft_id>/edit', methods=['GET', 'POST'])
@login_required
def qa_edit_draft(draft_id):
    draft = db.session.get(Question, draft_id)
    if not draft:
        flash('Draft not found.', 'danger')
        return redirect(url_for('qa_drafts'))

    if draft.author_id != current_user.id:
        flash('You are not authorized to access this draft.', 'danger')
        return redirect(url_for('qa_drafts'))

    form = DraftQuestionForm(obj=draft)

    if form.validate_on_submit():
        is_publish = bool(form.submit_publish.data or request.form.get('action') == 'publish')

        draft.title = form.title.data.strip()
        draft.category = form.category.data
        draft.faculty = form.faculty.data
        draft.visibility = form.visibility.data
        draft.content = form.content.data.strip() if form.content.data else ''

        # Handle screenshot attachments
        files = request.files.getlist('screenshots')
        if any(f and getattr(f, 'filename', None) for f in files):
            attachments, err = validate_and_save_screenshots(files, current_user.id, question_id=draft.id)
            if err:
                flash(err, 'danger')
                return render_template('qa/edit_draft.html', form=form, draft=draft)
            for att in attachments:
                att.question_id = draft.id
                db.session.add(att)

        if is_publish:
            # Full validation before publishing
            if len(draft.title) < 5:
                flash('Question title must be at least 5 characters long to publish.', 'danger')
                return render_template('qa/edit_draft.html', form=form, draft=draft)

            if len(draft.content) < 10:
                flash('Question details must be at least 10 characters long to publish.', 'danger')
                return render_template('qa/edit_draft.html', form=form, draft=draft)

            has_prof_t, term_t = contains_profanity(draft.title)
            if has_prof_t:
                flash(f"Title contains prohibited language ('{term_t}').", 'danger')
                return render_template('qa/edit_draft.html', form=form, draft=draft)

            has_prof_c, term_c = contains_profanity(draft.content)
            if has_prof_c:
                flash(f"Question details contain prohibited language ('{term_c}').", 'danger')
                return render_template('qa/edit_draft.html', form=form, draft=draft)

            draft.is_draft = False
            draft.created_at = datetime.now(timezone.utc)
            db.session.commit()
            process_mentions(draft.content, current_user, 'question', draft.id, draft.id)
            flash('Your question has been published!', 'success')
            return redirect(url_for('qa_detail', question_id=draft.id))
        else:
            db.session.commit()
            flash('Draft updated successfully.', 'info')
            return redirect(url_for('qa_drafts'))

    return render_template('qa/edit_draft.html', form=form, draft=draft)


@app.route('/qa/drafts/<int:draft_id>/delete', methods=['POST'])
@login_required
def qa_delete_draft(draft_id):
    draft = db.session.get(Question, draft_id)
    if not draft or draft.author_id != current_user.id:
        flash('Draft not found or unauthorized.', 'danger')
        return redirect(url_for('qa_drafts'))

    delete_attachment_files(draft.attachments)
    db.session.delete(draft)
    db.session.commit()
    flash('Draft question deleted.', 'info')
    return redirect(url_for('qa_drafts'))


@app.route('/qa/<int:question_id>', methods=['GET', 'POST'])
def qa_detail(question_id):
    question = db.session.get(Question, question_id)
    if not question:
        flash('Question not found.', 'danger')
        return redirect(url_for('qa_list'))

    # Question Visibility & Draft Access Check
    if not question.can_view(current_user):
        if question.is_draft:
            flash('This question is a private draft and can only be accessed by its author.', 'warning')
        else:
            flash(f"This question is private (Friends Only). You must be an accepted follower of @{question.author.username} to view it.", 'danger')
        return redirect(url_for('qa_list'))

    form = AnswerForm()
    if form.validate_on_submit():
        if not current_user.is_authenticated:
            flash('You must be logged in to submit an answer.', 'warning')
            return redirect(url_for('login'))

        # --- Reply-to-answer feature (Habib) ---
        parent_id_val = request.form.get('parent_answer_id')
        parent_answer_id = None
        if parent_id_val and parent_id_val.isdigit():
            parent_id_int = int(parent_id_val)
            parent_answer = db.session.get(Answer, parent_id_int)
            if parent_answer and parent_answer.question_id == question.id:
                parent_answer_id = parent_id_int

        # Handle optional screenshots
        files = request.files.getlist('screenshots')
        if not any(f and f.filename for f in files):
            reply_files = request.files.getlist('reply_screenshots')
            if any(f and f.filename for f in reply_files):
                files = reply_files

        attachments, err = validate_and_save_screenshots(files, current_user.id)
        if err:
            flash(err, 'danger')
            return redirect(url_for('qa_detail', question_id=question.id))

        try:
            answer = Answer(
                content=form.content.data.strip(),
                question_id=question.id,
                author_id=current_user.id,
                parent_answer_id=parent_answer_id,
                visibility=form.visibility.data
            )
            db.session.add(answer)
            db.session.flush()

            for att in attachments:
                att.answer_id = answer.id
                db.session.add(att)

            db.session.commit()

            # Process mentions in answer or reply
            process_mentions(answer.content, current_user, 'reply' if parent_answer_id else 'answer', answer.id, question.id)

            if parent_answer_id:
                flash('Your reply has been submitted!', 'success')
            else:
                flash('Your answer has been submitted!', 'success')
            return redirect(url_for('qa_detail', question_id=question.id) + f'#answer-{answer.id}')

        except Exception as e:
            app.logger.error(f"Error submitting answer: {e}")
            db.session.rollback()
            delete_attachment_files(attachments)
            flash('An error occurred while submitting your answer. Please try again.', 'danger')
            return redirect(url_for('qa_detail', question_id=question.id))

    # View count tracking on valid GET requests (at most once per session)
    if request.method == 'GET':
        viewed_questions = session.get('viewed_questions', [])
        if question.id not in viewed_questions:
            question.views = (question.views or 0) + 1
            db.session.commit()
            viewed_questions.append(question.id)
            session['viewed_questions'] = viewed_questions

    # Priority sorting (for visible top-level answers):
    top_level_answers = [a for a in question.answers if a.parent_answer_id is None and a.can_view(current_user)]
    sorted_answers = sorted(
        top_level_answers,
        key=lambda a: (
            a.total_points,
            1 if (a.author and a.author.is_professor()) else 0,
            a.created_at
        ),
        reverse=True
    )

    return render_template('qa/detail.html', question=question, answers=sorted_answers, form=form)


@app.route('/qa/answer/<int:answer_id>/best', methods=['POST'])
@login_required
def mark_best_answer(answer_id):
    answer = db.session.get(Answer, answer_id)
    if not answer:
        flash('Answer not found.', 'danger')
        return redirect(url_for('qa_list'))

    question = answer.question

    # Users cannot mark their own answer
    if answer.author_id == current_user.id:
        flash('You cannot mark your own answer as the best answer.', 'warning')
        return redirect(url_for('qa_detail', question_id=question.id))

    # Toggle best mark
    existing_mark = AnswerBestMark.query.filter_by(user_id=current_user.id, answer_id=answer.id).first()
    if existing_mark:
        db.session.delete(existing_mark)
        if current_user.is_professor():
            flash('Removed your Super Excellent endorsement.', 'info')
        else:
            flash('Removed your Best Answer mark.', 'info')
    else:
        new_mark = AnswerBestMark(user_id=current_user.id, answer_id=answer.id)
        db.session.add(new_mark)
        if current_user.is_professor():
            flash('Marked as Super Excellent (+50 pts)!', 'success')
        else:
            flash('Marked as Best Answer (+5 pts)!', 'success')

    db.session.commit()
    return redirect(url_for('qa_detail', question_id=question.id) + f'#answer-{answer.id}')


@app.route('/qa/answer/<int:answer_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_answer(answer_id):
    answer = db.session.get(Answer, answer_id)
    if not answer:
        flash('Answer not found.', 'danger')
        return redirect(url_for('qa_list'))

    if answer.author_id != current_user.id:
        flash('You can only edit your own answers.', 'danger')
        return redirect(url_for('qa_detail', question_id=answer.question_id))

    form = AnswerForm(obj=answer)
    if form.validate_on_submit():
        answer.content = form.content.data.strip()
        answer.visibility = form.visibility.data
        db.session.commit()

        # Process mentions on edit
        process_mentions(answer.content, current_user, 'reply' if answer.parent_answer_id else 'answer', answer.id, answer.question_id)

        flash('Your answer has been updated.', 'success')
        return redirect(url_for('qa_detail', question_id=answer.question_id) + f'#answer-{answer.id}')

    return render_template('qa/edit_answer.html', form=form, answer=answer)


@app.route('/qa/answer/<int:answer_id>/delete', methods=['POST'])
@login_required
def delete_answer(answer_id):
    answer = db.session.get(Answer, answer_id)
    if not answer:
        flash('Answer not found.', 'danger')
        return redirect(url_for('qa_list'))

    if answer.author_id != current_user.id:
        flash('You can only delete your own answers.', 'danger')
        return redirect(url_for('qa_detail', question_id=answer.question_id))

    question_id = answer.question_id
    if answer.is_best_answer or (answer.question and answer.question.best_answer_id == answer.id):
        answer.question.best_answer_id = None

    # Clean up physical screenshot files
    attachments_to_delete = list(answer.attachments)
    for reply in answer.replies:
        attachments_to_delete.extend(reply.attachments)
    delete_attachment_files(attachments_to_delete)

    db.session.delete(answer)
    db.session.commit()
    flash('Your answer has been deleted.', 'info')
    return redirect(url_for('qa_detail', question_id=question_id))


# =====================================================================
# ONE-TO-ONE PRIVATE CHAT & BLOCKING ROUTES (HABIB)
# =====================================================================

@app.route('/chat')
@login_required
def chat_list():
    sent_peers = db.session.query(ChatMessage.recipient_id).filter_by(sender_id=current_user.id)
    recv_peers = db.session.query(ChatMessage.sender_id).filter_by(recipient_id=current_user.id)
    peer_ids = list(set([pid[0] for pid in sent_peers.union(recv_peers).all()]))

    conversations = []
    for pid in peer_ids:
        peer = db.session.get(User, pid)
        if not peer:
            continue

        last_msg = ChatMessage.query.filter(
            ((ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_id == peer.id)) |
            ((ChatMessage.sender_id == peer.id) & (ChatMessage.recipient_id == current_user.id))
        ).order_by(ChatMessage.created_at.desc()).first()

        unread_count = ChatMessage.query.filter_by(
            sender_id=peer.id,
            recipient_id=current_user.id,
            is_read=False
        ).count()

        is_blocked = current_user.has_blocked_chat(peer)
        is_blocked_by = current_user.is_chat_blocked_by(peer)

        conversations.append({
            'peer': peer,
            'last_message': last_msg,
            'unread_count': unread_count,
            'is_blocked': is_blocked,
            'is_blocked_by': is_blocked_by
        })

    conversations.sort(
        key=lambda c: c['last_message'].created_at if c['last_message'] and c['last_message'].created_at else datetime.min.replace(tzinfo=timezone.utc),
        reverse=True
    )

    # Fetch users followed by current_user for Instagram-style quick messaging
    following_relations = UserFollow.query.filter_by(follower_id=current_user.id, status='accepted').all()
    followed_users = [rel.followed for rel in following_relations if rel.followed and not rel.followed.is_banned]

    return render_template('chat_list.html', conversations=conversations, followed_users=followed_users)


@app.route('/chat/<username>', methods=['GET', 'POST'])
@app.route('/chat/user/<username>', methods=['GET', 'POST'])
@login_required
def chat_conversation(username):
    peer = User.query.filter_by(username=username).first_or_404()

    if peer.id == current_user.id:
        flash('You cannot initiate a private chat with yourself.', 'info')
        return redirect(url_for('chat_list'))

    is_blocked_by_me = current_user.has_blocked_chat(peer)
    is_blocked_by_peer = current_user.is_chat_blocked_by(peer)
    is_messaging_disabled = is_blocked_by_me or is_blocked_by_peer

    form = ChatMessageForm()
    if form.validate_on_submit():
        if is_messaging_disabled:
            flash('Messaging is unavailable with this user.', 'danger')
            return redirect(url_for('chat_conversation', username=peer.username))

        msg_content = form.message.data.strip()
        new_msg = ChatMessage(
            sender_id=current_user.id,
            recipient_id=peer.id,
            message=msg_content
        )
        db.session.add(new_msg)
        db.session.commit()

        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({
                'success': True,
                'message': {
                    'id': new_msg.id,
                    'sender_id': current_user.id,
                    'sender_username': current_user.username,
                    'message': new_msg.message,
                    'created_at': new_msg.created_at.strftime('%b %d, %H:%M'),
                    'is_edited': False,
                    'is_mine': True
                }
            })

        flash('Message sent.', 'success')
        return redirect(url_for('chat_conversation', username=peer.username))

    # Mark incoming unread messages as read
    ChatMessage.query.filter_by(
        sender_id=peer.id,
        recipient_id=current_user.id,
        is_read=False
    ).update({'is_read': True})
    db.session.commit()

    messages = ChatMessage.query.filter(
        ((ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_id == peer.id)) |
        ((ChatMessage.sender_id == peer.id) & (ChatMessage.recipient_id == current_user.id))
    ).order_by(ChatMessage.created_at.asc()).all()

    return render_template(
        'chat_conversation.html',
        peer=peer,
        messages=messages,
        form=form,
        is_blocked_by_me=is_blocked_by_me,
        is_blocked_by_peer=is_blocked_by_peer,
        is_messaging_disabled=is_messaging_disabled
    )


@app.route('/chat/<username>/poll')
@login_required
def chat_poll(username):
    peer = User.query.filter_by(username=username).first_or_404()
    last_id = request.args.get('last_id', 0, type=int)

    new_messages = ChatMessage.query.filter(
        ChatMessage.id > last_id,
        ((ChatMessage.sender_id == current_user.id) & (ChatMessage.recipient_id == peer.id)) |
        ((ChatMessage.sender_id == peer.id) & (ChatMessage.recipient_id == current_user.id))
    ).order_by(ChatMessage.created_at.asc()).all()

    # Mark incoming new messages as read
    for m in new_messages:
        if m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True
    if new_messages:
        db.session.commit()

    last_read_id = db.session.query(db.func.max(ChatMessage.id)).filter_by(
        sender_id=current_user.id, recipient_id=peer.id, is_read=True
    ).scalar() or 0

    return jsonify({
        'messages': [
            {
                'id': m.id,
                'sender_id': m.sender_id,
                'sender_username': m.sender.username,
                'message': m.message,
                'created_at': m.created_at.strftime('%b %d, %H:%M') if m.created_at else '',
                'is_edited': getattr(m, 'is_edited', False),
                'is_read': m.is_read,
                'is_mine': (m.sender_id == current_user.id)
            } for m in new_messages
        ],
        'last_read_id': last_read_id,
        'is_blocked': current_user.has_blocked_chat(peer) or peer.has_blocked_chat(current_user)
    })


@app.route('/chat/message/<int:message_id>/edit', methods=['POST'])
@login_required
def chat_edit_message(message_id):
    msg = ChatMessage.query.get_or_404(message_id)

    # Security: only the sender can edit their own message
    if msg.sender_id != current_user.id:
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': 'You are not authorized to edit this message.'}), 403
        flash('You cannot edit someone else’s message.', 'danger')
        return redirect(request.referrer or url_for('chat_list'))

    # Extract text from json or form body
    if request.is_json:
        data = request.get_json() or {}
        new_text = (data.get('message') or '').strip()
    else:
        new_text = (request.form.get('message') or '').strip()

    if not new_text:
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': 'Message content cannot be empty.'}), 400
        flash('Message content cannot be empty.', 'warning')
        return redirect(request.referrer or url_for('chat_list'))

    if len(new_text) > 1000:
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': 'Message exceeds maximum length of 1000 characters.'}), 400
        flash('Message is too long (max 1000 characters).', 'warning')
        return redirect(request.referrer or url_for('chat_list'))

    has_prof, term = contains_profanity(new_text)
    if has_prof:
        err_msg = f"Your message contains prohibited or inappropriate language ('{term}')."
        if request.headers.get('Accept') == 'application/json' or request.is_json:
            return jsonify({'success': False, 'error': err_msg}), 400
        flash(err_msg, 'danger')
        return redirect(request.referrer or url_for('chat_list'))

    msg.message = new_text
    msg.is_edited = True
    msg.edited_at = datetime.now(timezone.utc)
    db.session.commit()

    if request.headers.get('Accept') == 'application/json' or request.is_json:
        return jsonify({
            'success': True,
            'message': {
                'id': msg.id,
                'message': msg.message,
                'is_edited': True,
                'edited_at': msg.edited_at.strftime('%b %d, %H:%M') if msg.edited_at else ''
            }
        })

    flash('Message updated successfully.', 'success')
    return redirect(request.referrer or url_for('chat_list'))


@app.route('/chat/<username>/block', methods=['POST'])
@login_required
def chat_block_user(username):
    peer = User.query.filter_by(username=username).first_or_404()
    if peer.id == current_user.id:
        flash('You cannot block yourself.', 'warning')
        return redirect(url_for('chat_list'))

    block_scope = request.form.get('block_scope', 'chat').strip()
    if block_scope not in ['chat', 'platform']:
        block_scope = 'chat'
    reason = request.form.get('reason', '').strip() or None
    details = request.form.get('details', '').strip() or None

    existing = ChatBlock.query.filter_by(blocker_id=current_user.id, blocked_id=peer.id).first()
    if not existing:
        block = ChatBlock(
            blocker_id=current_user.id,
            blocked_id=peer.id,
            block_scope=block_scope,
            reason=reason,
            details=details
        )
        db.session.add(block)
        db.session.commit()
        scope_text = "across CodeNest" if block_scope == "platform" else "from private chat"
        flash(f'You have blocked @{peer.username} {scope_text}.', 'info')
    else:
        existing.block_scope = block_scope
        existing.reason = reason
        existing.details = details
        db.session.commit()
        flash(f'Block settings for @{peer.username} have been updated.', 'info')

    # If blocked across platform, cleanly cancel any mutual follows
    if block_scope == 'platform':
        UserFollow.query.filter(
            ((UserFollow.follower_id == current_user.id) & (UserFollow.followed_id == peer.id)) |
            ((UserFollow.follower_id == peer.id) & (UserFollow.followed_id == current_user.id))
        ).delete(synchronize_session=False)
        db.session.commit()

    redirect_target = request.referrer or url_for('chat_conversation', username=peer.username)
    return redirect(redirect_target)


@app.route('/chat/<username>/unblock', methods=['POST'])
@login_required
def chat_unblock_user(username):
    peer = User.query.filter_by(username=username).first_or_404()
    block = ChatBlock.query.filter_by(blocker_id=current_user.id, blocked_id=peer.id).first()
    if block:
        db.session.delete(block)
        db.session.commit()
        flash(f'You have unblocked @{peer.username}.', 'success')
    else:
        flash(f'@{peer.username} is not blocked.', 'info')

    redirect_target = request.referrer or url_for('chat_conversation', username=peer.username)
    return redirect(redirect_target)


#-------------------------------
# RESOURCE HUB MODULE ROUTES 
#-------------------------------

# Configuration Limits for Collections & Uploads
MAX_COLLECTION_FILES = 30
MAX_COLLECTION_TOTAL_SIZE = 50 * 1024 * 1024  # 50 MB total per collection
MAX_INDIVIDUAL_FILE_SIZE = 10 * 1024 * 1024   # 10 MB per file
RESOURCES_PER_PAGE = 10


def sanitize_relative_path(raw_path, base_filename=None):
    """
    Sanitizes a client-supplied relative path from a folder upload.
    - Normalizes slashes to '/'
    - Strips leading/trailing slashes and whitespace
    - Rejects path traversal components like '..' and '.'
    - Secures each folder name and filename component
    - Returns a clean relative path (e.g. 'week1/notes.pdf') or None if invalid.
    """
    if not raw_path:
        if base_filename:
            return secure_filename(base_filename)
        return None
    normalized = raw_path.replace('\\', '/').strip().strip('/')
    parts = [p.strip() for p in normalized.split('/') if p.strip()]
    if not parts:
        if base_filename:
            return secure_filename(base_filename)
        return None
    # Strict directory traversal check
    for p in parts:
        if p in ('.', '..') or '..' in p or '/' in p or '\\' in p:
            return None
    safe_parts = [secure_filename(p) for p in parts]
    if any(not p for p in safe_parts):
        return None
    return '/'.join(safe_parts)


@app.route('/resources')
def resources_list():
    query_text = request.args.get('q', '').strip()
    selected_faculty = request.args.get('faculty', '').strip()
    selected_category = request.args.get('category', '').strip()
    selected_course_code = request.args.get('course_code', '').strip().upper()
    selected_semester = request.args.get('semester', '').strip()
    sort_by = request.args.get('sort', 'newest').strip()
    selected_sort = sort_by

    # Query standalone resources (top-level only, exclude collection member files)
    res_query = Resource.query.filter(Resource.collection_id.is_(None))

    # Query notes collections
    col_query = ResourceCollection.query

    if query_text:
        search_filter = f"%{query_text}%"
        res_query = res_query.filter(
            (Resource.title.ilike(search_filter)) | 
            (Resource.description.ilike(search_filter)) |
            (Resource.filename.ilike(search_filter)) |
            (Resource.course_code.ilike(search_filter)) |
            (Resource.course_name.ilike(search_filter))
        )
        col_query = col_query.outerjoin(Resource, ResourceCollection.id == Resource.collection_id).filter(
            (ResourceCollection.title.ilike(search_filter)) |
            (ResourceCollection.description.ilike(search_filter)) |
            (ResourceCollection.course_code.ilike(search_filter)) |
            (ResourceCollection.course_name.ilike(search_filter)) |
            (Resource.filename.ilike(search_filter)) |
            (Resource.title.ilike(search_filter))
        ).distinct()

    if selected_faculty:
        res_query = res_query.filter(Resource.faculty == selected_faculty)
        col_query = col_query.filter(ResourceCollection.faculty == selected_faculty)

    if selected_category:
        res_query = res_query.filter(Resource.category == selected_category)
        col_query = col_query.filter(ResourceCollection.category == selected_category)

    if selected_course_code:
        res_query = res_query.filter(Resource.course_code.ilike(f"%{selected_course_code}%"))
        col_query = col_query.filter(ResourceCollection.course_code.ilike(f"%{selected_course_code}%"))

    if selected_semester:
        res_query = res_query.filter(Resource.semester == selected_semester)
        col_query = col_query.filter(ResourceCollection.semester == selected_semester)

    res_items = res_query.all()
    col_items = col_query.all()
    all_items = list(res_items) + list(col_items)

    # Sorting
    if sort_by == 'downloads':
        # Descending download count, newest first as tie-breaker
        all_items.sort(
            key=lambda x: (x.download_count, x.created_at.timestamp() if x.created_at else 0),
            reverse=True
        )
    elif sort_by == 'rating':
        # Highest Rated: rated items first (descending average rating, then rating count),
        # unrated items after rated items, newest first as final tie-breaker
        all_items.sort(
            key=lambda x: (
                1 if x.rating_count > 0 else 0,
                x.average_rating if x.rating_count > 0 else 0.0,
                x.rating_count,
                x.created_at.timestamp() if x.created_at else 0
            ),
            reverse=True
        )
    else:
        # Default: Newest first
        sort_by = 'newest'
        all_items.sort(
            key=lambda x: x.created_at.timestamp() if x.created_at else 0,
            reverse=True
        )

    # Pagination: 10 items per page
    PER_PAGE = 10
    total_items = len(all_items)
    total_pages = max(1, (total_items + PER_PAGE - 1) // PER_PAGE)
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    if page < 1:
        page = 1
    elif page > total_pages and total_items > 0:
        page = total_pages

    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    items_for_page = all_items[start_idx:end_idx]

    rating_form = ResourceRatingForm()
    review_form = ProfessorReviewForm()

    return render_template(
        'resources/index.html',
        items=items_for_page,
        query_text=query_text,
        selected_faculty=selected_faculty,
        selected_category=selected_category,
        selected_course_code=selected_course_code,
        selected_semester=selected_semester,
        selected_sort=sort_by,
        sort_by=sort_by,
        faculties=FACULTIES,
        categories=RESOURCE_CATEGORIES,
        semesters=SEMESTER_CHOICES,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        rating_form=rating_form,
        review_form=review_form
    )


@app.route('/resources/my-uploads')
@login_required
def my_uploads():
    """Login-protected page displaying only current user's uploads (resources & collections)."""
    query_text = request.args.get('q', '').strip()
    selected_faculty = request.args.get('faculty', '').strip()
    selected_category = request.args.get('category', '').strip()
    selected_course_code = request.args.get('course_code', '').strip().upper()
    selected_semester = request.args.get('semester', '').strip()
    sort_by = request.args.get('sort', 'newest').strip()
    selected_sort = sort_by

    # Query user's standalone resources
    res_query = Resource.query.filter(
        Resource.uploader_id == current_user.id,
        Resource.collection_id.is_(None)
    )

    # Query user's collections
    col_query = ResourceCollection.query.filter(
        ResourceCollection.uploader_id == current_user.id
    )

    if query_text:
        search_filter = f"%{query_text}%"
        res_query = res_query.filter(
            (Resource.title.ilike(search_filter)) | 
            (Resource.description.ilike(search_filter)) |
            (Resource.filename.ilike(search_filter)) |
            (Resource.course_code.ilike(search_filter)) |
            (Resource.course_name.ilike(search_filter))
        )
        col_query = col_query.outerjoin(Resource, ResourceCollection.id == Resource.collection_id).filter(
            (ResourceCollection.title.ilike(search_filter)) |
            (ResourceCollection.description.ilike(search_filter)) |
            (ResourceCollection.course_code.ilike(search_filter)) |
            (ResourceCollection.course_name.ilike(search_filter)) |
            (Resource.filename.ilike(search_filter)) |
            (Resource.title.ilike(search_filter))
        ).distinct()

    if selected_faculty:
        res_query = res_query.filter(Resource.faculty == selected_faculty)
        col_query = col_query.filter(ResourceCollection.faculty == selected_faculty)

    if selected_category:
        res_query = res_query.filter(Resource.category == selected_category)
        col_query = col_query.filter(ResourceCollection.category == selected_category)

    if selected_course_code:
        res_query = res_query.filter(Resource.course_code.ilike(f"%{selected_course_code}%"))
        col_query = col_query.filter(ResourceCollection.course_code.ilike(f"%{selected_course_code}%"))

    if selected_semester:
        res_query = res_query.filter(Resource.semester == selected_semester)
        col_query = col_query.filter(ResourceCollection.semester == selected_semester)

    res_items = res_query.all()
    col_items = col_query.all()
    all_items = list(res_items) + list(col_items)

    # Sorting
    if sort_by == 'downloads':
        all_items.sort(
            key=lambda x: (x.download_count, x.created_at.timestamp() if x.created_at else 0),
            reverse=True
        )
    elif sort_by == 'rating':
        all_items.sort(
            key=lambda x: (
                1 if x.rating_count > 0 else 0,
                x.average_rating if x.rating_count > 0 else 0.0,
                x.rating_count,
                x.created_at.timestamp() if x.created_at else 0
            ),
            reverse=True
        )
    else:
        sort_by = 'newest'
        all_items.sort(
            key=lambda x: x.created_at.timestamp() if x.created_at else 0,
            reverse=True
        )

    # Pagination: 10 per page
    PER_PAGE = 10
    total_items = len(all_items)
    total_pages = max(1, (total_items + PER_PAGE - 1) // PER_PAGE)
    try:
        page = int(request.args.get('page', 1))
    except (ValueError, TypeError):
        page = 1
    if page < 1:
        page = 1
    elif page > total_pages and total_items > 0:
        page = total_pages

    start_idx = (page - 1) * PER_PAGE
    end_idx = start_idx + PER_PAGE
    items_for_page = all_items[start_idx:end_idx]

    rating_form = ResourceRatingForm()
    review_form = ProfessorReviewForm()

    return render_template(
        'resources/my_uploads.html',
        items=items_for_page,
        query_text=query_text,
        selected_faculty=selected_faculty,
        selected_category=selected_category,
        selected_course_code=selected_course_code,
        selected_semester=selected_semester,
        selected_sort=sort_by,
        sort_by=sort_by,
        faculties=FACULTIES,
        categories=RESOURCE_CATEGORIES,
        semesters=SEMESTER_CHOICES,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        rating_form=rating_form,
        review_form=review_form
    )


@app.route('/resources/<int:resource_id>/rate', methods=['POST'])
@login_required
def resource_rate(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    # Prevent users from rating their own uploads
    if resource.uploader_id == current_user.id:
        flash('You cannot rate your own uploaded resource.', 'warning')
        return redirect(request.referrer or url_for('resources_list'))

    form = RatingForm()
    if form.validate_on_submit():
        rating_val = int(form.rating.data)
        if not (1 <= rating_val <= 5):
            flash('Rating must be between 1 and 5 stars.', 'danger')
            return redirect(request.referrer or url_for('resources_list'))

        # Check for existing rating by current_user on this resource
        existing_rating = ResourceRating.query.filter_by(
            resource_id=resource.id,
            user_id=current_user.id
        ).first()

        if existing_rating:
            existing_rating.rating = rating_val
            existing_rating.updated_at = datetime.now(timezone.utc)
            flash(f"Your rating for '{resource.title}' has been updated to {rating_val} star(s)!", 'success')
        else:
            new_rating = ResourceRating(
                rating=rating_val,
                resource_id=resource.id,
                user_id=current_user.id
            )
            db.session.add(new_rating)
            flash(f"Thank you! You rated '{resource.title}' {rating_val} star(s).", 'success')

        db.session.commit()
    else:
        flash('Invalid rating submission. Please try again.', 'danger')

    return redirect(request.referrer or url_for('resources_list'))


@app.route('/resources/<int:resource_id>/review', methods=['POST'])
@login_required
def resource_review(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    # Authorization: Only verified professors can submit reviews
    if not current_user.is_verified or not current_user.is_professor():
        flash('Only verified MMU Professors can endorse and review academic resources.', 'danger')
        return abort(403)

    # Self-Review Prevention: Professors cannot review their own uploaded resources
    if resource.uploader_id == current_user.id:
        flash('Professors cannot review their own uploaded resources.', 'warning')
        return redirect(request.referrer or url_for('resources_list'))

    form = ProfessorReviewForm()
    if form.validate_on_submit():
        note = form.review_note.data.strip() if form.review_note.data else None

        existing_review = ResourceReview.query.filter_by(
            resource_id=resource.id,
            professor_id=current_user.id
        ).first()

        if existing_review:
            existing_review.review_note = note
            existing_review.updated_at = datetime.now(timezone.utc)
            flash(f"Your professor review note for '{resource.title}' has been updated.", 'success')
        else:
            new_review = ResourceReview(
                resource_id=resource.id,
                professor_id=current_user.id,
                review_note=note
            )
            db.session.add(new_review)
            flash(f"Resource '{resource.title}' has been endorsed with the Professor Reviewed badge!", 'success')

        db.session.commit()
    else:
        for err in form.review_note.errors:
            flash(f"Review note error: {err}", 'danger')

    return redirect(request.referrer or url_for('resources_list'))


@app.route('/resources/<int:resource_id>/unreview', methods=['POST'])
@login_required
def resource_unreview(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    # Authorization: Only verified professors can withdraw their reviews
    if not current_user.is_verified or not current_user.is_professor():
        flash('Only verified Professors can withdraw reviews.', 'danger')
        return abort(403)

    existing_review = ResourceReview.query.filter_by(
        resource_id=resource.id,
        professor_id=current_user.id
    ).first()

    if existing_review:
        db.session.delete(existing_review)
        db.session.commit()
        flash(f"Your professor review for '{resource.title}' has been withdrawn.", 'info')
    else:
        flash('No active review found from your account on this resource.', 'warning')

    return redirect(request.referrer or url_for('resources_list'))


@app.route('/resources/<int:resource_id>/preview')
@login_required
def resource_preview(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.stored_filename)
    if not os.path.exists(file_path):
        flash('The requested file is no longer available on disk for preview.', 'danger')
        return redirect(request.referrer or url_for('resources_list'))

    file_type = (resource.file_type or '').lower()

    if file_type == 'pdf':
        response = send_from_directory(
            app.config['UPLOAD_FOLDER'],
            resource.stored_filename,
            as_attachment=False,
            mimetype='application/pdf',
            download_name=resource.filename
        )
        response.headers['Content-Disposition'] = f'inline; filename="{resource.filename}"'
        return response

    elif file_type == 'txt':
        TEXT_PREVIEW_LIMIT = 100 * 1024  # 100 KB text preview limit
        is_truncated = False
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(TEXT_PREVIEW_LIMIT + 1)
                if len(content) > TEXT_PREVIEW_LIMIT:
                    content = content[:TEXT_PREVIEW_LIMIT]
                    is_truncated = True
        except Exception as e:
            flash(f'Failed to read text file: {e}', 'danger')
            return redirect(request.referrer or url_for('resources_list'))

        return render_template(
            'resources/preview_text.html',
            resource=resource,
            content=content,
            is_truncated=is_truncated
        )

    else:
        flash(f"In-browser preview is only supported for PDF and TXT files. '{resource.filename}' ({file_type.upper()}) must be downloaded directly.", 'warning')
        return redirect(request.referrer or url_for('resources_list'))



@app.route('/resources/upload', methods=['GET', 'POST'])
@login_required
def resource_upload():
    """Preserved individual resource upload flow with 10MB limit and profanity filtering."""
    form = ResourceForm()
    if request.method == 'GET' and hasattr(current_user, 'faculty') and current_user.faculty:
        form.faculty.data = current_user.faculty

    if form.validate_on_submit():
        file = form.file.data
        if not file or file.filename == '':
            flash('No file selected for upload.', 'danger')
            return render_template('resources/upload.html', form=form)

        original_filename = secure_filename(file.filename)
        if not original_filename:
            original_filename = "unnamed_file"

        file_ext = ''
        if '.' in original_filename:
            file_ext = original_filename.rsplit('.', 1)[1].lower()

        if file_ext not in ALLOWED_EXTENSIONS:
            flash(f"Invalid file type '.{file_ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS).upper()}", 'danger')
            return render_template('resources/upload.html', form=form)

        # Generate unique stored filename with timestamp + random token + original name
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
        unique_token = uuid.uuid4().hex[:8]
        stored_filename = f"{timestamp}_{unique_token}_{original_filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)

        # Save to disk
        file.save(file_path)

        # Verify file size on disk
        file_size = os.path.getsize(file_path)

        # 10MB size limit check (Resource Hub specific)
        if file_size > MAX_RESOURCE_FILE_SIZE:
            if os.path.exists(file_path):
                os.remove(file_path)
            flash('File exceeds the 10MB size limit.', 'danger')
            return render_template('resources/upload.html', form=form)

        # Normalize academic metadata
        raw_code = form.course_code.data.strip().upper() if form.course_code.data and form.course_code.data.strip() else None
        c_name = form.course_name.data.strip() if form.course_name.data and form.course_name.data.strip() else None
        acad_yr = form.academic_year.data.strip() if form.academic_year.data and form.academic_year.data.strip() else None
        sem = form.semester.data.strip() if form.semester.data and form.semester.data.strip() else None

        # Create database record
        resource = Resource(
            title=form.title.data.strip(),
            description=form.description.data.strip() if form.description.data else '',
            filename=original_filename,
            stored_filename=stored_filename,
            file_size=file_size,
            file_type=file_ext,
            category=form.category.data,
            faculty=form.faculty.data,
            uploader_id=current_user.id,
            course_code=raw_code,
            course_name=c_name,
            academic_year=acad_yr,
            semester=sem,
            download_count=0
        )
        db.session.add(resource)
        db.session.commit()

        flash(f"Resource '{resource.title}' uploaded successfully!", 'success')
        return redirect(url_for('resources_list'))

    return render_template('resources/upload.html', form=form)


@app.route('/resources/upload-folder', methods=['GET', 'POST'], endpoint='resource_upload_folder')
@app.route('/resources/upload-folder', methods=['GET', 'POST'], endpoint='resource_collection_upload')
@login_required
def resource_collection_upload():
    """Upload an entire folder containing multiple files as one notes collection."""
    form = CollectionUploadForm()
    if request.method == 'GET' and hasattr(current_user, 'faculty') and current_user.faculty:
        form.faculty.data = current_user.faculty

    if form.validate_on_submit():
        title = form.title.data.strip()
        description = form.description.data.strip() if form.description.data else ''
        category = form.category.data
        faculty = form.faculty.data

        # Shared profanity checks before handling files
        has_prof_title, term_t = contains_profanity(title)
        if has_prof_title:
            flash(f"Collection title contains prohibited language ('{term_t}').", 'danger')
            return render_template('resources/upload_folder.html', form=form)

        if description:
            has_prof_desc, term_d = contains_profanity(description)
            if has_prof_desc:
                flash(f"Collection description contains prohibited language ('{term_d}').", 'danger')
                return render_template('resources/upload_folder.html', form=form)

        files = request.files.getlist('files')
        relative_paths = request.form.getlist('relative_paths')

        if not files or len(files) == 0 or all(f.filename == '' for f in files):
            flash('Please select a folder with files to upload.', 'danger')
            return render_template('resources/upload_folder.html', form=form)

        # File count limit check
        if len(files) > MAX_COLLECTION_FILES:
            flash(f"Folder contains too many files ({len(files)}). Maximum allowed is {MAX_COLLECTION_FILES} files.", 'danger')
            return render_template('resources/upload_folder.html', form=form)

        valid_files_to_save = []
        rejected_files = []
        total_size = 0
        seen_relative_paths = set()

        for idx, file in enumerate(files):
            if not file or file.filename == '':
                continue

            raw_rel_path = relative_paths[idx] if idx < len(relative_paths) and relative_paths[idx] else file.filename
            safe_rel_path = sanitize_relative_path(raw_rel_path)

            if not safe_rel_path:
                rejected_files.append((file.filename, "Invalid or unsafe path/filename."))
                continue

            if safe_rel_path.lower() in seen_relative_paths:
                rejected_files.append((safe_rel_path, "Duplicate file path in upload."))
                continue
            seen_relative_paths.add(safe_rel_path.lower())

            original_filename = safe_rel_path.split('/')[-1]
            file_ext = ''
            if '.' in original_filename:
                file_ext = original_filename.rsplit('.', 1)[1].lower()

            if file_ext not in ALLOWED_EXTENSIONS:
                rejected_files.append((safe_rel_path, f"Unsupported file type '.{file_ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS).upper()}"))
                continue

            file.seek(0, os.SEEK_END)
            f_size = file.tell()
            file.seek(0)

            if f_size > MAX_RESOURCE_FILE_SIZE:
                rejected_files.append((safe_rel_path, f"Exceeds individual 10MB limit ({f_size / (1024*1024):.1f} MB)."))
                continue

            if f_size == 0:
                rejected_files.append((safe_rel_path, "File is empty (0 bytes)."))
                continue

            total_size += f_size
            if total_size > MAX_COLLECTION_TOTAL_SIZE:
                rejected_files.append((safe_rel_path, "Exceeds total collection 50MB limit."))
                continue

            valid_files_to_save.append({
                'file': file,
                'filename': original_filename,
                'relative_path': safe_rel_path,
                'file_size': f_size,
                'file_type': file_ext
            })

        # If all files are rejected, do not leave an empty collection
        if not valid_files_to_save:
            err_msg = "No valid files could be uploaded from this folder. "
            if rejected_files:
                err_msg += "Reasons: " + "; ".join([f"{f}: {r}" for f, r in rejected_files[:5]])
            flash(err_msg, 'danger')
            return render_template('resources/upload_folder.html', form=form)

        # Normalize academic metadata
        raw_code = form.course_code.data.strip().upper() if form.course_code.data and form.course_code.data.strip() else None
        c_name = form.course_name.data.strip() if form.course_name.data and form.course_name.data.strip() else None
        acad_yr = form.academic_year.data.strip() if form.academic_year.data and form.academic_year.data.strip() else None
        sem = form.semester.data.strip() if form.semester.data and form.semester.data.strip() else None

        saved_disk_paths = []
        try:
            collection = ResourceCollection(
                title=title,
                description=description,
                category=category,
                faculty=faculty,
                uploader_id=current_user.id,
                course_code=raw_code,
                course_name=c_name,
                academic_year=acad_yr,
                semester=sem
            )
            db.session.add(collection)
            db.session.flush()

            for item in valid_files_to_save:
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
                unique_token = uuid.uuid4().hex[:8]
                stored_filename = f"{timestamp}_{unique_token}_{item['filename']}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)

                item['file'].save(file_path)
                saved_disk_paths.append(file_path)

                resource = Resource(
                    title=item['filename'],
                    description=f"Part of notes collection: {collection.title}",
                    filename=item['filename'],
                    stored_filename=stored_filename,
                    file_size=item['file_size'],
                    file_type=item['file_type'],
                    category=category,
                    faculty=faculty,
                    uploader_id=current_user.id,
                    collection_id=collection.id,
                    relative_path=item['relative_path'],
                    course_code=collection.course_code,
                    course_name=collection.course_name,
                    academic_year=collection.academic_year,
                    semester=collection.semester,
                    download_count=0
                )
                db.session.add(resource)

            db.session.commit()

            success_msg = f"Notes collection '{collection.title}' uploaded successfully with {len(valid_files_to_save)} file(s)!"
            flash(success_msg, 'success')

            if rejected_files:
                rej_msg = f"{len(rejected_files)} file(s) were rejected: " + "; ".join([f"{f} ({r})" for f, r in rejected_files])
                flash(rej_msg, 'warning')

            return redirect(url_for('resource_collection_detail', collection_id=collection.id))

        except Exception as e:
            db.session.rollback()
            # Clean up newly saved physical files on disk
            for p in saved_disk_paths:
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            app.logger.error(f"Failed to save folder collection: {e}")
            flash('An error occurred while saving the collection. All uploaded files were cleaned up. Please try again.', 'danger')
            return render_template('resources/upload_folder.html', form=form)

    return render_template('resources/upload_folder.html', form=form)


@app.route('/resources/collections/<int:collection_id>', endpoint='resource_collection_detail')
@app.route('/resources/collections/<int:collection_id>', endpoint='collection_detail')
@app.route('/resources/collection/<int:collection_id>', endpoint='collection_detail_alias')
def resource_collection_detail(collection_id):
    """View collection details, subfolders, member files, downloads, and ratings."""
    collection = db.session.get(ResourceCollection, collection_id)
    if not collection:
        flash('Collection not found.', 'danger')
        return redirect(url_for('resources_list'))

    rating_form = ResourceRatingForm()
    review_form = ProfessorReviewForm()
    return render_template(
        'resources/collection_detail.html',
        collection=collection,
        rating_form=rating_form,
        review_form=review_form
    )


@app.route('/resources/collections/<int:collection_id>/edit', methods=['GET', 'POST'], endpoint='resource_collection_edit')
@app.route('/resources/collections/<int:collection_id>/edit', methods=['GET', 'POST'], endpoint='collection_edit')
@app.route('/resources/collection/<int:collection_id>/edit', methods=['GET', 'POST'], endpoint='collection_edit_singular')
@login_required
def resource_collection_edit(collection_id):
    """Edit collection metadata with profanity checks. Enforce uploader or admin permission."""
    collection = db.session.get(ResourceCollection, collection_id)
    if not collection:
        flash('Collection not found.', 'danger')
        return redirect(url_for('resources_list'))

    if collection.uploader_id != current_user.id and not current_user.is_admin():
        flash('You are not authorized to edit this collection.', 'danger')
        return redirect(url_for('resource_collection_detail', collection_id=collection.id))

    form = CollectionEditForm(obj=collection)
    if form.validate_on_submit():
        # Check if replacement files/folder were provided
        replacement_files = request.files.getlist('replacement_folder')
        if not replacement_files or all(f.filename == '' for f in replacement_files):
            replacement_files = request.files.getlist('files')

        has_new_files = replacement_files and any(f.filename != '' for f in replacement_files)
        if has_new_files:
            rel_paths = request.form.getlist('relative_paths')
            valid_files = [f for f in replacement_files if f and f.filename != '']
            if len(valid_files) > MAX_COLLECTION_FILES:
                flash(f"Folder contains too many files ({len(valid_files)}). Maximum allowed is {MAX_COLLECTION_FILES} files.", 'danger')
                return render_template('resources/collection_edit.html', form=form, collection=collection)

            valid_files_to_save = []
            rejected_files = []
            total_size = 0
            seen_relative_paths = set()

            for idx, file in enumerate(valid_files):
                raw_rel_path = rel_paths[idx] if idx < len(rel_paths) and rel_paths[idx] else file.filename
                safe_rel_path = sanitize_relative_path(raw_rel_path)
                if not safe_rel_path:
                    rejected_files.append((file.filename, "Invalid or unsafe path/filename."))
                    continue
                if safe_rel_path.lower() in seen_relative_paths:
                    rejected_files.append((safe_rel_path, "Duplicate file path in upload."))
                    continue
                seen_relative_paths.add(safe_rel_path.lower())

                original_filename = safe_rel_path.split('/')[-1]
                file_ext = ''
                if '.' in original_filename:
                    file_ext = original_filename.rsplit('.', 1)[1].lower()
                if file_ext not in ALLOWED_EXTENSIONS:
                    rejected_files.append((safe_rel_path, f"Unsupported file type '.{file_ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS).upper()}"))
                    continue

                file.seek(0, os.SEEK_END)
                f_size = file.tell()
                file.seek(0)

                if f_size > MAX_RESOURCE_FILE_SIZE:
                    rejected_files.append((safe_rel_path, f"Exceeds individual 10MB limit."))
                    continue
                if f_size == 0:
                    rejected_files.append((safe_rel_path, "File is empty (0 bytes)."))
                    continue

                total_size += f_size
                if total_size > MAX_COLLECTION_TOTAL_SIZE:
                    rejected_files.append((safe_rel_path, "Exceeds total collection 50MB limit."))
                    continue

                valid_files_to_save.append({
                    'file': file,
                    'filename': original_filename,
                    'relative_path': safe_rel_path,
                    'file_size': f_size,
                    'file_type': file_ext
                })

            if not valid_files_to_save:
                reasons = '; '.join([f"{f}: {r}" for f, r in rejected_files]) if rejected_files else 'No valid files found.'
                flash(f"Replacement folder could not be saved: {reasons}", 'danger')
                return render_template('resources/collection_edit.html', form=form, collection=collection)

            # Delete old member files from disk and database
            old_disk_files = []
            for old_res in list(collection.resources):
                old_path = os.path.join(app.config['UPLOAD_FOLDER'], old_res.stored_filename)
                old_disk_files.append(old_path)
                db.session.delete(old_res)

            saved_paths = []
            try:
                for item in valid_files_to_save:
                    clean_sec_name = secure_filename(item['filename']) or "notes_file"
                    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
                    unique_token = uuid.uuid4().hex[:8]
                    stored_filename = f"{timestamp}_{unique_token}_{clean_sec_name}"
                    disk_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)

                    item['file'].save(disk_path)
                    saved_paths.append(disk_path)

                    res = Resource(
                        title=item['filename'],
                        description='',
                        filename=item['filename'],
                        stored_filename=stored_filename,
                        file_size=item['file_size'],
                        file_type=item['file_type'],
                        category=form.category.data,
                        faculty=form.faculty.data,
                        uploader_id=current_user.id,
                        collection_id=collection.id,
                        relative_path=item['relative_path'],
                        course_code=form.course_code.data.strip().upper() if form.course_code.data and form.course_code.data.strip() else None,
                        course_name=form.course_name.data.strip() if form.course_name.data and form.course_name.data.strip() else None,
                        academic_year=form.academic_year.data.strip() if form.academic_year.data and form.academic_year.data.strip() else None,
                        semester=form.semester.data.strip() if form.semester.data and form.semester.data.strip() else None,
                        download_count=0
                    )
                    db.session.add(res)

                for op in old_disk_files:
                    if os.path.exists(op):
                        try:
                            os.remove(op)
                        except Exception:
                            pass
            except Exception as e:
                for sp in saved_paths:
                    if os.path.exists(sp):
                        try:
                            os.remove(sp)
                        except Exception:
                            pass
                db.session.rollback()
                flash(f"Error saving replacement files: {e}", 'danger')
                return render_template('resources/collection_edit.html', form=form, collection=collection)

        collection.title = form.title.data.strip()
        collection.description = form.description.data.strip() if form.description.data else ''
        collection.category = form.category.data
        collection.faculty = form.faculty.data
        collection.course_code = form.course_code.data.strip().upper() if form.course_code.data and form.course_code.data.strip() else None
        collection.course_name = form.course_name.data.strip() if form.course_name.data and form.course_name.data.strip() else None
        collection.academic_year = form.academic_year.data.strip() if form.academic_year.data and form.academic_year.data.strip() else None
        collection.semester = form.semester.data.strip() if form.semester.data and form.semester.data.strip() else None

        # Synchronize faculty, category, and academic metadata across member resources
        for member in collection.resources:
            member.category = collection.category
            member.faculty = collection.faculty
            member.course_code = collection.course_code
            member.course_name = collection.course_name
            member.academic_year = collection.academic_year
            member.semester = collection.semester

        db.session.commit()
        flash('Collection details updated successfully!', 'success')
        return redirect(url_for('resource_collection_detail', collection_id=collection.id))

    return render_template('resources/collection_edit.html', form=form, collection=collection)


@app.route('/resources/collections/<int:collection_id>/delete', methods=['POST'], endpoint='resource_collection_delete')
@app.route('/resources/collections/<int:collection_id>/delete', methods=['POST'], endpoint='collection_delete')
@app.route('/resources/collection/<int:collection_id>/delete', methods=['POST'], endpoint='collection_delete_singular')
@login_required
def resource_collection_delete(collection_id):
    """Delete a collection, all its member physical files, ratings, and records."""
    collection = db.session.get(ResourceCollection, collection_id)
    if not collection:
        flash('Collection not found.', 'danger')
        return redirect(url_for('resources_list'))

    if collection.uploader_id != current_user.id and not current_user.is_admin():
        flash('You are not authorized to delete this collection.', 'danger')
        return redirect(url_for('resources_list'))

    # Delete all member physical files from disk
    for r in collection.resources:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], r.stored_filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                app.logger.warning(f"Failed to remove member file {file_path}: {e}")

    title = collection.title
    db.session.delete(collection)
    db.session.commit()

    flash(f"Notes collection '{title}' and all its files have been deleted.", 'info')
    return redirect(url_for('resources_list'))


@app.route('/resources/collection/<int:collection_id>/download-zip')
@login_required
def collection_download_zip(collection_id):
    collection = db.session.get(ResourceCollection, collection_id)
    if not collection:
        flash('Notes collection not found.', 'danger')
        return redirect(url_for('resources_list'))

    if not collection.resources:
        flash('This collection currently contains no files to download.', 'warning')
        return redirect(url_for('collection_detail', collection_id=collection.id))

    # Pre-flight integrity check: ensure all files physically exist on disk
    for r in collection.resources:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], r.stored_filename)
        if not os.path.exists(file_path):
            flash('Cannot generate ZIP archive: one or more member files in this collection are missing from the server storage.', 'danger')
            return redirect(url_for('collection_detail', collection_id=collection.id))

    # In-memory ZIP archive generation
    mem_buf = io.BytesIO()
    seen_arcnames = set()

    with zipfile.ZipFile(mem_buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for r in collection.resources:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], r.stored_filename)
            raw_arcname = (r.relative_path or r.filename).replace('\\', '/').strip('/')
            
            # Directory traversal prevention
            parts = [p for p in raw_arcname.split('/') if p and p != '.' and p != '..']
            if not parts:
                parts = [secure_filename(r.filename) or 'file']
            safe_arcname = '/'.join(parts)

            # Duplicate path collision handling within ZIP
            final_arcname = safe_arcname
            counter = 1
            while final_arcname in seen_arcnames:
                dir_name, base_name = os.path.split(safe_arcname)
                name_root, ext = os.path.splitext(base_name)
                final_base = f"{name_root}_{counter}{ext}"
                final_arcname = os.path.join(dir_name, final_base).replace('\\', '/') if dir_name else final_base
                counter += 1

            seen_arcnames.add(final_arcname)
            zf.write(file_path, arcname=final_arcname)

    mem_buf.seek(0)

    # Atomic download count increment across all included member resources
    for r in collection.resources:
        Resource.query.filter_by(id=r.id).update({
            Resource.download_count: Resource.download_count + 1
        })
    db.session.commit()

    safe_title = secure_filename(collection.title) or 'collection'
    zip_filename = f"{safe_title}_collection.zip"

    return send_file(
        mem_buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_filename
    )


@app.route('/resources/collection/<int:collection_id>/add-files', methods=['GET', 'POST'])
@login_required
def collection_add_files(collection_id):
    collection = db.session.get(ResourceCollection, collection_id)
    if not collection:
        flash('Collection not found.', 'danger')
        return redirect(url_for('resources_list'))

    # Authorization: Only collection owner or admin can append files
    if collection.uploader_id != current_user.id and not current_user.is_admin():
        flash('You are not authorized to add files to this collection.', 'danger')
        return abort(403)

    form = AddFilesToCollectionForm()
    if form.validate_on_submit():
        raw_files = request.files.getlist('files')
        valid_selected_files = [f for f in raw_files if f and f.filename and f.filename.strip() != '']

        if not valid_selected_files:
            flash('Please select at least one file or folder to add.', 'danger')
            return render_template('resources/collection_add_files.html', form=form, collection=collection)

        current_file_count = len(collection.resources)
        current_total_size = collection.total_size_bytes
        existing_paths = {r.relative_path or r.filename for r in collection.resources}

        valid_files_to_save = []
        skipped_files = []
        seen_new_paths = set()

        for file_obj in valid_selected_files:
            raw_filename = file_obj.filename.strip()
            clean_rel = raw_filename.replace('\\', '/').strip('/')
            base_filename = os.path.basename(clean_rel)

            safe_rel_path = sanitize_relative_path(clean_rel, base_filename)
            if not safe_rel_path:
                skipped_files.append((raw_filename, 'Unsafe path characters or traversal detected'))
                continue

            if safe_rel_path in existing_paths:
                skipped_files.append((raw_filename, 'A file with this relative path already exists in this collection'))
                continue

            if safe_rel_path in seen_new_paths:
                skipped_files.append((raw_filename, 'Duplicate file path within upload batch'))
                continue

            file_ext = ''
            if '.' in base_filename:
                file_ext = base_filename.rsplit('.', 1)[1].lower()

            if file_ext not in ALLOWED_EXTENSIONS:
                skipped_files.append((raw_filename, f"Invalid format '.{file_ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS).upper()}"))
                continue

            file_obj.seek(0, os.SEEK_END)
            file_size = file_obj.tell()
            file_obj.seek(0)

            if file_size == 0:
                skipped_files.append((raw_filename, 'File is empty (0 bytes)'))
                continue

            if file_size > MAX_INDIVIDUAL_FILE_SIZE:
                skipped_files.append((raw_filename, f'Exceeds 10MB individual limit ({file_size / (1024*1024):.1f} MB)'))
                continue

            if current_total_size + file_size > MAX_COLLECTION_TOTAL_SIZE:
                skipped_files.append((raw_filename, 'Exceeds 50MB collection total limit'))
                continue

            if current_file_count + len(valid_files_to_save) + 1 > MAX_COLLECTION_FILES:
                skipped_files.append((raw_filename, f'Exceeds maximum limit of {MAX_COLLECTION_FILES} files per collection'))
                continue

            seen_new_paths.add(safe_rel_path)
            current_total_size += file_size
            valid_files_to_save.append((file_obj, safe_rel_path, base_filename, file_ext, file_size))

        if not valid_files_to_save:
            reasons = "; ".join([f"{name} ({reason})" for name, reason in skipped_files])
            flash(f'No valid files could be added to the collection. Reasons: {reasons}', 'danger')
            return render_template('resources/collection_add_files.html', form=form, collection=collection)

        saved_disk_files = []
        try:
            for file_obj, safe_rel_path, base_filename, file_ext, file_size in valid_files_to_save:
                timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
                unique_token = uuid.uuid4().hex[:8]
                clean_sec_name = secure_filename(base_filename) or "notes_file"
                stored_filename = f"{timestamp}_{unique_token}_{clean_sec_name}"
                disk_path = os.path.join(app.config['UPLOAD_FOLDER'], stored_filename)

                file_obj.save(disk_path)
                saved_disk_files.append(disk_path)

                member_resource = Resource(
                    title=base_filename,
                    description='',
                    filename=base_filename,
                    stored_filename=stored_filename,
                    file_size=file_size,
                    file_type=file_ext,
                    category=collection.category,
                    faculty=collection.faculty,
                    uploader_id=current_user.id,
                    collection_id=collection.id,
                    relative_path=safe_rel_path,
                    course_code=collection.course_code,
                    course_name=collection.course_name,
                    academic_year=collection.academic_year,
                    semester=collection.semester,
                    download_count=0
                )
                db.session.add(member_resource)

            db.session.commit()
        except Exception as e:
            db.session.rollback()
            for disk_file in saved_disk_files:
                if os.path.exists(disk_file):
                    try:
                        os.remove(disk_file)
                    except Exception:
                        pass
            flash(f'An unexpected error occurred while adding files: {e}', 'danger')
            return render_template('resources/collection_add_files.html', form=form, collection=collection)

        flash(f"Successfully added {len(valid_files_to_save)} new file(s) to '{collection.title}'!", 'success')
        if skipped_files:
            skipped_summary = "; ".join([f"{name}: {reason}" for name, reason in skipped_files])
            flash(f"Notice: {len(skipped_files)} file(s) were skipped: {skipped_summary}", 'warning')

        return redirect(url_for('collection_detail', collection_id=collection.id))

    return render_template('resources/collection_add_files.html', form=form, collection=collection)


@app.route('/resources/download/<int:resource_id>')
def resource_download(resource_id):
    """
    Download a resource file.
    Increments download count atomically only after confirming the resource
    and physical file exist and preparing a valid download response.
    Note: Records download requests served by the server, not proof that the browser finished saving.
    """
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.stored_filename)
    if not os.path.exists(file_path):
        flash('The requested file is no longer available on disk.', 'danger')
        return redirect(url_for('resources_list'))

    # Atomic increment in database
    Resource.query.filter_by(id=resource.id).update(
        {Resource.download_count: Resource.download_count + 1}
    )
    db.session.commit()

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        resource.stored_filename,
        as_attachment=True,
        download_name=resource.filename
    )




@app.route('/resources/<int:resource_id>/edit', methods=['GET', 'POST'])
@login_required
def resource_edit(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    # Only uploader or admin can edit
    if resource.uploader_id != current_user.id and not current_user.is_admin():
        flash('You are not authorized to edit this resource.', 'danger')
        return redirect(url_for('resources_list'))

    form = ResourceEditForm(obj=resource)
    if form.validate_on_submit():
        # Handle optional replacement file upload (e.g. latest PDF version)
        new_file = form.file.data
        if new_file and getattr(new_file, 'filename', None) and new_file.filename.strip():
            raw_orig_filename = secure_filename(new_file.filename) or "updated_file"
            file_ext = ''
            if '.' in raw_orig_filename:
                file_ext = raw_orig_filename.rsplit('.', 1)[1].lower()

            if file_ext not in ALLOWED_EXTENSIONS:
                flash(f"Invalid file type '.{file_ext}'. Allowed types: {', '.join(ALLOWED_EXTENSIONS).upper()}", 'danger')
                return render_template('resources/edit.html', form=form, resource=resource)

            timestamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
            unique_token = uuid.uuid4().hex[:8]
            new_stored_filename = f"{timestamp}_{unique_token}_{raw_orig_filename}"
            new_file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_stored_filename)

            new_file.save(new_file_path)
            new_file_size = os.path.getsize(new_file_path)

            if new_file_size > app.config['MAX_CONTENT_LENGTH']:
                if os.path.exists(new_file_path):
                    os.remove(new_file_path)
                flash('Replacement file exceeds the 10MB size limit.', 'danger')
                return render_template('resources/edit.html', form=form, resource=resource)

            # Safely remove old physical file from disk
            if resource.stored_filename:
                old_file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.stored_filename)
                if os.path.exists(old_file_path) and resource.stored_filename != new_stored_filename:
                    try:
                        os.remove(old_file_path)
                    except Exception as e:
                        app.logger.warning(f"Failed to remove old resource file {old_file_path}: {e}")

            resource.filename = raw_orig_filename
            resource.stored_filename = new_stored_filename
            resource.file_size = new_file_size
            resource.file_type = file_ext

        resource.title = form.title.data.strip()
        resource.description = form.description.data.strip() if form.description.data else ''
        resource.category = form.category.data
        resource.faculty = form.faculty.data
        resource.course_code = form.course_code.data.strip().upper() if form.course_code.data and form.course_code.data.strip() else None
        resource.course_name = form.course_name.data.strip() if form.course_name.data and form.course_name.data.strip() else None
        resource.academic_year = form.academic_year.data.strip() if form.academic_year.data and form.academic_year.data.strip() else None
        resource.semester = form.semester.data.strip() if form.semester.data and form.semester.data.strip() else None

        db.session.commit()
        flash('Resource details and file updated successfully!', 'success')
        if resource.collection_id:
            return redirect(url_for('resource_collection_detail', collection_id=resource.collection_id))
        return redirect(url_for('resources_list'))

    return render_template('resources/edit.html', form=form, resource=resource)


@app.route('/resources/<int:resource_id>/bookmark', methods=['POST'])
@login_required
def toggle_resource_bookmark(resource_id):
    """Toggle bookmark state for a resource."""
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(request.referrer or url_for('resources_list'))

    existing = ResourceBookmark.query.filter_by(
        user_id=current_user.id,
        resource_id=resource.id
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        flash(f"Removed '{resource.title}' from your bookmarks.", 'info')
    else:
        new_bookmark = ResourceBookmark(user_id=current_user.id, resource_id=resource.id)
        db.session.add(new_bookmark)
        db.session.commit()
        flash(f"Bookmarked '{resource.title}' successfully!", 'success')

    next_url = request.form.get('next') or request.referrer or url_for('resources_list')
    return redirect(next_url)


@app.route('/resources/<int:resource_id>/delete', methods=['POST'])
@login_required
def resource_delete(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    # Only uploader or admin can delete
    if resource.uploader_id != current_user.id and not current_user.is_admin():
        flash('You are not authorized to delete this resource.', 'danger')
        return redirect(url_for('resources_list'))

    col_id = resource.collection_id

    # Remove physical file from disk
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.stored_filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            app.logger.warning(f"Failed to remove physical file {file_path}: {e}")

    # Remove database record (cascades to ratings and reviews)
    db.session.delete(resource)
    db.session.commit()

    flash(f"Resource '{resource.title}' has been deleted.", 'info')
    if col_id:
        return redirect(url_for('resource_collection_detail', collection_id=col_id))
    return redirect(url_for('resources_list'))


@app.context_processor
def inject_global_vars():
    return dict(app_name="Codenest")


# -------------------------------
# BAN & SUSPENSION ENFORCEMENT HOOK
# -------------------------------
@app.before_request
def check_account_restrictions():
    if current_user.is_authenticated:
        try:
            db.session.refresh(current_user)
        except Exception:
            pass

        is_restricted = False
        message = ""

        if current_user.is_banned:
            is_restricted = True
            message = "This account has been permanently banned from CodeNest."
        else:
            is_susp, susp_date, susp_reason = current_user.get_suspension_status()
            if is_susp:
                is_restricted = True
                date_str = susp_date.strftime('%Y-%m-%d %H:%M UTC') if hasattr(susp_date, 'strftime') else str(susp_date)
                reason_str = f" Reason: {susp_reason}" if susp_reason else ""
                message = f"Your account is temporarily suspended until {date_str}.{reason_str}"

        if is_restricted:
            logout_user()
            session.clear()

            is_ajax = (
                request.headers.get('X-Requested-With') == 'XMLHttpRequest'
                or request.is_json
                or request.accept_mimetypes.best == 'application/json'
            )
            if is_ajax:
                return jsonify({'error': message, 'status': 'restricted'}), 403

            flash(message, 'danger')
            return redirect(url_for('login'))


# -------------------------------
# SECURITY & BROWSER CACHE CONTROL HOOK
# -------------------------------
@app.after_request
def set_security_cache_headers(response):
    """
    Prevent browsers from storing authenticated responses in the local disk cache
    or back-forward cache (bfcache). When users log out and press the browser 'Back'
    button, the browser is forced to re-validate with the server, where @login_required
    intercepts the request and redirects to the login screen.
    """
    content_type = response.headers.get('Content-Type', '')
    if 'text/html' in content_type or current_user.is_authenticated:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response



#-------------------------------
#GLOBAL APP RUN
#-------------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=int(os.environ.get('PORT', 5050)))
