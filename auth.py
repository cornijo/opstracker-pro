"""
Authentication Module — Secure login with bcrypt password hashing.
Provides login page, session management, and admin user setup.
"""

import os
import json
import bcrypt
import streamlit as st
import datetime

DATA_DIR = "data"
EMPLOYEES_FILE = os.path.join(DATA_DIR, "employees.json")


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def _verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except Exception:
        return False


def _load_employees():
    """Load employee data from JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(EMPLOYEES_FILE):
        with open(EMPLOYEES_FILE, "r") as f:
            return json.load(f)
    return {"employees": []}


def _save_employees(data):
    """Save employee data to JSON."""
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EMPLOYEES_FILE, "w") as f:
        json.dump(data, f, indent=2)


def ensure_passwords_exist():
    """
    Ensure all employees have a password_hash field.
    Employees without a password get a default password = their email address.
    The admin (first user) gets 'admin123' as default if no password set.
    If no employees exist at all, create a default admin account.
    """
    data = _load_employees()
    changed = False

    # If no employees exist, create default admin
    if not data["employees"]:
        data["employees"].append({
            "name": "John Cornias",
            "email": "john.cornias@retiina.com",
            "role": "admin",
            "manager": "",
            "password_hash": _hash_password("admin123")
        })
        changed = True

    for i, emp in enumerate(data["employees"]):
        if "password_hash" not in emp or not emp["password_hash"]:
            # Set default password to the employee's email, or 'admin123' for first admin
            if i == 0 and emp.get("role") == "admin":
                default_pw = "admin123"
            else:
                default_pw = emp.get("email", "password123")
            emp["password_hash"] = _hash_password(default_pw)
            changed = True
    if changed:
        _save_employees(data)
    return data


def set_employee_password(employee_name: str, new_password: str) -> bool:
    """Set a new password for an employee."""
    data = _load_employees()
    for emp in data["employees"]:
        if emp["name"].lower() == employee_name.lower():
            emp["password_hash"] = _hash_password(new_password)
            _save_employees(data)
            return True
    return False


def authenticate(email_or_name: str, password: str):
    """
    Authenticate a user by email or name + password.
    Returns the employee dict on success, None on failure.
    """
    data = _load_employees()
    login_lower = email_or_name.strip().lower()

    for emp in data["employees"]:
        # Match by email or name (case-insensitive)
        if (emp.get("email", "").lower() == login_lower or
                emp["name"].lower() == login_lower):
            hashed = emp.get("password_hash", "")
            if hashed and _verify_password(password, hashed):
                return emp
    return None


def is_authenticated() -> bool:
    """Check if the user is currently authenticated."""
    return st.session_state.get("authenticated", False)


def get_current_user() -> str:
    """Get the currently logged-in user's name."""
    return st.session_state.get("current_user", "")


def get_current_user_role() -> str:
    """Get the currently logged-in user's role."""
    return st.session_state.get("current_role", "employee")


def logout():
    """Clear authentication state."""
    for key in ["authenticated", "current_user", "current_role", "current_email"]:
        if key in st.session_state:
            del st.session_state[key]


def render_login_page():
    """
    Render the login page. Returns True if user just authenticated.
    Call this at the top of your app — if it returns False, stop rendering.
    """
    # Initialize password defaults
    ensure_passwords_exist()

    if is_authenticated():
        return True

    # --- Login Page ---
    st.set_page_config(page_title="OpsTracker Pro — Login", layout="centered", page_icon="💼")

    # Custom CSS for login page
    st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
        .stApp { background: linear-gradient(135deg, #1B2A4A 0%, #111D35 50%, #0D1526 100%); }

        .login-container {
            max-width: 420px;
            margin: 0 auto;
            padding: 2.5rem;
            background: rgba(255,255,255,0.97);
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.4);
        }
        .login-header {
            text-align: center;
            margin-bottom: 2rem;
        }
        .login-header h1 {
            color: #1B2A4A;
            font-size: 1.8rem;
            font-weight: 700;
            margin: 0;
        }
        .login-header .subtitle {
            color: #00838F;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.15em;
            font-weight: 600;
            margin-top: 4px;
        }
        .login-footer {
            text-align: center;
            color: rgba(255,255,255,0.4);
            font-size: 0.7rem;
            margin-top: 2rem;
        }
        /* Hide Streamlit header/footer on login page */
        header[data-testid="stHeader"] { display: none; }
        footer { display: none; }
        #MainMenu { display: none; }
        .stDeployButton { display: none; }
    </style>
    """, unsafe_allow_html=True)

    # Spacer
    st.markdown("<br><br>", unsafe_allow_html=True)

    # Login form
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div class="login-header">
            <h1>💼 OpsTracker Pro</h1>
            <div class="subtitle">Enterprise Time & Expense</div>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form", clear_on_submit=False):
            login_id = st.text_input(
                "Email or Name",
                placeholder="john@example.com",
                key="login_id"
            )
            password = st.text_input(
                "Password",
                type="password",
                placeholder="Enter your password",
                key="login_password"
            )

            submitted = st.form_submit_button("Sign In", type="primary", use_container_width=True)

            if submitted:
                if not login_id or not password:
                    st.error("Please enter your email/name and password.")
                else:
                    emp = authenticate(login_id, password)
                    if emp:
                        st.session_state["authenticated"] = True
                        st.session_state["current_user"] = emp["name"]
                        st.session_state["current_role"] = emp.get("role", "employee")
                        st.session_state["current_email"] = emp.get("email", "")
                        st.rerun()
                    else:
                        st.error("❌ Invalid credentials. Please try again.")

        st.markdown("""
        <div class="login-footer">
            <p>Powered by OpsTracker Pro<br>Contact your administrator for access</p>
        </div>
        """, unsafe_allow_html=True)

    return False
