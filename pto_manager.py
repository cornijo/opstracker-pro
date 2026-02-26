"""
PTO Manager Module — Employee data, PTO accrual, request workflow, email notifications.
"""

import os
import json
import datetime
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Configuration ---
DATA_DIR = "data"
EMPLOYEES_FILE = os.path.join(DATA_DIR, "employees.json")
PTO_REQUESTS_FILE = os.path.join(DATA_DIR, "pto_requests.csv")
PTO_LOG_FILE = os.path.join(DATA_DIR, "pto_email_log.txt")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")

# Default PTO accrual: 10 hrs/month (~15 days/year at 8 hrs/day)
DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH = 10
PTO_REQUEST_COLS = [
    "RequestID", "Employee", "StartDate", "EndDate", "Hours",
    "Reason", "Status", "RequestedAt", "ReviewedBy", "ReviewedAt"
]

# SMTP (from .env)
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


# =========================================================================
#  EMPLOYEE DATA
# =========================================================================

def _default_employees():
    """Default employee list — admin can edit later."""
    return {
        "employees": [
            {
                "name": "John Cornias",
                "email": "john@example.com",
                "role": "admin",
                "manager_email": "",
                "hire_date": "2024-01-01",
                "pto_accrual_rate": DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH,
                "pto_carryover": 0,
            }
        ]
    }


def load_employees():
    """Load employee data from JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(EMPLOYEES_FILE):
        with open(EMPLOYEES_FILE, "r") as f:
            return json.load(f)
    # Create default file
    data = _default_employees()
    save_employees(data)
    return data


def save_employees(data):
    """Save employee data to JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EMPLOYEES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_employee(name):
    """Get a single employee record by name (case-insensitive)."""
    data = load_employees()
    for emp in data["employees"]:
        if emp["name"].lower() == name.lower():
            return emp
    return None


def add_employee(name, email, role="employee", manager_email="", hire_date=None, accrual_rate=None):
    """Add a new employee."""
    from auth import _hash_password
    data = load_employees()
    if any(e["name"].lower() == name.lower() for e in data["employees"]):
        return False  # Already exists
    
    # Generate default password (use email, stripped of spaces)
    default_pw = email.strip() if email else "password123"

    data["employees"].append({
        "name": name.strip(),
        "email": email.strip() if email else "",
        "role": role,
        "manager_email": manager_email,
        "hire_date": (hire_date or datetime.date.today()).isoformat(),
        "pto_accrual_rate": accrual_rate or DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH,
        "pto_carryover": 0,
        "password_hash": _hash_password(default_pw),
    })
    save_employees(data)
    return True


def update_employee(name, updates):
    """Update employee fields by name."""
    data = load_employees()
    for emp in data["employees"]:
        if emp["name"].lower() == name.lower():
            emp.update(updates)
            save_employees(data)
            return True
    return False


def delete_employee(name):
    """Delete an employee by name. Returns True if deleted."""
    data = load_employees()
    original_len = len(data["employees"])
    data["employees"] = [e for e in data["employees"] if e["name"].lower() != name.lower()]
    if len(data["employees"]) < original_len:
        save_employees(data)
        return True
    return False


def is_admin(name):
    """Check if user is admin."""
    emp = get_employee(name)
    return emp is not None and emp.get("role") == "admin"


def get_all_employee_names():
    """Return sorted list of all employee names."""
    data = load_employees()
    return sorted([e["name"] for e in data["employees"]])


# =========================================================================
#  PROJECT / TASK MANAGEMENT
# =========================================================================

_DEFAULT_PROJECTS = {
    "PROJ-001 (Internal)": ["Admin", "Training", "Meetings"],
    "PROJ-102 (Client A)": ["Design", "Development", "Testing", "Project Mgmt"],
    "PROJ-205 (Client B)": ["On-Site Support", "Travel", "Implementation"],
}


def load_projects():
    """Load projects from JSON. Seeds from defaults on first call."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(PROJECTS_FILE):
        with open(PROJECTS_FILE, "r") as f:
            return json.load(f)
    # Seed with defaults
    save_projects(_DEFAULT_PROJECTS)
    return dict(_DEFAULT_PROJECTS)


def save_projects(projects):
    """Save projects dict to JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PROJECTS_FILE, "w") as f:
        json.dump(projects, f, indent=2)


def add_project(name, tasks):
    """Add a new project with a list of tasks. Returns True if added."""
    projects = load_projects()
    if name in projects:
        return False
    projects[name] = tasks
    save_projects(projects)
    return True


def update_project(name, tasks):
    """Update tasks for an existing project. Returns True if updated."""
    projects = load_projects()
    if name not in projects:
        return False
    projects[name] = tasks
    save_projects(projects)
    return True


def delete_project(name):
    """Remove a project. Returns True if deleted."""
    projects = load_projects()
    if name not in projects:
        return False
    del projects[name]
    save_projects(projects)
    return True


def get_all_project_names():
    """Return sorted list of project names."""
    return sorted(load_projects().keys())


def get_tasks_for_project(project_name):
    """Return list of tasks for a project."""
    return load_projects().get(project_name, [])


# =========================================================================
#  TIMESHEET / EXPENSE APPROVAL HELPERS
# =========================================================================

TIMESHEET_STATUS_COLS = ["Status", "SubmittedAt", "ReviewedBy", "ReviewedAt"]
EXPENSE_STATUS_COLS = ["Status", "SubmittedAt", "ReviewedBy", "ReviewedAt"]


def ensure_status_columns(df, extra_cols):
    """Add missing status columns to a dataframe for backward compat."""
    for col in extra_cols:
        if col not in df.columns:
            df[col] = ""
    # Default empty Status to "Draft"
    if "Status" in df.columns:
        df["Status"] = df["Status"].replace("", "Draft")
        df["Status"] = df["Status"].fillna("Draft")
    return df


def submit_timesheet_week(df, user, week_start_str):
    """
    Mark all Draft timesheet entries for a user's week as 'Submitted'.
    Returns updated dataframe.
    """
    mask = (
        (df["User"].str.lower() == user.lower()) &
        (df["Status"] == "Draft")
    )
    # Filter to the specific week's dates
    week_dates = _week_date_strings(week_start_str)
    mask = mask & df["Date"].isin(week_dates)

    if mask.sum() == 0:
        return df, False, "No draft entries to submit."

    now = datetime.datetime.now().isoformat()
    df.loc[mask, "Status"] = "Submitted"
    df.loc[mask, "SubmittedAt"] = now
    return df, True, f"Submitted {mask.sum()} entries."


def review_timesheet_week(df, user, week_start_str, reviewer, approve=True):
    """
    Approve or deny submitted timesheet entries for a user's week.
    Returns updated dataframe.
    """
    status = "Approved" if approve else "Denied"
    mask = (
        (df["User"].str.lower() == user.lower()) &
        (df["Status"] == "Submitted")
    )
    week_dates = _week_date_strings(week_start_str)
    mask = mask & df["Date"].isin(week_dates)

    if mask.sum() == 0:
        return df, False, "No submitted entries found."

    now = datetime.datetime.now().isoformat()
    df.loc[mask, "Status"] = status
    df.loc[mask, "ReviewedBy"] = reviewer
    df.loc[mask, "ReviewedAt"] = now

    # Denied entries go back to Draft so employee can re-edit
    if not approve:
        df.loc[mask, "Status"] = "Denied"

    return df, True, f"{status} {mask.sum()} entries."


def submit_expense_week(df, user, week_start_str):
    """
    Mark all Draft expense entries for a user's week as 'Submitted'.
    Returns updated dataframe.
    """
    mask = (
        (df["User"].str.lower() == user.lower()) &
        (df["Status"] == "Draft")
    )
    week_dates = _week_date_strings(week_start_str)
    mask = mask & df["Date"].isin(week_dates)

    if mask.sum() == 0:
        return df, False, "No draft expenses to submit."

    now = datetime.datetime.now().isoformat()
    df.loc[mask, "Status"] = "Submitted"
    df.loc[mask, "SubmittedAt"] = now
    return df, True, f"Submitted {mask.sum()} expenses."


def review_expense_week(df, user, week_start_str, reviewer, approve=True):
    """
    Approve or deny submitted expense entries for a user's week.
    Returns updated dataframe.
    """
    status = "Approved" if approve else "Denied"
    mask = (
        (df["User"].str.lower() == user.lower()) &
        (df["Status"] == "Submitted")
    )
    week_dates = _week_date_strings(week_start_str)
    mask = mask & df["Date"].isin(week_dates)

    if mask.sum() == 0:
        return df, False, "No submitted expenses found."

    now = datetime.datetime.now().isoformat()
    df.loc[mask, "Status"] = status
    df.loc[mask, "ReviewedBy"] = reviewer
    df.loc[mask, "ReviewedAt"] = now
    return df, True, f"{status} {mask.sum()} expenses."


def _week_date_strings(week_start_str):
    """Return list of 7 date strings (YYYY-MM-DD) for a week starting at week_start_str."""
    sun = datetime.date.fromisoformat(week_start_str)
    return [(sun + datetime.timedelta(days=i)).isoformat() for i in range(7)]


def get_submitted_weeks(df, status="Submitted"):
    """
    Return list of dicts with user, week_start, and total for weeks
    that have entries with the given status.
    Used by admin to see what needs approval.
    """
    if df.empty or "Status" not in df.columns:
        return []
    filtered = df[df["Status"] == status]
    if filtered.empty:
        return []
    seen = set()
    result = []
    # Determine the value column (Hours for timesheets, Amount for expenses)
    value_col = "Hours" if "Hours" in df.columns else "Amount"
    for user in filtered["User"].unique():
        user_rows = filtered[filtered["User"] == user]
        for date_str in user_rows["Date"].unique():
            try:
                d = datetime.date.fromisoformat(str(date_str))
                sun, _ = get_week_range(d)
                key = (user, sun.isoformat())
                if key not in seen:
                    seen.add(key)
                    # Calculate total for this user's week
                    week_dates = _week_date_strings(sun.isoformat())
                    week_mask = (
                        (df["User"] == user) &
                        (df["Date"].isin(week_dates))
                    )
                    total = df.loc[week_mask, value_col].astype(float).sum()
                    result.append({
                        "user": user,
                        "week_start": sun.isoformat(),
                        "total": total,
                    })
            except (ValueError, TypeError):
                continue
    return result


# =========================================================================
#  PTO ACCRUAL & BALANCE
# =========================================================================

def calculate_accrued_pto(employee_name, as_of_date=None):
    """
    Calculate total PTO accrued from hire date to as_of_date.
    Returns hours.
    """
    emp = get_employee(employee_name)
    if emp is None:
        return 0

    if as_of_date is None:
        as_of_date = datetime.date.today()

    hire_str = emp.get("hire_date", "2025-01-01")
    if not hire_str:
        hire_str = "2025-01-01"
    hire = datetime.date.fromisoformat(hire_str)
    if as_of_date < hire:
        return 0

    # Months between hire and now
    months = (as_of_date.year - hire.year) * 12 + (as_of_date.month - hire.month)
    if as_of_date.day < hire.day:
        months -= 1
    months = max(months, 0)

    rate = emp.get("pto_accrual_rate", DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH)
    return round(months * rate, 1)


def calculate_used_pto(employee_name):
    """Calculate total approved PTO hours used."""
    df = load_pto_requests()
    if df.empty:
        return 0
    approved = df[(df["Employee"].str.lower() == employee_name.lower()) & (df["Status"] == "Approved")]
    return approved["Hours"].sum() if not approved.empty else 0


def get_pto_balance(employee_name, as_of_date=None):
    """Get PTO balance: accrued + carryover - used."""
    emp = get_employee(employee_name)
    if emp is None:
        return {"accrued": 0, "used": 0, "carryover": 0, "balance": 0}

    accrued = calculate_accrued_pto(employee_name, as_of_date)
    used = calculate_used_pto(employee_name)
    carryover = emp.get("pto_carryover", 0)

    return {
        "accrued": accrued,
        "used": used,
        "carryover": carryover,
        "balance": round(accrued + carryover - used, 1),
        "accrual_rate": emp.get("pto_accrual_rate", DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH),
    }


def set_carryover(employee_name, hours):
    """Admin-only: set PTO carryover hours."""
    return update_employee(employee_name, {"pto_carryover": hours})


# =========================================================================
#  PTO REQUESTS
# =========================================================================

def load_pto_requests():
    """Load PTO requests from CSV."""
    if os.path.exists(PTO_REQUESTS_FILE):
        return pd.read_csv(PTO_REQUESTS_FILE)
    return pd.DataFrame(columns=PTO_REQUEST_COLS)


def save_pto_requests(df):
    """Save PTO requests to CSV."""
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(PTO_REQUESTS_FILE, index=False)


def _next_request_id():
    df = load_pto_requests()
    if df.empty:
        return "PTO-001"
    last_num = df["RequestID"].str.extract(r"PTO-(\d+)").astype(float).max().iloc[0]
    return f"PTO-{int(last_num) + 1:03d}"


def submit_pto_request(employee_name, start_date, end_date, hours, reason=""):
    """
    Submit a new PTO request. Sends email to manager.
    Returns (success, message).
    """
    # Check balance
    balance = get_pto_balance(employee_name)
    if hours > balance["balance"]:
        return False, f"Insufficient PTO balance ({balance['balance']} hrs available, {hours} hrs requested)"

    request_id = _next_request_id()
    df = load_pto_requests()

    new_row = pd.DataFrame([{
        "RequestID": request_id,
        "Employee": employee_name,
        "StartDate": start_date.isoformat() if hasattr(start_date, "isoformat") else start_date,
        "EndDate": end_date.isoformat() if hasattr(end_date, "isoformat") else end_date,
        "Hours": hours,
        "Reason": reason,
        "Status": "Pending",
        "RequestedAt": datetime.datetime.now().isoformat(),
        "ReviewedBy": "",
        "ReviewedAt": "",
    }])

    df = pd.concat([df, new_row], ignore_index=True)
    save_pto_requests(df)

    # Send email to manager
    emp = get_employee(employee_name)
    if emp and emp.get("manager_email"):
        _send_pto_email(
            to=emp["manager_email"],
            subject=f"PTO Request: {employee_name} ({request_id})",
            body=f"""
New PTO Request from {employee_name}

Request ID: {request_id}
Dates: {start_date} — {end_date}
Hours: {hours}
Reason: {reason or 'N/A'}
PTO Balance After: {balance['balance'] - hours} hrs

Please approve or deny this request in OpsTracker.
            """.strip()
        )

    return True, f"Request {request_id} submitted successfully"


def review_pto_request(request_id, reviewer_name, approve=True):
    """
    Approve or deny a PTO request. Sends email to employee.
    """
    df = load_pto_requests()
    mask = df["RequestID"] == request_id
    if mask.sum() == 0:
        return False, "Request not found"

    status = "Approved" if approve else "Denied"
    df.loc[mask, "Status"] = status
    df.loc[mask, "ReviewedBy"] = reviewer_name
    df.loc[mask, "ReviewedAt"] = datetime.datetime.now().isoformat()
    save_pto_requests(df)

    # Email employee
    row = df[mask].iloc[0]
    emp = get_employee(row["Employee"])
    if emp:
        _send_pto_email(
            to=emp.get("email", ""),
            subject=f"PTO Request {status}: {request_id}",
            body=f"""
Your PTO request ({request_id}) has been {status.lower()} by {reviewer_name}.

Dates: {row['StartDate']} — {row['EndDate']}
Hours: {row['Hours']}
Status: {status}
            """.strip()
        )

    return True, f"Request {request_id} {status.lower()}"


def get_pending_requests(for_employee=None):
    """Get pending PTO requests, optionally filtered by employee."""
    df = load_pto_requests()
    if df.empty:
        return df
    pending = df[df["Status"] == "Pending"]
    if for_employee:
        pending = pending[pending["Employee"].str.lower() == for_employee.lower()]
    return pending


def get_employee_requests(employee_name):
    """Get all PTO requests for an employee."""
    df = load_pto_requests()
    if df.empty:
        return df
    return df[df["Employee"].str.lower() == employee_name.lower()]


# =========================================================================
#  EMAIL
# =========================================================================

def send_notification_email(to, subject, body):
    """Send email notification. Falls back to logging if SMTP not configured."""
    if not to:
        return
    if not SMTP_USER or not SMTP_PASSWORD:
        _log_email(to, subject, body)
        return
    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, to, msg.as_string())
    except Exception as e:
        _log_email(to, subject, body, error=str(e))


# Keep backward compat
_send_pto_email = send_notification_email


def send_denial_email(employee_name, denial_type, week_label, reviewer, comment=""):
    """
    Send a denial notification email to an employee.
    denial_type: 'timesheet', 'expense', or 'pto'
    week_label: human-readable week or date range (e.g. 'Feb 22 – Feb 28, 2026')
    reviewer: name of the person who denied
    comment: optional review comment
    """
    emp = get_employee(employee_name)
    if not emp or not emp.get("email"):
        return False

    type_labels = {
        "timesheet": "Timesheet",
        "expense": "Expense Report",
        "pto": "PTO Request",
    }
    type_label = type_labels.get(denial_type, denial_type.title())

    subject = f"⚠️ {type_label} Denied — {week_label}"
    body = f"""Hi {employee_name},

Your {type_label} for {week_label} has been DENIED by {reviewer}.

{"Comment from reviewer: " + comment if comment else "No comment was provided."}

Please review and revise your submission in OpsTracker Pro, then resubmit.

— OpsTracker Pro"""

    send_notification_email(emp["email"], subject, body)
    return True


def _log_email(to, subject, body, error=None):
    """Log email that would have been sent (when SMTP is not configured)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(PTO_LOG_FILE, "a") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"Time: {datetime.datetime.now().isoformat()}\n")
        f.write(f"To: {to}\n")
        f.write(f"Subject: {subject}\n")
        if error:
            f.write(f"ERROR: {error}\n")
        f.write(f"Body:\n{body}\n")


# =========================================================================
#  WEEK HELPERS (used by both timesheet & expense pages)
# =========================================================================

def get_week_range(ref_date=None):
    """
    Get Sunday–Saturday week containing ref_date.
    Returns (sunday, saturday) as datetime.date objects.
    """
    if ref_date is None:
        ref_date = datetime.date.today()
    # Python: Monday=0 ... Sunday=6
    # We want Sunday=start: shift so Sunday=0
    day_of_week = (ref_date.weekday() + 1) % 7  # Sun=0, Mon=1, ..., Sat=6
    sunday = ref_date - datetime.timedelta(days=day_of_week)
    saturday = sunday + datetime.timedelta(days=6)
    return sunday, saturday


def get_week_dates(ref_date=None):
    """Return list of 7 dates (Sun–Sat) for the week containing ref_date."""
    sunday, _ = get_week_range(ref_date)
    return [sunday + datetime.timedelta(days=i) for i in range(7)]


def format_week_label(ref_date=None):
    """Format like 'Sun Feb 9 – Sat Feb 15, 2026'."""
    sun, sat = get_week_range(ref_date)
    return f"Sun {sun.strftime('%b %-d')} – Sat {sat.strftime('%b %-d, %Y')}"
