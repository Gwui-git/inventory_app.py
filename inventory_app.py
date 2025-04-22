import streamlit as st
import pandas as pd
from datetime import datetime
import os

# --- Reuse ALL your existing functions ---
def parse_batch(batch):
    # (Keep your exact implementation)
    pass

def is_file_open(file_path):
    # (Keep your exact implementation)
    pass

def process_files(endcaps_df, open_space_df, selected_types, move_into_types):
    # (Keep your ENTIRE existing processing logic)
    # Only change: Replace `messagebox` with `st.error()`/`st.success()`
    return final_output, summary_output, updated_open_space_df

# --- Streamlit UI ---
st.set_page_config(layout="wide")
st.title("📊 Advanced Inventory Consolidation")

# File Upload (with validation)
st.header("1. Upload Files")
col1, col2 = st.columns(2)
with col1:
    endcaps_file = st.file_uploader("Endcaps File", type=["xlsx"], key="endcaps")
with col2:
    open_space_file = st.file_uploader("Open Space File", type=["xlsx"], key="openspace")

# Storage Type Selection (multi-column layout)
st.header("2. Select Storage Types")
storage_types = ["901", "902", "910", "916", "920", "921", "922", "980", "998", "999",
                "DT1", "LT1", "LT2", "LT4", "LT5", "OE1", "OVG", "OVL", "OVP", "OVT",
                "PC1", "PC2", "PC4", "PC5", "PSA", "QAH", "RET", "TB1", "TB2", "TB4",
                "TR1", "TR2", "VIR", "VTL"]

cols = st.columns(4)
storage_vars = {}
for i, stype in enumerate(storage_types):
    with cols[i % 4]:
        storage_vars[stype] = st.checkbox(stype, value=True, key=f"filter_{stype}")

# Move-Into Types (separate section)
st.header("3. Select Storage Types to Move Into")
move_into_cols = st.columns(4)
move_into_vars = {}
for i, stype in enumerate(storage_types):
    with move_into_cols[i % 4]:
        move_into_vars[stype] = st.checkbox(stype, value=True, key=f"moveinto_{stype}")

# Debug Mode
debug_mode = st.checkbox("Enable Debug Logging")

# Process Button
if st.button("🚀 Process Files", type="primary"):
    if not endcaps_file or not open_space_file:
        st.error("Please upload both files!")
    else:
        with st.spinner("Processing..."):
            try:
                # Get selected types
                selected_types = [stype for stype, val in storage_vars.items() if val]
                move_into_types = [stype for stype, val in move_into_vars.items() if val]

                # Read files
                endcaps_df = pd.read_excel(endcaps_file)
                open_space_df = pd.read_excel(open_space_file)

                # Process (your existing logic)
                final, summary, updated = process_files(
                    endcaps_df, open_space_df, 
                    selected_types, move_into_types
                )

                # Show debug log if enabled
                if debug_mode:
                    with open("debug_log.txt") as f:
                        st.text_area("Debug Log", f.read(), height=200)

                # Download buttons
                st.success("Processing complete!")
                st.download_button(
                    "📥 Final Assignments",
                    final.to_csv(index=False),
                    "final_assignments.csv"
                )
                st.download_button(
                    "📥 Summary Report",
                    summary.to_csv(index=False),
                    "summary_assignments.csv"
                )
                st.download_button(
                    "📥 Updated Open Space",
                    updated.to_csv(index=False),
                    "updated_open_space.csv"
                )

            except Exception as e:
                st.error(f"Error: {str(e)}")
                if debug_mode:
                    st.exception(e)