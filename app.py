import streamlit as st
import pandas as pd
from sqlalchemy import select

from models import SessionLocal, Regulation, RegulationLink

# new website monitoring modules
from web_monitor import discover_articles
from web_ingest import ingest_web_article

st.set_page_config(page_title="RegTracker", layout="wide")

st.title("Maritime Regulation Tracker")

st.caption(
    "Automated monitoring of regulatory sources (DNV, IMO, EU etc.) "
    "with AI-assisted extraction."
)

# ----------------------------------------------------
# DATABASE QUERY
# ----------------------------------------------------

def load_regulations():

    with SessionLocal() as s:

        regs = s.execute(
            select(Regulation)
        ).scalars().all()

        data = []

        for r in regs:

            data.append(
                {
                    "ID": r.id,
                    "Title": r.title,
                    "Source": r.source,
                    "Jurisdiction": r.jurisdiction,
                    "Category": r.category,
                    "Status": r.status,
                    "Summary": r.summary,
                }
            )

        return pd.DataFrame(data)


# ----------------------------------------------------
# DASHBOARD
# ----------------------------------------------------

st.header("Regulation Dashboard")

df = load_regulations()

if len(df) == 0:
    st.info("No regulations in database yet.")

else:

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Regulations", len(df))

    with col2:
        st.metric("Open", len(df[df["Status"] == "Open"]))

    with col3:
        st.metric("Closed", len(df[df["Status"] == "Closed"]))

    st.dataframe(df, use_container_width=True)


# ----------------------------------------------------
# WEBSITE MONITOR
# ----------------------------------------------------

st.divider()
st.header("Regulatory Website Monitor")

st.caption(
    "Scans regulatory websites such as DNV technical regulatory news, "
    "IMO updates and EU maritime announcements."
)

if st.button("Scan Regulatory Websites"):

    with st.spinner("Scanning sources..."):

        items = discover_articles()

        new_items = 0

        for item in items:

            created = ingest_web_article(item)

            if created:
                new_items += 1

    st.success(f"{new_items} new regulatory updates discovered.")


# ----------------------------------------------------
# REGULATION DETAIL VIEW
# ----------------------------------------------------

st.divider()
st.header("Regulation Detail")

selected_id = st.number_input("Enter regulation ID", min_value=1, step=1)

if st.button("Load Regulation"):

    with SessionLocal() as s:

        reg = s.get(Regulation, selected_id)

        if not reg:
            st.error("Regulation not found")

        else:

            st.subheader(reg.title)

            st.write("Source:", reg.source)
            st.write("Jurisdiction:", reg.jurisdiction)
            st.write("Category:", reg.category)
            st.write("Status:", reg.status)

            st.markdown("### Summary")
            st.write(reg.summary)

            links = s.execute(
                select(RegulationLink).where(
                    RegulationLink.regulation_id == reg.id
                )
            ).scalars().all()

            if links:

                st.markdown("### Links")

                for link in links:

                    st.markdown(f"- [{link.title}]({link.url})")


# ----------------------------------------------------
# MANUAL INGESTION
# ----------------------------------------------------

st.divider()
st.header("Manual Regulation Entry")

with st.form("manual_regulation_form"):

    title = st.text_input("Title")
    source = st.text_input("Source")
    jurisdiction = st.text_input("Jurisdiction")
    category = st.text_input("Category")
    summary = st.text_area("Summary")

    submit = st.form_submit_button("Create Regulation")

    if submit:

        with SessionLocal() as s:

            reg = Regulation(
                title=title,
                source=source,
                jurisdiction=jurisdiction,
                category=category,
                summary=summary,
                status="Open",
            )

            s.add(reg)
            s.commit()

        st.success("Regulation created successfully")


# ----------------------------------------------------
# REFRESH BUTTON
# ----------------------------------------------------

st.divider()

if st.button("Refresh Dashboard"):
    st.experimental_rerun()
