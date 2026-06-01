import streamlit as st
import matplotlib.pyplot as plt
from assignment import run_assignment, export_to_sheets

st.set_page_config(
    page_title="Guide Assignment System",
    page_icon="🗺️",
    layout="wide",
)

st.title("🗺️ Guide Assignment System")
st.caption("Sistem penugasan guide otomatis dari Google Sheets")

st.divider()

if st.button("▶ Generate Assignment", type="primary", use_container_width=True):
    with st.spinner("Memuat data dari Google Sheets..."):
        try:
            assignment_df = run_assignment()
            st.session_state["assignment_df"] = assignment_df
            st.success(f"✅ Berhasil memproses **{len(assignment_df)}** jadwal.")
        except Exception as e:
            st.error(f"❌ Error saat generate: {e}")
            st.exception(e)

if "assignment_df" in st.session_state:
    assignment_df = st.session_state["assignment_df"]

    st.subheader("Hasil Penugasan")
    st.dataframe(assignment_df, use_container_width=True)

    st.subheader("Statistik")
    total_jadwal = len(assignment_df)
    tidak_ada    = (assignment_df["GUIDE_DITUGASKAN"] == "TIDAK ADA GUIDE").sum()
    berhasil     = total_jadwal - tidak_ada
    guide_unik   = assignment_df[
        assignment_df["GUIDE_DITUGASKAN"] != "TIDAK ADA GUIDE"
    ]["GUIDE_DITUGASKAN"].nunique()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Jadwal", total_jadwal)
    c2.metric("Berhasil Ditugaskan", berhasil)
    c3.metric("Guide Terlibat", guide_unik)

    st.subheader("Distribusi Penugasan Guide")
    guide_stats = (
        assignment_df[
            assignment_df["GUIDE_DITUGASKAN"] != "TIDAK ADA GUIDE"
        ]["GUIDE_DITUGASKAN"].value_counts()
    )
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(guide_stats.index, guide_stats.values, color="#4C72B0")
    ax.set_xlabel("Guide")
    ax.set_ylabel("Jumlah Penugasan")
    ax.set_title("Distribusi Penugasan Guide")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    st.pyplot(fig)

    st.subheader("Total Penugasan per Guide")
    summary_df = (
        assignment_df[assignment_df["GUIDE_DITUGASKAN"] != "TIDAK ADA GUIDE"]
        .groupby("GUIDE_DITUGASKAN")
        .agg(
            Total_Penugasan=("GUIDE_DITUGASKAN", "count"),
            Rating=("RATING", "first"),
        )
        .reset_index()
        .rename(columns={"GUIDE_DITUGASKAN": "Guide"})
        .sort_values("Total_Penugasan", ascending=False)
        .reset_index(drop=True)
    )
    summary_df.index += 1
    st.dataframe(summary_df, use_container_width=True)

    st.divider()

    st.subheader("Export ke Google Sheets")
    if st.button("📤 Tulis ke Sheet 'Penugasan'", use_container_width=True):
        with st.spinner("Menulis ke Google Sheets..."):
            try:
                export_to_sheets(assignment_df)
                st.success("✅ Data berhasil ditulis ke Google Sheets!")
            except Exception as e:
                st.error(f"❌ Gagal export: {e}")
                st.exception(e)
