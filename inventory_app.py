import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO

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
st.set_page_config(layout="wide")
st.title("📊 Inventory Consolidation Tool")

# File Upload
endcaps_file = st.file_uploader("Endcaps File", type=["xlsx"])
open_space_file = st.file_uploader("Open Space File", type=["xlsx"])

if endcaps_file and open_space_file:
    try:
        endcaps_df = pd.read_excel(endcaps_file, sheet_name="Sheet1")
        open_space_df = pd.read_excel(open_space_file, sheet_name="Sheet1")
        
        # Get storage types from data
        storage_types = sorted(endcaps_df["Storage Type"].dropna().unique())
        move_into_types = sorted(open_space_df["Storage Type"].dropna().unique())
        
        # Filter selection
        selected_types = st.multiselect("Filter these storage types:", storage_types, default=storage_types)
        move_into_types = st.multiselect("Move into these storage types:", move_into_types, default=move_into_types)
        
        if st.button("Process Files"):
            with st.spinner("Processing..."):
                # --- CORE PROCESSING (Matches Original Tkinter Logic) ---
                # 1. Filter VIR locations
                open_space_df = open_space_df[open_space_df["Storage Type"] != "VIR"].copy()
                
                # 2. Filter Endcaps based on selected storage types
                endcaps_df = endcaps_df[endcaps_df["Storage Type"].isin(selected_types)].copy()
                
                # 3. Calculate SU count per storage bin (EXACT original logic)
                endcaps_df["Storage Unit"] = endcaps_df["Storage Unit"].astype(str).str.strip()
                endcaps_df["Storage Bin"] = endcaps_df["Storage Bin"].astype(str).str.strip()
                su_count_per_bin = endcaps_df.groupby("Storage Bin")["Storage Unit"].nunique().reset_index()
                su_count_per_bin.columns = ["Storage Bin", "Total Unique SU Count"]
                endcaps_df = endcaps_df.merge(su_count_per_bin, on="Storage Bin", how="left")
                endcaps_df.sort_values("Total Unique SU Count", ascending=True, inplace=True)  # Smallest first
                
                # 4. Sort Open Space by SU Count (Descending - EXACT original logic)
                open_space_df.sort_values("SU Count", ascending=False, inplace=True)
                
                # 5. Standardize and parse batches (EXACT original logic)
                endcaps_df["Material"] = endcaps_df["Material"].astype(str).str.strip()
                open_space_df["Material Number"] = open_space_df["Material Number"].astype(str).str.strip()
                endcaps_df["Batch"] = endcaps_df["Batch"].astype(str).str.strip()
                open_space_df["Batch Number"] = open_space_df["Batch Number"].astype(str).str.strip()
                
                endcaps_df[["Batch Prefix", "Batch Date"]] = endcaps_df["Batch"].apply(parse_batch).apply(pd.Series)
                open_space_df[["Batch Prefix", "Batch Date"]] = open_space_df["Batch Number"].apply(parse_batch).apply(pd.Series)
                
                endcaps_df["Batch Date"] = pd.to_datetime(endcaps_df["Batch Date"], errors='coerce')
                open_space_df["Batch Date"] = pd.to_datetime(open_space_df["Batch Date"], errors='coerce')
                
                # 6. Filter available bins (EXACT original logic)
                available_bins = open_space_df[
                    open_space_df["Storage Type"].isin(move_into_types) & 
                    (open_space_df["Utilization %"] < 100)
                ].copy()
                
                # --- ASSIGNMENT LOGIC (Matches Original Exactly) ---
                assignments = []
                summary_data = []
                assigned_bins = set()
                
                for storage_bin, bin_group in endcaps_df.groupby("Storage Bin", sort=False):
                    if storage_bin in assigned_bins:
                        continue
                        
                    total_su_in_bin = bin_group["Total Unique SU Count"].iloc[0]
                    bin_group = bin_group.sort_values("Total Unique SU Count", ascending=True)
                    
                    # Find matching bins (with date compatibility check)
                    matching_bins = available_bins[
                        (available_bins["Material Number"] == bin_group["Material"].iloc[0]) & 
                        (available_bins["Batch Prefix"] == bin_group["Batch Prefix"].iloc[0]) & 
                        (available_bins["Storage Bin"] != storage_bin)
                    ].copy()
                    
                    matching_bins = matching_bins.dropna(subset=["Batch Date"])
                    
                    for _, open_space_bin in matching_bins.iterrows():
                        if open_space_bin["Storage Bin"] in assigned_bins:
                            continue
                            
                        if open_space_bin["Avail SU"] >= total_su_in_bin:
                            # Verify batch date compatibility for ALL items
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
                                # Create assignments
                                oldest_target = matching_bins.loc[matching_bins["Batch Date"].idxmin(), "Batch Number"]
                                newest_target = matching_bins.loc[matching_bins["Batch Date"].idxmax(), "Batch Number"]
                                
                                for _, su_row in bin_group.iterrows():
                                    assignments.append([
                                        open_space_bin["Storage Type"],
                                        open_space_bin["Storage Bin"],
                                        storage_bin,
                                        su_row["Storage Type"],
                                        su_row["Material"],
                                        oldest_target,
                                        su_row["Batch"],
                                        open_space_bin["SU Capacity"],
                                        1,
                                        open_space_bin["Avail SU"] - total_su_in_bin,
                                        su_row["Storage Unit"],
                                        su_row["Total Stock"]
                                    ])
                                
                                # Add to summary
                                oldest_source = bin_group.loc[bin_group["Batch Date"].idxmin(), "Batch"]
                                newest_source = bin_group.loc[bin_group["Batch Date"].idxmax(), "Batch"]
                                summary_data.append([
                                    open_space_bin["Storage Type"],
                                    bin_group["Storage Type"].iloc[0],
                                    open_space_bin["Storage Bin"],
                                    storage_bin,
                                    bin_group["Material"].iloc[0],
                                    oldest_target,
                                    newest_target,
                                    oldest_source,
                                    newest_source,
                                    open_space_bin["SU Capacity"],
                                    open_space_bin["SU Count"],
                                    open_space_bin["Avail SU"],
                                    total_su_in_bin
                                ])
                                
                                # Update availability
                                open_space_df.loc[open_space_df["Storage Bin"] == open_space_bin["Storage Bin"], "Avail SU"] -= total_su_in_bin
                                assigned_bins.add(storage_bin)
                                assigned_bins.add(open_space_bin["Storage Bin"])
                                break
                
                # --- OUTPUT GENERATION ---
                if assignments:
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
                    
                    # Create Excel with all sheets
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        final_output.to_excel(writer, sheet_name='Final Assignments', index=False)
                        summary_output.to_excel(writer, sheet_name='Summary Report', index=False)
                        open_space_df.to_excel(writer, sheet_name='Updated Open Space', index=False)
                    output.seek(0)
                    
                    st.success(f"Created {len(assignments)} assignments!")
                    st.download_button(
                        "📥 Download All Reports",
                        data=output,
                        file_name="inventory_assignments.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                    
                    # Preview Data
                    with st.expander("Final Assignments Preview"):
                        st.dataframe(final_output.head())
                    with st.expander("Summary Preview"):
                        st.dataframe(summary_output.head())
                    with st.expander("Updated Open Space Preview"):
                        st.dataframe(open_space_df.head())
                else:
                    st.warning("No suitable matches found")
                    
    except Exception as e:
        st.error(f"Error: {str(e)}")
