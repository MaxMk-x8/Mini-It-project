# CodeNest

An academic collaboration platform for Multimedia University (MMU) students and lecturers — ask questions, share study resources, find project teammates, and message each other, all behind MMU-verified accounts.

Built as a foundation-year Mini IT Project by a team of three.

---

## Features

### Authentication & Accounts
- Registration restricted to official MMU domains (`@student.mmu.edu.my`, `@mmu.edu.my`)
- Role assigned automatically from the email domain
- Email verification with a 6-digit OTP (5-minute expiry, 30-second resend cooldown, 5 attempts)
- Login with username **or** email, with a 60-second lockout after 5 failed attempts
- Password reset over a two-step OTP flow
- Profile editing, avatar upload, and admin-reviewed username changes

### Q&A Forum
- Post questions by faculty and category, with optional screenshot attachments
- Drafts, editing, and deletion for your own posts
- Answer sorting: pinned best answer first, then verified professor answers, then the rest
- Question author marks the best answer
- `@username` mentions with hover cards and in-app notifications
- Post visibility: public or friends-only
- Search across titles and details, filter by faculty and category

### Resource Hub
- Upload study materials (PDF, DOCX, PPTX, TXT, ZIP — 10 MB per file)
- Collections that group files, with ZIP download
- Star ratings and professor reviews
- Bookmarks, keyword search, faculty and category filters
- In-browser preview for PDF and TXT

### Idea Lab
- Post project ideas with category, faculty, course code and team size (2–10)
- Browse, search and filter open ideas
- Express interest with a pitch message; owner accepts or rejects
- Automatic team-full handling and manual open/close toggle
- Personal dashboard of ideas you posted and ideas you applied to

### Chat & Social
- One-to-one direct messaging with edit, pin and block
- Follow system with accept/decline requests
- Public profiles, user search, saved questions and answers
- Notification inbox

### Moderation & Administration
- Report any post or user; moderator queue with actions
- Warnings delivered to the user's inbox
- Temporary suspensions and permanent bans, re-checked on every request
- Moderator applications reviewed by admins
- Admin dashboard with user statistics and management

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask 3.1 |
| Database | SQLite, Flask-SQLAlchemy 3.1 |
| Auth & sessions | Flask-Login |
| Forms & CSRF | Flask-WTF, WTForms |
| Email | Resend HTTPS API (Flask-Mail SMTP fallback) |
| Images | Pillow |
| Frontend | Jinja2 templates, vanilla CSS and JavaScript |

**Scale:** 119 routes · 24 models · 36 forms · 56 templates · ~7,800 lines of Python

---

## Getting Started

### Requirements
- Python 3.11 or newer
- pip

### Installation

```bash
git clone https://github.com/MaxMk-x8/Mini-It-project.git
cd Mini-It-project

python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key-here
PORT=5050

# Email delivery (optional locally — OTP codes also print to the console)
RESEND_API_KEY=re_xxxxxxxxxx
```

### Run

```bash
python app.py
```

Open http://127.0.0.1:5050

Tables are created automatically on first run, and any new model columns are added on startup.

### Create an admin account

```bash
python seed_admin.py
```

Prompts for a username, email and password, and seeds an Admin directly into the database.

---

## Project Structure

```
Mini-It-project/
├── app.py                  # Routes, configuration, email dispatch
├── models.py               # SQLAlchemy models and schema migration
├── forms.py                # WTForms definitions and validators
├── constants.py            # Faculty constants, profanity filter
├── seed_admin.py           # Admin account seeder
├── requirements.txt
├── Procfile                # Gunicorn entry point for deployment
├── static/
│   ├── images/             # Logo and favicons
│   └── resources.css
├── templates/
│   ├── base.html           # Layout, navigation, theme variables
│   ├── index.html          # Landing page
│   ├── qa/                 # Q&A forum pages
│   ├── resources/          # Resource hub pages
│   ├── ideas/              # Idea Lab pages
│   └── ...                 # Auth, dashboards, chat, moderation
├── uploads/                # User uploads (gitignored)
│   ├── avatars/
│   ├── resources/
│   └── screenshots/
└── instance/
    └── codenest.db         # SQLite database (gitignored)
```

---

## Module Ownership

| Module | Owner |
|---|---|
| Authentication, Dashboards, Moderation | Mohammad Khan |
| Q&A Forum | Anik Md Ahoshan Habib |
| Resource Hub, Idea Lab | Pritiv |

---

## Security

- Passwords hashed with Werkzeug (scrypt); never stored in plain text
- CSRF protection on every form via Flask-WTF
- SQL injection prevented by SQLAlchemy's parameterised ORM
- XSS mitigated by Jinja2 autoescaping, with explicit escaping in custom filters
- Uploads validated by extension, size, and content (PDF magic bytes, Pillow verification), then stored under timestamped unique names
- Ownership and role checks on every write route
- Bans and suspensions enforced on every request
- Secrets kept in `.env`, which is gitignored

---

## Deployment

Deployed on Render as a Web Service.

- **Build:** `pip install -r requirements.txt`
- **Start:** `gunicorn -b 0.0.0.0:$PORT --timeout 120 app:app`
- **Environment variables:** `SECRET_KEY`, `RESEND_API_KEY`

Email is sent through the Resend HTTPS API from a verified domain, because Render blocks outbound SMTP ports. Note that the free instance type has an ephemeral filesystem — the SQLite database and uploaded files reset on each deploy.

---

## Roadmap

- Team chat for accepted Idea Lab members
- Skills on user profiles, searchable for finding collaborators
- Split `app.py` into Flask Blueprints per module
- Move from SQLite to PostgreSQL for persistent deployment
- Automated end-to-end tests

---

## License

Coursework submission for Multimedia University. Not licensed for reuse.
