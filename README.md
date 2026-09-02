# CodeNest

CodeNest is an academic collaboration web app for MMU students and lecturers to ask and answer questions, share study resources, and interact by faculty.

---

## 1. User Roles & Access Control

* **Student:**
  * Automatically assigned when registering with an `@student.mmu.edu.my` email.
  * Can post questions, write answers, view the student dashboard, and browse resources.
* **Professor:**
  * Automatically assigned when registering with an `@mmu.edu.my` email.
  * Answers are prioritized and highlighted in the Q&A section as official faculty answers.
* **Community Moderator:**
  * Assigned by admins/system for content moderation.
  * Access to the moderator dashboard.
* **Admin:**
  * Created via backend seed script (`python seed_admin.py`).
  * Access to the admin dashboard with user management and statistics.

---

## 2. Authentication & Security

* **Restricted MMU Registration:**
  * Only official MMU email domains allowed (`@student.mmu.edu.my` and `@mmu.edu.my`).
  * Auto role assignment based on domain.
  * Password hashing using Werkzeug.
* **Email Verification (OTP):**
  * 6-digit verification code sent on registration.
  * Accounts must be verified before login.
  * Option to resend verification code.
* **Login & Session:**
  * Login with either Username or Email + Password.
  * Session management handled with Flask-Login.

---

## 3. Dashboard System

* **Smart Dashboard Route (`/dashboard`):**
  * Single navbar link that automatically redirects each user to their specific dashboard based on their role.
* **Student Dashboard (`/dashboard/student`):**
  * Profile overview, activity links to Q&A and study materials.
* **Professor Dashboard (`/dashboard/professor`):**
  * Profile overview and faculty portal links.
* **Moderator Dashboard (`/dashboard/moderator`):**
  * Moderator status and oversight links.
* **Admin Dashboard (`/dashboard/admin`):**
  * Total user count metric and user list table (ID, username, email, role, faculty).

---

## 4. Q&A Forum Module

* **Question Feed (`/qa`):**
  * View all posted questions sorted by newest first.
  * Search bar (searches question titles and details).
  * Filter by Faculty (FCI, FOM).
  * Filter by Category (General, Assignments, Exams, Projects, Coding, Administrative).
* **Ask Question (`/qa/ask`):**
  * Logged-in users can post questions with title, details, faculty, and category.
* **Question Discussion Page (`/qa/<id>`):**
  * View question details, author, faculty, and timestamp.
  * Logged-in users can submit answers.
* **Smart Answer Sorting:**
  * Pinned "Best Answer" always stays at the top.
  * Verified Professor answers are ranked second for quick faculty help.
  * Community/student answers sorted chronologically.
* **Best Answer System:**
  * Question author can mark/unmark an answer as the "Best Answer".
* **Answer Management:**
  * Users can edit or delete their own answers.

---

## 5. Resource Hub Module

* **Resource Feed (`/resources`):**
  * Browse all shared academic resources ordered newest first.
  * Keyword search across title, description, and filename.
  * Faculty filtering (FCI, FOM).
  * Category filtering (Lecture Notes, Past Year Papers, Lab Sheets, Textbooks & References, Cheatsheets & Summaries, Other).
* **Upload Resource (`/resources/upload`):**
  * Logged-in users can upload study resources.
  * File validation: Allowed formats (`PDF`, `DOCX`, `PPTX`, `TXT`, `ZIP`) and 10MB size limit.
  * Secure server-side timestamped unique naming preventing collision and path traversal.
* **Download Resource (`/resources/download/<id>`):**
  * Secure file downloading using `send_from_directory` with original filename preservation.
* **Resource Management (`/resources/<id>/edit`, `/resources/<id>/delete`):**
  * Resource uploaders and admins can edit resource metadata (title, category, faculty, description).
  * Resource uploaders and admins can delete resources with automated database and physical file cleanup.

---

## 6. Tech Stack

* **Backend:** Python, Flask
* **Database:** SQLite, Flask-SQLAlchemy
* **Auth & Forms:** Flask-Login, Flask-WTF, WTForms, email_validator
* **Mailing:** Flask-Mail (SMTP OTP delivery)
* **Frontend:** HTML5, Jinja2 Templates

