import streamlit as st
import pandas as pd
from datetime import datetime
import io

# --- Function Definitions ---
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

def create_download_links(final_output, summary_output, updated_open_space):
    """Create download links for all output files"""
    towrite = io.BytesIO()
    with pd.ExcelWriter(towrite, engine='openpyxl') as writer:
        final_output.to_excel(writer, sheet_name='Assignments', index=False)
        summary_output.to_excel(writer, sheet_name='Summary', index=False)
        updated_open_space.to_excel(writer, sheet_name='Updated_Open_Space', index=False)
    towrite.seek(0)
    return towrite

# --- Streamlit UI ---
st.set_page_config(layout="wide", page_title="Inventory Consolidation Tool")
st.title("📦 Inventory Consolidation Processor")

# File Upload
st.header("1. Upload Files")
col1, col2 = st.columns(2)
with col1:
    endcaps_file = st.file_uploader("Endcaps File", type=["xlsx"], key="endcaps")
with col2:
    open_space_file = st.file_uploader("Open Space File", type=["xlsx"], key="openspace")

if endcaps_file and open_space_file:
    try:
        endcaps_df = pd.read_excel(endcaps_file, sheet_name="Sheet1")
        open_space_df = pd.read_excel(open_space_file, sheet_name="Sheet1")
    except Exception as e:
        st.error(f"❌ Failed to read Excel files: {str(e)}")
        st.stop()

    # Get unique storage types
    storage_types = sorted(endcaps_df["Storage Type"].dropna().unique())
    move_into_types = sorted(open_space_df["Storage Type"].dropna().unique())

    # Selection UI
    st.header("2. Configure Filters")
    with st.expander("Storage Type Filters"):
        cols = st.columns(2)
        with cols[0]:
            selected_types = st.multiselect(
                "Storage Types to FILTER (Endcaps)",
                options=storage_types,
                default=storage_types
            )
        with cols[1]:
            move_into_types = st.multiselect(
                "Storage Types to MOVE INTO (Open Space)",
                options=move_into_types,
                default=move_into_types
            )

    if st.button("🚀 Process Files", type="primary"):
        with st.spinner("Processing data..."):
            try:
                # --- Processing Pipeline ---
                # 1. Filter VIR locations
                open_space_df = open_space_df[open_space_df["Storage Type"] != "VIR"].copy()
                
                # 2. Filter Endcaps by selected types
                endcaps_df = endcaps_df[endcaps_df["Storage Type"].isin(selected_types)].copy()
                
                # 3. Calculate SU counts per bin
                endcaps_df["Storage Unit"] = endcaps_df["Storage Unit"].astype(str).str.strip()
                endcaps_df["Storage Bin"] = endcaps_df["Storage Bin"].astype(str).str.strip()
                su_count_per_bin = endcaps_df.groupby("Storage Bin")["Storage Unit"].nunique().reset_index()
                su_count_per_bin.columns = ["Storage Bin", "Total Unique SU Count"]
                endcaps_df = endcaps_df.merge(su_count_per_bin, on="Storage Bin", how="left")
                endcaps_df.sort_values("Total Unique SU Count", inplace=True)
                
                # 4. Sort Open Space by SU Count
                open_space_df.sort_values("SU Count", ascending=False, inplace=True)
                
                # 5. Standardize and parse batches
                endcaps_df[["Batch Prefix", "Batch Date"]] = endcaps_df["Batch"].apply(lambda x: pd.Series(parse_batch(x)))
                open_space_df[["Batch Prefix", "Batch Date"]] = open_space_df["Batch Number"].apply(lambda x: pd.Series(parse_batch(x)))
                endcaps_df["Batch Date"] = pd.to_datetime(endcaps_df["Batch Date"], errors='coerce')
                open_space_df["Batch Date"] = pd.to_datetime(open_space_df["Batch Date"], errors='coerce')
                
                # 6. Filter available Open Space bins
                available_bins = open_space_df[
                    open_space_df["Storage Type"].isin(move_into_types) & 
                    (open_space_df["Utilization %"] < 100)
                ].copy()
                
                # --- Assignment Logic ---
                assignments = []
                summary_data = []
                assigned_bins = set()
                
                for storage_bin, bin_group in endcaps_df.groupby("Storage Bin"):
                    if storage_bin in assigned_bins:
                        continue
                        
                    total_su_in_bin = bin_group["Total Unique SU Count"].iloc[0]
                    
                    # Find matching Open Space bins
                    matching_bins = available_bins[
                        (available_bins["Material Number"] == bin_group["Material"].iloc[0]) &
                        (available_bins["Batch Prefix"] == bin_group["Batch Prefix"].iloc[0]) &
                        (available_bins["Storage Bin"] != storage_bin)
                    ].copy()
                    
                    for _, open_space_bin in matching_bins.iterrows():
                        if open_space_bin["Storage Bin"] in assigned_bins:
                            continue
                            
                        if open_space_bin["Avail SU"] >= total_su_in_bin:
                            # Create assignments for each SU
                            for _, su_row in bin_group.iterrows():
                                assignments.append([
                                    open_space_bin["Storage Type"],
                                    open_space_bin["Storage Bin"],
                                    storage_bin,
                                    su_row["Storage Type"],
                                    su_row["Material"],
                                    open_space_bin["Batch Number"],  # Open Space batch
                                    su_row["Batch"],  # Original batch
                                    open_space_bin["SU Capacity"],
                                    1,  # SU Count
                                    open_space_bin["Avail SU"] - total_su_in_bin,
                                    su_row["Storage Unit"],
                                    su_row["Total Stock"]
                                ])
                            
                            # Add summary entry
                            oldest_source = bin_group.loc[bin_group["Batch Date"].idxmin(), "Batch"]
                            newest_source = bin_group.loc[bin_group["Batch Date"].idxmax(), "Batch"]
                            summary_data.append([
                                open_space_bin["Storage Type"],
                                bin_group["Storage Type"].iloc[0],
                                open_space_bin["Storage Bin"],
                                storage_bin,
                                bin_group["Material"].iloc[0],
                                open_space_bin["Batch Number"],
                                open_space_bin["Batch Number"],  # Same as above for simplicity
                                oldest_source,
                                newest_source,
                                open_space_bin["SU Capacity"],
                                open_space_bin["SU Count"],
                                open_space_bin["Avail SU"],
                                total_su_in_bin
                            ])
                            
                            # Update available capacity
                            open_space_df.loc[open_space_df["Storage Bin"] == open_space_bin["Storage Bin"], "Avail SU"] -= total_su_in_bin
                            assigned_bins.add(storage_bin)
                            assigned_bins.add(open_space_bin["Storage Bin"])
                            break
                
                # --- Output Generation ---
                if assignments:
                    # Create DataFrames
                    final_output = pd.DataFrame(assignments, columns=[
                        "Open Space Storage Type", "Storage Bin", "Bin Moving From",
                        "Endcap Storage Type", "Material", "Open Space Batch", 
                        "Original Batch", "SU Capacity", "SU Count", 
                        "Avail SU", "Storage Unit", "Total Stock"
                    ])
                    
                    summary_output = pd.DataFrame(summary_data, columns=[
                        "Open Space Storage Type", "Endcap Storage Type",
                        "Open Space Storage Bin", "Endcap Storage Bin",
                        "Material", "Open Space Oldest Batch", "Open Space Newest Batch",
                        "Endcap Oldest Batch", "Endcap Newest Batch",
                        "SU Capacity", "Starting SU Count", "Starting Avail SU",
                        "SUs Being Moved"
                    ])
                    
                    # Create download bundle
                    excel_data = create_download_links(final_output, summary_output, open_space_df)
                    
                    # UI Output
                    st.success(f"✅ Successfully created {len(assignments)} assignments!")
                    
                    st.download_button(
                        label="📥 Download All Reports",
                        data=excel_data,
                        file_name="inventory_assignments.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    with st.expander("Preview Assignments"):
                        st.dataframe(final_output.head(10))
                    
                    with st.expander("Preview Summary"):
                        st.dataframe(summary_output.head(10))
                    
                    with st.expander("Preview Updated Open Space"):
                        st.dataframe(open_space_df.head(10))
                else:
                    st.warning("⚠️ No matching assignments found with current filters")
                    
            except Exception as e:
                st.error(f"❌ Processing error: {str(e)}")
                st.exception(e)
