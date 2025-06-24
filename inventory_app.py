import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO

# --- Cached Data Loading Functions ---
@st.cache_data(ttl=3600, show_spinner=False)
def load_endcaps_data(uploaded_file):
    """Cached function to load endcaps data"""
    return pd.read_excel(uploaded_file, sheet_name="Sheet1")

@st.cache_data(ttl=3600, show_spinner=False)
def load_open_space_data(uploaded_file):
    """Cached function to load open space data"""
    return pd.read_excel(uploaded_file, sheet_name="Sheet1")

def parse_batch(batch):
    if isinstance(batch, str) and len(batch) >= 10:
        batch_prefix = batch[:2]
        try:
            year = int("20" + batch[-2:])
            week = int(batch[-4:-2])
            batch_date = datetime.strptime(f"{year}-W{week}-1", "%Y-W%W-%w")
            return batch_prefix, batch_date
        except ValueError:
            return batch_prefix, pd.NaT
    return None, pd.NaT

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="Inventory Consolidation Tool")
st.title("📦 Advanced Inventory Processor")

def validate_excel_file(uploaded_file):
    """Helper function to validate Excel files"""
    if uploaded_file is None:
        return None
    if not uploaded_file.name.lower().endswith('.xlsx'):
        st.error(f"Invalid file type: {uploaded_file.name}. Please upload an .xlsx file")
        return None
    return uploaded_file

# File Upload with custom validation
with st.expander("📂 STEP 1: Upload Files", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        endcaps_file = st.file_uploader(
            "Endcaps File", 
            type=None,
            help="Upload the Endcaps inventory Excel file (.xlsx)"
        )
        endcaps_file = validate_excel_file(endcaps_file)
        
    with col2:
        open_space_file = st.file_uploader(
            "Open Space File", 
            type=None,
            help="Upload the Open Space inventory Excel file (.xlsx)"
        )
        open_space_file = validate_excel_file(open_space_file)

# Only proceed if both files are valid
if endcaps_file and open_space_file:
    try:
        # Load data with caching
        with st.spinner("Loading Endcaps data..."):
            endcaps_df = load_endcaps_data(endcaps_file).copy()
        with st.spinner("Loading Open Space data..."):
            open_space_df = load_open_space_data(open_space_file).copy()
        
        # Get storage types from data
        storage_types = sorted(endcaps_df["Storage Type"].dropna().unique())
        move_into_types = sorted(open_space_df["Storage Type"].dropna().unique())
        
        # Configuration
        with st.expander("⚙️ STEP 2: Configure Filters", expanded=True):
            cols = st.columns(2)
            with cols[0]:
                selected_types = st.multiselect(
                    "Filter these storage types (Endcaps):",
                    options=storage_types,
                    default=storage_types,
                    help="Only process these storage types from Endcaps",
                    key="endcap_types_filter"
                )
            with cols[1]:
                move_into_types = st.multiselect(
                    "Move into these storage types (Open Space):",
                    options=move_into_types,
                    default=move_into_types,
                    help="Only consider these storage types in Open Space",
                    key="openspace_types_filter"
                )
        
        if st.button("🚀 Process Files", type="primary", help="Run the consolidation algorithm"):
            with st.spinner("Crunching numbers..."):
                # --- CORE PROCESSING (ORIGINAL ALGORITHM) ---
                open_space_df = open_space_df[open_space_df["Storage Type"] != "VIR"].copy()
                endcaps_df = endcaps_df[endcaps_df["Storage Type"].isin(selected_types)].copy()
                
                # Calculate SU count per storage bin
                endcaps_df["Storage Unit"] = endcaps_df["Storage Unit"].astype(str).str.strip()
                endcaps_df["Storage Bin"] = endcaps_df["Storage Bin"].astype(str).str.strip()
                su_count_per_bin = endcaps_df.groupby("Storage Bin")["Storage Unit"].nunique().reset_index()
                su_count_per_bin.columns = ["Storage Bin", "Total Unique SU Count"]
                endcaps_df = endcaps_df.merge(su_count_per_bin, on="Storage Bin", how="left")
                endcaps_df.sort_values("Total Unique SU Count", ascending=True, inplace=True)
                
                open_space_df.sort_values("SU Count", ascending=False, inplace=True)
                
                # Standardize and parse batches
                endcaps_df["Material"] = endcaps_df["Material"].astype(str).str.strip()
                open_space_df["Material Number"] = open_space_df["Material Number"].astype(str).str.strip()
                endcaps_df["Batch"] = endcaps_df["Batch"].astype(str).str.strip()
                open_space_df["Batch Number"] = open_space_df["Batch Number"].astype(str).str.strip()
                
                endcaps_df[["Batch Prefix", "Batch Date"]] = endcaps_df["Batch"].apply(parse_batch).apply(pd.Series)
                open_space_df[["Batch Prefix", "Batch Date"]] = open_space_df["Batch Number"].apply(parse_batch).apply(pd.Series)
                
                endcaps_df["Batch Date"] = pd.to_datetime(endcaps_df["Batch Date"], errors='coerce')
                open_space_df["Batch Date"] = pd.to_datetime(open_space_df["Batch Date"], errors='coerce')
                
                # --- DYNAMIC ASSIGNMENT LOGIC (UNCHANGED) ---
                assignments = []
                summary_data = []
                used_source_bins = set()
                excluded_target_bins = set()
                
                available_bins = open_space_df[
                    open_space_df["Storage Type"].isin(move_into_types) & 
                    (open_space_df["Utilization %"] < 100) &
                    (open_space_df["Avail SU"] > 0) &
                    (~open_space_df["Storage Bin"].isin(excluded_target_bins))
                ].copy()
                
                sorted_endcap_bins = endcaps_df.groupby("Storage Bin").first().sort_values("Total Unique SU Count").index
                
                for storage_bin in sorted_endcap_bins:
                    if storage_bin in used_source_bins:
                        continue
                        
                    bin_group = endcaps_df[endcaps_df["Storage Bin"] == storage_bin]
                    total_su_in_bin = bin_group["Total Unique SU Count"].iloc[0]
                    
                    matching_bins = available_bins[
                        (available_bins["Material Number"] == bin_group["Material"].iloc[0]) & 
                        (available_bins["Batch Prefix"] == bin_group["Batch Prefix"].iloc[0]) & 
                        (available_bins["Storage Bin"] != storage_bin) &
                        (available_bins["Avail SU"] >= total_su_in_bin)
                    ].copy()
                    
                    matching_bins = matching_bins.dropna(subset=["Batch Date"])
                    
                    for _, open_space_bin in matching_bins.iterrows():
                        valid_match = True
                        for _, su_row in bin_group.iterrows():
                            su_batch_date = su_row["Batch Date"]
                            if pd.isna(su_batch_date):
                                valid_match = False
                                break
                                
                            date_diffs = abs((matching_bins["Batch Date"] - su_batch_date).dt.days)
                            if any(date_diffs > 364):
                                valid_match = False
                                break
                                
                        if valid_match:
                            if open_space_bin["Avail SU"] - total_su_in_bin < 0:
                                continue
                                
                            target_batches = available_bins[
                                (available_bins["Storage Bin"] == open_space_bin["Storage Bin"]) & 
                                (available_bins["Material Number"] == open_space_bin["Material Number"]) & 
                                (available_bins["Batch Prefix"] == open_space_bin["Batch Prefix"])
                            ]
                            oldest_target = target_batches.loc[target_batches["Batch Date"].idxmin(), "Batch Number"]
                            newest_target = target_batches.loc[target_batches["Batch Date"].idxmax(), "Batch Number"]
                            
                            for _, su_row in bin_group.iterrows():
                                assignments.append([
                                    open_space_bin["Storage Type"],      # 0 - TO STORAGE TYPE
                                    open_space_bin["Storage Bin"],       # 1 - TO LOC
                                    storage_bin,                         # 2 - FROM LOC
                                    su_row["Storage Type"],              # 3 - FROM STORAGE TYPE
                                    su_row["Material"],                  # 4 - Material
                                    oldest_target,                       # 5 - TO BATCH
                                    su_row["Batch"],                     # 6 - FROM BATCH
                                    open_space_bin["SU Capacity"],       # 7 - SU CAPACITY
                                    1,                                   # 8 - SU COUNT
                                    open_space_bin["Avail SU"] - total_su_in_bin, # 9 - AVAILABLE SU
                                    su_row["Storage Unit"],              # 10 - LP#
                                    su_row["Total Stock"]                # 11 - RACK QTY
                                ])
                            
                            oldest_source = bin_group.loc[bin_group["Batch Date"].idxmin(), "Batch"]
                            newest_source = bin_group.loc[bin_group["Batch Date"].idxmax(), "Batch"]
                            summary_data.append([
                                open_space_bin["Storage Type"],          # 0 - TO STORAGE TYPE
                                bin_group["Storage Type"].iloc[0],       # 1 - FROM STORAGE TYPE
                                open_space_bin["Storage Bin"],           # 2 - TO LOC
                                storage_bin,                             # 3 - FROM LOC
                                bin_group["Material"].iloc[0],           # 4 - Material
                                oldest_target,                           # 5 - TO OLDEST BATCH
                                newest_target,                           # 6 - TO NEWEST BATCH
                                oldest_source,                           # 7 - FROM OLDEST BATCH
                                newest_source,                           # 8 - FROM NEWEST BATCH
                                open_space_bin["SU Capacity"],           # 9 - SU CAPACITY
                                open_space_bin["SU Count"],              # 10 - CURRENT SU COUNT
                                open_space_bin["Avail SU"],              # 11 - AVAILABLE SU
                                total_su_in_bin                          # 12 - SUs TO MOVE
                            ])
                            
                            used_source_bins.add(storage_bin)
                            excluded_target_bins.add(storage_bin)
                            available_bins.loc[available_bins["Storage Bin"] == open_space_bin["Storage Bin"], "Avail SU"] -= total_su_in_bin
                            available_bins = available_bins[~available_bins["Storage Bin"].isin(excluded_target_bins)]
                            break
                
                for _, row in available_bins.iterrows():
                    open_space_df.loc[open_space_df["Storage Bin"] == row["Storage Bin"], "Avail SU"] = row["Avail SU"]
                
                # --- OUTPUT GENERATION WITH CORRECT COLUMN ORDERING ---
                if assignments:
                    final_output = pd.DataFrame(
                        data={
                            "FROM STORAGE TYPE": [x[3] for x in assignments],
                            "TO STORAGE TYPE": [x[0] for x in assignments],
                            "Material": [x[4] for x in assignments],
                            "TO BATCH": [x[5] for x in assignments],
                            "FROM BATCH": [x[6] for x in assignments],
                            "SU CAPACITY": [x[7] for x in assignments],
                            "SU COUNT": [x[8] for x in assignments],
                            "AVAILABLE SU": [x[9] for x in assignments],
                            "LP#": [x[10] for x in assignments],
                            "RACK QTY": [x[11] for x in assignments],
                            "FROM LOC": [x[2] for x in assignments],
                            "TO LOC": [x[1] for x in assignments]
                        }
                    )
                    
                    summary_output = pd.DataFrame(
                        data={
                            "FROM STORAGE TYPE": [x[1] for x in summary_data],
                            "TO STORAGE TYPE": [x[0] for x in summary_data],
                            "Material": [x[4] for x in summary_data],
                            "FROM OLDEST BATCH": [x[7] for x in summary_data],
                            "FROM NEWEST BATCH": [x[8] for x in summary_data],
                            "TO OLDEST BATCH": [x[5] for x in summary_data],
                            "TO NEWEST BATCH": [x[6] for x in summary_data],
                            "SU CAPACITY": [x[9] for x in summary_data],
                            "CURRENT SU COUNT": [x[10] for x in summary_data],
                            "AVAILABLE SU": [x[11] for x in summary_data],
                            "SUs TO MOVE": [x[12] for x in summary_data],
                            "FROM LOC": [x[3] for x in summary_data],
                            "TO LOC": [x[2] for x in summary_data]
                        }
                    )
                    
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        final_output.to_excel(writer, sheet_name='Final Assignments', index=False)
                        summary_output.to_excel(writer, sheet_name='Summary Report', index=False)
                        open_space_df.to_excel(writer, sheet_name='Updated Open Space', index=False)
                    output.seek(0)
                    
                    st.success(f"✅ Successfully created {len(assignments)} assignments across {len(summary_data)} target locations!")
                    
                    st.download_button(
                        label="📥 Download Complete Report Package",
                        data=output,
                        file_name="inventory_assignments.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    with st.expander("🔍 View Assignment Details", expanded=False):
                        st.dataframe(final_output.head(20))
                        st.info(f"Showing first 20 of {len(final_output)} assignments")
                        
                    with st.expander("📊 View Summary Report", expanded=False):
                        st.dataframe(summary_output)
                        
                    with st.expander("🔄 View Updated Open Space", expanded=False):
                        st.dataframe(open_space_df.head(20))
                else:
                    st.warning("⚠️ No valid assignments found with current filters and inventory")
                    
    except Exception as e:
        st.error(f"❌ Processing failed: {str(e)}")
        st.exception(e)
