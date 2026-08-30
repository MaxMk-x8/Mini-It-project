from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField
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
