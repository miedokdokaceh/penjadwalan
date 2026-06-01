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

col1, col2 = st.columns([2, 1])

with col1:
    st.subheader("Generate Penugasan")
    st.write(
        "Klik tombol di bawah untuk memproses data dari Google Sheets "
        "dan menghasilkan penugasan guide secara otomatis."
    )

with col2:
    st.subheader("Status")
    status_box = st.empty()
    status_box.info("Belum ada proses yang dijalankan.")

st.divider()

if st.button("▶ Generate Assignment", type="primary", use_container_width=True):

    with st.spinner("Memuat data dari Google Sheets..."):
        try:
            assignment_df = run_assignment()
            st.session_state["assignment_df"] = assignment_df
            status_box.success("✅ Assignment berhasil dibuat!")
        except Exception as e:
            status_box.error(f"❌ Error: {e}")
            st.exception(e)
            st.stop()

    st.success(f"✅ Berhasil memproses **{len(assignment_df)}** jadwal.")

    # ---- Tabel hasil ----
    st.subheader("Hasil Penugasan")
    st.dataframe(assignment_df, use_container_width=True)

    # ---- Statistik ringkas ----
    st.subheader("Statistik")
    total_jadwal = len(assignment_df)
    tidak_ada = (assignment_df["GUIDE_DITUGASKAN"] == "TIDAK ADA GUIDE").sum()
    berhasil = total_jadwal - tidak_ada
    guide_unik = assignment_df[
        assignment_df["GUIDE_DITUGASKAN"] != "TIDAK ADA GUIDE"
    ]["GUIDE_DITUGASKAN"].nunique()

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Jadwal", total_jadwal)
    c2.metric("Berhasil Ditugaskan", berhasil)
    c3.metric("Guide Terlibat", guide_unik)

    # ---- Visualisasi distribusi ----
    st.subheader("Distribusi Penugasan Guide")
    guide_stats = (
        assignment_df[
            assignment_df["GUIDE_DITUGASKAN"] != "TIDAK ADA GUIDE"
        ]["GUIDE_DITUGASKAN"]
        .value_counts()
    )
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(guide_stats.index, guide_stats.values, color="#4C72B0")
    ax.set_xlabel("Guide")
    ax.set_ylabel("Jumlah Penugasan")
    ax.set_title("Distribusi Penugasan Guide")
    plt.xticks(rotation=45, ha="right")
    plt.tight_layout()
    st.pyplot(fig)

    st.divider()

    # ---- Export ke Sheets ----
    st.subheader("Export ke Google Sheets")
    if st.button("📤 Tulis ke Sheet 'Penugasan'", use_container_width=True):
        with st.spinner("Menulis ke Google Sheets..."):
            try:
                export_to_sheets(assignment_df)
                st.success("✅ Data berhasil ditulis ke Google Sheets!")
            except Exception as e:
                st.error(f"❌ Gagal export: {e}")
                st.exception(e)

# Kalau sudah ada hasil di session, tampilkan ulang tanpa generate ulang
elif "assignment_df" in st.session_state:
    st.info("Data assignment terakhir masih tersimpan. Generate ulang untuk refresh.")
    st.dataframe(st.session_state["assignment_df"], use_container_width=True)
