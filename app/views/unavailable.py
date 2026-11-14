"""Shown at the URLs of pages that were removed (Operational Impact, Data Quality), so an
old link or bookmark gets a message instead of an error. Their metrics functions, SQL
views and tests are kept so the pages can come back."""

import streamlit as st

st.info("This page isn't available.", icon="🚧")
