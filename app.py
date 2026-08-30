import os
import random
from flask import Flask, render_template, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message

from models import db, User
from forms import RegistrationForm, LoginForm, VerificationForm
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'codenest-foundation-secret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///codenest.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True') == 'True'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')

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

        try:
            msg = Message(
                subject='CodeNest - Verify Your Account',
                sender=app.config['MAIL_USERNAME'],
                recipients=[user.email]
            )
            msg.body = f'Hi {user.username},\n\nYour CodeNest verification code is: {code}\n\nEnter this code to activate your account.'
            mail.send(msg)
        except Exception as e:
            flash(f'Account created, but the verification email failed to send: {e}', 'warning')

        flash(f'Account created! Role assigned: {role}. Please check your email for your 6-digit code.', 'info')
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
        flash(f'Failed to send verification email: {e}', 'warning')

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
