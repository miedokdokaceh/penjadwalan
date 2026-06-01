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
                "Tambahkan [gcp_service_account] di Streamlit Secrets, "
                "atau letakkan service_account.json di folder project."
            )
        creds = Credentials.from_service_account_file(
            "service_account.json", scopes=scope,
        )
    return gspread.authorize(creds)


# =========================================================
# HELPER: ekstrak tanggal dari teks dashboard
# Format: "1 Jumat Mei 2026, PAKUALAMAN (09:00)"
# =========================================================

def extract_date(text):
    # Cari pola: angka hari + nama hari + nama bulan + tahun
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
# "1 Jumat Mei 2026, ..." → 1
# =========================================================

def extract_day_number(text):
    match = re.match(r"(\d{1,2})\s", str(text).strip())
    if match:
        return int(match.group(1))
    return None


# =========================================================
# HELPER: tentukan shift dari jam di teks dashboard
# Format jam: (HH:MM)
# PAGI 06:00-11:59 | SORE 12:00-17:59 | MALAM 18:00-23:59
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
# MAPPING nilai dropdown → shift yang tidak tersedia
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
# HELPER: baca sheet unavailability
#
# Struktur sheet:
#   - Ada beberapa blok tabel (per minggu)
#   - Baris header tiap blok: kolom B = "Guide", kolom C dst = angka tanggal
#   - Baris data: kolom B = nama guide, kolom C dst = nilai P/S/M/TS/PM/SM/PS
#
# Return: { "NamaGuide": { (tanggal_int, "SHIFT"), ... } }
# =========================================================

def parse_unavailability_sheet(spreadsheet_id, sheet_name):
    encoded = quote(sheet_name)
    csv_url = (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={encoded}"
    )
    raw = pd.read_csv(csv_url, header=None, dtype=str)

    unavail = {}  # { guide_name: set of (day_int, shift_str) }

    # Temukan semua baris yang kolom B (index 1) == "Guide" → header tabel
    header_rows = raw.index[
        raw.iloc[:, 1].astype(str).str.strip().str.lower() == "guide"
    ].tolist()

    for h_idx in header_rows:
        header_row = raw.iloc[h_idx]

        # Mapping: kolom index → angka tanggal
        col_to_day = {}
        for col_idx in range(2, len(header_row)):
            val = str(header_row[col_idx]).strip()
            # Ambil hanya yang berupa angka (tanggal 1-31)
            if re.match(r"^\d{1,2}$", val):
                col_to_day[col_idx] = int(val)

        # Baca baris data guide sampai baris kosong / header berikutnya
        for row_idx in range(h_idx + 1, len(raw)):
            guide_name = str(raw.iloc[row_idx, 1]).strip()

            # Berhenti kalau baris kosong atau ketemu header lagi
            if guide_name in ("", "nan") or guide_name.lower() == "guide":
                break

            if guide_name not in unavail:
                unavail[guide_name] = set()

            for col_idx, day_num in col_to_day.items():
                cell_val = str(raw.iloc[row_idx, col_idx]).strip().upper()
                if cell_val in SHIFT_MAP:
                    for shift in SHIFT_MAP[cell_val]:
                        unavail[guide_name].add((day_num, shift))

    return unavail


# =========================================================
# MAIN: jalankan assignment
# =========================================================

def run_assignment():
    SPREADSHEET_ID       = "1oYpIm7qRNS69oWxgWPVPx1eOywvOsanr2VLaH7_pnSY"
    GS_UNAVAILABILITY_ID = "1jS8KUIYfCHAHafgibzr74GwCEBQvaObHSgoCqRiyGCA"
    GS_RATING_ID         = "1jS8KUIYfCHAHafgibzr74GwCEBQvaObHSgoCqRiyGCA"

    # ---- Load Dashboard ----
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
    dashboard["WEEK"] = dashboard["DATE"].dt.isocalendar().week
    dashboard = dashboard.sort_values(by="DATE", ascending=True).reset_index(drop=True)

    # ---- Load Unavailability ----
    unavail_dict = parse_unavailability_sheet(
        GS_UNAVAILABILITY_ID, "CHECK UNAVAILABILITY MONTHLY"
    )

    # ---- Load Rating ----
    encoded_rating = quote("RATING GUIDE")
    csv_url_rating = (
        f"https://docs.google.com/spreadsheets/d/{GS_RATING_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={encoded_rating}"
    )
    ratings_gs = pd.read_csv(csv_url_rating, header=0, dtype=str)

    # Cari kolom rating (judulnya bisa berubah tiap bulan)
    rating_col = [c for c in ratings_gs.columns if "RATING" in c.upper()]
    if not rating_col:
        raise ValueError("Kolom RATING tidak ditemukan di sheet RATING GUIDE")
    rating_col = rating_col[0]

    ratings_gs = ratings_gs[["Guide", rating_col]].copy()
    ratings_gs = ratings_gs.rename(columns={"Guide": "Name", rating_col: "Rating"})
    ratings_gs["Rating"] = pd.to_numeric(ratings_gs["Rating"], errors="coerce")

    # Gabung semua nama guide dari kedua sumber
    all_guide_names = set(unavail_dict.keys()) | set(
        ratings_gs["Name"].dropna().astype(str).tolist()
    )

    guide_dict = {}
    for name in all_guide_names:
        name = str(name).strip()
        if not name or name == "nan":
            continue
        rating_row = ratings_gs[ratings_gs["Name"] == name]
        rating = (
            float(rating_row["Rating"].values[0])
            if len(rating_row) > 0 and not pd.isna(rating_row["Rating"].values[0])
            else 3.0
        )
        guide_dict[name] = {
            "rating": rating,
            "unavailable": unavail_dict.get(name, set()),  # set of (day_int, shift)
            "assigned_count": 0,
        }

    # ---- Assignment Process ----
    all_results = []
    weeks = sorted(dashboard["WEEK"].dropna().unique())

    for current_week in weeks:
        dashboard_week = dashboard[dashboard["WEEK"] == current_week].copy()
        dashboard_week = dashboard_week.sort_values(
            by="DATE", ascending=True
        ).reset_index(drop=True)

        # Reset hitungan tiap minggu
        for guide in guide_dict:
            guide_dict[guide]["assigned_count"] = 0

        assignment_output = []

        for _, row in dashboard_week.iterrows():
            jadwal  = row["TANGGAL & RUTE"]
            day_num = row["DAY_NUM"]
            shift   = row["SHIFT"]

            feasible = []
            for guide, info in guide_dict.items():
                # Cek apakah guide tidak tersedia di (tanggal, shift) ini
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
        by="DATE", ascending=True
    ).reset_index(drop=True)
    assignment_df = assignment_df.drop(columns=["TANGGAL & RUTE"])

    return assignment_df


# =========================================================
# EXPORT KE GOOGLE SHEETS
# =========================================================

def export_to_sheets(assignment_df):
    gc = get_gspread_client()
    SPREADSHEET_ID_EXPORT = "1oYpIm7qRNS69oWxgWPVPx1eOywvOsanr2VLaH7_pnSY"
    sheet_name_export = "Penugasan"

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
