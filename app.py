import os
import random
from flask import Flask, render_template, redirect, url_for, flash, request, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message

from models import db, User, Question, Answer
from forms import RegistrationForm, LoginForm, VerificationForm, QuestionForm, AnswerForm, QUESTION_CATEGORIES
from constants import FACULTIES
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'codenest-foundation-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///codenest.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

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

        if email.endswith('@mmu.edu.my') and not email.endswith('@student.mmu.edu.my'):
            role = 'Professor'
        elif email.endswith('@student.mmu.edu.my'):
            role = 'Student'
        else:
            role = 'Student'

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


@app.route('/dashboard/user')
@login_required
def user_dashboard():
    return render_template('user_dashboard.html', user=current_user)


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
# Q&A MODULE ROUTES (WEEKS 1-3)
#-------------------------------

@app.route('/qa')
def qa_list():
    query_text = request.args.get('q', '').strip()
    selected_faculty = request.args.get('faculty', '').strip()
    selected_category = request.args.get('category', '').strip()

    query = Question.query

    if query_text:
        search_filter = f"%{query_text}%"
        query = query.filter((Question.title.ilike(search_filter)) | (Question.content.ilike(search_filter)))

    if selected_faculty:
        query = query.filter(Question.faculty == selected_faculty)

    if selected_category:
        query = query.filter(Question.category == selected_category)

    questions = query.order_by(Question.created_at.desc()).all()

    return render_template(
        'qa/index.html',
        questions=questions,
        query_text=query_text,
        selected_faculty=selected_faculty,
        selected_category=selected_category,
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
        question = Question(
            title=form.title.data.strip(),
            content=form.content.data.strip(),
            category=form.category.data,
            faculty=form.faculty.data,
            author_id=current_user.id
        )
        db.session.add(question)
        db.session.commit()
        flash('Your question has been posted!', 'success')
        return redirect(url_for('qa_detail', question_id=question.id))

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

        answer = Answer(
            content=form.content.data.strip(),
            question_id=question.id,
            author_id=current_user.id
        )
        db.session.add(answer)
        db.session.commit()
        flash('Your answer has been submitted!', 'success')
        return redirect(url_for('qa_detail', question_id=question.id))

    # Priority sorting:
    # 1. Best Answer first
    # 2. Professor Answers next (using current_user/user is_professor check)
    # 3. Oldest to newest or chronologically
    sorted_answers = sorted(
        question.answers,
        key=lambda a: (
            1 if a.is_best_answer else 0,
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
    # Only the author of the question can mark the best answer
    if question.author_id != current_user.id:
        flash('Only the author of the question can mark the best answer.', 'danger')
        return redirect(url_for('qa_detail', question_id=question.id))

    if answer.is_best_answer:
        # Toggle off
        answer.is_best_answer = False
        question.best_answer_id = None
        flash('Best answer unmarked.', 'info')
    else:
        # Clear previous best answers for this question
        for other_answer in question.answers:
            other_answer.is_best_answer = False
        answer.is_best_answer = True
        question.best_answer_id = answer.id
        flash('Marked as best answer!', 'success')

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

    db.session.delete(answer)
    db.session.commit()
    flash('Your answer has been deleted.', 'info')
    return redirect(url_for('qa_detail', question_id=question_id))


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
