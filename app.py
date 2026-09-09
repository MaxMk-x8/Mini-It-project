import os
import random
import uuid
from datetime import datetime, timezone
from flask import Flask, render_template, redirect, url_for, flash, request, abort, send_from_directory, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from werkzeug.utils import secure_filename
from PIL import Image

from models import db, User, Question, Answer, Resource, AnswerBestMark, QAAttachment
from forms import (
    RegistrationForm, LoginForm, VerificationForm, QuestionForm, AnswerForm, 
    QUESTION_CATEGORIES, ResourceForm, ResourceEditForm, RESOURCE_CATEGORIES, ALLOWED_EXTENSIONS,
    ALLOWED_SCREENSHOT_EXTENSIONS, MAX_SCREENSHOT_SIZE, MAX_SCREENSHOTS_COUNT
)
from constants import FACULTIES
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

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

login_manager = LoginManager()
login_manager.init_app(app)
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

        existing_user = User.query.filter(
            (User.email == email) | (User.username == form.username.data.strip())
        ).first()

        if existing_user:
            flash('An account with that email or username already exists.', 'danger')
            return render_template('register.html', form=form)

        if email.endswith('@student.mmu.edu.my'):
            role = 'Student'
        elif email.endswith('@mmu.edu.my'):
            role = 'Professor'
        else:
            flash('Registration is restricted to official MMU emails (@student.mmu.edu.my or @mmu.edu.my).', 'danger')
            return render_template('register.html', form=form)

        code = str(random.randint(100000, 999999))

        user = User(
            username=form.username.data.strip(),
            email=email,
            faculty=form.faculty.data,
            role=role,
            verification_code=code,
            is_verified=False
        )
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

    if user.is_verified:
        flash('Your account is already verified.', 'info')
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        return redirect(url_for('login'))

    form = VerificationForm()
    if form.validate_on_submit():
        if form.code.data.strip() == user.verification_code:
            user.is_verified = True
            db.session.commit()
            login_user(user)
            flash(f'Account verified successfully! Welcome, {user.username}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid verification code.', 'danger')

    return render_template('verify_code.html', form=form, user=user)


@app.route('/resend-code/<int:user_id>')
def resend_code(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('register'))

    if user.is_verified:
        flash('Your account is already verified.', 'info')
        return redirect(url_for('login'))

    code = str(random.randint(100000, 999999))
    user.verification_code = code
    db.session.commit()

    # Log new verification code to console for local development
    print(f"\n========================================\n[CodeNest OTP] New verification code for {user.username} ({user.email}): {code}\n========================================\n", flush=True)

    try:
        msg = Message(
            subject='CodeNest - Verify Your Account',
            sender=app.config['MAIL_USERNAME'],
            recipients=[user.email]
        )
        msg.body = f'Hi {user.username},\n\nYour new CodeNest verification code is: {code}\n\nEnter this code to activate your account.'
        mail.send(msg)
        flash('A new verification code has been sent to your email.', 'info')
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

        if user and user.check_password(password):
            if not user.is_verified:
                flash('Please verify your account before logging in.', 'warning')
                return redirect(url_for('verify_code', user_id=user.id))
            login_user(user)
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email/username or password.', 'danger')

    return render_template('login.html', form=form)


@app.route('/logout')
@login_required
def logout():
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
    return render_template('moderator_dashboard.html', user=current_user)


@app.route('/dashboard/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin():
        flash('Not authorized to view the admin dashboard.', 'danger')
        return redirect(url_for('home'))

    total_users = User.query.count()
    all_users = User.query.all()
    return render_template('admin_dashboard.html', user=current_user, total_users=total_users, all_users=all_users)


#-------------------------------
# Q&A MODULE HELPERS & ROUTES (HABIB - WEEKS 1-4)
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



#-------------------------------
#GLOBAL APP RUN
#-------------------------------
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=int(os.environ.get('PORT', 5050)))
