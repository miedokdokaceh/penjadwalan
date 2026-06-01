import pandas as pd
import re
from datetime import datetime
from urllib.parse import quote
import gspread
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
import streamlit as st


# =========================================================
# AUTH — Service Account (ganti dari google.colab.auth)
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
            "service_account.json",
            scopes=scope,
        )

    return gspread.authorize(creds)


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def extract_day_shift(text):
    parts = str(text).split(",")
    if parts:
        date_part = parts[0].strip()
        date_subparts = date_part.split(" ")
        if len(date_subparts) > 1:
            day = date_subparts[1]
        else:
            day = "UNKNOWN_DAY"
    else:
        day = "UNKNOWN_DAY"
    return day


def format_unavailability_slot_for_guides(slot_name_gs):
    return slot_name_gs.replace(" - ", "-")


def get_unavailability_string_from_gs(row):
    unavailable_slots = []
    day_shift_columns_gs = [
        col for col in row.index if "AM" in col or "PM" in col
    ]
    for col in day_shift_columns_gs:
        if pd.notna(row[col]) and str(row[col]).strip().lower() == "x":
            formatted_slot = format_unavailability_slot_for_guides(col)
            unavailable_slots.append(formatted_slot)
    return ",".join(unavailable_slots)


def extract_date(text):
    match = re.search(r"(\d{1,2})\s(\w+)\s(\w+)\s(\d{4})", str(text))
    if match:
        day_num = match.group(1)
        indo_month = match.group(3)
        year = match.group(4)
        month_map = {
            "Januari": "January", "Februari": "February", "Maret": "March",
            "April": "April", "Mei": "May", "Juni": "June",
            "Juli": "July", "Agustus": "August", "September": "September",
            "Oktober": "October", "November": "November", "Desember": "December",
        }
        translated_month = month_map.get(indo_month, indo_month)
        date_str = f"{day_num} {translated_month} {year}"
        return datetime.strptime(date_str, "%d %B %Y")
    return None


# =========================================================
# MAIN FUNCTION
# =========================================================

def run_assignment():
    SPREADSHEET_ID = "1oYpIm7qRNS69oWxgWPVPx1eOywvOsanr2VLaH7_pnSY"
    GS_UNAVAILABILITY_ID = "1jS8KUIYfCHAHafgibzr74GwCEBQvaObHSgoCqRiyGCA"
    GS_RATING_ID = "1jS8KUIYfCHAHafgibzr74GwCEBQvaObHSgoCqRiyGCA"

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
    dashboard["DATE"] = dashboard["TANGGAL & RUTE"].apply(extract_date)
    dashboard = dashboard[dashboard["DATE"].notna()].copy()
    dashboard["DAY_SHIFT"] = dashboard["TANGGAL & RUTE"].apply(extract_day_shift)
    dashboard["WEEK"] = dashboard["DATE"].dt.isocalendar().week
    dashboard = dashboard.sort_values(by="DATE", ascending=True).reset_index(drop=True)

    # ---- Load Unavailability ----
    encoded_sheet = quote("CHECK UNAVAILABILITY MONTHLY")
    csv_url_unavailability = (
        f"https://docs.google.com/spreadsheets/d/{GS_UNAVAILABILITY_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={encoded_sheet}"
    )
    unavailability_gs = pd.read_csv(csv_url_unavailability, header=16)
    guides_from_gs = unavailability_gs.copy()
    guides_from_gs = guides_from_gs.rename(columns={"Guide": "Name"})
    guides_from_gs["Rating"] = 3.0
    guides_from_gs["Unavailability"] = guides_from_gs.apply(
        get_unavailability_string_from_gs, axis=1
    )
    guides = guides_from_gs[["Name", "Rating", "Unavailability"]].copy()

    # ---- Load Rating ----
    encoded_rating = quote("RATING GUIDE")
    csv_url_rating = (
        f"https://docs.google.com/spreadsheets/d/{GS_RATING_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={encoded_rating}"
    )
    ratings_gs = pd.read_csv(csv_url_rating, header=0)
    ratings_gs = ratings_gs[["Guide", "MAY RATING GUIDE (1-10)"]].copy()
    ratings_gs = ratings_gs.rename(
        columns={"Guide": "Name", "MAY RATING GUIDE (1-10)": "Rating"}
    )
    ratings_gs["Rating"] = ratings_gs["Rating"].astype(float)
    guides = pd.merge(
        guides.drop(columns=["Rating"]),
        ratings_gs[["Name", "Rating"]],
        on="Name",
        how="left",
    )
    guides["Rating"] = guides["Rating"].fillna(3.0)
    guides["Unavailability"] = guides["Unavailability"].fillna("").astype(str)

    # ---- Guide Dictionary ----
    guide_dict = {}
    for _, row in guides.iterrows():
        unavailable = [
            x.strip() for x in row["Unavailability"].split(",") if x.strip()
        ]
        guide_dict[row["Name"]] = {
            "rating": float(row["Rating"]),
            "unavailable": unavailable,
            "assigned_count": 0,
        }

    # ---- Assignment Process ----
    all_assignment_results = []
    weeks = sorted(dashboard["WEEK"].dropna().unique())

    for current_week in weeks:
        dashboard_week = dashboard[dashboard["WEEK"] == current_week].copy()
        dashboard_week = dashboard_week.sort_values(
            by="DATE", ascending=True
        ).reset_index(drop=True)

        for guide in guide_dict:
            guide_dict[guide]["assigned_count"] = 0

        assignment_output = []

        for _, row in dashboard_week.iterrows():
            jadwal = row["TANGGAL & RUTE"]
            feasible_guides = []

            for guide, info in guide_dict.items():
                slot = row["DAY_SHIFT"]
                available = slot not in info["unavailable"]
                if available:
                    rating = info["rating"]
                    k = info["assigned_count"]
                    weight = rating / (k + 1)
                    feasible_guides.append({
                        "guide": guide,
                        "rating": rating,
                        "weight": weight,
                        "k": k,
                    })

            if len(feasible_guides) == 0:
                assignment_output.append({
                    "WEEK": str(current_week),
                    "JADWAL": jadwal,
                    "GUIDE_DITUGASKAN": "TIDAK ADA GUIDE",
                    "RATING": "",
                    "k_i": "",
                    "BOBOT": "",
                    "TOTAL_DITUGASKAN": "0",
                })
                continue

            chosen = max(feasible_guides, key=lambda x: x["weight"])
            guide_dict[chosen["guide"]]["assigned_count"] += 1
            total_ditugaskan = str(guide_dict[chosen["guide"]]["assigned_count"])

            assignment_output.append({
                "WEEK": str(current_week),
                "JADWAL": jadwal,
                "GUIDE_DITUGASKAN": chosen["guide"],
                "RATING": chosen["rating"],
                "k_i": chosen["k"],
                "BOBOT": round(chosen["weight"], 3),
                "TOTAL_DITUGASKAN": total_ditugaskan,
            })

        assignment_df_week = pd.DataFrame(assignment_output)
        all_assignment_results.append(assignment_df_week)

    # ---- Gabung & Sort ----
    assignment_df = pd.concat(all_assignment_results, ignore_index=True)
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
