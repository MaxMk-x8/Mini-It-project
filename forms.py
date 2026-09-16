from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, TextAreaField, MultipleFileField, IntegerField
from wtforms.validators import DataRequired, Email, Length, EqualTo, ValidationError, NumberRange

from constants import FACULTIES, contains_profanity


class NoProfanity:
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        if field.data:
            has_profanity, term = contains_profanity(field.data)
            if has_profanity:
                msg = self.message or f"Your submission contains prohibited or inappropriate language ('{term}'). Please maintain respectful and academic discourse."
                raise ValidationError(msg)


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

# Habib - Week 4: Allowed screenshot extensions & limits
ALLOWED_SCREENSHOT_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp']
MAX_SCREENSHOT_SIZE = 5 * 1024 * 1024  # 5 MB per image
MAX_SCREENSHOTS_COUNT = 3


class QuestionForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=5, max=150), NoProfanity()])
    category = SelectField('Category', choices=QUESTION_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    content = TextAreaField('Question Details', validators=[DataRequired(), Length(min=10), NoProfanity()])
    screenshots = MultipleFileField('Screenshots (Optional, max 3, up to 5MB each, PNG/JPG/WebP)')
    submit = SubmitField('Post Question')


class AnswerForm(FlaskForm):
    content = TextAreaField('Your Answer', validators=[DataRequired(), Length(min=2), NoProfanity()])
    screenshots = MultipleFileField('Screenshots (Optional, max 3, up to 5MB each, PNG/JPG/WebP)')
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

SEMESTER_CHOICES = [
    ('', '-- Select Trimester / Semester (Optional) --'),
    ('Trimester 1', 'Trimester 1'),
    ('Trimester 2', 'Trimester 2'),
    ('Trimester 3', 'Trimester 3'),
    ('Semester 1', 'Semester 1'),
    ('Semester 2', 'Semester 2'),
    ('Special Term / Summer', 'Special Term / Summer')
]

ALLOWED_EXTENSIONS = ['pdf', 'docx', 'pptx', 'txt', 'zip']


class ResourceForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=3, max=150), NoProfanity()])
    category = SelectField('Category', choices=RESOURCE_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    description = TextAreaField('Description (Optional)', validators=[Length(max=1000), NoProfanity()])
    course_code = StringField('Course / Module Code (Optional)', validators=[Length(max=20), NoProfanity()], filters=[lambda x: x.strip().upper() if x else None])
    course_name = StringField('Course / Module Name (Optional)', validators=[Length(max=150), NoProfanity()])
    academic_year = StringField('Academic Year (Optional, e.g. 2023/2024)', validators=[Length(max=20), NoProfanity()])
    semester = SelectField('Semester (Optional)', choices=SEMESTER_CHOICES)
    file = FileField('Resource File', validators=[
        FileRequired(message='Please select a file to upload.'),
        FileAllowed(ALLOWED_EXTENSIONS, f'Allowed file types: {", ".join(ALLOWED_EXTENSIONS).upper()}')
    ])
    submit = SubmitField('Upload Resource')


class ResourceEditForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(min=3, max=150), NoProfanity()])
    category = SelectField('Category', choices=RESOURCE_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    description = TextAreaField('Description (Optional)', validators=[Length(max=1000), NoProfanity()])
    course_code = StringField('Course / Module Code (Optional)', validators=[Length(max=20), NoProfanity()], filters=[lambda x: x.strip().upper() if x else None])
    course_name = StringField('Course / Module Name (Optional)', validators=[Length(max=150), NoProfanity()])
    academic_year = StringField('Academic Year (Optional, e.g. 2023/2024)', validators=[Length(max=20), NoProfanity()])
    semester = SelectField('Semester (Optional)', choices=SEMESTER_CHOICES)
    submit = SubmitField('Update Resource')


class RatingForm(FlaskForm):
    rating = SelectField('Your Rating', choices=[
        (5, '★★★★★ (5 - Excellent)'),
        (4, '★★★★☆ (4 - Very Good)'),
        (3, '★★★☆☆ (3 - Good)'),
        (2, '★★☆☆☆ (2 - Fair)'),
        (1, '★☆☆☆☆ (1 - Poor)')
    ], coerce=int, validators=[DataRequired(message='Please choose a rating (1 to 5 stars).')])
    submit = SubmitField('Submit Rating')


class ProfessorReviewForm(FlaskForm):
    review_note = TextAreaField('Endorsement / Review Note (Optional)', validators=[Length(max=255), NoProfanity()])
    submit = SubmitField('Endorse & Review')


class CollectionForm(FlaskForm):
    title = StringField('Collection Title', validators=[DataRequired(), Length(min=3, max=150), NoProfanity()])
    category = SelectField('Category', choices=RESOURCE_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    description = TextAreaField('Description (Optional)', validators=[Length(max=1000), NoProfanity()])
    course_code = StringField('Course / Module Code (Optional)', validators=[Length(max=20), NoProfanity()], filters=[lambda x: x.strip().upper() if x else None])
    course_name = StringField('Course / Module Name (Optional)', validators=[Length(max=150), NoProfanity()])
    academic_year = StringField('Academic Year (Optional, e.g. 2023/2024)', validators=[Length(max=20), NoProfanity()])
    semester = SelectField('Semester (Optional)', choices=SEMESTER_CHOICES)
    files = MultipleFileField('Notes Folder / Files')
    submit = SubmitField('Upload Notes Collection')


# Alias for compatibility with prompt specifications
CollectionUploadForm = CollectionForm


class CollectionEditForm(FlaskForm):
    title = StringField('Collection Title', validators=[DataRequired(), Length(min=3, max=150), NoProfanity()])
    category = SelectField('Category', choices=RESOURCE_CATEGORIES, validators=[DataRequired()])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    description = TextAreaField('Description (Optional)', validators=[Length(max=1000), NoProfanity()])
    course_code = StringField('Course / Module Code (Optional)', validators=[Length(max=20), NoProfanity()], filters=[lambda x: x.strip().upper() if x else None])
    course_name = StringField('Course / Module Name (Optional)', validators=[Length(max=150), NoProfanity()])
    academic_year = StringField('Academic Year (Optional, e.g. 2023/2024)', validators=[Length(max=20), NoProfanity()])
    semester = SelectField('Semester (Optional)', choices=SEMESTER_CHOICES)
    submit = SubmitField('Update Collection')


class AddFilesToCollectionForm(FlaskForm):
    files = MultipleFileField('Additional Files / Folder', validators=[DataRequired(message='Please select files to add.')])
    submit = SubmitField('Add Files to Collection')



# -------------------------------
# SETTINGS & AUTH FORMS 
# -------------------------------

class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters long.')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('new_password', message='New password and confirmation do not match.')
    ])
    submit = SubmitField('Change Password')


class LogoutForm(FlaskForm):
    submit = SubmitField('Logout')


# -------------------------------
# REPORTING & MODERATION FORMS 
# -------------------------------

REPORT_REASONS = [
    ('spam', 'Spam or advertising'),
    ('inappropriate', 'Inappropriate or abusive language'),
    ('misinformation', 'Harmful or incorrect academic material'),
    ('plagiarism', 'Plagiarism / Honor code violation'),
    ('other', 'Other reason')
]


class ReportForm(FlaskForm):
    content_type = StringField('Content Type', validators=[DataRequired()])
    content_id = StringField('Content ID', validators=[DataRequired()])
    reason = SelectField('Reason for Report', choices=REPORT_REASONS, validators=[DataRequired()])
    details = TextAreaField('Additional Details (Optional)', validators=[Length(max=1000)])
    submit = SubmitField('Submit Report')


class ReportActionForm(FlaskForm):
    action = SelectField('Action', choices=[
        ('resolve', 'Mark as Resolved (Content Kept)'),
        ('dismiss', 'Dismiss Report (No Violation Found)'),
        ('remove_content', 'Remove Content (Delete Content & Attachments)')
    ], validators=[DataRequired()])
    decision_note = TextAreaField('Decision Note (Optional)', validators=[Length(max=1000)])
    submit = SubmitField('Submit Moderation Decision')


# -------------------------------
# MODERATOR APPLICATION FORMS
# -------------------------------

class ModeratorApplicationForm(FlaskForm):
    full_name = StringField('Full Name', validators=[
        DataRequired(message='Full name is required.'),
        Length(min=2, max=100, message='Full name must be between 2 and 100 characters.')
    ])
    matric_number = StringField('Student ID / Matric Number', validators=[
        DataRequired(message='Student ID / Matric number is required.'),
        Length(min=5, max=30, message='Student ID must be between 5 and 30 characters.')
    ])
    faculty = SelectField('Faculty', choices=FACULTIES, validators=[DataRequired()])
    reason = TextAreaField('Why do you want to become a Community Moderator? (Statement of Motivation)', validators=[
        DataRequired(message='Please explain why you want to become a moderator.'),
        Length(min=20, max=2000, message='Your statement must be between 20 and 2000 characters.'),
        NoProfanity()
    ])
    submit = SubmitField('Submit Application')


class ModeratorApplicationReviewForm(FlaskForm):
    action = SelectField('Decision', choices=[
        ('approve', 'Approve Application (Promote to Community Moderator)'),
        ('reject', 'Reject Application')
    ], validators=[DataRequired()])
    admin_note = TextAreaField('Admin Note / Feedback (Optional)', validators=[Length(max=1000)])
    submit = SubmitField('Submit Review Decision')


# -------------------------------
# AUTH RECOVERY & DISCIPLINE FORMS
# -------------------------------

class ForgotPasswordForm(FlaskForm):
    email_or_username = StringField('Email or Username', validators=[
        DataRequired(message='Please enter your registered MMU email or username.')
    ])
    submit = SubmitField('Send Password Reset Code')


class ResetPasswordForm(FlaskForm):
    code = StringField('6-Digit Reset Code', validators=[
        DataRequired(message='Please enter the 6-digit code sent to your email.'),
        Length(min=6, max=6, message='Reset code must be exactly 6 digits.')
    ])
    new_password = PasswordField('New Password', validators=[
        DataRequired(message='Please enter a new password.'),
        Length(min=6, message='Password must be at least 6 characters long.')
    ])
    confirm_password = PasswordField('Confirm New Password', validators=[
        DataRequired(message='Please confirm your new password.'),
        EqualTo('new_password', message='New password and confirmation do not match.')
    ])
    submit = SubmitField('Reset Password')


class BanUserForm(FlaskForm):
    reason = StringField('Reason for Ban (Optional)', validators=[Length(max=255)])
    submit = SubmitField('Permanently Ban User')


class SuspendUserForm(FlaskForm):
    days = IntegerField('Suspension Duration (Days)', default=30, validators=[
        DataRequired(),
        NumberRange(min=1, max=365, message='Duration must be between 1 and 365 days.')
    ])
    reason = StringField('Reason for Suspension (Optional)', validators=[Length(max=255)])
    submit = SubmitField('Suspend User')


class IssueWarningForm(FlaskForm):
    message = TextAreaField('Warning Message', validators=[
        DataRequired(message='Please write a message explaining the warning.'),
        Length(min=5, max=1000, message='Warning message must be between 5 and 1000 characters.')
    ])
    submit = SubmitField('Send Official Warning')



