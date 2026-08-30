"""
Admin account creation
seeded directly to database
"""
import getpass
from app import app, db
from models import User

with app.app_context():
    db.create_all()

    username = input("Admin username: ").strip()
    email = input("Admin email: ").strip().lower()
    faculty = 'FCI'  
    password = getpass.getpass("Admin password (hidden while typing): ")

    existing = User.query.filter(
        (User.username == username) | (User.email == email)
    ).first()

    if existing:
        print(f"A user with that username/email already exists: {existing.username}")
    elif faculty not in ('FCI', 'FOM'):
        print("Faculty must be FCI or FOM.")
    else:
        admin = User(username=username, email=email, role='Admin', faculty=faculty, is_verified=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"Admin account '{username}' created successfully.")