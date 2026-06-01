import pandas as pd
import re
from datetime import datetime
from urllib.parse import quote
import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
import streamlit as st


# =========================================================
# AUTH
# =========================================================

def get_gspread_client():
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            st.secrets["gcp_service_account"],
            scopes=scope,
        )
    else:
        import os
        if not os.path.exists("service_account.json"):
            raise FileNotFoundError(
                "Credentials tidak ditemukan. "
                "Tambahkan [gcp_service_account] di Streamlit Secrets."
            )
        creds = Credentials.from_service_account_file(
            "service_account.json", scopes=scope,
        )
    return gspread.authorize(creds)


# =========================================================
# HELPER: normalisasi nama guide (strip whitespace)
# Dipanggil di semua tempat yang handle nama guide
# =========================================================

def normalize_name(name):
    return str(name).strip()


# =========================================================
# HELPER: ekstrak tanggal dari teks dashboard
# Format: "3 Rabu Juni 2026, KOTABARU (15:30)"
# =========================================================

def extract_date(text):
    match = re.search(r"(\d{1,2})\s+\w+\s+(\w+)\s+(\d{4})", str(text))
    if match:
        day_num    = match.group(1)
        indo_month = match.group(2)
        year       = match.group(3)
        month_map = {
            "Januari": "January", "Februari": "February", "Maret": "March",
            "April": "April", "Mei": "May", "Juni": "June",
            "Juli": "July", "Agustus": "August", "September": "September",
            "Oktober": "October", "November": "November", "Desember": "December",
        }
        translated = month_map.get(indo_month, indo_month)
        try:
            return datetime.strptime(f"{day_num} {translated} {year}", "%d %B %Y")
        except ValueError:
            return None
    return None


# =========================================================
# HELPER: ekstrak angka tanggal dari teks dashboard
# "3 Rabu Juni 2026, ..." → 3
# =========================================================

def extract_day_number(text):
    match = re.match(r"(\d{1,2})\s", str(text).strip())
    if match:
        return int(match.group(1))
    return None


# =========================================================
# HELPER: tentukan shift dari jam di teks dashboard
# "KOTABARU (15:30)" → SORE
# PAGI  = 06:00–11:59
# SORE  = 12:00–17:59
# MALAM = 18:00–23:59
# =========================================================

def extract_shift(text):
    match = re.search(r"\((\d{1,2}):(\d{2})\)", str(text))
    if match:
        hour = int(match.group(1))
        if 6 <= hour < 12:
            return "PAGI"
        elif 12 <= hour < 18:
            return "SORE"
        elif 18 <= hour <= 23:
            return "MALAM"
    return "UNKNOWN"


# =========================================================
# MAPPING dropdown → shift yang TIDAK TERSEDIA
#
# Nilai dropdown di sheet:
#   P  = tidak bisa PAGI
#   S  = tidak bisa SORE
#   M  = tidak bisa MALAM
#   TS = tidak bisa semua (PAGI, SORE, MALAM)
#   PM = tidak bisa PAGI & MALAM
#   SM = tidak bisa SORE & MALAM
#   PS = tidak bisa PAGI & SORE
# =========================================================

SHIFT_MAP = {
    "P":  ["PAGI"],
    "S":  ["SORE"],
    "M":  ["MALAM"],
    "TS": ["PAGI", "SORE", "MALAM"],
    "PM": ["PAGI", "MALAM"],
    "SM": ["SORE", "MALAM"],
    "PS": ["PAGI", "SORE"],
}


# =========================================================
# BACA UNAVAILABILITY via Sheets API (bukan CSV)
#
# Return: { "NamaGuide": { (tanggal_int, "SHIFT"), ... } }
# =========================================================

def parse_unavailability_sheet(gc, spreadsheet_id, sheet_name):
    spreadsheet = gc.open_by_key(spreadsheet_id)
    worksheet   = spreadsheet.worksheet(sheet_name)
    all_values  = worksheet.get_all_values()

    unavail = {}

    header_row_indices = [
        i for i, row in enumerate(all_values)
        if len(row) > 1 and row[1].strip().lower() == "guide"
    ]

    for h_idx in header_row_indices:
        header_row = all_values[h_idx]

        col_to_day = {}
        for col_idx in range(2, len(header_row)):
            val = header_row[col_idx].strip()
            if re.match(r"^\d{1,2}$", val):
                col_to_day[col_idx] = int(val)

        for row_idx in range(h_idx + 1, len(all_values)):
            row = all_values[row_idx]

            if len(row) < 2:
                break
            # FIX 1: normalisasi nama saat baca unavailability
            guide_name = normalize_name(row[1])

            if not guide_name or guide_name.lower() == "guide":
                break

            if guide_name not in unavail:
                unavail[guide_name] = set()

            for col_idx, day_num in col_to_day.items():
                if col_idx >= len(row):
                    continue
                cell_val = row[col_idx].strip().upper()
                if cell_val in SHIFT_MAP:
                    for shift in SHIFT_MAP[cell_val]:
                        unavail[guide_name].add((day_num, shift))

    return unavail


# =========================================================
# HELPER: Load Rating dari sheet RATING GUIDE
# =========================================================

def load_ratings(gc, spreadsheet_id, sheet_name="RATING GUIDE"):
    spreadsheet = gc.open_by_key(spreadsheet_id)
    worksheet   = spreadsheet.worksheet(sheet_name)
    all_values  = worksheet.get_all_values()

    header_idx = None
    for i, row in enumerate(all_values):
        row_upper = [str(c).strip().upper() for c in row]
        if "GUIDE" in row_upper and any("RATING" in c for c in row_upper):
            header_idx = i
            break

    if header_idx is None:
        raise ValueError(
            "Baris header 'Guide' + 'RATING' tidak ditemukan di sheet RATING GUIDE"
        )

    headers   = [str(c).strip() for c in all_values[header_idx]]
    data_rows = all_values[header_idx + 1:]

    ratings_gs = pd.DataFrame(data_rows, columns=headers)
    ratings_gs = ratings_gs[ratings_gs["Guide"].str.strip() != ""].copy()
    ratings_gs = ratings_gs[ratings_gs["Guide"].notna()].copy()

    # FIX 1: normalisasi nama di sheet rating
    ratings_gs["Guide"] = ratings_gs["Guide"].apply(normalize_name)

    rating_col = [c for c in ratings_gs.columns if "RATING" in c.upper()]
    if not rating_col:
        raise ValueError("Kolom RATING tidak ditemukan di sheet RATING GUIDE")
    rating_col = rating_col[0]

    ratings_gs = ratings_gs[["Guide", rating_col]].copy()
    ratings_gs = ratings_gs.rename(columns={"Guide": "Name", rating_col: "Rating"})
    ratings_gs["Rating"] = pd.to_numeric(ratings_gs["Rating"], errors="coerce")

    return ratings_gs


# =========================================================
# MAIN: jalankan assignment
# =========================================================

def run_assignment():
    SPREADSHEET_ID       = "1oYpIm7qRNS69oWxgWPVPx1eOywvOsanr2VLaH7_pnSY"
    GS_UNAVAILABILITY_ID = "1jS8KUIYfCHAHafgibzr74GwCEBQvaObHSgoCqRiyGCA"
    GS_RATING_ID         = "1jS8KUIYfCHAHafgibzr74GwCEBQvaObHSgoCqRiyGCA"

    gc = get_gspread_client()

    # ---- Load Dashboard via CSV ----
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet=DASHBOARD"
    )
    dashboard = pd.read_csv(csv_url, header=1)
    dashboard = dashboard[dashboard["SUDAH DIKIRIM"].notna()].copy()
    dashboard = dashboard[
        dashboard["SUDAH DIKIRIM"].astype(str).str.strip() != ""
    ]
    dashboard["DATE"]    = dashboard["TANGGAL & RUTE"].apply(extract_date)
    dashboard["DAY_NUM"] = dashboard["TANGGAL & RUTE"].apply(extract_day_number)
    dashboard["SHIFT"]   = dashboard["TANGGAL & RUTE"].apply(extract_shift)
    dashboard = dashboard[dashboard["DATE"].notna()].copy()

    # FIX 2: buang baris yang DAY_NUM atau SHIFT tidak terbaca
    # Kalau DAY_NUM None → (None, shift) tidak akan pernah cocok dengan unavailability
    # sehingga guide tetap di-assign walau harusnya tidak bisa
    dashboard = dashboard[dashboard["DAY_NUM"].notna()].copy()
    dashboard = dashboard[dashboard["SHIFT"] != "UNKNOWN"].copy()

    dashboard["WEEK"] = dashboard["DATE"].dt.isocalendar().week
    dashboard = dashboard.sort_values("DATE", ascending=True).reset_index(drop=True)

    # ---- Load Unavailability via Sheets API ----
    unavail_dict = parse_unavailability_sheet(
        gc, GS_UNAVAILABILITY_ID, "CHECK UNAVAILABILITY MONTHLY"
    )

    # ---- Load Rating via Sheets API ----
    ratings_gs = load_ratings(gc, GS_RATING_ID, "RATING GUIDE")

    # ---- Buat guide_dict ----
    all_guide_names = set(unavail_dict.keys()) | set(
        ratings_gs["Name"].dropna().apply(normalize_name).tolist()
    )

    guide_dict = {}
    for name in all_guide_names:
        name = normalize_name(name)
        if not name or name == "nan":
            continue

        # FIX 1: normalisasi nama saat lookup rating
        rating_row = ratings_gs[ratings_gs["Name"] == name]
        if len(rating_row) > 0 and not pd.isna(rating_row["Rating"].values[0]):
            rating = float(rating_row["Rating"].values[0])
        else:
            rating = 3.0

        guide_dict[name] = {
            "rating":         rating,
            "unavailable":    unavail_dict.get(name, set()),
            "assigned_count": 0,
        }

    # ---- Assignment Process ----
    all_results = []
    weeks = sorted(dashboard["WEEK"].dropna().unique())

    for current_week in weeks:
        dashboard_week = dashboard[dashboard["WEEK"] == current_week].copy()
        dashboard_week = dashboard_week.sort_values(
            "DATE", ascending=True
        ).reset_index(drop=True)

        for guide in guide_dict:
            guide_dict[guide]["assigned_count"] = 0

        assignment_output = []

        for _, row in dashboard_week.iterrows():
            jadwal  = row["TANGGAL & RUTE"]
            # FIX 2: cast ke int agar (3, "SORE") bukan (3.0, "SORE")
            day_num = int(row["DAY_NUM"])
            shift   = row["SHIFT"]

            feasible = []
            for guide, info in guide_dict.items():
                is_unavailable = (day_num, shift) in info["unavailable"]
                if not is_unavailable:
                    k      = info["assigned_count"]
                    rating = info["rating"]
                    weight = rating / (k + 1)
                    feasible.append({
                        "guide":  guide,
                        "rating": rating,
                        "weight": weight,
                        "k":      k,
                    })

            if not feasible:
                assignment_output.append({
                    "WEEK":             str(current_week),
                    "JADWAL":           jadwal,
                    "SHIFT":            shift,
                    "GUIDE_DITUGASKAN": "TIDAK ADA GUIDE",
                    "RATING":           "",
                    "k_i":              "",
                    "BOBOT":            "",
                    "TOTAL_DITUGASKAN": "0",
                })
                continue

            chosen = max(feasible, key=lambda x: x["weight"])
            guide_dict[chosen["guide"]]["assigned_count"] += 1

            assignment_output.append({
                "WEEK":             str(current_week),
                "JADWAL":           jadwal,
                "SHIFT":            shift,
                "GUIDE_DITUGASKAN": chosen["guide"],
                "RATING":           chosen["rating"],
                "k_i":              chosen["k"],
                "BOBOT":            round(chosen["weight"], 3),
                "TOTAL_DITUGASKAN": str(guide_dict[chosen["guide"]]["assigned_count"]),
            })

        all_results.append(pd.DataFrame(assignment_output))

    # ---- Gabung & Sort ----
    assignment_df = pd.concat(all_results, ignore_index=True)
    assignment_df = assignment_df.merge(
        dashboard[["TANGGAL & RUTE", "DATE"]],
        left_on="JADWAL",
        right_on="TANGGAL & RUTE",
        how="left",
    )
    assignment_df = assignment_df.sort_values(
        "DATE", ascending=True
    ).reset_index(drop=True)
    assignment_df = assignment_df.drop(columns=["TANGGAL & RUTE"])

    return assignment_df


# =========================================================
# EXPORT KE GOOGLE SHEETS
# =========================================================

def export_to_sheets(assignment_df):
    gc = get_gspread_client()
    SPREADSHEET_ID_EXPORT = "1oYpIm7qRNS69oWxgWPVPx1eOywvOsanr2VLaH7_pnSY"
    sheet_name_export     = "Penugasan"

    spreadsheet = gc.open_by_key(SPREADSHEET_ID_EXPORT)
    try:
        worksheet = spreadsheet.worksheet(sheet_name_export)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=sheet_name_export, rows=5000, cols=20
        )

    worksheet.clear()
    set_with_dataframe(
        worksheet=worksheet,
        dataframe=assignment_df,
        include_index=False,
        include_column_header=True,
        resize=True,
    )
