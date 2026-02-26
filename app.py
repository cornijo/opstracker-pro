import streamlit as st
import pandas as pd
import datetime
import plotly.express as px
import os
import io

from auth import (
    render_login_page, is_authenticated, get_current_user,
    get_current_user_role, logout, set_employee_password,
    ensure_passwords_exist
)

# --- AUTHENTICATION GATE ---
# This MUST come before set_page_config since login page sets its own
if not is_authenticated():
    render_login_page()
    st.stop()

from gsa_rates import (
    load_locations_df, build_full_cache, get_cache_info,
    search_rates, get_rate_for_location, lookup_zip,
    get_states_from_cache, get_locations_for_state,
    invalidate_cache, calc_daily_meal_allowance, get_mie_breakdown,
    MONTH_COLS, MONTH_MAP, CURRENT_FY, GSA_MILEAGE_RATE,
    STANDARD_LODGING, STANDARD_MEALS
)

from pto_manager import (
    load_employees, get_employee, add_employee, update_employee, delete_employee,
    is_admin, get_all_employee_names,
    get_pto_balance, set_carryover, calculate_accrued_pto,
    submit_pto_request, review_pto_request,
    load_pto_requests, get_pending_requests, get_employee_requests,
    send_denial_email,

    get_week_range, get_week_dates, format_week_label,
    DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH,
    # Project / Task management
    load_projects, add_project, update_project, delete_project,
    get_all_project_names, get_tasks_for_project,
    # Approval helpers
    ensure_status_columns, TIMESHEET_STATUS_COLS, EXPENSE_STATUS_COLS,
    submit_timesheet_week, review_timesheet_week,
    submit_expense_week, review_expense_week,
    get_submitted_weeks,
)

# --- CONFIGURATION & STORAGE ---
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

FILES = {
    "time": os.path.join(DATA_DIR, "timesheets.csv"),
    "expenses": os.path.join(DATA_DIR, "expenses.csv"),
}

# Projects are now loaded dynamically from data/projects.json
# via load_projects() from pto_manager

DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

RECEIPTS_DIR = os.path.join(DATA_DIR, "receipts")
os.makedirs(RECEIPTS_DIR, exist_ok=True)

EXPENSE_COLUMNS = [
    "User", "Date", "Category", "Details", "Amount", "GSA_Limit",
    "Reimbursable", "PaidBy", "TicketNumber", "TravelFrom", "TravelTo",
    "Receipt", "Project", "Task", "Notes",
    "DayType", "BreakfastProvided", "LunchProvided", "DinnerProvided",
    "MIE_Rate"
]

# --- HELPER FUNCTIONS ---
def load_data(key):
    if os.path.exists(FILES[key]):
        df = pd.read_csv(FILES[key])
        # Ensure all expense columns exist (backward compat)
        if key == "expenses":
            for col in EXPENSE_COLUMNS:
                if col not in df.columns:
                    df[col] = ""
        # Ensure status / approval columns exist (backward compat)
        if key == "time":
            df = ensure_status_columns(df, TIMESHEET_STATUS_COLS)
        if key == "expenses":
            df = ensure_status_columns(df, EXPENSE_STATUS_COLS)
        return df
    else:
        if key == "time":
            return pd.DataFrame(columns=["User", "Date", "Project", "Task", "Hours", "Notes"] + TIMESHEET_STATUS_COLS)
        elif key == "expenses":
            return pd.DataFrame(columns=EXPENSE_COLUMNS + EXPENSE_STATUS_COLS)
        return pd.DataFrame()

def _safe_str(val):
    """Return empty string for NaN/None, otherwise str(val)."""
    if val is None or (isinstance(val, float) and val != val):
        return ""
    s = str(val).strip()
    return "" if s.lower() == "nan" else s

def save_data(key, df):
    df.to_csv(FILES[key], index=False)

def save_receipt(uploaded_file, user, date_str):
    """Save an uploaded receipt file. Returns the filename."""
    if uploaded_file is None:
        return ""
    safe_user = user.replace(" ", "_").lower()
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    ext = os.path.splitext(uploaded_file.name)[1] or ".pdf"
    filename = f"{safe_user}_{date_str}_{timestamp}{ext}"
    filepath = os.path.join(RECEIPTS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(uploaded_file.getbuffer())
    return filename

def get_employees_for_manager(manager_name):
    employees = load_employees()
    return [e["Name"] for e in employees if e.get("Manager") == manager_name]


# ============================================================
#  PAGE CONFIGURATION
# ============================================================
st.set_page_config(page_title="OpsTracker Pro", layout="wide", page_icon="💼")

# --- Professional CSS — Unanet-inspired corporate design ---
st.markdown("""
<style>
/* ═══════════════════════════════════════════════════════════
   GOOGLE FONTS
   ═══════════════════════════════════════════════════════════ */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ═══════════════════════════════════════════════════════════
   CSS VARIABLES — Unanet color palette
   ═══════════════════════════════════════════════════════════ */
:root {
    --unanet-navy:      #1B2A4A;
    --unanet-navy-deep: #111D35;
    --unanet-teal:      #00838F;
    --unanet-teal-light:#4DD0E1;
    --unanet-teal-bg:   rgba(0,131,143,0.08);
    --unanet-blue:      #1565C0;
    --unanet-blue-light:#42A5F5;
    --unanet-green:     #2E7D32;
    --unanet-green-bg:  rgba(46,125,50,0.08);
    --unanet-orange:    #E65100;
    --unanet-orange-bg: rgba(230,81,0,0.08);
    --unanet-red:       #C62828;
    --unanet-red-bg:    rgba(198,40,40,0.08);
    --unanet-gray-50:   #FAFBFC;
    --unanet-gray-100:  #F1F3F5;
    --unanet-gray-200:  #E1E5EA;
    --unanet-gray-300:  #CED4DA;
    --unanet-gray-500:  #868E96;
    --unanet-gray-700:  #495057;
    --unanet-gray-900:  #212529;
    --card-shadow:      0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    --card-shadow-hover:0 4px 16px rgba(0,0,0,0.10);
    --radius:           8px;
    --radius-lg:        12px;
}

/* ═══════════════════════════════════════════════════════════
   GLOBAL TYPOGRAPHY & BASE
   ═══════════════════════════════════════════════════════════ */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
.main {
    background: var(--unanet-gray-50) !important;
}
.main .block-container {
    padding-top: 1rem;
    padding-bottom: 2rem;
    max-width: 1280px;
}

/* ═══════════════════════════════════════════════════════════
   SIDEBAR — Dark Navy with Teal accents (Unanet signature)
   ═══════════════════════════════════════════════════════════ */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, var(--unanet-navy) 0%, var(--unanet-navy-deep) 100%) !important;
    border-right: 1px solid rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] * {
    color: #B0BEC5 !important;
}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 {
    color: #ffffff !important;
}
/* Sidebar labels */
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stRadio label {
    color: var(--unanet-teal-light) !important;
    font-weight: 600;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
/* Sidebar select inputs */
section[data-testid="stSidebar"] .stSelectbox > div > div {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 6px;
    color: #ffffff !important;
    transition: all 0.2s ease;
}
section[data-testid="stSidebar"] .stSelectbox > div > div:hover {
    border-color: var(--unanet-teal) !important;
    background: rgba(255,255,255,0.09) !important;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.08) !important;
}
/* Sidebar alerts */
section[data-testid="stSidebar"] .stAlert {
    background: rgba(0,131,143,0.12) !important;
    border: 1px solid rgba(0,131,143,0.25) !important;
    border-left: 3px solid var(--unanet-teal) !important;
}
section[data-testid="stSidebar"] .stCaption {
    color: #78909C !important;
}
/* Sidebar buttons */
section[data-testid="stSidebar"] button {
    background: rgba(0,131,143,0.15) !important;
    border: 1px solid rgba(0,131,143,0.30) !important;
    color: var(--unanet-teal-light) !important;
    border-radius: 6px;
    font-weight: 500;
    font-size: 0.82rem;
    transition: all 0.2s ease;
}
section[data-testid="stSidebar"] button:hover {
    background: rgba(0,131,143,0.25) !important;
    border-color: var(--unanet-teal) !important;
    color: #ffffff !important;
    transform: translateY(-1px);
}
/* Sidebar expander */
section[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: rgba(255,255,255,0.02) !important;
    border: 1px solid rgba(255,255,255,0.06) !important;
    border-radius: var(--radius);
}

/* ═══════════════════════════════════════════════════════════
   TOP HEADER BAR — Unanet-style breadcrumb bar
   ═══════════════════════════════════════════════════════════ */
.unanet-header {
    background: linear-gradient(135deg, var(--unanet-navy) 0%, #1a3a5c 50%, var(--unanet-teal) 100%);
    color: white;
    padding: 18px 28px;
    border-radius: var(--radius-lg);
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    box-shadow: 0 4px 20px rgba(27,42,74,0.25);
    position: relative;
    overflow: hidden;
}
.unanet-header::before {
    content: '';
    position: absolute;
    top: 0; right: 0;
    width: 300px; height: 100%;
    background: radial-gradient(ellipse at top right, rgba(77,208,225,0.15), transparent 70%);
    pointer-events: none;
}
.unanet-header h1 {
    color: white !important;
    font-size: 1.4rem !important;
    font-weight: 700 !important;
    margin: 0 !important;
    letter-spacing: -0.01em !important;
}
.unanet-header .header-sub {
    color: rgba(255,255,255,0.7);
    font-size: 0.78rem;
    font-weight: 400;
    margin-top: 2px;
}
.unanet-header .header-badge {
    background: rgba(255,255,255,0.15);
    border: 1px solid rgba(255,255,255,0.2);
    color: white;
    padding: 6px 16px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.03em;
    backdrop-filter: blur(4px);
}

/* ═══════════════════════════════════════════════════════════
   TOP-LEVEL TABS — Unanet-style navigation tabs
   ═══════════════════════════════════════════════════════════ */
[data-testid="stTabs"] > div:first-child {
    background: #ffffff;
    border-bottom: 2px solid var(--unanet-gray-200);
    padding: 0 0.25rem;
    gap: 0;
    border-radius: var(--radius) var(--radius) 0 0;
}
button[data-baseweb="tab"] {
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.84rem !important;
    color: var(--unanet-gray-500) !important;
    padding: 0.7rem 1.1rem !important;
    border-radius: 0 !important;
    border-bottom: 3px solid transparent !important;
    transition: all 0.15s ease !important;
    text-transform: none !important;
    letter-spacing: 0.01em !important;
    background: transparent !important;
    white-space: nowrap !important;
}
button[data-baseweb="tab"]:hover {
    color: var(--unanet-teal) !important;
    background: var(--unanet-teal-bg) !important;
}
button[data-baseweb="tab"][aria-selected="true"] {
    color: var(--unanet-teal) !important;
    border-bottom-color: var(--unanet-teal) !important;
    background: var(--unanet-teal-bg) !important;
}

/* ═══════════════════════════════════════════════════════════
   METRIC CARDS — Unanet-style with colored left accent
   ═══════════════════════════════════════════════════════════ */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid var(--unanet-gray-200);
    border-left: 4px solid var(--unanet-teal) !important;
    border-radius: var(--radius);
    padding: 16px 20px 12px;
    box-shadow: var(--card-shadow);
    transition: box-shadow 0.2s ease, transform 0.15s ease;
}
[data-testid="stMetric"]:hover {
    box-shadow: var(--card-shadow-hover);
    transform: translateY(-2px);
}
[data-testid="stMetric"] label {
    font-size: 0.68rem !important;
    font-weight: 700 !important;
    text-transform: uppercase !important;
    letter-spacing: 0.07em !important;
    color: var(--unanet-gray-500) !important;
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 700 !important;
    color: var(--unanet-navy) !important;
}

/* ═══════════════════════════════════════════════════════════
   CONTAINERS & CARDS — Elevated card style
   ═══════════════════════════════════════════════════════════ */
[data-testid="stVerticalBlock"] > div[style*="border"] {
    border: 1px solid var(--unanet-gray-200) !important;
    border-radius: var(--radius-lg) !important;
    box-shadow: var(--card-shadow) !important;
    background: #ffffff !important;
    transition: box-shadow 0.2s ease, transform 0.15s ease;
}
[data-testid="stVerticalBlock"] > div[style*="border"]:hover {
    box-shadow: var(--card-shadow-hover) !important;
    transform: translateY(-1px);
}

/* Expanders */
[data-testid="stExpander"] {
    border: 1px solid var(--unanet-gray-200) !important;
    border-radius: var(--radius) !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.03) !important;
    background: #ffffff;
    transition: border-color 0.2s ease;
}
[data-testid="stExpander"]:hover {
    border-color: var(--unanet-gray-300) !important;
}
[data-testid="stExpander"] summary {
    font-weight: 600 !important;
    color: var(--unanet-gray-700) !important;
    font-size: 0.9rem !important;
}

/* ═══════════════════════════════════════════════════════════
   BUTTONS — Unanet teal primary, clean secondary
   ═══════════════════════════════════════════════════════════ */
.stButton > button[kind="primary"],
.stButton > button[type="primary"] {
    background: linear-gradient(135deg, var(--unanet-teal) 0%, #00695C 100%) !important;
    border: none !important;
    border-radius: var(--radius) !important;
    font-weight: 600 !important;
    font-size: 0.84rem !important;
    padding: 0.5rem 1.25rem !important;
    letter-spacing: 0.01em !important;
    color: white !important;
    box-shadow: 0 2px 6px rgba(0,131,143,0.30) !important;
    transition: all 0.2s ease !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[type="primary"]:hover {
    background: linear-gradient(135deg, #00695C 0%, #004D40 100%) !important;
    box-shadow: 0 4px 14px rgba(0,131,143,0.40) !important;
    transform: translateY(-1px) !important;
}
.stButton > button[kind="secondary"] {
    background: #ffffff !important;
    border: 1px solid var(--unanet-gray-300) !important;
    border-radius: var(--radius) !important;
    color: var(--unanet-gray-700) !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
}
.stButton > button[kind="secondary"]:hover {
    background: var(--unanet-gray-50) !important;
    border-color: var(--unanet-teal) !important;
    color: var(--unanet-teal) !important;
}

/* ═══════════════════════════════════════════════════════════
   STATUS BADGES — Pill-style inline badges
   ═══════════════════════════════════════════════════════════ */
.status-draft {
    background: #FFF8E1; color: #F57F17;
    padding: 3px 12px; border-radius: 12px;
    font-size: 0.72rem; font-weight: 700;
    display: inline-block; letter-spacing: 0.03em;
    border: 1px solid #FFE082;
}
.status-submitted {
    background: #E3F2FD; color: #1565C0;
    padding: 3px 12px; border-radius: 12px;
    font-size: 0.72rem; font-weight: 700;
    display: inline-block; letter-spacing: 0.03em;
    border: 1px solid #90CAF9;
}
.status-approved {
    background: #E8F5E9; color: #2E7D32;
    padding: 3px 12px; border-radius: 12px;
    font-size: 0.72rem; font-weight: 700;
    display: inline-block; letter-spacing: 0.03em;
    border: 1px solid #A5D6A7;
}
.status-denied {
    background: #FFEBEE; color: #C62828;
    padding: 3px 12px; border-radius: 12px;
    font-size: 0.72rem; font-weight: 700;
    display: inline-block; letter-spacing: 0.03em;
    border: 1px solid #EF9A9A;
}

/* ═══════════════════════════════════════════════════════════
   ALERTS — Unanet-style with colored left accent
   ═══════════════════════════════════════════════════════════ */
.stAlert {
    border-radius: var(--radius) !important;
    font-size: 0.86rem !important;
    border-left: 4px solid !important;
}
[data-testid="stAlert"][data-baseweb*="info"],
div[data-testid="stNotification"][data-baseweb*="info"] {
    border-left-color: var(--unanet-blue) !important;
    background: rgba(21,101,192,0.04) !important;
}
[data-testid="stAlert"][data-baseweb*="success"],
div[data-testid="stNotification"][data-baseweb*="success"] {
    border-left-color: var(--unanet-green) !important;
    background: var(--unanet-green-bg) !important;
}
[data-testid="stAlert"][data-baseweb*="warning"],
div[data-testid="stNotification"][data-baseweb*="warning"] {
    border-left-color: var(--unanet-orange) !important;
    background: var(--unanet-orange-bg) !important;
}
[data-testid="stAlert"][data-baseweb*="error"],
div[data-testid="stNotification"][data-baseweb*="error"] {
    border-left-color: var(--unanet-red) !important;
    background: var(--unanet-red-bg) !important;
}

/* ═══════════════════════════════════════════════════════════
   DATAFRAMES & TABLES — Clean corporate grid
   ═══════════════════════════════════════════════════════════ */
[data-testid="stDataFrame"] {
    border: 1px solid var(--unanet-gray-200);
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--card-shadow);
}

/* ═══════════════════════════════════════════════════════════
   DATA EDITOR — Unanet grid-style
   ═══════════════════════════════════════════════════════════ */
[data-testid="stDataEditor"] {
    border: 1px solid var(--unanet-gray-200);
    border-radius: var(--radius);
    overflow: hidden;
    box-shadow: var(--card-shadow);
}

/* ═══════════════════════════════════════════════════════════
   FORMS & INPUTS — Refined with teal focus
   ═══════════════════════════════════════════════════════════ */
.stForm {
    padding-top: 0 !important;
    border: 1px solid var(--unanet-gray-200) !important;
    border-radius: var(--radius-lg) !important;
    padding: 1.25rem 1.5rem !important;
    background: #ffffff !important;
    box-shadow: var(--card-shadow) !important;
}
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stSelectbox > div > div {
    border-radius: 6px !important;
    border-color: var(--unanet-gray-300) !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease !important;
    font-size: 0.88rem !important;
}
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus {
    border-color: var(--unanet-teal) !important;
    box-shadow: 0 0 0 3px rgba(0,131,143,0.12) !important;
}
/* Input labels */
.stTextInput label, .stNumberInput label, .stSelectbox label,
.stDateInput label, .stFileUploader label, .stTextArea label,
.stCheckbox label, .stRadio label {
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    color: var(--unanet-gray-700) !important;
}

/* ═══════════════════════════════════════════════════════════
   HEADERS — Unanet corporate typography
   ═══════════════════════════════════════════════════════════ */
h1 {
    color: var(--unanet-navy) !important;
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    font-size: 1.65rem !important;
}
h2 {
    color: var(--unanet-navy) !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
    font-size: 1.3rem !important;
}
h3 {
    color: var(--unanet-gray-700) !important;
    font-weight: 600 !important;
    font-size: 1.05rem !important;
}
h5 {
    color: var(--unanet-teal) !important;
    font-weight: 700 !important;
    font-size: 0.82rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.06em !important;
}

/* ═══════════════════════════════════════════════════════════
   DIVIDERS
   ═══════════════════════════════════════════════════════════ */
hr {
    border-color: var(--unanet-gray-200) !important;
    margin: 0.75rem 0 !important;
}

/* ═══════════════════════════════════════════════════════════
   DOWNLOAD BUTTONS — Green accent
   ═══════════════════════════════════════════════════════════ */
[data-testid="stDownloadButton"] > button {
    background: linear-gradient(135deg, var(--unanet-green) 0%, #1B5E20 100%) !important;
    border: none !important;
    color: white !important;
    border-radius: var(--radius) !important;
    font-weight: 600 !important;
    box-shadow: 0 2px 6px rgba(46,125,50,0.30) !important;
    transition: all 0.2s ease !important;
}
[data-testid="stDownloadButton"] > button:hover {
    background: linear-gradient(135deg, #1B5E20 0%, #0D3B13 100%) !important;
    box-shadow: 0 4px 14px rgba(46,125,50,0.40) !important;
    transform: translateY(-1px) !important;
}

/* ═══════════════════════════════════════════════════════════
   CAPTION STYLING
   ═══════════════════════════════════════════════════════════ */
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--unanet-gray-500) !important;
    font-size: 0.76rem !important;
}

/* ═══════════════════════════════════════════════════════════
   PLOTLY CHARTS
   ═══════════════════════════════════════════════════════════ */
[data-testid="stPlotlyChart"] {
    border: 1px solid var(--unanet-gray-200);
    border-radius: var(--radius-lg);
    overflow: hidden;
    background: #ffffff;
    box-shadow: var(--card-shadow);
}

/* ═══════════════════════════════════════════════════════════
   SCROLLBAR (subtle)
   ═══════════════════════════════════════════════════════════ */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: var(--unanet-gray-300);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--unanet-gray-500);
}

/* ═══════════════════════════════════════════════════════════
   WEEK PICKER — cleaner navigation bar
   ═══════════════════════════════════════════════════════════ */
.week-nav {
    background: #ffffff;
    border: 1px solid var(--unanet-gray-200);
    border-radius: var(--radius-lg);
    padding: 12px 20px;
    box-shadow: var(--card-shadow);
    margin-bottom: 0.75rem;
}

/* ═══════════════════════════════════════════════════════════
   SECTION CARDS — for grouping content areas
   ═══════════════════════════════════════════════════════════ */
.section-card {
    background: #ffffff;
    border: 1px solid var(--unanet-gray-200);
    border-radius: var(--radius-lg);
    padding: 20px 24px;
    box-shadow: var(--card-shadow);
    margin-bottom: 1rem;
}
.section-card h3 {
    margin-top: 0 !important;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--unanet-gray-100);
    margin-bottom: 16px !important;
}

/* ═══════════════════════════════════════════════════════════
   QUICK ACTIONS BAR
   ═══════════════════════════════════════════════════════════ */
.quick-actions {
    display: flex;
    gap: 8px;
    padding: 8px 0;
}
.quick-action-btn {
    background: var(--unanet-teal-bg);
    border: 1px solid rgba(0,131,143,0.15);
    color: var(--unanet-teal);
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s ease;
    text-decoration: none;
}
.quick-action-btn:hover {
    background: rgba(0,131,143,0.15);
    transform: translateY(-1px);
}

/* ═══════════════════════════════════════════════════════════
   ANIMATIONS
   ═══════════════════════════════════════════════════════════ */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
.main .block-container {
    animation: fadeInUp 0.3s ease-out;
}
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---
# Company logo
_logo_path = os.path.join(DATA_DIR, "retina-logo.png")
if not os.path.exists(_logo_path):
    _alt_logo = os.path.join(os.path.dirname(__file__), "Christmas bingo all together", "retina-logo.png")
    if os.path.exists(_alt_logo):
        import shutil
        shutil.copy2(_alt_logo, _logo_path)
if os.path.exists(_logo_path):
    st.sidebar.image(_logo_path, use_container_width=True)

# Branding
st.sidebar.markdown("""
<div style="text-align:center; padding: 0 0 0.75rem;">
    <span style="color:#4DD0E1; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.12em; font-weight:700;">
        Enterprise Time &amp; Expense
    </span>
    <div style="color:#546E7A; font-size:0.6rem; margin-top:3px; letter-spacing:0.05em;">Powered by OpsTracker Pro</div>
</div>
""", unsafe_allow_html=True)
st.sidebar.markdown("---")

# --- Authenticated User (from session) ---
current_user = get_current_user()
user_is_admin = is_admin(current_user)

# User info display
_role_color = "#4DD0E1" if user_is_admin else "#90A4AE"
_role_label = "Administrator" if user_is_admin else "Employee"
_role_icon = "🔑" if user_is_admin else "👤"

st.sidebar.markdown(f"""
<div style="text-align:center; margin-bottom:0.5rem;">
    <div style="color:#B0BEC5; font-size:0.68rem; text-transform:uppercase; letter-spacing:0.1em; font-weight:600;">Logged in as</div>
    <div style="color:#ffffff; font-size:0.95rem; font-weight:600; margin-top:4px;">{current_user}</div>
</div>
""", unsafe_allow_html=True)

st.sidebar.markdown(f"""
<div style="
    background: {'rgba(0,131,143,0.15)' if user_is_admin else 'rgba(144,164,174,0.12)'};
    border: 1px solid {'rgba(0,131,143,0.30)' if user_is_admin else 'rgba(144,164,174,0.2)'};
    border-radius: 20px;
    padding: 6px 14px;
    margin: 0.25rem 0 0.5rem;
    text-align: center;
">
    <span style="color: {_role_color}; font-weight: 700; font-size: 0.72rem; letter-spacing: 0.06em;">
        {_role_icon} {_role_label.upper()}
    </span>
</div>
""", unsafe_allow_html=True)

# Logout button
if st.sidebar.button("🚪 Sign Out", use_container_width=True):
    logout()
    st.rerun()

# Password change (in expander)
with st.sidebar.expander("🔒 Change Password", expanded=False):
    new_pw = st.text_input("New Password", type="password", key="change_pw")
    confirm_pw = st.text_input("Confirm Password", type="password", key="confirm_pw")
    if st.button("Update Password", key="update_pw_btn"):
        if new_pw and new_pw == confirm_pw:
            if len(new_pw) >= 6:
                set_employee_password(current_user, new_pw)
                st.success("✅ Password updated!")
            else:
                st.error("Password must be at least 6 characters.")
        elif new_pw != confirm_pw:
            st.error("Passwords don't match.")
        else:
            st.error("Please enter a new password.")

st.sidebar.markdown("---")

# --- Navigation (role-gated) ---
base_pages = ["Weekly Time & Expenses", "GSA Rate Lookup", "PTO Management"]
if user_is_admin:
    base_pages.append("Admin Dashboard")
# --- Unanet-style Header Bar ---
_today = datetime.date.today()
st.markdown(f"""
<div class="unanet-header">
    <div>
        <h1>💼 OpsTracker Pro</h1>
        <div class="header-sub">📅 {_today.strftime('%A, %B %d, %Y')} &nbsp;·&nbsp; Logged in as <b>{current_user}</b></div>
    </div>
    <div class="header-badge">{_role_icon} {_role_label.upper()}</div>
</div>
""", unsafe_allow_html=True)

# Create top-level tabs
main_tabs_list = st.tabs(base_pages)
tabs_dict = dict(zip(base_pages, main_tabs_list))


# GSA Cache Status — collapsed expander
with st.sidebar.expander("📡 GSA Data", expanded=False):
    cache_info = get_cache_info()
    if cache_info:
        st.success(f"FY{cache_info['fiscal_year']} • {cache_info['total_locations']} locations • {cache_info['total_zips']:,} ZIPs")
        st.caption(f"Built: {cache_info['built_at'][:10]}")
    else:
        st.warning("No rate data cached")

    if st.button("🔄 Refresh GSA Rates", key="sidebar_refresh"):
        with st.spinner("Building GSA rate database..."):
            prog = st.progress(0, text="Starting...")
            def _prog(msg, cur, tot):
                if tot > 0:
                    prog.progress(min((cur+1)/(tot+1), 1.0), text=msg)
            loc_count, zip_count = build_full_cache(CURRENT_FY, progress_callback=_prog)
            prog.progress(1.0, text="Complete!")
            invalidate_cache()
        st.success(f"✅ {loc_count} locations, {zip_count:,} ZIPs!")
        st.rerun()


# ============================================================
#  SHARED: WEEK PICKER (with green current-week indicator)
# ============================================================



def week_picker(key_prefix="wp"):
    """Render a Sun–Sat week picker. Returns (sunday, saturday, [7 dates], is_current_week)."""
    if f"{key_prefix}_ref" not in st.session_state:
        st.session_state[f"{key_prefix}_ref"] = datetime.date.today()

    ref = st.session_state[f"{key_prefix}_ref"]
    sun, sat = get_week_range(ref)
    dates = get_week_dates(ref)

    today_sun, _ = get_week_range(datetime.date.today())
    is_current_week = (sun == today_sun)

    col_prev, col_label, col_next, col_today = st.columns([1, 4, 1, 2])
    with col_prev:
        if st.button("◀ Prev", key=f"{key_prefix}_prev"):
            st.session_state[f"{key_prefix}_ref"] = ref - datetime.timedelta(weeks=1)
            st.rerun()
    with col_label:
        week_label = format_week_label(ref)
        if is_current_week:
            st.markdown(f"### 📅 {week_label} &nbsp; <span style='background:#00838F; color:white; padding:2px 12px; border-radius:12px; font-size:0.7rem; font-weight:700; vertical-align:middle; letter-spacing:0.04em;'>CURRENT</span>", unsafe_allow_html=True)
        else:
            st.markdown(f"### 📅 {week_label}")
    with col_next:
        if st.button("Next ▶", key=f"{key_prefix}_next"):
            st.session_state[f"{key_prefix}_ref"] = ref + datetime.timedelta(weeks=1)
            st.rerun()
    with col_today:
        if st.button("↩ Today", key=f"{key_prefix}_today", type="primary" if not is_current_week else "secondary"):
            st.session_state[f"{key_prefix}_ref"] = datetime.date.today()
            st.rerun()

    return sun, sat, dates, is_current_week


def _save_expense_rows(new_rows, current_user, date_strs):
    """Shared save logic: drop old user/week rows and concat new_rows."""
    df_current_all = load_data("expenses")
    if not df_current_all.empty:
        df_current_all["Date"] = df_current_all["Date"].astype(str)
        mask_drop = (df_current_all["User"] == current_user) & (df_current_all["Date"].isin(date_strs))
        df_current_all = df_current_all[~mask_drop]

    new_rows["User"] = current_user
    new_rows["Status"] = "Draft"
    new_rows["SubmittedAt"] = ""
    new_rows["ReviewedBy"] = ""
    new_rows["ReviewedAt"] = ""
    for col in EXPENSE_COLUMNS + EXPENSE_STATUS_COLS:
        if col not in new_rows.columns:
            new_rows[col] = ""
    df_updated = pd.concat([df_current_all, new_rows], ignore_index=True)
    save_data("expenses", df_updated)


def _render_expense_tab(current_user, sun, sat, week_dates, date_strs):
    """Expense tab content — Grid-based entry with per diem calculator."""

    # Quick lookup
    with st.expander("🔍 Quick GSA Rate Lookup", expanded=False):
        cache_info = get_cache_info()
        has_cache = cache_info is not None
        if has_cache:
            qs = st.text_input("Search", placeholder="e.g. 07097, San Francisco...", key="exp_qs")
            if qs:
                res = search_rates(qs)
                mc = MONTH_MAP[datetime.datetime.now().month]
                if not res.empty:
                    dc = []
                    if "ZIP" in res.columns: dc.append("ZIP")
                    dc += ["Name", "County", "State", "Meals"]
                    if mc in res.columns: dc.append(mc)
                    disp = res[[c for c in dc if c in res.columns]].copy()
                    if mc in disp.columns:
                        disp = disp.rename(columns={mc: f"Lodging ({mc})"})
                    st.dataframe(disp, use_container_width=True, height=min(250, 40 + len(disp)*35))
                else:
                    st.info(f"No results for '{qs}'.")
        else:
            st.info("Load GSA rates from sidebar first.")

    # -------------------------------------------------------
    #  LOAD DATA
    # -------------------------------------------------------
    df_exp_all = load_data("expenses")
    if not df_exp_all.empty:
        df_exp_all["Date"] = df_exp_all["Date"].astype(str)
        mask = (df_exp_all["User"] == current_user) & (df_exp_all["Date"].isin(date_strs))
        df_week_exp = df_exp_all[mask].copy()
    else:
        df_week_exp = pd.DataFrame(columns=EXPENSE_COLUMNS + EXPENSE_STATUS_COLS)
        mask = []

    # --- Week Status ---
    exp_statuses = df_week_exp["Status"].unique().tolist() if not df_week_exp.empty else []
    exp_locked = False

    if "Submitted" in exp_statuses:
        st.markdown("""<div style="display:flex; align-items:center; gap:12px; padding:10px 18px; background:rgba(21,101,192,0.06); border-left:4px solid #1565C0; border-radius:6px; margin:8px 0;">
            <span class="status-submitted">SUBMITTED</span>
            <span style='font-size:0.88rem; color:#37474F;'>Awaiting admin approval — expenses are <b>read-only</b>.</span>
        </div>""", unsafe_allow_html=True)
        exp_locked = True
    elif "Approved" in exp_statuses:
        st.markdown("""<div style="display:flex; align-items:center; gap:12px; padding:10px 18px; background:rgba(46,125,50,0.06); border-left:4px solid #2E7D32; border-radius:6px; margin:8px 0;">
            <span class="status-approved">APPROVED</span>
            <span style='font-size:0.88rem; color:#37474F;'>This week's expenses have been approved.</span>
        </div>""", unsafe_allow_html=True)
        exp_locked = True
    elif "Denied" in exp_statuses:
        st.warning("🔄 **Status: Denied** — Please revise and resubmit.")
        df_exp_all.loc[
            (df_exp_all["User"] == current_user) &
            (df_exp_all["Date"].isin(date_strs)) &
            (df_exp_all["Status"] == "Denied"),
            "Status"
        ] = "Draft"
        save_data("expenses", df_exp_all)
        st.rerun()
    else:
        st.caption("📝 **Status: Draft** — Edit expenses below.")

    # -------------------------------------------------------
    #  GRID EDITOR
    # -------------------------------------------------------
    st.markdown("### 📋 Expense Grid")

    # All projects & tasks for select options
    all_projects = get_all_project_names()
    # Build a flat list of all tasks across all projects
    all_tasks_flat = []
    for p in all_projects:
        all_tasks_flat.extend(get_tasks_for_project(p))
    all_tasks_flat = sorted(set(all_tasks_flat)) if all_tasks_flat else ["General"]

    grid_schema = [
        "Date", "Category", "Amount", "Project", "Task",
        "DayType", "BreakfastProvided", "LunchProvided", "DinnerProvided",
        "Details", "Notes", "PaidBy", "Reimbursable", "Receipt"
    ]

    # Ensure all grid cols exist
    for col in grid_schema:
        if col not in df_week_exp.columns:
            if col in ("BreakfastProvided", "LunchProvided", "DinnerProvided"):
                df_week_exp[col] = False
            elif col == "Reimbursable":
                df_week_exp[col] = True
            else:
                df_week_exp[col] = ""

    # Fix data types
    text_cols = ["Task", "Details", "Notes", "Receipt", "Category", "Project", "PaidBy", "DayType"]
    for c in text_cols:
        if c in df_week_exp.columns:
            df_week_exp[c] = df_week_exp[c].fillna("").astype(str)
    for bc in ["BreakfastProvided", "LunchProvided", "DinnerProvided"]:
        if bc in df_week_exp.columns:
            df_week_exp[bc] = df_week_exp[bc].fillna(False).astype(bool)
    if "Reimbursable" in df_week_exp.columns:
        df_week_exp["Reimbursable"] = df_week_exp["Reimbursable"].fillna(True).astype(bool)

    # Convert Date to actual date type for DateColumn compatibility
    df_week_exp["Date"] = pd.to_datetime(df_week_exp["Date"], errors="coerce").dt.date
    df_week_exp = df_week_exp.sort_values("Date")

    # Column configurations
    column_config = {
        "Date": st.column_config.DateColumn(
            "Date",
            min_value=week_dates[0],
            max_value=week_dates[-1],
            format="YYYY-MM-DD",
            required=True
        ),
        "Category": st.column_config.SelectboxColumn(
            "Category",
            options=["Auto (Mileage)", "Auto (Gas/Tolls/Parking)", "Meals (Per Diem)", "Lodging", "Airfare", "Other"],
            required=True
        ),
        "Amount": st.column_config.NumberColumn(
            "Amount ($)",
            min_value=0.0,
            format="$%.2f",
            required=True
        ),
        "Project": st.column_config.SelectboxColumn(
            "Project",
            options=all_projects,
            required=True
        ),
        "Task": st.column_config.SelectboxColumn(
            "Task",
            options=all_tasks_flat,
            required=True
        ),
        "DayType": st.column_config.SelectboxColumn(
            "Day Type",
            options=["Full Day", "First Day", "Last Day"],
            default="Full Day",
            help="First/Last day of travel = 75% M&IE rate"
        ),
        "BreakfastProvided": st.column_config.CheckboxColumn(
            "🍳 Bkft",
            help="Breakfast was provided",
            default=False
        ),
        "LunchProvided": st.column_config.CheckboxColumn(
            "🥪 Lunch",
            help="Lunch was provided",
            default=False
        ),
        "DinnerProvided": st.column_config.CheckboxColumn(
            "🍽️ Dinner",
            help="Dinner was provided",
            default=False
        ),
        "Details": st.column_config.TextColumn("Details (Loc/Desc)", width="medium"),
        "Notes": st.column_config.TextColumn("Notes", width="small"),
        "PaidBy": st.column_config.SelectboxColumn(
            "Paid By",
            options=["Employee", "Company"],
            default="Employee",
            required=True
        ),
        "Reimbursable": st.column_config.CheckboxColumn(
            "Reimb?",
            default=True
        ),
        "Receipt": st.column_config.TextColumn(
            "Receipt File",
            disabled=True,
            help="Upload receipt below"
        )
    }

    if exp_locked:
        st.dataframe(
            df_week_exp[grid_schema],
            column_config=column_config,
            use_container_width=True,
            hide_index=True
        )
    else:
        # EDITABLE GRID
        edited_df = st.data_editor(
            df_week_exp[grid_schema],
            column_config=column_config,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key="expense_grid"
        )

        st.caption("💡 Changes in the grid are temporary until you click Save. For Meals (Per Diem), use the calculator below to auto-compute your amount.")

        col_save, col_receipt = st.columns([1, 2])

        with col_save:
            if st.button("💾 Save Grid Changes", type="primary"):
                _save_expense_rows(edited_df.copy(), current_user, date_strs)
                st.success("✅ Expenses Saved!")
                st.rerun()

        # RECEIPT UPLOAD
        with col_receipt:
            with st.expander("📎 Attach Receipt to Row"):
                if not edited_df.empty:
                    edited_df_display = edited_df.reset_index(drop=True)

                    def _fmt_row(idx):
                        r = edited_df_display.iloc[idx]
                        return f"Row {idx+1}: {r['Date']} - ${r['Amount']} - {r['Category']}"

                    row_idx = st.selectbox(
                        "Select Expense Row",
                        range(len(edited_df_display)),
                        format_func=_fmt_row
                    )

                    uploaded_file = st.file_uploader("Choose File", type=["pdf", "jpg", "png"], key="grid_receipt")

                    if uploaded_file and st.button("Attach & Save"):
                        date_str = str(edited_df_display.iloc[row_idx]["Date"])
                        fname = save_receipt(uploaded_file, current_user, date_str)
                        edited_df.iloc[row_idx, edited_df.columns.get_loc("Receipt")] = fname
                        _save_expense_rows(edited_df.copy(), current_user, date_strs)
                        st.success(f"📎 Attached {fname}!")
                        st.rerun()
                else:
                    st.info("Add rows to the grid first.")

    # -------------------------------------------------------
    #  GSA AUTO-FILL: MEALS & LODGING
    # -------------------------------------------------------
    st.divider()
    st.markdown("### 🏛️ GSA Per Diem Auto-Fill")
    st.caption("Auto-populate expense amounts from GSA rates. Select a location to get started.")

    # --- Shared location lookup ---
    gsa_loc_col1, gsa_loc_col2 = st.columns([2, 1])
    with gsa_loc_col1:
        gsa_location = st.text_input(
            "📍 Location / ZIP Code",
            key="gsa_autofill_loc",
            placeholder="e.g. 07097, San Francisco, Fairfax..."
        )
    with gsa_loc_col2:
        gsa_travel_date = st.selectbox(
            "📅 Travel Date",
            options=week_dates,
            format_func=lambda d: f"{DAY_LABELS[week_dates.index(d)]} {d.strftime('%m/%d/%Y')}",
            key="gsa_travel_date"
        )

    # --- Look up rates based on location ---
    _gsa_mie_rate = STANDARD_MEALS
    _gsa_lodging_rate = STANDARD_LODGING
    _gsa_rate_source = "Standard CONUS"
    _gsa_found = False

    if gsa_location:
        loc_str = gsa_location.strip()
        if loc_str.isdigit() and len(loc_str) <= 5:
            rate_info = lookup_zip(loc_str)
            if rate_info:
                _gsa_mie_rate = rate_info["meals"]
                # Get lodging for the travel date's month
                _month_key = MONTH_MAP[gsa_travel_date.month]
                _gsa_lodging_rate = rate_info["lodging"].get(_month_key, STANDARD_LODGING)
                _gsa_rate_source = f"{rate_info['name']}, {rate_info['state']}"
                _gsa_found = True
        else:
            res = search_rates(loc_str)
            if not res.empty and "Meals" in res.columns:
                _gsa_mie_rate = int(res.iloc[0]["Meals"])
                _month_key = MONTH_MAP[gsa_travel_date.month]
                _gsa_lodging_rate = int(res.iloc[0].get(_month_key, STANDARD_LODGING))
                _gsa_rate_source = str(res.iloc[0].get("Name", loc_str))
                _gsa_found = True

    # Show rate source
    if _gsa_found:
        st.markdown(f"""<div style='background:rgba(0,131,143,0.06); border-left:4px solid #00838F;
             padding:10px 16px; border-radius:6px; margin:0.5rem 0; font-size:0.85rem;'>
            📍 <b>{_gsa_rate_source}</b> — M&IE: <b>${_gsa_mie_rate}</b> / Lodging: <b>${_gsa_lodging_rate}</b> ({MONTH_MAP[gsa_travel_date.month]})
        </div>""", unsafe_allow_html=True)
    elif gsa_location:
        st.caption(f"ℹ️ Using standard CONUS rates: M&IE ${_gsa_mie_rate} / Lodging ${_gsa_lodging_rate}")

    # --- Two column layout: Meals | Lodging ---
    meals_col, lodging_col = st.columns(2)

    # ===== MEALS PER DIEM =====
    with meals_col:
        with st.expander("🍽️ **Meals Per Diem Calculator**", expanded=not exp_locked):
            st.markdown("""
            <div style='background:#f0f7ff; border-left:4px solid #00838F; padding:10px 14px;
                 border-radius:6px; margin-bottom:0.75rem; font-size:0.82rem;'>
                <b>GSA Rules:</b> First/Last day = 75% of M&IE. Provided meals are deducted at the GSA rate.
            </div>
            """, unsafe_allow_html=True)

            pd_project = st.selectbox("📁 Project", options=all_projects, key="pd_project")
            pd_tasks = get_tasks_for_project(pd_project) if pd_project else ["General"]
            pd_task = st.selectbox("📌 Task", options=pd_tasks, key="pd_task")

            pd_day_type = st.radio(
                "🗓️ Day Type",
                options=["Full Day", "First Day", "Last Day"],
                horizontal=True,
                key="pd_day_type",
                help="First/Last day of travel = 75% of M&IE rate per GSA rules"
            )

            st.markdown("**Meals Provided** *(deducted from per diem)*")
            mp1, mp2, mp3 = st.columns(3)
            with mp1:
                pd_breakfast = st.checkbox("🍳 Breakfast", key="pd_breakfast")
            with mp2:
                pd_lunch = st.checkbox("🥪 Lunch", key="pd_lunch")
            with mp3:
                pd_dinner = st.checkbox("🍽️ Dinner", key="pd_dinner")

            pd_paidby = st.selectbox("💳 Paid By", ["Employee", "Company"], key="pd_paidby")

            # --- Calculate ---
            is_fl = pd_day_type in ("First Day", "Last Day")
            allowance = calc_daily_meal_allowance(
                _gsa_mie_rate,
                is_first_or_last_day=is_fl,
                breakfast_provided=pd_breakfast,
                lunch_provided=pd_lunch,
                dinner_provided=pd_dinner
            )
            breakdown = get_mie_breakdown(_gsa_mie_rate)

            # --- Detailed Breakdown Display ---
            st.markdown("---")
            st.markdown("#### 💰 Calculation Breakdown")

            # Line-by-line breakdown
            lines = []
            lines.append(("M&IE Base Rate", f"${_gsa_mie_rate:.2f}", "neutral"))

            if is_fl:
                pct_reduction = _gsa_mie_rate - breakdown["first_last_day"]
                lines.append((f"↳ {pd_day_type} (75% rule)", f"-${pct_reduction:.2f}", "deduction"))
                lines.append(("Adjusted Base", f"${breakdown['first_last_day']:.2f}", "neutral"))

            if pd_breakfast:
                lines.append(("↳ Breakfast provided", f"-${breakdown['breakfast']:.2f}", "deduction"))
            if pd_lunch:
                lines.append(("↳ Lunch provided", f"-${breakdown['lunch']:.2f}", "deduction"))
            if pd_dinner:
                lines.append(("↳ Dinner provided", f"-${breakdown['dinner']:.2f}", "deduction"))

            # Render the breakdown table
            for label, amount, style in lines:
                if style == "deduction":
                    st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:4px 12px;
                         background:rgba(198,40,40,0.04); border-radius:4px; margin:2px 0; font-size:0.85rem;'>
                        <span style='color:#C62828;'>{label}</span>
                        <span style='color:#C62828; font-weight:600;'>{amount}</span>
                    </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:4px 12px;
                         font-size:0.85rem; margin:2px 0;'>
                        <span>{label}</span>
                        <span style='font-weight:500;'>{amount}</span>
                    </div>""", unsafe_allow_html=True)

            # Final amount
            total_deductions = allowance["deductions"] + (_gsa_mie_rate - breakdown["first_last_day"] if is_fl else 0)
            st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:8px 12px;
                 background:rgba(0,131,143,0.08); border:1px solid rgba(0,131,143,0.2);
                 border-radius:6px; margin-top:8px; font-size:0.95rem;'>
                <span style='font-weight:700; color:#00838F;'>✅ Claimable Amount</span>
                <span style='font-weight:700; color:#00838F; font-size:1.1rem;'>${allowance['final']:.2f}</span>
            </div>""", unsafe_allow_html=True)

            if total_deductions > 0:
                st.caption(f"💡 Total savings/deductions: -${total_deductions:.2f} from ${_gsa_mie_rate} base rate")

            # --- Add button ---
            if not exp_locked:
                st.markdown("")
                if st.button("➕ Add Per Diem to Expense Grid", type="primary", key="add_perdiem"):
                    new_entry = {
                        "Date": gsa_travel_date.isoformat(),
                        "Category": "Meals (Per Diem)",
                        "Amount": allowance["final"],
                        "Project": pd_project,
                        "Task": pd_task,
                        "DayType": pd_day_type,
                        "BreakfastProvided": pd_breakfast,
                        "LunchProvided": pd_lunch,
                        "DinnerProvided": pd_dinner,
                        "Details": f"{_gsa_rate_source} (M&IE ${_gsa_mie_rate})",
                        "Notes": "",
                        "PaidBy": pd_paidby,
                        "Reimbursable": True,
                        "Receipt": "",
                        "MIE_Rate": _gsa_mie_rate,
                        "GSA_Limit": _gsa_mie_rate,
                        "User": current_user,
                        "Status": "Draft",
                        "SubmittedAt": "",
                        "ReviewedBy": "",
                        "ReviewedAt": "",
                    }
                    df_all = load_data("expenses")
                    if not df_all.empty:
                        df_all["Date"] = df_all["Date"].astype(str)
                    new_row_df = pd.DataFrame([new_entry])
                    for col in EXPENSE_COLUMNS + EXPENSE_STATUS_COLS:
                        if col not in new_row_df.columns:
                            new_row_df[col] = ""
                    df_all = pd.concat([df_all, new_row_df], ignore_index=True)
                    save_data("expenses", df_all)
                    st.success(f"✅ Added ${allowance['final']:.2f} per diem for {gsa_travel_date.strftime('%a %m/%d')}")
                    st.rerun()

    # ===== LODGING AUTO-FILL =====
    with lodging_col:
        with st.expander("🏨 **Lodging Rate Lookup**", expanded=not exp_locked):
            st.markdown(f"""
            <div style='background:#f0f7ff; border-left:4px solid #1565C0; padding:10px 14px;
                 border-radius:6px; margin-bottom:0.75rem; font-size:0.82rem;'>
                <b>GSA lodging rate = room only</b> (taxes excluded).<br>
                Taxes/fees on top of the room rate are reimbursable <b>with a receipt</b>.
            </div>
            """, unsafe_allow_html=True)

            ldg_project = st.selectbox("📁 Project", options=all_projects, key="ldg_project")
            ldg_tasks = get_tasks_for_project(ldg_project) if ldg_project else ["General"]
            ldg_task = st.selectbox("📌 Task", options=ldg_tasks, key="ldg_task")

            # Show the GSA max rate
            st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:8px 12px;
                 background:rgba(21,101,192,0.06); border:1px solid rgba(21,101,192,0.15);
                 border-radius:6px; margin:0.5rem 0;'>
                <span style='font-weight:600; color:#1565C0;'>🏨 GSA Max Nightly Rate ({MONTH_MAP[gsa_travel_date.month]})</span>
                <span style='font-weight:700; color:#1565C0; font-size:1.05rem;'>${_gsa_lodging_rate}</span>
            </div>""", unsafe_allow_html=True)

            # Room rate
            ldg_room = st.number_input(
                "Room Rate per Night ($)",
                value=float(_gsa_lodging_rate),
                min_value=0.0,
                step=1.0,
                key="ldg_room",
                help="The nightly room rate before taxes/fees."
            )

            # Taxes & Fees
            ldg_taxes = st.number_input(
                "Taxes & Fees ($)",
                value=0.0,
                min_value=0.0,
                step=0.01,
                key="ldg_taxes",
                help="Hotel taxes, resort fees, etc. Reimbursable with receipt."
            )

            ldg_paidby = st.selectbox("💳 Paid By", ["Employee", "Company"], key="ldg_paidby")

            # --- Receipt Upload ---
            ldg_receipt = st.file_uploader(
                "📎 Hotel Receipt (required for tax reimbursement)",
                type=["pdf", "png", "jpg", "jpeg"],
                key="ldg_receipt",
                help="Upload hotel folio/receipt to substantiate taxes & fees."
            )

            # --- Calculation logic ---
            ldg_total = ldg_room + ldg_taxes
            room_within_gsa = ldg_room <= _gsa_lodging_rate
            has_receipt = ldg_receipt is not None

            # Determine reimbursable amount
            if room_within_gsa:
                # Room ≤ GSA: full amount (room + taxes) reimbursable WITH receipt
                if ldg_taxes > 0 and has_receipt:
                    reimbursable_lodging = ldg_total
                    flag_status = "ok_with_taxes"
                elif ldg_taxes > 0 and not has_receipt:
                    reimbursable_lodging = ldg_room  # Can't reimburse taxes without receipt
                    flag_status = "needs_receipt"
                else:
                    reimbursable_lodging = ldg_room
                    flag_status = "ok"
            else:
                # Room > GSA: cap room at GSA, taxes still reimbursable with receipt
                if has_receipt:
                    reimbursable_lodging = float(_gsa_lodging_rate) + ldg_taxes
                    flag_status = "room_over_gsa"
                else:
                    reimbursable_lodging = float(_gsa_lodging_rate)
                    flag_status = "room_over_no_receipt"

            # --- Breakdown Display ---
            st.markdown("---")
            st.markdown("#### 🧾 Cost Breakdown")

            breakdown_lines = [
                ("Room Rate", f"${ldg_room:.2f}", "neutral"),
            ]
            if ldg_taxes > 0:
                breakdown_lines.append(("Taxes & Fees", f"${ldg_taxes:.2f}", "neutral"))
                breakdown_lines.append(("Total Hotel Bill", f"${ldg_total:.2f}", "neutral"))

            if not room_within_gsa:
                over_amt = ldg_room - _gsa_lodging_rate
                breakdown_lines.append((f"↳ Room over GSA limit", f"-${over_amt:.2f}", "deduction"))
                breakdown_lines.append(("Capped room rate", f"${_gsa_lodging_rate:.2f}", "neutral"))

            for label, amount, style in breakdown_lines:
                if style == "deduction":
                    st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:4px 12px;
                         background:rgba(198,40,40,0.04); border-radius:4px; margin:2px 0; font-size:0.85rem;'>
                        <span style='color:#C62828;'>{label}</span>
                        <span style='color:#C62828; font-weight:600;'>{amount}</span>
                    </div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:4px 12px;
                         font-size:0.85rem; margin:2px 0;'>
                        <span>{label}</span>
                        <span style='font-weight:500;'>{amount}</span>
                    </div>""", unsafe_allow_html=True)

            # Status messages
            if flag_status == "needs_receipt":
                st.markdown(f"""<div style='background:rgba(230,81,0,0.06); border-left:4px solid #E65100;
                     padding:8px 14px; border-radius:6px; font-size:0.84rem; margin:0.5rem 0;'>
                    ⚠️ <b>Receipt required</b> to reimburse ${ldg_taxes:.2f} in taxes/fees.
                    Without receipt, only the room rate (${ldg_room:.2f}) is reimbursable.
                </div>""", unsafe_allow_html=True)
            elif flag_status == "room_over_gsa":
                st.markdown(f"""<div style='background:rgba(230,81,0,0.06); border-left:4px solid #E65100;
                     padding:8px 14px; border-radius:6px; font-size:0.84rem; margin:0.5rem 0;'>
                    ⚠️ Room rate exceeds GSA limit. Capped at <b>${_gsa_lodging_rate}</b> + taxes.
                </div>""", unsafe_allow_html=True)
            elif flag_status == "room_over_no_receipt":
                st.markdown(f"""<div style='background:rgba(198,40,40,0.06); border-left:4px solid #C62828;
                     padding:8px 14px; border-radius:6px; font-size:0.84rem; margin:0.5rem 0;'>
                    🚫 Room over GSA limit & no receipt. Capped at <b>${_gsa_lodging_rate}</b>.
                    Upload a receipt to include taxes for reimbursement.
                </div>""", unsafe_allow_html=True)
            elif flag_status == "ok_with_taxes" and has_receipt:
                st.markdown(f"""<div style='background:rgba(46,125,50,0.06); border-left:4px solid #2E7D32;
                     padding:8px 14px; border-radius:6px; font-size:0.84rem; margin:0.5rem 0;'>
                    ✅ Room within GSA limit + receipt attached. Full amount reimbursable.
                </div>""", unsafe_allow_html=True)

            # Final reimbursable amount
            st.markdown(f"""<div style='display:flex; justify-content:space-between; padding:8px 12px;
                 background:rgba(0,131,143,0.08); border:1px solid rgba(0,131,143,0.2);
                 border-radius:6px; margin-top:8px; font-size:0.95rem;'>
                <span style='font-weight:700; color:#00838F;'>✅ Reimbursable Amount</span>
                <span style='font-weight:700; color:#00838F; font-size:1.1rem;'>${reimbursable_lodging:.2f}</span>
            </div>""", unsafe_allow_html=True)

            if ldg_total > reimbursable_lodging:
                out_of_pocket = ldg_total - reimbursable_lodging
                st.caption(f"💡 Employee out-of-pocket: ${out_of_pocket:.2f}")

            # --- Add button ---
            if not exp_locked:
                st.markdown("")
                if st.button("➕ Add Lodging to Expense Grid", type="primary", key="add_lodging"):
                    # Save receipt if uploaded
                    receipt_filename = ""
                    if ldg_receipt:
                        receipt_filename = save_receipt(ldg_receipt, current_user, gsa_travel_date.isoformat())

                    # Build notes
                    notes_parts = []
                    if ldg_room != reimbursable_lodging - ldg_taxes:
                        notes_parts.append(f"Actual room: ${ldg_room:.2f}")
                    if ldg_taxes > 0:
                        notes_parts.append(f"Taxes/fees: ${ldg_taxes:.2f}")
                    if not room_within_gsa:
                        notes_parts.append(f"Room capped at GSA ${_gsa_lodging_rate}")

                    new_entry = {
                        "Date": gsa_travel_date.isoformat(),
                        "Category": "Lodging",
                        "Amount": reimbursable_lodging,
                        "Project": ldg_project,
                        "Task": ldg_task,
                        "DayType": "Full Day",
                        "BreakfastProvided": False,
                        "LunchProvided": False,
                        "DinnerProvided": False,
                        "Details": f"{_gsa_rate_source} (GSA max ${_gsa_lodging_rate})",
                        "Notes": " | ".join(notes_parts) if notes_parts else "",
                        "PaidBy": ldg_paidby,
                        "Reimbursable": True,
                        "Receipt": receipt_filename,
                        "GSA_Limit": _gsa_lodging_rate,
                        "User": current_user,
                        "Status": "Draft",
                        "SubmittedAt": "",
                        "ReviewedBy": "",
                        "ReviewedAt": "",
                    }
                    df_all = load_data("expenses")
                    if not df_all.empty:
                        df_all["Date"] = df_all["Date"].astype(str)
                    new_row_df = pd.DataFrame([new_entry])
                    for col in EXPENSE_COLUMNS + EXPENSE_STATUS_COLS:
                        if col not in new_row_df.columns:
                            new_row_df[col] = ""
                    df_all = pd.concat([df_all, new_row_df], ignore_index=True)
                    save_data("expenses", df_all)
                    st.success(f"✅ Added ${reimbursable_lodging:.2f} lodging for {gsa_travel_date.strftime('%a %m/%d')}" +
                              (f" (receipt attached)" if receipt_filename else ""))
                    st.rerun()

    # -------------------------------------------------------
    #  SUBMIT (Bulk)
    # -------------------------------------------------------
    st.divider()
    week_total = df_week_exp["Amount"].astype(float).sum()
    st.metric("💰 Week Total", f"${week_total:,.2f}")

    if not exp_locked and not df_week_exp.empty:
        if st.button("📤 Submit Expenses for Approval", type="primary"):
            df_all = load_data("expenses")
            if not df_all.empty:
                df_all["Date"] = df_all["Date"].astype(str)
            df_all, ok, msg = submit_expense_week(df_all, current_user, sun.isoformat())
            if ok:
                save_data("expenses", df_all)
                st.success(f"✅ {msg}")
                st.rerun()
            else:
                st.info(msg)
# ============================================================
#  MODULE 1: WEEKLY TIME & EXPENSES (combined)
# ============================================================
with tabs_dict["Weekly Time & Expenses"]:

    st.header("📋 Weekly Time & Expenses")

    sun, sat, week_dates, is_current = week_picker("we")

    if is_current:
        st.markdown("""<div style='background:rgba(0,131,143,0.08); border:1px solid rgba(0,131,143,0.2); border-radius:8px; padding:8px 16px; display:inline-block;'>
            <span style='color:#00838F; font-weight:700; font-size:0.82rem;'>📗 Current Week</span>
        </div>""", unsafe_allow_html=True)

    date_strs = [d.isoformat() for d in week_dates]

    # --- Combined Tabs ---
    we_tab_time, we_tab_exp, we_tab_summary = st.tabs(["✏️ Timesheet", "💳 Expenses", "📊 Summary"])

    # ====== TIMESHEET TAB ======
    with we_tab_time:

        # Load data
        df_all = load_data("time")
        if not df_all.empty:
            df_all["Date"] = df_all["Date"].astype(str)
            df_week = df_all[(df_all["User"] == current_user) & (df_all["Date"].isin(date_strs))]
        else:
            df_week = pd.DataFrame(columns=["User", "Date", "Project", "Task", "Hours", "Notes"] + TIMESHEET_STATUS_COLS)

        # --- Week Status Badge ---
        week_statuses = df_week["Status"].unique().tolist() if not df_week.empty else []
        if "Submitted" in week_statuses:
            st.markdown("""<div style="display:flex; align-items:center; gap:12px; padding:10px 18px; background:rgba(21,101,192,0.06); border-left:4px solid #1565C0; border-radius:6px; margin:8px 0;">
            <span class="status-submitted">SUBMITTED</span>
            <span style='font-size:0.88rem; color:#37474F;'>Awaiting admin approval — entries are <b>read-only</b>.</span>
        </div>""", unsafe_allow_html=True)
            week_locked = True
        elif "Approved" in week_statuses:
            st.markdown("""<div style="display:flex; align-items:center; gap:12px; padding:10px 18px; background:rgba(46,125,50,0.06); border-left:4px solid #2E7D32; border-radius:6px; margin:8px 0;">
            <span class="status-approved">APPROVED</span>
            <span style='font-size:0.88rem; color:#37474F;'>This week has been approved.</span>
        </div>""", unsafe_allow_html=True)
            week_locked = True
        elif "Denied" in week_statuses:
            st.warning("🔄 **Status: Denied** — Please revise and resubmit.")
            df_all.loc[
                (df_all["User"] == current_user) &
                (df_all["Date"].isin(date_strs)) &
                (df_all["Status"] == "Denied"),
                "Status"
            ] = "Draft"
            save_data("time", df_all)
            df_all = load_data("time")
            df_all["Date"] = df_all["Date"].astype(str)
            df_week = df_all[(df_all["User"] == current_user) & (df_all["Date"].isin(date_strs))]
            week_locked = False
        else:
            st.caption("📝 **Status: Draft**")
            week_locked = False

        # Get existing project-task combos for this week
        existing_combos = []
        if not df_week.empty:
            existing_combos = df_week[["Project", "Task"]].drop_duplicates().values.tolist()

        # -------------------------------------------------------
        #  EXISTING TIME ENTRIES — editable rows with delete
        # -------------------------------------------------------
        if existing_combos:
            st.markdown("##### 📋 Current Entries")
            if not week_locked:
                st.caption("Edit hours inline or delete rows.")

            delete_combos = []
            for combo_idx, (combo_proj, combo_task) in enumerate(existing_combos):
                with st.container(border=True):
                    label_col, *edit_cols_list = st.columns([3] + [1]*7 + [1])
                    edit_cols = [label_col] + edit_cols_list
                    with edit_cols[0]:
                        st.markdown(f"**{combo_proj}**")
                        st.caption(combo_task)
                        if not week_locked:
                            if st.button("🗑️", key=f"del_{combo_idx}"):
                                delete_combos.append((combo_proj, combo_task))

                    for i in range(7):
                        with edit_cols[i+1]:
                            existing_val = 0.0
                            if not df_week.empty:
                                match = df_week[
                                    (df_week["Project"] == combo_proj) &
                                    (df_week["Task"] == combo_task) &
                                    (df_week["Date"] == date_strs[i])
                                ]
                                if not match.empty:
                                    existing_val = float(match["Hours"].sum())

                            if week_locked:
                                st.text_input(
                                    f"{DAY_LABELS[i]} {week_dates[i].strftime('%m/%d')}",
                                    value=f"{existing_val:.1f}",
                                    disabled=True,
                                    key=f"edit_{combo_idx}_{i}"
                                )
                            else:
                                st.number_input(
                                    f"{DAY_LABELS[i]} {week_dates[i].strftime('%m/%d')}",
                                    min_value=0.0, max_value=24.0, step=0.5,
                                    value=existing_val,
                                    key=f"edit_{combo_idx}_{i}"
                                )
                    with edit_cols[8]:
                        if week_locked:
                            row_total = sum(
                                float(df_week[
                                    (df_week["Project"] == combo_proj) &
                                    (df_week["Task"] == combo_task) &
                                    (df_week["Date"] == date_strs[i])
                                ]["Hours"].sum()) for i in range(7)
                            )
                        else:
                            row_total = sum(
                                st.session_state.get(f"edit_{combo_idx}_{i}", 0.0) for i in range(7)
                            )
                        st.metric("Total", f"{row_total:.1f}")

            if not week_locked:
                if delete_combos:
                    df_all = load_data("time")
                    if not df_all.empty:
                        df_all["Date"] = df_all["Date"].astype(str)
                    for dp, dt in delete_combos:
                        mask = (
                            (df_all["User"] == current_user) &
                            (df_all["Date"].isin(date_strs)) &
                            (df_all["Project"] == dp) &
                            (df_all["Task"] == dt)
                        )
                        df_all = df_all[~mask]
                    save_data("time", df_all)
                    st.success(f"🗑️ Deleted {len(delete_combos)} row(s)")
                    st.rerun()

                if st.button("💾 Save All Changes", key="ts_save_all", type="primary"):
                    df_all = load_data("time")
                    if not df_all.empty:
                        df_all["Date"] = df_all["Date"].astype(str)

                    for combo_idx, (combo_proj, combo_task) in enumerate(existing_combos):
                        for i, d in enumerate(week_dates):
                            d_str = d.isoformat()
                            new_val = st.session_state.get(f"edit_{combo_idx}_{i}", 0.0)

                            if not df_all.empty:
                                mask = (
                                    (df_all["User"] == current_user) &
                                    (df_all["Date"] == d_str) &
                                    (df_all["Project"] == combo_proj) &
                                    (df_all["Task"] == combo_task)
                                )
                                df_all = df_all[~mask]

                            if new_val > 0:
                                new_row = pd.DataFrame([{
                                    "User": current_user,
                                    "Date": d_str,
                                    "Project": combo_proj,
                                    "Task": combo_task,
                                    "Hours": new_val,
                                    "Notes": "",
                                    "Status": "Draft",
                                    "SubmittedAt": "",
                                    "ReviewedBy": "",
                                    "ReviewedAt": "",
                                }])
                                df_all = pd.concat([df_all, new_row], ignore_index=True)

                    save_data("time", df_all)
                    st.success("✅ All changes saved!")
                    st.rerun()

            st.divider()

        # -------------------------------------------------------
        #  ADD NEW PROJECT-TASK ROW (only if not locked)
        # -------------------------------------------------------
        if not week_locked:
            st.markdown("##### ➕ Add New Project/Task")
            add_col1, add_col2 = st.columns(2)
            with add_col1:
                _projects = load_projects()
                proj = st.selectbox("Project", list(_projects.keys()), key="ts_proj")
            with add_col2:
                task = st.selectbox("Task", _projects.get(proj, []), key="ts_task")

            combo_exists = [proj, task] in existing_combos if existing_combos else False

            if combo_exists:
                st.info("☝️ This project/task is already above — edit it there.")
            else:
                st.markdown(f"##### Hours for: {proj} — {task}")
                new_cols = st.columns(8)
                new_hours = []
                for i in range(7):
                    with new_cols[i]:
                        h = st.number_input(
                            f"{DAY_LABELS[i]} {week_dates[i].strftime('%m/%d')}",
                            min_value=0.0, max_value=24.0, step=0.5,
                            value=0.0,
                            key=f"ts_new_{i}"
                        )
                        new_hours.append(h)
                with new_cols[7]:
                    total = sum(new_hours)
                    st.metric("Total", f"{total:.1f}")

                notes = st.text_input("Notes (optional)", key="ts_notes")

                if st.button("💾 Add & Save", key="ts_add_save", type="primary"):
                    if sum(new_hours) > 0:
                        df_all = load_data("time")
                        if not df_all.empty:
                            df_all["Date"] = df_all["Date"].astype(str)

                        for i, d in enumerate(week_dates):
                            if new_hours[i] > 0:
                                new_row = pd.DataFrame([{
                                    "User": current_user,
                                    "Date": d.isoformat(),
                                    "Project": proj,
                                    "Task": task,
                                    "Hours": new_hours[i],
                                    "Notes": notes,
                                    "Status": "Draft",
                                    "SubmittedAt": "",
                                    "ReviewedBy": "",
                                    "ReviewedAt": "",
                                }])
                                df_all = pd.concat([df_all, new_row], ignore_index=True)

                        save_data("time", df_all)
                        st.success("✅ Added!")
                        st.rerun()
                    else:
                        st.warning("Enter at least some hours.")

        # -------------------------------------------------------
        #  SUBMIT WEEK (only if there are Draft entries)
        # -------------------------------------------------------
        if not week_locked and existing_combos:
            st.divider()
            st.markdown("##### 📤 Submit Timesheet for Approval")
            st.caption("Once submitted, entries become read-only until reviewed by an admin.")
            if st.button("📤 Submit This Week", key="ts_submit_week", type="primary"):
                df_all = load_data("time")
                if not df_all.empty:
                    df_all["Date"] = df_all["Date"].astype(str)
                df_all, ok, msg = submit_timesheet_week(df_all, current_user, sun.isoformat())
                if ok:
                    save_data("time", df_all)
                    st.success(f"✅ {msg}")
                    st.rerun()
                else:
                    st.info(msg)

    # ====== EXPENSES TAB ======
    with we_tab_exp:

        cache_info = get_cache_info()
        has_cache = cache_info is not None
        if not has_cache:
            st.warning("⚠️ GSA rates not loaded. Click **🔄 Refresh GSA Rates** in sidebar.")

        _render_expense_tab(current_user, sun, sat, week_dates, date_strs)

    # ====== SUMMARY TAB ======
    with we_tab_summary:
        st.subheader("📊 Week Summary")

        df_all_fresh = load_data("time")
        if not df_all_fresh.empty:
            df_all_fresh["Date"] = df_all_fresh["Date"].astype(str)
            df_week_display = df_all_fresh[
                (df_all_fresh["User"] == current_user) & (df_all_fresh["Date"].isin(date_strs))
            ]

            if not df_week_display.empty:
                df_week_display["Day"] = pd.Categorical(
                    df_week_display["Date"].apply(
                        lambda x: DAY_LABELS[date_strs.index(x)] if x in date_strs else ""
                    ),
                    categories=DAY_LABELS, ordered=True
                )

                pivot = df_week_display.pivot_table(
                    values="Hours", index=["Project", "Task"], columns="Day",
                    aggfunc="sum", fill_value=0
                )
                pivot["Total"] = pivot.sum(axis=1)
                col_totals = pivot.sum(axis=0)
                col_totals.name = ("Daily Total", "")
                pivot = pd.concat([pivot, col_totals.to_frame().T])

                st.dataframe(pivot, use_container_width=True)
                week_total = df_week_display["Hours"].sum()
                st.metric("🕐 Weekly Total Hours", f"{week_total:.1f}")
            else:
                st.info("No time logged for this week.")
        else:
            st.info("No time entries yet.")

        st.divider()
        st.subheader("💳 Expense Summary")
        df_exp_summary = load_data("expenses")
        if not df_exp_summary.empty:
            df_exp_summary["Date"] = df_exp_summary["Date"].astype(str)
            df_exp_week = df_exp_summary[
                (df_exp_summary["User"] == current_user) & (df_exp_summary["Date"].isin(date_strs))
            ]
            if not df_exp_week.empty:
                by_cat = df_exp_week.groupby("Category")["Amount"].sum().reset_index()
                st.dataframe(by_cat, use_container_width=True, hide_index=True)
                exp_total = df_exp_week["Amount"].astype(float).sum()
                st.metric("💰 Week Expense Total", f"${exp_total:,.2f}")
            else:
                st.info("No expenses for this week.")
        else:
            st.info("No expense entries yet.")



# ============================================================
#  MODULE 2: GSA RATE LOOKUP
# ============================================================
with tabs_dict["GSA Rate Lookup"]:

    st.header("🔍 GSA Per Diem Rate Lookup (FY 2026)")

    cache_info = get_cache_info()

    if cache_info is None:
        st.error("⚠️ No GSA rate data. Click **🔄 Refresh GSA Rates** in the sidebar.")
    else:
        st.markdown(
            f"**{cache_info['total_locations']}** destinations • "
            f"**{cache_info['total_zips']:,}** ZIP codes • "
            f"Search by **city, county, state, or ZIP code**"
        )

        col_search, col_month = st.columns([3, 1])
        with col_search:
            search_query = st.text_input("🔎 Quick Search",
                placeholder="e.g. San Francisco, 07097, Fairfax...", key="gsa_search")
        with col_month:
            month_names_display = ["January", "February", "March", "April", "May", "June",
                                   "July", "August", "September", "October", "November", "December"]
            current_month_idx = datetime.datetime.now().month - 1
            selected_month_name = st.selectbox("Travel Month", month_names_display, index=current_month_idx)
            selected_month_num = month_names_display.index(selected_month_name) + 1
            month_col = MONTH_MAP[selected_month_num]

        if search_query:
            results = search_rates(search_query)
            if results.empty:
                st.warning(f"No results for **'{search_query}'**.")
            else:
                st.success(f"Found **{len(results)}** matching location(s)")
                display_cols = []
                if "ZIP" in results.columns:
                    display_cols.append("ZIP")
                display_cols += ["Name", "County", "State", "Meals"]
                if month_col in results.columns:
                    display_cols.append(month_col)
                display_df = results[[c for c in display_cols if c in results.columns]].copy()
                if month_col in display_df.columns:
                    display_df = display_df.rename(columns={month_col: f"Lodging ({selected_month_name})"})
                fmt = {"Meals": "${:.0f}", f"Lodging ({selected_month_name})": "${:.0f}"}
                fmt = {k: v for k, v in fmt.items() if k in display_df.columns}
                st.dataframe(display_df.style.format(fmt), use_container_width=True,
                             height=min(500, 40 + len(display_df) * 35))
        else:
            st.subheader("Browse by State")
            browse_state = st.selectbox("Select State", get_states_from_cache())
            if browse_state:
                state_results = search_rates(browse_state)
                if not state_results.empty:
                    display_cols = ["Name", "County", "Meals"]
                    if month_col in state_results.columns:
                        display_cols.append(month_col)
                    display_df = state_results[[c for c in display_cols if c in state_results.columns]].copy()
                    if month_col in display_df.columns:
                        display_df = display_df.rename(columns={month_col: f"Lodging ({selected_month_name})"})
                    fmt = {"Meals": "${:.0f}", f"Lodging ({selected_month_name})": "${:.0f}"}
                    fmt = {k: v for k, v in fmt.items() if k in display_df.columns}
                    st.dataframe(display_df.style.format(fmt), use_container_width=True,
                                 height=min(500, 40 + len(display_df) * 35))

        st.divider()
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("🚗 Mileage Rate", f"${GSA_MILEAGE_RATE}/mile")
        with c2:
            st.metric("🏨 Standard Lodging", f"${STANDARD_LODGING}")
        with c3:
            st.metric("🍽️ Standard M&IE", f"${STANDARD_MEALS}")

# ============================================================
#  MODULE 4: PTO MANAGEMENT
# ============================================================
with tabs_dict["PTO Management"]:

    st.header("🏖️ PTO Management")

    user_is_admin = is_admin(current_user)

    # PTO Balance
    balance = get_pto_balance(current_user)

    st.markdown("#### My PTO Balance")
    bc1, bc2, bc3, bc4 = st.columns(4)
    with bc1:
        st.metric("🟢 Available", f"{balance['balance']:.1f} hrs",
                  help=f"{balance['balance']/8:.1f} days")
    with bc2:
        st.metric("📈 Accrued", f"{balance['accrued']:.1f} hrs",
                  help=f"@ {balance['accrual_rate']} hrs/month")
    with bc3:
        st.metric("📅 Used", f"{balance['used']:.1f} hrs")
    with bc4:
        st.metric("🔄 Carryover", f"{balance['carryover']:.1f} hrs")

    st.divider()

    # --- Side-by-side: Request form (left) + My Requests (right) ---
    pto_left, pto_right = st.columns([1, 1])

    with pto_left:
        st.markdown("#### 📝 Request Time Off")

        pto_c1, pto_c2 = st.columns(2)
        with pto_c1:
            pto_start = st.date_input("Start Date", datetime.date.today(), key="pto_start")
            pto_end = st.date_input("End Date", datetime.date.today(), key="pto_end")
        with pto_c2:
            pto_hours = st.number_input("Hours", min_value=0.0, max_value=200.0, step=4.0, value=8.0, key="pto_hrs")
            pto_reason = st.text_input("Reason", key="pto_reason")

        if pto_end < pto_start:
            st.error("End date must be on or after start date.")
        elif pto_hours > balance["balance"]:
            st.warning(f"⚠️ Requesting {pto_hours} hrs but only {balance['balance']:.1f} hrs available.")

        if st.button("📨 Submit PTO Request", type="primary"):
            if pto_end >= pto_start and pto_hours > 0:
                success, message = submit_pto_request(current_user, pto_start, pto_end, pto_hours, pto_reason)
                if success:
                    st.success(f"✅ {message}")
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

    with pto_right:
        st.markdown("#### 📋 My Requests")
        my_reqs = get_employee_requests(current_user)
        if not my_reqs.empty:
            display_reqs = my_reqs[["RequestID", "StartDate", "EndDate", "Hours", "Status", "RequestedAt", "ReviewedBy"]].copy()
            def style_status(val):
                colors = {"Pending": "color: orange", "Approved": "color: green", "Denied": "color: red"}
                return colors.get(val, "")
            st.dataframe(display_reqs.style.map(style_status, subset=["Status"]),
                         use_container_width=True, hide_index=True)
        else:
            st.info("No PTO requests yet.")

    # ADMIN SECTION
    if user_is_admin:
        st.divider()
        st.markdown("---")
        st.markdown("## 🔐 Admin Panel")

        admin_tab1, admin_tab2, admin_tab3 = st.tabs(["Pending Approvals", "All Balances", "Manage Employees"])

        with admin_tab1:
            pending = get_pending_requests()
            if not pending.empty:
                for _, req in pending.iterrows():
                    req_balance = get_pto_balance(req["Employee"])
                    with st.container(border=True):
                        rc1, rc2, rc3 = st.columns([3, 1, 1])
                        with rc1:
                            st.markdown(
                                f"**{req['Employee']}** — {req['StartDate']} to {req['EndDate']} "
                                f"({req['Hours']} hrs)"
                            )
                            st.caption(f"Reason: {req['Reason'] or 'N/A'} | "
                                      f"Balance after: {req_balance['balance'] - req['Hours']:.1f} hrs | "
                                      f"Submitted: {req['RequestedAt'][:16]}")
                        with rc2:
                            if st.button("✅ Approve", key=f"approve_{req['RequestID']}"):
                                review_pto_request(req['RequestID'], current_user, approve=True)
                                st.success(f"Approved {req['RequestID']}")
                                st.rerun()
                        with rc3:
                            if st.button("❌ Deny", key=f"deny_{req['RequestID']}"):
                                review_pto_request(req['RequestID'], current_user, approve=False)
                                st.warning(f"Denied {req['RequestID']}")
                                st.rerun()
            else:
                st.info("No pending PTO requests. 🎉")

        with admin_tab2:
            emp_data = load_employees()
            rows = []
            for emp in emp_data["employees"]:
                bal = get_pto_balance(emp["name"])
                rows.append({
                    "Employee": emp["name"],
                    "Role": emp["role"].title(),
                    "Accrued (hrs)": bal["accrued"],
                    "Used (hrs)": bal["used"],
                    "Carryover (hrs)": bal["carryover"],
                    "Available (hrs)": bal["balance"],
                    "Available (days)": round(bal["balance"] / 8, 1),
                })
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            st.markdown("##### ↻ Adjust Carryover")
            co_emp = st.selectbox("Employee", get_all_employee_names(), key="co_emp")
            co_hrs = st.number_input("Set Carryover Hours", min_value=0.0, step=1.0, key="co_hrs")
            if st.button("Set Carryover", key="co_btn"):
                set_carryover(co_emp, co_hrs)
                st.success(f"Set {co_emp} carryover to {co_hrs} hrs")
                st.rerun()

        with admin_tab3:
            st.markdown("##### Current Employees")
            st.caption("For full employee editing & deletion, go to **Admin Dashboard → Users**.")
            emp_data = load_employees()
            for pidx, emp in enumerate(emp_data["employees"]):
                with st.expander(f"{emp['name']} — {emp['role'].title()}"):
                    pc1, pc2 = st.columns(2)
                    with pc1:
                        st.text(f"Email: {emp['email']}")
                        st.text(f"Manager: {emp.get('manager_email', 'N/A')}")
                    with pc2:
                        st.text(f"Hire Date: {emp['hire_date']}")
                        st.text(f"Accrual: {emp.get('pto_accrual_rate', DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH)} hrs/month")

                    # Quick role update
                    new_role = st.selectbox(
                        "Role", ["employee", "admin"],
                        index=0 if emp["role"] == "employee" else 1,
                        key=f"pto_role_{pidx}_{emp['name']}"
                    )
                    if new_role != emp["role"]:
                        if st.button(f"Update Role → {new_role.title()}", key=f"pto_role_btn_{pidx}"):
                            update_employee(emp["name"], {"role": new_role})
                            st.success(f"Updated {emp['name']} to {new_role}")
                            st.rerun()

                    # Delete (with confirmation)
                    if emp["name"].lower() != current_user.lower():
                        if st.checkbox("Confirm delete", key=f"pto_del_confirm_{pidx}"):
                            if st.button(f"🗑️ Delete {emp['name']}", key=f"pto_del_btn_{pidx}", type="primary"):
                                delete_employee(emp["name"])
                                st.success(f"Deleted {emp['name']}")
                                st.rerun()

            st.markdown("##### ➕ Add Employee")
            with st.form("add_emp_form"):
                ne_name = st.text_input("Full Name")
                ne_email = st.text_input("Email")
                ne_role = st.selectbox("Role", ["employee", "admin"])
                ne_mgr = st.text_input("Manager Email")
                ne_hire = st.date_input("Hire Date", datetime.date.today())
                ne_rate = st.number_input("PTO Accrual (hrs/month)", value=float(DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH), step=1.0)

                if st.form_submit_button("Add Employee"):
                    if ne_name:
                        ok = add_employee(ne_name, ne_email, ne_role, ne_mgr, ne_hire, ne_rate)
                        if ok:
                            st.success(f"Added {ne_name}")
                            st.rerun()
                        else:
                            st.warning(f"{ne_name} already exists.")
                    else:
                        st.error("Name required.")


# ============================================================
#  MODULE 5: ADMIN DASHBOARD
# ============================================================
if user_is_admin and "Admin Dashboard" in tabs_dict:
    with tabs_dict["Admin Dashboard"]:

        st.header("📊 Admin Dashboard")
    
        df_time = load_data("time")
        df_exp = load_data("expenses")
    
        # --- Top-level metrics (compact 3-column layout) ---
        m1, m2, m3 = st.columns(3)
        with m1:
            total_hours = df_time["Hours"].sum() if not df_time.empty else 0
            st.metric("⏱️ Total Hours Logged", f"{total_hours:.1f}")
            pending_ts = len(get_submitted_weeks(df_time)) if not df_time.empty else 0
            st.caption(f"📋 {pending_ts} weeks pending approval")
        with m2:
            total_exp = df_exp["Amount"].sum() if not df_exp.empty else 0
            st.metric("💰 Total Expenses", f"${total_exp:,.2f}")
            pending_exp = len(get_submitted_weeks(df_exp)) if not df_exp.empty else 0
            st.caption(f"💳 {pending_exp} weeks pending approval")
        with m3:
            all_reqs = load_pto_requests()
            pending_pto = len(all_reqs[all_reqs["Status"] == "Pending"]) if not all_reqs.empty else 0
            emp_count = len(load_employees()["employees"])
            st.metric("👥 Employees", emp_count)
            st.caption(f"🏖️ {pending_pto} PTO requests pending")
    
        st.divider()
    
        # --- Tabbed sections (combined approvals) ---
        tab_overview, tab_users, tab_projects, tab_approvals, tab_tracker, tab_pto_approvals, tab_reports = st.tabs([
            "📊 Overview", "👥 Users", "📁 Projects",
            "✅ Approvals", "📋 Submission Tracker",
            "🏖️ PTO Approvals", "📄 Reports"
        ])
    
        # ------ OVERVIEW TAB ------
        with tab_overview:
            col1, col2 = st.columns(2)
            with col1:
                st.subheader("Hours by Project")
                if not df_time.empty:
                    fig = px.pie(df_time, values="Hours", names="Project", title="Utilization")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No timesheet data yet.")
    
            with col2:
                st.subheader("Expenses by Type")
                if not df_exp.empty:
                    fig = px.bar(df_exp, x="Category", y="Amount", color="User", title="Costs")
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("No expense data yet.")
    
            st.subheader("🏖️ PTO Overview")
            emp_data = load_employees()
            pto_rows = []
            for emp in emp_data["employees"]:
                bal = get_pto_balance(emp["name"])
                pto_rows.append({
                    "Employee": emp["name"],
                    "Available (hrs)": bal["balance"],
                    "Available (days)": round(bal["balance"]/8, 1),
                    "Accrued": bal["accrued"],
                    "Used": bal["used"],
                })
            if pto_rows:
                st.dataframe(pd.DataFrame(pto_rows), use_container_width=True, hide_index=True)
    
            st.divider()
            st.subheader("📄 Detailed Export")
            export_tab1, export_tab2 = st.tabs(["Timesheets", "Expenses"])
            with export_tab1:
                st.dataframe(df_time)
            with export_tab2:
                st.dataframe(df_exp)
    
        # ------ USERS TAB ------
    
    
        with tab_users:
            st.subheader("👥 Employee Management")
            emp_data = load_employees()

            for idx, emp in enumerate(emp_data["employees"]):
                emp_name = emp["name"]
                _badge = "🔑 Admin" if emp["role"] == "admin" else "👤 Employee"
                with st.expander(f"{emp_name} — {_badge}"):
                    # --- VIEW MODE: Show current info ---
                    info1, info2, info3, info4 = st.columns(4)
                    with info1:
                        st.markdown(f"**📧 Email**")
                        st.caption(emp.get("email", "—"))
                    with info2:
                        st.markdown(f"**👤 Manager**")
                        st.caption(emp.get("manager_email", "—") or "—")
                    with info3:
                        st.markdown(f"**📅 Hired**")
                        st.caption(emp.get("hire_date", "—"))
                    with info4:
                        st.markdown(f"**📈 PTO Accrual**")
                        st.caption(f"{emp.get('pto_accrual_rate', DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH)} hrs/mo")

                    st.markdown("---")

                    # --- EDIT FORM ---
                    with st.form(f"edit_emp_{idx}_{emp_name}"):
                        st.markdown("##### ✏️ Edit Employee Details")
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            ed_email = st.text_input("Email", value=emp.get("email", ""), key=f"ed_email_{idx}")
                            ed_mgr = st.text_input("Manager Email", value=emp.get("manager_email", ""), key=f"ed_mgr_{idx}")
                            ed_role = st.selectbox(
                                "Role", ["employee", "admin"],
                                index=0 if emp["role"] == "employee" else 1,
                                key=f"ed_role_{idx}"
                            )
                        with ec2:
                            try:
                                hire_val = datetime.date.fromisoformat(emp.get("hire_date", "2024-01-01"))
                            except (ValueError, TypeError):
                                hire_val = datetime.date.today()
                            ed_hire = st.date_input("Hire Date", value=hire_val, key=f"ed_hire_{idx}")
                            ed_rate = st.number_input(
                                "PTO Accrual (hrs/month)",
                                value=float(emp.get("pto_accrual_rate", DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH)),
                                step=1.0, key=f"ed_rate_{idx}"
                            )

                        if st.form_submit_button("💾 Save Changes", type="primary"):
                            updates = {
                                "email": ed_email,
                                "manager_email": ed_mgr,
                                "role": ed_role,
                                "hire_date": ed_hire.isoformat(),
                                "pto_accrual_rate": ed_rate,
                            }
                            update_employee(emp_name, updates)
                            st.success(f"✅ Updated {emp_name}")
                            st.rerun()

                    # --- DELETE ---
                    st.markdown("")
                    if emp_name.lower() == current_user.lower():
                        st.caption("🔒 You cannot delete your own account.")
                    else:
                        del_col1, del_col2, del_col3 = st.columns([2, 1, 2])
                        with del_col2:
                            confirm_key = f"confirm_del_{idx}_{emp_name}"
                            if st.checkbox("I confirm", key=confirm_key):
                                if st.button(f"🗑️ Delete {emp_name}", key=f"del_btn_{idx}_{emp_name}", type="primary"):
                                    ok = delete_employee(emp_name)
                                    if ok:
                                        st.success(f"Deleted {emp_name}")
                                        st.rerun()
                                    else:
                                        st.error("Could not delete employee.")
                            else:
                                st.button(f"🗑️ Delete {emp_name}", key=f"del_btn_disabled_{idx}", disabled=True)

                    # --- PASSWORD RESET ---
                    with st.expander(f"🔑 Reset Password for {emp_name}", expanded=False):
                        reset_pw = st.text_input("New Password", type="password", key=f"reset_pw_{idx}")
                        if st.button("Set Password", key=f"reset_pw_btn_{idx}"):
                            if reset_pw and len(reset_pw) >= 6:
                                set_employee_password(emp_name, reset_pw)
                                st.success(f"✅ Password reset for {emp_name}")
                            elif reset_pw:
                                st.error("Password must be at least 6 characters.")
                            else:
                                st.error("Enter a password.")

            st.divider()
            st.markdown("##### ➕ Add New Employee")
            with st.form("admin_add_emp_form"):
                ac1, ac2 = st.columns(2)
                with ac1:
                    ne_name = st.text_input("Full Name")
                    ne_email = st.text_input("Email")
                    ne_role = st.selectbox("Role", ["employee", "admin"])
                with ac2:
                    ne_mgr = st.text_input("Manager Email")
                    ne_hire = st.date_input("Hire Date", datetime.date.today())
                    ne_rate = st.number_input("PTO Accrual (hrs/month)", value=float(DEFAULT_PTO_ACCRUAL_HOURS_PER_MONTH), step=1.0)

                if st.form_submit_button("Add Employee", type="primary"):
                    if ne_name:
                        ok = add_employee(ne_name, ne_email, ne_role, ne_mgr, ne_hire, ne_rate)
                        if ok:
                            st.success(f"Added {ne_name}")
                            st.rerun()
                        else:
                            st.warning(f"{ne_name} already exists.")
                    else:
                        st.error("Name required.")
    
        # ------ PROJECTS TAB ------
        with tab_projects:
            st.subheader("📁 Project & Task Management")
            projects = load_projects()
    
            for proj_name, tasks in projects.items():
                with st.expander(f"📂 {proj_name} ({len(tasks)} tasks)"):
                    for t in tasks:
                        st.markdown(f"  • {t}")
    
                    # Add task
                    new_task = st.text_input("Add task", key=f"proj_task_{proj_name}")
                    if st.button("➕ Add Task", key=f"proj_add_task_{proj_name}"):
                        if new_task:
                            tasks.append(new_task)
                            update_project(proj_name, tasks)
                            st.success(f"Added '{new_task}' to {proj_name}")
                            st.rerun()
    
                    # Delete project
                    if st.button("🗑️ Delete Project", key=f"proj_del_{proj_name}"):
                        delete_project(proj_name)
                        st.warning(f"Deleted {proj_name}")
                        st.rerun()
    
            st.divider()
            st.markdown("##### ➕ Add New Project")
            with st.form("add_project_form"):
                new_proj_name = st.text_input("Project Name")
                new_proj_tasks = st.text_area("Tasks (one per line)")
                if st.form_submit_button("Create Project"):
                    if new_proj_name:
                        task_list = [t.strip() for t in new_proj_tasks.strip().split("\n") if t.strip()]
                        if not task_list:
                            task_list = ["General"]
                        add_project(new_proj_name, task_list)
                        st.success(f"Created project '{new_proj_name}' with {len(task_list)} tasks")
                        st.rerun()
                    else:
                        st.error("Project name required.")
    
        # ------ COMBINED APPROVALS TAB ------
        with tab_approvals:

            # =========================================================
            #  TIMESHEET APPROVALS — Full Detail View
            # =========================================================
            st.subheader("⏱️ Timesheet Approvals")

            df_time_fresh = load_data("time")
            if not df_time_fresh.empty:
                df_time_fresh["Date"] = df_time_fresh["Date"].astype(str)
            submitted_ts = get_submitted_weeks(df_time_fresh) if not df_time_fresh.empty else []

            if submitted_ts:
                for ts_idx, sw in enumerate(submitted_ts):
                    user = sw["user"]
                    week_start = sw["week_start"]
                    total = sw["total"]

                    # Get all 7 days of this week
                    _ws = datetime.date.fromisoformat(week_start)
                    _we = _ws + datetime.timedelta(days=6)
                    _week_dates = [_ws + datetime.timedelta(days=i) for i in range(7)]
                    _date_strs = [d.isoformat() for d in _week_dates]

                    # Header card
                    with st.container(border=True):
                        # --- Summary Row ---
                        hdr1, hdr2, hdr3, hdr4 = st.columns([3, 2, 1.5, 2])
                        with hdr1:
                            st.markdown(f"### 👤 {user}")
                            st.caption(f"Week of {_ws.strftime('%b %d')} – {_we.strftime('%b %d, %Y')}")
                        with hdr2:
                            st.metric("⏱️ Total Hours", f"{total:.1f}")
                        with hdr3:
                            st.markdown("""
                            <div style="background:#00838F; color:white; padding:6px 14px;
                                 border-radius:20px; text-align:center; font-weight:700;
                                 font-size:0.72rem; margin-top:0.5rem; letter-spacing:0.04em;">
                                📤 SUBMITTED
                            </div>
                            """, unsafe_allow_html=True)
                        with hdr4:
                            submitted_at = ""
                            if not df_time_fresh.empty:
                                _sa_rows = df_time_fresh[
                                    (df_time_fresh["User"] == user) &
                                    (df_time_fresh["Date"].isin(_date_strs)) &
                                    (df_time_fresh["Status"] == "Submitted")
                                ]
                                if not _sa_rows.empty and "SubmittedAt" in _sa_rows.columns:
                                    _sa_val = _sa_rows["SubmittedAt"].dropna()
                                    if not _sa_val.empty:
                                        submitted_at = str(_sa_val.iloc[0])[:16].replace("T", " ")
                            if submitted_at:
                                st.caption(f"📅 Submitted: {submitted_at}")

                        # --- Detailed Timesheet Grid ---
                        with st.expander("📋 **View Timesheet Details**", expanded=False):
                            # Get this user's entries for the week
                            ts_entries = df_time_fresh[
                                (df_time_fresh["User"] == user) &
                                (df_time_fresh["Date"].isin(_date_strs))
                            ].copy()

                            if not ts_entries.empty:
                                # Build pivot table: Project/Task as rows, Days as columns
                                ts_entries["Day"] = ts_entries["Date"].apply(
                                    lambda x: f"{DAY_LABELS[_date_strs.index(x)]} {_week_dates[_date_strs.index(x)].strftime('%m/%d')}"
                                    if x in _date_strs else ""
                                )
                                day_order = [f"{DAY_LABELS[i]} {_week_dates[i].strftime('%m/%d')}" for i in range(7)]

                                pivot = ts_entries.pivot_table(
                                    values="Hours",
                                    index=["Project", "Task"],
                                    columns="Day",
                                    aggfunc="sum",
                                    fill_value=0
                                )
                                # Reorder columns
                                for dc in day_order:
                                    if dc not in pivot.columns:
                                        pivot[dc] = 0.0
                                pivot = pivot[day_order]
                                pivot["Total"] = pivot.sum(axis=1)

                                # Daily totals row
                                daily_totals = pivot.sum(axis=0)
                                daily_totals.name = ("DAILY TOTAL", "")
                                pivot = pd.concat([pivot, daily_totals.to_frame().T])

                                # Style the dataframe
                                st.dataframe(
                                    pivot.style.format("{:.1f}").map(
                                        lambda v: "font-weight:700" if v > 0 else "color:#cbd5e1",
                                    ),
                                    use_container_width=True,
                                    height=min(45 + len(pivot) * 35, 400)
                                )

                                # Notes summary
                                notes_entries = ts_entries[ts_entries["Notes"].fillna("").str.strip() != ""]
                                if not notes_entries.empty:
                                    st.markdown("**📝 Notes:**")
                                    for _, ne in notes_entries.iterrows():
                                        st.caption(f"• {ne['Date']} / {ne['Project']} / {ne['Task']}: {ne['Notes']}")
                            else:
                                st.info("No entries found for this week.")

                        # --- Approve / Deny Actions ---
                        st.markdown("---")
                        act_col1, act_col2, act_col3 = st.columns([4, 1.5, 1.5])
                        with act_col1:
                            review_comment = st.text_input(
                                "Review comment (optional)",
                                key=f"ts_comment_{ts_idx}_{user}_{week_start}",
                                placeholder="Add a note for the employee..."
                            )
                        with act_col2:
                            if st.button("✅ Approve Timesheet", key=f"ts_approve_{ts_idx}_{user}_{week_start}", type="primary"):
                                df_time_fresh, ok, msg = review_timesheet_week(
                                    df_time_fresh, user, week_start, current_user, approve=True
                                )
                                if ok:
                                    save_data("time", df_time_fresh)
                                    st.success(f"✅ {msg}")
                                    st.rerun()
                        with act_col3:
                            if st.button("❌ Deny Timesheet", key=f"ts_deny_{ts_idx}_{user}_{week_start}"):
                                df_time_fresh, ok, msg = review_timesheet_week(
                                    df_time_fresh, user, week_start, current_user, approve=False
                                )
                                if ok:
                                    save_data("time", df_time_fresh)
                                    # Send denial email
                                    _week_label = f"{_ws.strftime('%b %d')} – {_we.strftime('%b %d, %Y')}"
                                    send_denial_email(user, "timesheet", _week_label, current_user, review_comment)
                                    st.warning(f"🔄 {msg} — Denial email sent to {user}.")
                                    st.rerun()

            else:
                st.info("No timesheets pending approval. 🎉")

            st.divider()

            # =========================================================
            #  EXPENSE APPROVALS — Full Detail View with Receipts
            # =========================================================
            st.subheader("💳 Expense Approvals")

            df_exp_fresh = load_data("expenses")
            if not df_exp_fresh.empty:
                df_exp_fresh["Date"] = df_exp_fresh["Date"].astype(str)
            submitted_exp = get_submitted_weeks(df_exp_fresh) if not df_exp_fresh.empty else []

            if submitted_exp:
                for exp_idx, sw in enumerate(submitted_exp):
                    user = sw["user"]
                    week_start = sw["week_start"]
                    total = sw["total"]

                    _ws = datetime.date.fromisoformat(week_start)
                    _we = _ws + datetime.timedelta(days=6)
                    _week_dates = [_ws + datetime.timedelta(days=i) for i in range(7)]
                    _date_strs = [d.isoformat() for d in _week_dates]

                    with st.container(border=True):
                        # --- Summary Row ---
                        hdr1, hdr2, hdr3, hdr4 = st.columns([3, 2, 1.5, 2])
                        with hdr1:
                            st.markdown(f"### 👤 {user}")
                            st.caption(f"Week of {_ws.strftime('%b %d')} – {_we.strftime('%b %d, %Y')}")
                        with hdr2:
                            st.metric("💰 Total Expenses", f"${total:,.2f}")
                        with hdr3:
                            st.markdown("""
                            <div style="background:#00838F; color:white; padding:6px 14px;
                                 border-radius:20px; text-align:center; font-weight:700;
                                 font-size:0.72rem; margin-top:0.5rem; letter-spacing:0.04em;">
                                📤 SUBMITTED
                            </div>
                            """, unsafe_allow_html=True)
                        with hdr4:
                            submitted_at = ""
                            if not df_exp_fresh.empty:
                                _sa_rows = df_exp_fresh[
                                    (df_exp_fresh["User"] == user) &
                                    (df_exp_fresh["Date"].isin(_date_strs)) &
                                    (df_exp_fresh["Status"] == "Submitted")
                                ]
                                if not _sa_rows.empty and "SubmittedAt" in _sa_rows.columns:
                                    _sa_val = _sa_rows["SubmittedAt"].dropna()
                                    if not _sa_val.empty:
                                        submitted_at = str(_sa_val.iloc[0])[:16].replace("T", " ")
                            if submitted_at:
                                st.caption(f"📅 Submitted: {submitted_at}")

                        # --- Detailed Expense Line Items ---
                        with st.expander("💳 **View Expense Details**", expanded=False):
                            exp_entries = df_exp_fresh[
                                (df_exp_fresh["User"] == user) &
                                (df_exp_fresh["Date"].isin(_date_strs))
                            ].copy()

                            if not exp_entries.empty:
                                # Summary by category
                                cat_summary = exp_entries.groupby("Category")["Amount"].agg(["sum", "count"]).reset_index()
                                cat_summary.columns = ["Category", "Total", "Items"]
                                cat_summary["Total"] = cat_summary["Total"].apply(lambda x: f"${x:,.2f}")

                                st.markdown("**📊 Summary by Category**")
                                summary_cols = st.columns(min(len(cat_summary), 4))
                                for ci, (_, cat_row) in enumerate(cat_summary.iterrows()):
                                    with summary_cols[ci % len(summary_cols)]:
                                        st.metric(cat_row["Category"], cat_row["Total"], f"{int(cat_row['Items'])} items")

                                st.markdown("---")
                                st.markdown("**📋 Line Items**")

                                # Show each expense line
                                for li_idx, (_, exp_row) in enumerate(exp_entries.iterrows()):
                                    exp_date = str(exp_row.get("Date", ""))
                                    exp_cat = str(exp_row.get("Category", ""))
                                    exp_amt = float(exp_row.get("Amount", 0))
                                    exp_proj = str(exp_row.get("Project", ""))
                                    exp_task = str(exp_row.get("Task", ""))
                                    exp_details = str(exp_row.get("Details", ""))
                                    exp_notes = str(exp_row.get("Notes", ""))
                                    exp_paidby = str(exp_row.get("PaidBy", ""))
                                    exp_reimb = exp_row.get("Reimbursable", True)
                                    exp_receipt = str(exp_row.get("Receipt", ""))
                                    exp_day_type = str(exp_row.get("DayType", ""))
                                    exp_bkft = exp_row.get("BreakfastProvided", False)
                                    exp_lunch = exp_row.get("LunchProvided", False)
                                    exp_dinner = exp_row.get("DinnerProvided", False)

                                    li1, li2, li3, li4, li5 = st.columns([1.5, 2.5, 1.5, 2, 1.5])

                                    with li1:
                                        try:
                                            d_obj = datetime.date.fromisoformat(exp_date)
                                            st.markdown(f"**{d_obj.strftime('%a %m/%d')}**")
                                        except ValueError:
                                            st.markdown(f"**{exp_date}**")
                                        # Show Day Type badge for per diem
                                        if exp_day_type and exp_day_type not in ("", "nan"):
                                            if exp_day_type in ("First Day", "Last Day"):
                                                st.markdown(f"<span style='background:#f59e0b; color:white; padding:1px 8px; border-radius:10px; font-size:0.65rem; font-weight:600;'>{exp_day_type} (75%)</span>", unsafe_allow_html=True)
                                            else:
                                                st.caption(f"📅 {exp_day_type}")

                                    with li2:
                                        st.markdown(f"**{exp_cat}**")
                                        if exp_task and exp_task not in ("", "nan"):
                                            st.caption(f"📌 Task: {exp_task}")
                                        if exp_details and exp_details not in ("", "nan"):
                                            st.caption(exp_details)
                                        # Meals provided indicators for per diem entries
                                        if exp_cat == "Meals (Per Diem)":
                                            meals_flags = []
                                            if exp_bkft:
                                                meals_flags.append("🍳 Bkft")
                                            if exp_lunch:
                                                meals_flags.append("🥪 Lunch")
                                            if exp_dinner:
                                                meals_flags.append("🍽️ Dinner")
                                            if meals_flags:
                                                st.caption(f"Meals provided: {', '.join(meals_flags)}")

                                    with li3:
                                        amt_color = "#dc2626" if exp_amt > 500 else "#1e293b"
                                        st.markdown(f"<span style='font-size:1.1rem; font-weight:700; color:{amt_color};'>${exp_amt:,.2f}</span>", unsafe_allow_html=True)
                                        reimb_label = "✅ Reimbursable" if exp_reimb else "⬜ Non-reimb"
                                        st.caption(f"{reimb_label} · {exp_paidby}")

                                    with li4:
                                        st.caption(f"📁 {exp_proj}")
                                        if exp_notes and exp_notes not in ("", "nan"):
                                            st.caption(f"📝 {exp_notes}")

                                    with li5:
                                        if exp_receipt and exp_receipt not in ("", "nan"):
                                            receipt_path = os.path.join(RECEIPTS_DIR, exp_receipt)
                                            if os.path.exists(receipt_path):
                                                ext = os.path.splitext(exp_receipt)[1].lower()
                                                if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
                                                    st.image(receipt_path, width=100, caption="Receipt")
                                                else:
                                                    with open(receipt_path, "rb") as rf:
                                                        st.download_button(
                                                            "📎 Receipt",
                                                            data=rf.read(),
                                                            file_name=exp_receipt,
                                                            key=f"rcpt_{exp_idx}_{li_idx}"
                                                        )
                                            else:
                                                st.caption(f"📎 {exp_receipt}")
                                        else:
                                            st.caption("No receipt")

                                    # Thin divider between line items
                                    if li_idx < len(exp_entries) - 1:
                                        st.markdown("<hr style='margin:4px 0; border-color:#f1f5f9;'>", unsafe_allow_html=True)

                                # Totals footer
                                st.markdown("---")
                                tot1, tot2, tot3 = st.columns([3, 1.5, 3.5])
                                with tot1:
                                    st.markdown(f"**{len(exp_entries)} line items**")
                                with tot2:
                                    reimb_total = exp_entries[exp_entries.get("Reimbursable", True) == True]["Amount"].astype(float).sum() if "Reimbursable" in exp_entries.columns else total
                                    st.markdown(f"**Reimbursable: ${reimb_total:,.2f}**")

                            else:
                                st.info("No expense entries found for this week.")

                        # --- Approve / Deny Actions ---
                        st.markdown("---")
                        act_col1, act_col2, act_col3 = st.columns([4, 1.5, 1.5])
                        with act_col1:
                            review_comment = st.text_input(
                                "Review comment (optional)",
                                key=f"exp_comment_{exp_idx}_{user}_{week_start}",
                                placeholder="Add a note for the employee..."
                            )
                        with act_col2:
                            if st.button("✅ Approve Expenses", key=f"exp_approve_{exp_idx}_{user}_{week_start}", type="primary"):
                                df_exp_fresh, ok, msg = review_expense_week(
                                    df_exp_fresh, user, week_start, current_user, approve=True
                                )
                                if ok:
                                    save_data("expenses", df_exp_fresh)
                                    st.success(f"✅ {msg}")
                                    st.rerun()
                        with act_col3:
                            if st.button("❌ Deny Expenses", key=f"exp_deny_{exp_idx}_{user}_{week_start}"):
                                df_exp_fresh, ok, msg = review_expense_week(
                                    df_exp_fresh, user, week_start, current_user, approve=False
                                )
                                if ok:
                                    save_data("expenses", df_exp_fresh)
                                    # Send denial email
                                    _week_label = f"{_ws.strftime('%b %d')} – {_we.strftime('%b %d, %Y')}"
                                    send_denial_email(user, "expense", _week_label, current_user, review_comment)
                                    st.warning(f"🔄 {msg} — Denial email sent to {user}.")
                                    st.rerun()

            else:
                st.info("No expenses pending approval. 🎉")

        # ------ SUBMISSION TRACKER TAB ------
        with tab_tracker:
            st.subheader("📋 Submission Tracker")
            st.caption("Track who has submitted timesheets and expenses and who still needs a reminder.")

            # --- Week Selector ---
            if "tracker_ref" not in st.session_state:
                st.session_state["tracker_ref"] = datetime.date.today()

            tracker_ref = st.session_state["tracker_ref"]
            tr_sun, tr_sat = get_week_range(tracker_ref)
            tr_week_dates = [tr_sun + datetime.timedelta(days=i) for i in range(7)]
            tr_date_strs = [d.isoformat() for d in tr_week_dates]

            today_sun, _ = get_week_range(datetime.date.today())
            tr_is_current = (tr_sun == today_sun)

            tr_prev, tr_label, tr_next, tr_today = st.columns([1, 4, 1, 2])
            with tr_prev:
                if st.button("◀ Prev", key="tr_prev"):
                    st.session_state["tracker_ref"] = tracker_ref - datetime.timedelta(weeks=1)
                    st.rerun()
            with tr_label:
                wk_label = f"{tr_sun.strftime('%b %d')} – {tr_sat.strftime('%b %d, %Y')}"
                if tr_is_current:
                    st.markdown(f"### 📅 {wk_label} &nbsp; <span style='background:#00838F; color:white; padding:2px 12px; border-radius:12px; font-size:0.7rem; font-weight:700; vertical-align:middle; letter-spacing:0.04em;'>CURRENT</span>", unsafe_allow_html=True)
                else:
                    st.markdown(f"### 📅 {wk_label}")
            with tr_next:
                if st.button("Next ▶", key="tr_next"):
                    st.session_state["tracker_ref"] = tracker_ref + datetime.timedelta(weeks=1)
                    st.rerun()
            with tr_today:
                if st.button("↩ Today", key="tr_today", type="primary" if not tr_is_current else "secondary"):
                    st.session_state["tracker_ref"] = datetime.date.today()
                    st.rerun()

            st.markdown("---")

            # --- Build status for every employee ---
            emp_data = load_employees()
            all_emp = [e["name"] for e in emp_data["employees"]]

            # Load fresh data
            df_ts = load_data("time")
            if not df_ts.empty:
                df_ts["Date"] = df_ts["Date"].astype(str)
            df_ex = load_data("expenses")
            if not df_ex.empty:
                df_ex["Date"] = df_ex["Date"].astype(str)

            tracker_rows = []
            ts_not_submitted = []
            exp_not_submitted = []

            for emp_name in all_emp:
                # --- Timesheet status ---
                ts_status = "Not Started"
                ts_hours = 0.0
                ts_submitted_at = ""
                if not df_ts.empty:
                    emp_ts = df_ts[
                        (df_ts["User"] == emp_name) &
                        (df_ts["Date"].isin(tr_date_strs))
                    ]
                    if not emp_ts.empty:
                        ts_hours = emp_ts["Hours"].astype(float).sum()
                        statuses = emp_ts["Status"].unique().tolist() if "Status" in emp_ts.columns else []
                        if "Approved" in statuses:
                            ts_status = "Approved"
                        elif "Submitted" in statuses:
                            ts_status = "Submitted"
                            if "SubmittedAt" in emp_ts.columns:
                                sa = emp_ts["SubmittedAt"].dropna()
                                if not sa.empty:
                                    ts_submitted_at = str(sa.iloc[0])[:16].replace("T", " ")
                        elif "Denied" in statuses:
                            ts_status = "Denied"
                        else:
                            ts_status = "Draft"

                # --- Expense status ---
                exp_status = "Not Started"
                exp_total = 0.0
                exp_submitted_at = ""
                if not df_ex.empty:
                    emp_ex = df_ex[
                        (df_ex["User"] == emp_name) &
                        (df_ex["Date"].isin(tr_date_strs))
                    ]
                    if not emp_ex.empty:
                        exp_total = emp_ex["Amount"].astype(float).sum()
                        statuses = emp_ex["Status"].unique().tolist() if "Status" in emp_ex.columns else []
                        if "Approved" in statuses:
                            exp_status = "Approved"
                        elif "Submitted" in statuses:
                            exp_status = "Submitted"
                            if "SubmittedAt" in emp_ex.columns:
                                sa = emp_ex["SubmittedAt"].dropna()
                                if not sa.empty:
                                    exp_submitted_at = str(sa.iloc[0])[:16].replace("T", " ")
                        elif "Denied" in statuses:
                            exp_status = "Denied"
                        else:
                            exp_status = "Draft"

                # Track who needs reminders
                if ts_status not in ("Submitted", "Approved"):
                    ts_not_submitted.append(emp_name)
                if exp_status not in ("Submitted", "Approved"):
                    exp_not_submitted.append(emp_name)

                tracker_rows.append({
                    "Employee": emp_name,
                    "Timesheet Status": ts_status,
                    "Hours": ts_hours,
                    "TS Submitted": ts_submitted_at if ts_submitted_at else "—",
                    "Expense Status": exp_status,
                    "Expenses ($)": exp_total,
                    "Exp Submitted": exp_submitted_at if exp_submitted_at else "—",
                })

            # --- Summary metrics ---
            tot_emp = len(all_emp)
            ts_sub_count = tot_emp - len(ts_not_submitted)
            exp_sub_count = tot_emp - len(exp_not_submitted)

            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("👥 Total Employees", tot_emp)
            with m2:
                pct = int(ts_sub_count / tot_emp * 100) if tot_emp else 0
                color = "#22c55e" if pct == 100 else "#f59e0b" if pct >= 50 else "#ef4444"
                st.metric("⏱️ Timesheets Submitted", f"{ts_sub_count}/{tot_emp}")
                st.markdown(f"""
                <div style="background: linear-gradient(to right, {color} {pct}%, #e2e8f0 {pct}%);
                     height:6px; border-radius:3px; margin-top:-0.5rem;"></div>
                """, unsafe_allow_html=True)
            with m3:
                pct = int(exp_sub_count / tot_emp * 100) if tot_emp else 0
                color = "#22c55e" if pct == 100 else "#f59e0b" if pct >= 50 else "#ef4444"
                st.metric("💳 Expenses Submitted", f"{exp_sub_count}/{tot_emp}")
                st.markdown(f"""
                <div style="background: linear-gradient(to right, {color} {pct}%, #e2e8f0 {pct}%);
                     height:6px; border-radius:3px; margin-top:-0.5rem;"></div>
                """, unsafe_allow_html=True)
            with m4:
                all_done = (len(ts_not_submitted) == 0) and (len(exp_not_submitted) == 0)
                if all_done:
                    st.markdown("""
                    <div style='background:#22c55e; color:white; padding:12px; border-radius:8px;
                         text-align:center; font-weight:700; font-size:1rem; margin-top:1.3rem;'>
                        ✅ ALL COMPLETE
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    need_reminder = set(ts_not_submitted) | set(exp_not_submitted)
                    st.metric("⚠️ Need Reminder", f"{len(need_reminder)}")

            st.markdown("---")

            # --- Status Table ---
            if tracker_rows:
                df_tracker = pd.DataFrame(tracker_rows)

                def _color_status(val):
                    colors = {
                        "Approved": "background-color: #dcfce7; color: #166534; font-weight:600;",
                        "Submitted": "background-color: #dbeafe; color: #1e40af; font-weight:600;",
                        "Draft": "background-color: #fef9c3; color: #92400e;",
                        "Denied": "background-color: #fee2e2; color: #991b1b; font-weight:600;",
                        "Not Started": "background-color: #fef2f2; color: #dc2626; font-weight:600;",
                    }
                    return colors.get(val, "")

                styled = df_tracker.style.applymap(
                    _color_status,
                    subset=["Timesheet Status", "Expense Status"]
                ).format({
                    "Hours": "{:.1f}",
                    "Expenses ($)": "${:,.2f}"
                })

                st.dataframe(
                    styled,
                    use_container_width=True,
                    hide_index=True,
                    height=min(45 + len(df_tracker) * 35, 500)
                )

            # --- Reminder Section ---
            st.markdown("---")
            st.subheader("📬 Send Reminders")

            need_ts = ts_not_submitted
            need_exp = exp_not_submitted
            need_both = list(set(need_ts) & set(need_exp))
            need_ts_only = [n for n in need_ts if n not in need_both]
            need_exp_only = [n for n in need_exp if n not in need_both]

            if not need_ts and not need_exp:
                st.success("🎉 Everyone has submitted their timesheets and expenses for this week!")
            else:
                r1, r2, r3 = st.columns(3)

                with r1:
                    if need_both:
                        st.markdown("**🔴 Missing Both**")
                        for name in sorted(need_both):
                            emp = get_employee(name)
                            email = emp.get("email", "") if emp else ""
                            st.markdown(f"• **{name}**")
                            if email:
                                st.caption(f"  📧 {email}")
                    else:
                        st.markdown("**🔴 Missing Both**")
                        st.caption("None — all clear!")

                with r2:
                    if need_ts_only:
                        st.markdown("**🟡 Missing Timesheet Only**")
                        for name in sorted(need_ts_only):
                            emp = get_employee(name)
                            email = emp.get("email", "") if emp else ""
                            st.markdown(f"• **{name}**")
                            if email:
                                st.caption(f"  📧 {email}")
                    else:
                        st.markdown("**🟡 Missing Timesheet Only**")
                        st.caption("None — all clear!")

                with r3:
                    if need_exp_only:
                        st.markdown("**🟠 Missing Expenses Only**")
                        for name in sorted(need_exp_only):
                            emp = get_employee(name)
                            email = emp.get("email", "") if emp else ""
                            st.markdown(f"• **{name}**")
                            if email:
                                st.caption(f"  📧 {email}")
                    else:
                        st.markdown("**🟠 Missing Expenses Only**")
                        st.caption("None — all clear!")

                # --- Generate Reminder Email ---
                st.markdown("---")
                all_needing = sorted(set(need_ts + need_exp))

                if all_needing:
                    # Build email addresses list
                    emails = []
                    for name in all_needing:
                        emp = get_employee(name)
                        if emp and emp.get("email"):
                            emails.append(emp["email"])

                    week_str = f"{tr_sun.strftime('%b %d')} – {tr_sat.strftime('%b %d, %Y')}"

                    # Build mailto body
                    subject = f"Reminder: Submit your timesheet and expenses for {week_str}"
                    body_lines = [
                        f"Hi team,",
                        f"",
                        f"This is a friendly reminder to submit your timesheet and/or expense report for the week of {week_str}.",
                        f"",
                        f"The following items are still outstanding:",
                    ]
                    for name in all_needing:
                        missing = []
                        if name in need_ts:
                            missing.append("Timesheet")
                        if name in need_exp:
                            missing.append("Expenses")
                        body_lines.append(f"  • {name}: {', '.join(missing)}")

                    body_lines += [
                        f"",
                        f"Please submit as soon as possible.",
                        f"",
                        f"Thank you!",
                    ]
                    body_text = "\n".join(body_lines)

                    col_email, col_copy = st.columns([1, 1])
                    with col_email:
                        if emails:
                            import urllib.parse
                            mailto_link = f"mailto:{','.join(emails)}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body_text)}"
                            st.markdown(f"""
                            <a href="{mailto_link}" target="_blank" style="
                                display:inline-block; background:#3b82f6; color:white;
                                padding:10px 24px; border-radius:8px; text-decoration:none;
                                font-weight:600; font-size:0.9rem;">
                                📧 Open Email Draft ({len(emails)} recipients)
                            </a>
                            """, unsafe_allow_html=True)
                            st.caption(f"To: {', '.join(emails)}")
                        else:
                            st.info("No email addresses configured for these employees.")

                    with col_copy:
                        # Show a copyable list of names + status
                        reminder_text = f"Submission Reminder — Week of {week_str}\n\n"
                        for name in all_needing:
                            missing = []
                            if name in need_ts:
                                missing.append("Timesheet")
                            if name in need_exp:
                                missing.append("Expenses")
                            emp = get_employee(name)
                            email = emp.get("email", "") if emp else ""
                            reminder_text += f"• {name}"
                            if email:
                                reminder_text += f" ({email})"
                            reminder_text += f": {', '.join(missing)}\n"

                        st.text_area(
                            "📋 Copy Reminder List",
                            value=reminder_text,
                            height=150,
                            key="reminder_copy"
                        )

        # ------ PTO APPROVALS TAB ------
        with tab_pto_approvals:
            st.subheader("🏖️ PTO Approvals")
            all_reqs = load_pto_requests()
            if not all_reqs.empty:
                pending = all_reqs[all_reqs["Status"] == "Pending"]
                if not pending.empty:
                    for _, req in pending.iterrows():
                        with st.container(border=True):
                            pc1, pc2, pc3 = st.columns([3, 2, 2])
                            with pc1:
                                st.markdown(f"**{req['Employee']}**")
                                st.caption(f"{req['StartDate']} → {req['EndDate']}")
                            with pc2:
                                st.markdown(f"**{req['Hours']} hours**")
                                reason = req.get("Reason", "")
                                if reason:
                                    st.caption(reason)
                            with pc3:
                                col_a, col_d = st.columns(2)
                                with col_a:
                                    if st.button("✅ Approve", key=f"pto_approve_{req['RequestID']}"):
                                        review_pto_request(req['RequestID'], current_user, approve=True)
                                        st.success(f"Approved {req['RequestID']}")
                                        st.rerun()
                                with col_d:
                                    if st.button("❌ Deny", key=f"pto_deny_{req['RequestID']}"):
                                        review_pto_request(req['RequestID'], current_user, approve=False)
                                        st.warning(f"Denied {req['RequestID']}")
                                        st.rerun()
                else:
                    st.info("No pending PTO requests. 🎉")
            else:
                st.info("No PTO requests found.")
    
        # ------ REPORTS TAB ------
        with tab_reports:
            st.subheader("📄 Reports & Export")
    
            report_type = st.radio("Report Type", ["Timesheets", "Expenses"], horizontal=True, key="rpt_type")
    
            # Filters
            st.markdown("##### 🔍 Filters")
            rf1, rf2, rf3 = st.columns(3)
    
            all_employees = ["All"] + get_all_employee_names()
            with rf1:
                rpt_employee = st.selectbox("Employee", all_employees, key="rpt_emp")
            with rf2:
                rpt_start = st.date_input("Start Date", value=datetime.date.today() - datetime.timedelta(days=30), key="rpt_start")
            with rf3:
                rpt_end = st.date_input("End Date", value=datetime.date.today(), key="rpt_end")
    
            all_projects = ["All"] + get_all_project_names()
            rpt_project = st.selectbox("Project", all_projects, key="rpt_proj")
    
            st.divider()
    
            # Load and filter data
            if report_type == "Timesheets":
                rpt_df = load_data("time").copy()
            else:
                rpt_df = load_data("expenses").copy()
    
            if not rpt_df.empty:
                # Convert dates for filtering
                rpt_df["_date"] = pd.to_datetime(rpt_df["Date"], errors="coerce")
                rpt_start_dt = pd.Timestamp(rpt_start)
                rpt_end_dt = pd.Timestamp(rpt_end)
                rpt_df = rpt_df[(rpt_df["_date"] >= rpt_start_dt) & (rpt_df["_date"] <= rpt_end_dt)]
    
                if rpt_employee != "All":
                    rpt_df = rpt_df[rpt_df["User"] == rpt_employee]
                if rpt_project != "All":
                    rpt_df = rpt_df[rpt_df["Project"] == rpt_project]
    
                # Drop helper column
                rpt_df = rpt_df.drop(columns=["_date"], errors="ignore")
    
                if not rpt_df.empty:
                    # Summary metrics
                    rc1, rc2, rc3 = st.columns(3)
                    with rc1:
                        st.metric("Records", len(rpt_df))
                    with rc2:
                        if report_type == "Timesheets":
                            st.metric("Total Hours", f"{rpt_df['Hours'].sum():.1f}")
                        else:
                            st.metric("Total Amount", f"${rpt_df['Amount'].sum():,.2f}")
                    with rc3:
                        st.metric("Employees", rpt_df["User"].nunique())
    
                    st.dataframe(rpt_df, use_container_width=True, hide_index=True)
    
                    # Excel download
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine="openpyxl") as writer:
                        rpt_df.to_excel(writer, index=False, sheet_name=report_type)
                    output.seek(0)
    
                    fname = f"{report_type.lower()}_{rpt_start}_{rpt_end}.xlsx"
                    st.download_button(
                        label="📥 Download Excel",
                        data=output,
                        file_name=fname,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary"
                    )
                else:
                    st.info("No records match your filters.")
            else:
                st.info("No data available.")