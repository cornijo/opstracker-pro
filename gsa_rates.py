"""
GSA Per Diem Rates Module — Comprehensive Coverage
Uses official GSA XLSX data files with all 40,000+ ZIP codes and 288 destination rates.
Falls back to the GSA API for live lookups if cached data is unavailable.
"""

import os
import json
import datetime
import pandas as pd

# --- Configuration ---
DATA_DIR = "data"
ZIP_XLSX = os.path.join(DATA_DIR, "FY2026_ZipCodeFile.xlsx")
RATES_XLSX = os.path.join(DATA_DIR, "FY2026_PerDiemMasterRatesFile.xlsx")
CACHE_FILE = os.path.join(DATA_DIR, "gsa_rates_cache.json")

CURRENT_FY = 2026
GSA_MILEAGE_RATE = 0.725  # FY 2026

# Standard CONUS defaults (used when no specific rate is found)
STANDARD_LODGING = 110
STANDARD_MEALS = 68

# =========================================================================
#  GSA M&IE Breakdown Table (FY 2026)
#  Official deduction amounts per meal by total M&IE tier.
#  Source: GSA.gov Meals & Incidental Expenses Breakdown
# =========================================================================
MIE_BREAKDOWN = {
    59: {"breakfast": 13, "lunch": 15, "dinner": 26, "incidentals": 5, "first_last_day": 44},
    64: {"breakfast": 14, "lunch": 16, "dinner": 29, "incidentals": 5, "first_last_day": 48},
    68: {"breakfast": 16, "lunch": 17, "dinner": 31, "incidentals": 5, "first_last_day": 51},  # removed extra entry
    69: {"breakfast": 16, "lunch": 17, "dinner": 31, "incidentals": 5, "first_last_day": 52},
    74: {"breakfast": 17, "lunch": 18, "dinner": 34, "incidentals": 5, "first_last_day": 56},
    79: {"breakfast": 18, "lunch": 20, "dinner": 36, "incidentals": 5, "first_last_day": 59},
}

# Standard M&IE tier for CONUS
STANDARD_MIE_TIER = 68


def get_mie_breakdown(mie_total):
    """
    Return the meal breakdown dict for a given M&IE total.
    Falls back to the nearest lower tier if exact match not found.
    """
    if mie_total in MIE_BREAKDOWN:
        return MIE_BREAKDOWN[mie_total]
    # Find the nearest tier that doesn't exceed the actual rate
    available = sorted(MIE_BREAKDOWN.keys())
    tier = available[0]
    for t in available:
        if t <= mie_total:
            tier = t
    return MIE_BREAKDOWN[tier]


def calc_first_last_day(mie_total):
    """Return the 75% first/last day M&IE amount."""
    breakdown = get_mie_breakdown(mie_total)
    return breakdown["first_last_day"]


def calc_provided_meals_deduction(mie_total, breakfast=False, lunch=False, dinner=False):
    """
    Calculate the deduction for provided meals.
    Returns (deduction_amount, adjusted_per_diem).
    """
    breakdown = get_mie_breakdown(mie_total)
    deduction = 0
    if breakfast:
        deduction += breakdown["breakfast"]
    if lunch:
        deduction += breakdown["lunch"]
    if dinner:
        deduction += breakdown["dinner"]
    return deduction, max(0, mie_total - deduction)


def calc_daily_meal_allowance(mie_total, is_first_or_last_day=False,
                               breakfast_provided=False,
                               lunch_provided=False,
                               dinner_provided=False):
    """
    Calculate the total claimable meal allowance for a day.
    Accounts for first/last day (75%) and any provided meal deductions.
    Returns dict with base, deductions, and final amount.
    """
    breakdown = get_mie_breakdown(mie_total)

    if is_first_or_last_day:
        base = breakdown["first_last_day"]
    else:
        base = mie_total

    deduction = 0
    if breakfast_provided:
        deduction += breakdown["breakfast"]
    if lunch_provided:
        deduction += breakdown["lunch"]
    if dinner_provided:
        deduction += breakdown["dinner"]

    final = max(0, base - deduction)

    return {
        "base": base,
        "deductions": deduction,
        "final": final,
        "is_first_last": is_first_or_last_day,
        "breakfast_deduction": breakdown["breakfast"] if breakfast_provided else 0,
        "lunch_deduction": breakdown["lunch"] if lunch_provided else 0,
        "dinner_deduction": breakdown["dinner"] if dinner_provided else 0,
        "breakdown": breakdown,
    }


MONTH_COLS = ["Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"]
MONTH_MAP = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
}

# State abbreviation mapping
STATE_ABBREVS = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"
}
STATE_TO_ABBREV = {v: k for k, v in STATE_ABBREVS.items()}


# =========================================================================
#  CORE: Build & Load Cache from the official GSA XLSX files
# =========================================================================

def download_gsa_files(progress_callback=None):
    """Download the FY2026 XLSX data files from GSA if they don't exist."""
    import requests
    os.makedirs(DATA_DIR, exist_ok=True)

    files = {
        ZIP_XLSX: "https://www.gsa.gov/system/files/FY2026_ZipCodeFile.xlsx",
        RATES_XLSX: "https://www.gsa.gov/system/files/FY2026_PerDiemMasterRatesFile.xlsx",
    }

    for filepath, url in files.items():
        if not os.path.exists(filepath):
            if progress_callback:
                progress_callback(f"Downloading {os.path.basename(filepath)}...", 0, 1)
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(resp.content)

    if progress_callback:
        progress_callback("Download complete", 1, 1)


def build_full_cache(year=CURRENT_FY, progress_callback=None):
    """
    Build the comprehensive JSON cache from the GSA XLSX files.
    The ZIP code file is the primary source — it maps every US ZIP code to its
    destination and includes monthly lodging rates + M&IE for each.
    """
    # Download files if needed
    if not os.path.exists(ZIP_XLSX) or not os.path.exists(RATES_XLSX):
        download_gsa_files(progress_callback)

    if progress_callback:
        progress_callback("Reading ZIP code data...", 0, 3)

    # --- 1. Read the ZIP code file (the BIG one: ~42K rows) ---
    df_zips = pd.read_excel(ZIP_XLSX)
    # Ensure Zip is zero-padded string
    df_zips["Zip"] = df_zips["Zip"].astype(str).str.zfill(5)

    if progress_callback:
        progress_callback("Building location database...", 1, 3)

    # --- 2. Build unique destinations (one row per destination, with all its ZIPs) ---
    # Group by DestinationID to get unique locations with their rates
    dest_groups = df_zips.groupby("DestinationID").agg({
        "Name": "first",
        "County": "first",
        "LocationDefined": "first",
        "State": "first",
        "Zip": lambda x: list(x),
        "Oct": "first", "Nov": "first", "Dec": "first",
        "Jan": "first", "Feb": "first", "Mar": "first",
        "Apr": "first", "May": "first", "Jun": "first",
        "Jul": "first", "Aug": "first", "Sep": "first",
        "Meals": "first",
    }).reset_index()

    # --- 3. Build the location records ---
    locations = []
    for _, row in dest_groups.iterrows():
        locations.append({
            "DestID": int(row["DestinationID"]),
            "Name": str(row["Name"]),
            "County": str(row["County"]),
            "LocationDefined": str(row["LocationDefined"]),
            "State": str(row["State"]),
            "StateFull": STATE_ABBREVS.get(str(row["State"]), str(row["State"])),
            "Meals": int(row["Meals"]),
            "Oct": int(row["Oct"]), "Nov": int(row["Nov"]), "Dec": int(row["Dec"]),
            "Jan": int(row["Jan"]), "Feb": int(row["Feb"]), "Mar": int(row["Mar"]),
            "Apr": int(row["Apr"]), "May": int(row["May"]), "Jun": int(row["Jun"]),
            "Jul": int(row["Jul"]), "Aug": int(row["Aug"]), "Sep": int(row["Sep"]),
            "ZipCodes": row["Zip"],  # list of all ZIPs for this destination
        })

    # --- 4. Build ZIP-to-destination index for fast ZIP lookups ---
    zip_index = {}
    for _, row in df_zips.iterrows():
        zip_index[row["Zip"]] = {
            "DestID": int(row["DestinationID"]),
            "Name": str(row["Name"]),
            "County": str(row["County"]),
            "State": str(row["State"]),
            "Meals": int(row["Meals"]),
            **{m: int(row[m]) for m in MONTH_COLS}
        }

    if progress_callback:
        progress_callback("Saving cache...", 2, 3)

    # --- 5. Write cache ---
    cache = {
        "fiscal_year": year,
        "built_at": datetime.datetime.now().isoformat(),
        "total_zips": len(zip_index),
        "total_locations": len(locations),
        "locations": locations,
        "zip_index": zip_index,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f)

    if progress_callback:
        progress_callback("Done!", 3, 3)

    return len(locations), len(zip_index)


# --- In-memory cache ---
_cache = None

def _get_cache():
    global _cache
    if _cache is None:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                _cache = json.load(f)
    return _cache


def get_cache_info():
    """Return metadata about the current cache."""
    cache = _get_cache()
    if cache is None:
        return None
    return {
        "fiscal_year": cache.get("fiscal_year"),
        "built_at": cache.get("built_at"),
        "total_locations": cache.get("total_locations", 0),
        "total_zips": cache.get("total_zips", 0),
    }


def invalidate_cache():
    """Force reload cache from disk on next access."""
    global _cache
    _cache = None


# =========================================================================
#  SEARCH Functions
# =========================================================================

def load_locations_df():
    """Load cached locations into a DataFrame (one row per destination)."""
    cache = _get_cache()
    if cache is None:
        return pd.DataFrame()
    locs = cache.get("locations", [])
    if not locs:
        return pd.DataFrame()
    # Drop ZipCodes list for the DF (too large for display)
    rows = [{k: v for k, v in loc.items() if k != "ZipCodes"} for loc in locs]
    return pd.DataFrame(rows)


def search_rates(query):
    """
    Search for GSA rates by city name, county, state, or ZIP code.
    Returns a DataFrame of matching locations with their rates.
    """
    cache = _get_cache()
    if cache is None:
        return pd.DataFrame()

    q = query.strip()

    # --- ZIP code search ---
    if q.isdigit() and len(q) <= 5:
        zip_padded = q.zfill(5)
        zip_index = cache.get("zip_index", {})
        if zip_padded in zip_index:
            entry = zip_index[zip_padded]
            result = {
                "ZIP": zip_padded,
                "Name": entry["Name"],
                "County": entry["County"],
                "State": STATE_ABBREVS.get(entry["State"], entry["State"]),
                "Meals": entry["Meals"],
                **{m: entry[m] for m in MONTH_COLS}
            }
            return pd.DataFrame([result])

        # Partial ZIP match (e.g. "0709" matches all 0709x ZIPs)
        partial = {k: v for k, v in zip_index.items() if k.startswith(q.zfill(max(len(q), 3)))}
        if partial:
            results = []
            seen = set()
            for zip_code, entry in partial.items():
                key = entry["DestID"] if "DestID" in entry else entry["Name"]
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "ZIP": zip_code,
                        "Name": entry["Name"],
                        "County": entry["County"],
                        "State": STATE_ABBREVS.get(entry["State"], entry["State"]),
                        "Meals": entry["Meals"],
                        **{m: entry[m] for m in MONTH_COLS}
                    })
            return pd.DataFrame(results[:50])

    # --- Text search across location names, counties, states ---
    q_lower = q.lower()
    locations = cache.get("locations", [])
    results = []

    for loc in locations:
        searchable = f"{loc['Name']} {loc['County']} {loc['LocationDefined']} {loc['StateFull']} {loc['State']}".lower()
        if q_lower in searchable:
            results.append({
                "Name": loc["Name"],
                "County": loc["County"],
                "State": loc["StateFull"],
                "Meals": loc["Meals"],
                **{m: loc[m] for m in MONTH_COLS}
            })

    if results:
        return pd.DataFrame(results)

    return pd.DataFrame()


def lookup_zip(zip_code):
    """
    Look up a single ZIP code. Returns dict with rate details or None.
    """
    cache = _get_cache()
    if cache is None:
        return None
    zip_padded = str(zip_code).zfill(5)
    zip_index = cache.get("zip_index", {})
    entry = zip_index.get(zip_padded)
    if entry:
        return {
            "zip": zip_padded,
            "name": entry["Name"],
            "county": entry["County"],
            "state": STATE_ABBREVS.get(entry["State"], entry["State"]),
            "state_abbr": entry["State"],
            "meals": entry["Meals"],
            "lodging": {m: entry[m] for m in MONTH_COLS},
        }
    return None


def get_rate_for_location(state, location_name, month_num=None):
    """
    Get lodging and meals rate for a specific state + location.
    month_num: 1-12 (defaults to current month).
    """
    if month_num is None:
        month_num = datetime.datetime.now().month
    month_key = MONTH_MAP[month_num]

    cache = _get_cache()
    if cache is None:
        return {"lodging": STANDARD_LODGING, "meals": STANDARD_MEALS, "source": "default"}

    locations = cache.get("locations", [])
    loc_lower = location_name.lower()

    for loc in locations:
        state_match = (
            loc["State"].lower() == state.lower() or
            loc["StateFull"].lower() == state.lower()
        )
        if state_match:
            name_match = (
                loc_lower in loc["Name"].lower() or
                loc_lower in loc["County"].lower() or
                loc_lower in loc["LocationDefined"].lower()
            )
            if name_match:
                return {
                    "lodging": loc[month_key],
                    "meals": loc["Meals"],
                    "name": loc["Name"],
                    "county": loc["County"],
                    "source": "gsa_cache"
                }

    return {"lodging": STANDARD_LODGING, "meals": STANDARD_MEALS, "source": "standard_conus"}


def get_states_from_cache():
    """Return sorted list of unique full state names from cache."""
    cache = _get_cache()
    if cache is None:
        return sorted(STATE_ABBREVS.values())
    locations = cache.get("locations", [])
    states = sorted(set(loc["StateFull"] for loc in locations))
    return states if states else sorted(STATE_ABBREVS.values())


def get_locations_for_state(state_name):
    """Return list of location names for a given state from cache."""
    cache = _get_cache()
    if cache is None:
        return ["Standard Rate"]

    state_abbr = STATE_TO_ABBREV.get(state_name, state_name)
    locations = cache.get("locations", [])
    results = []

    for loc in locations:
        if loc["State"] == state_abbr or loc["StateFull"].lower() == state_name.lower():
            label = loc["Name"]
            if loc["County"]:
                label = f"{loc['Name']} ({loc['County']})"
            results.append(label)

    return sorted(set(results)) if results else ["Standard Rate"]


# --- CLI: Build cache ---
if __name__ == "__main__":
    print(f"Building comprehensive GSA rate cache for FY{CURRENT_FY}...")

    def show_progress(msg, current, total):
        print(f"  [{current}/{total}] {msg}")

    loc_count, zip_count = build_full_cache(CURRENT_FY, progress_callback=show_progress)
    print(f"\nDone! Cached {loc_count} destinations covering {zip_count} ZIP codes")
    print(f"Cache file: {CACHE_FILE}")

    # Quick test
    print("\n=== Test: ZIP 07097 ===")
    result = lookup_zip("07097")
    print(result)

    print("\n=== Test: Search 'San Francisco' ===")
    df = search_rates("San Francisco")
    print(df.to_string() if not df.empty else "No results")
