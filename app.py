import os
import random
import uuid
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory, session, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, AnonymousUserMixin
from flask_mail import Mail, Message
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from PIL import Image

from models import db, User, Question, Answer, Resource, AnswerBestMark, QAAttachment, Report, ModeratorApplication, BannedEmail, UserWarning
from forms import (
    RegistrationForm, LoginForm, VerificationForm, QuestionForm, AnswerForm, 
    QUESTION_CATEGORIES, ResourceForm, ResourceEditForm, RESOURCE_CATEGORIES, ALLOWED_EXTENSIONS,
    ALLOWED_SCREENSHOT_EXTENSIONS, MAX_SCREENSHOT_SIZE, MAX_SCREENSHOTS_COUNT,
    ChangePasswordForm, LogoutForm, ReportActionForm,
    ModeratorApplicationForm, ModeratorApplicationReviewForm,
    ForgotPasswordForm, ResetPasswordForm, BanUserForm, SuspendUserForm, IssueWarningForm
)
from constants import FACULTIES, FACULTY_CODES
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

# Max request limit set to 20MB to support multiple 5MB screenshot uploads safely
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024


app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USE_SSL'] = os.environ.get('MAIL_USE_SSL', 'False') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

db.init_app(app)
mail = Mail(app)

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
                    return redirect(url_for('reset_password', user_id=user.id))

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

            return redirect(url_for('reset_password', user_id=user.id))
        else:
            flash('No account found with that email or username.', 'danger')

    return render_template('forgot_password.html', form=form)


@app.route('/reset-password/<int:user_id>', methods=['GET', 'POST'])
def reset_password(user_id):
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        is_valid, err_msg = user.is_reset_code_valid(form.code.data.strip())
        if is_valid:
            user.set_password(form.new_password.data)
            user.reset_code = None
            user.reset_code_created_at = None
            user.reset_resend_available_at = None
            user.reset_attempts = 0
            user.reset_login_lockout()
            db.session.commit()
            flash('Password reset successful! You may now log in with your new password.', 'success')
            return redirect(url_for('login'))
        else:
            flash(err_msg, 'danger')

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
            return redirect(url_for('reset_password', user_id=user.id))

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

    return redirect(url_for('reset_password', user_id=user.id))


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
    flash('You have been logged out.', 'info')
    return redirect(url_for('home'))


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_professor():
        return redirect(url_for('professor_dashboard'))
    elif current_user.is_student():
        return redirect(url_for('student_dashboard'))
    elif current_user.is_moderator():
        return redirect(url_for('moderator_dashboard'))
    elif current_user.is_admin():
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('home'))


@app.route('/dashboard/student')
@login_required
def student_dashboard():
    if not current_user.is_student():
        flash('Not authorized to view the student dashboard.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('student_dashboard.html', user=current_user)


@app.route('/dashboard/professor')
@login_required
def professor_dashboard():
    if not current_user.is_professor():
        flash('Not authorized to view the professor dashboard.', 'danger')
        return redirect(url_for('dashboard'))
    return render_template('professor_dashboard.html', user=current_user)


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

    return render_template(
        'moderator_dashboard.html',
        user=current_user,
        assigned_faculty=assigned_faculty,
        pending_reports=pending_reports,
        resolved_reports=resolved_reports
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

    banned_emails = BannedEmail.query.order_by(BannedEmail.created_at.desc()).all()
    ban_form = BanUserForm()
    suspend_form = SuspendUserForm()
    warn_form = IssueWarningForm()

    return render_template(
        'admin_dashboard.html',
        user=current_user,
        total_users=total_users,
        all_users=all_users,
        reports=reports,
        moderator_applications=moderator_applications,
        app_status_filter=app_status_filter,
        selected_faculty=selected_faculty,
        status_filter=status_filter,
        faculties=FACULTIES,
        banned_emails=banned_emails,
        ban_form=ban_form,
        suspend_form=suspend_form,
        warn_form=warn_form
    )


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
    return render_template('inbox.html', warnings=warnings)


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

    if form.validate_on_submit():
        # Handle optional screenshot uploads (up to 3)
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
                author_id=current_user.id,
                views=0
            )
            db.session.add(question)
            db.session.flush()

            for att in attachments:
                att.question_id = question.id
                db.session.add(att)

            db.session.commit()
            flash('Your question has been posted!', 'success')
            return redirect(url_for('qa_detail', question_id=question.id))

        except Exception as e:
            app.logger.error(f"Error saving question: {e}")
            db.session.rollback()
            delete_attachment_files(attachments)
            flash('An error occurred while saving your question. Please try again.', 'danger')
            return render_template('qa/ask.html', form=form)

    return render_template('qa/ask.html', form=form)


@app.route('/qa/<int:question_id>', methods=['GET', 'POST'])
def qa_detail(question_id):
    question = db.session.get(Question, question_id)
    if not question:
        flash('Question not found.', 'danger')
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
            # Verify the parent answer exists and belongs to this question
            parent_answer = db.session.get(Answer, parent_id_int)
            if parent_answer and parent_answer.question_id == question.id:
                parent_answer_id = parent_id_int

        # Handle optional screenshots (from main answer form or reply form)
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
                parent_answer_id=parent_answer_id  # --- Reply-to-answer feature (Habib) ---
            )
            db.session.add(answer)
            db.session.flush()

            for att in attachments:
                att.answer_id = answer.id
                db.session.add(att)

            db.session.commit()
            if parent_answer_id:
                flash('Your reply has been submitted!', 'success')
            else:
                flash('Your answer has been submitted!', 'success')
            return redirect(url_for('qa_detail', question_id=question.id))

        except Exception as e:
            app.logger.error(f"Error submitting answer: {e}")
            db.session.rollback()
            delete_attachment_files(attachments)
            flash('An error occurred while submitting your answer. Please try again.', 'danger')
            return redirect(url_for('qa_detail', question_id=question.id))

    # View count tracking on valid GET requests (at most once per browser session)
    if request.method == 'GET':
        viewed_questions = session.get('viewed_questions', [])
        if question.id not in viewed_questions:
            question.views = (question.views or 0) + 1
            db.session.commit()
            viewed_questions.append(question.id)
            session['viewed_questions'] = viewed_questions

    # Priority sorting (for top-level answers):
    # 1. Total Points (Professor endorsement = 50 pts, Student mark = 5 pts)
    # 2. Professor Answers next (authority boost)
    # 3. Oldest to newest or chronologically
    top_level_answers = [a for a in question.answers if a.parent_answer_id is None]
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

    # Toggle best mark (like a Facebook like / upvote)
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
    return redirect(url_for('qa_detail', question_id=question.id))


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
        db.session.commit()
        flash('Your answer has been updated.', 'success')
        return redirect(url_for('qa_detail', question_id=answer.question_id))

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

    # Clean up physical screenshot files for this answer and any nested replies
    attachments_to_delete = list(answer.attachments)
    for reply in answer.replies:
        attachments_to_delete.extend(reply.attachments)
    delete_attachment_files(attachments_to_delete)

    db.session.delete(answer)
    db.session.commit()
    flash('Your answer has been deleted.', 'info')
    return redirect(url_for('qa_detail', question_id=question_id))


#-------------------------------
# RESOURCE HUB MODULE ROUTES 
#-------------------------------

@app.route('/resources')
def resources_list():
    query_text = request.args.get('q', '').strip()
    selected_faculty = request.args.get('faculty', '').strip()
    selected_category = request.args.get('category', '').strip()

    query = Resource.query

    if query_text:
        search_filter = f"%{query_text}%"
        query = query.filter(
            (Resource.title.ilike(search_filter)) | 
            (Resource.description.ilike(search_filter)) |
            (Resource.filename.ilike(search_filter))
        )

    if selected_faculty:
        query = query.filter(Resource.faculty == selected_faculty)

    if selected_category:
        query = query.filter(Resource.category == selected_category)

    resources = query.order_by(Resource.created_at.desc()).all()

    return render_template(
        'resources/index.html',
        resources=resources,
        query_text=query_text,
        selected_faculty=selected_faculty,
        selected_category=selected_category,
        faculties=FACULTIES,
        categories=RESOURCE_CATEGORIES
    )


@app.route('/resources/upload', methods=['GET', 'POST'])
@login_required
def resource_upload():
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
        if file_size > 10 * 1024 * 1024:
            if os.path.exists(file_path):
                os.remove(file_path)
            flash('File exceeds the 10MB size limit.', 'danger')
            return render_template('resources/upload.html', form=form)

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
            uploader_id=current_user.id
        )
        db.session.add(resource)
        db.session.commit()

        flash(f"Resource '{resource.title}' uploaded successfully!", 'success')
        return redirect(url_for('resources_list'))

    return render_template('resources/upload.html', form=form)


@app.route('/resources/download/<int:resource_id>')
def resource_download(resource_id):
    resource = db.session.get(Resource, resource_id)
    if not resource:
        flash('Resource not found.', 'danger')
        return redirect(url_for('resources_list'))

    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.stored_filename)
    if not os.path.exists(file_path):
        flash('The requested file is no longer available on disk.', 'danger')
        return redirect(url_for('resources_list'))

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
        resource.title = form.title.data.strip()
        resource.description = form.description.data.strip() if form.description.data else ''
        resource.category = form.category.data
        resource.faculty = form.faculty.data

        db.session.commit()
        flash('Resource details updated successfully!', 'success')
        return redirect(url_for('resources_list'))

    return render_template('resources/edit.html', form=form, resource=resource)


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

    # Remove physical file from disk
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], resource.stored_filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception as e:
            app.logger.warning(f"Failed to remove physical file {file_path}: {e}")

    # Remove database record
    db.session.delete(resource)
    db.session.commit()

    flash(f"Resource '{resource.title}' has been deleted.", 'info')
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



#-------------------------------
#GLOBAL APP RUN
#-------------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=int(os.environ.get('PORT', 5050)))
