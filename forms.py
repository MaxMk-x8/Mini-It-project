from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, EqualTo

from constants import FACULTIES


class RegistrationForm(FlaskForm):
    """
    No role field - role is auto-assigned from email domain
    in the register() route in app.py.
    """
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=50)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')


class LoginForm(FlaskForm):
    email_or_username = StringField('Email or Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')


class VerificationForm(FlaskForm):
    code = StringField('6-Digit Code', validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField('Verify')


QUESTION_CATEGORIES = [
    ('General', 'General'),
    ('Assignments', 'Assignments'),
    ('Exams', 'Exams'),
    ('Projects', 'Projects'),
    ('Coding', 'Coding'),
    ('Administrative', 'Administrative')
]


class QuestionForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=5, max=150)])
    category = SelectField('Category', choices=QUESTION_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    content = TextAreaField('Question Details', validators=[DataRequired(), Length(min=10)])
    submit = SubmitField('Post Question')


class AnswerForm(FlaskForm):
    content = TextAreaField('Your Answer', validators=[DataRequired(), Length(min=2)])
    submit = SubmitField('Submit Answer')


# -------------------------------
# RESOURCE HUB MODULE FORMS 
# -------------------------------
from flask_wtf.file import FileField, FileRequired, FileAllowed

RESOURCE_CATEGORIES = [
    ('Lecture Notes', 'Lecture Notes'),
    ('Past Year Papers', 'Past Year Papers'),
    ('Lab Sheets', 'Lab Sheets'),
    ('Textbooks & References', 'Textbooks & References'),
    ('Cheatsheets & Summaries', 'Cheatsheets & Summaries'),
    ('Other', 'Other')
]

ALLOWED_EXTENSIONS = ['pdf', 'docx', 'pptx', 'txt', 'zip']


class ResourceForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=3, max=150)])
    category = SelectField('Category', choices=RESOURCE_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    description = TextAreaField('Description (Optional)', validators=[Length(max=1000)])
    file = FileField('Resource File', validators=[
        FileRequired(message='Please select a file to upload.'),
        FileAllowed(ALLOWED_EXTENSIONS, f'Allowed file types: {", ".join(ALLOWED_EXTENSIONS).upper()}')
    ])
    submit = SubmitField('Upload Resource')


class ResourceEditForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=3, max=150)])
    category = SelectField('Category', choices=RESOURCE_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    description = TextAreaField('Description (Optional)', validators=[Length(max=1000)])
    submit = SubmitField('Update Resource')
