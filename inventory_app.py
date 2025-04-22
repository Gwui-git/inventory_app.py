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
st.set_page_config(layout="wide", page_title="Inventory Consolidation Tool")
st.title("📦 Advanced Inventory Processor")

# File Upload
with st.expander("📂 STEP 1: Upload Files", expanded=True):
    col1, col2 = st.columns(2)
    with col1:
        endcaps_file = st.file_uploader("Endcaps File", type=["xlsx"], help="Upload the Endcaps inventory Excel file")
    with col2:
        open_space_file = st.file_uploader("Open Space File", type=["xlsx"], help="Upload the Open Space inventory Excel file")

if endcaps_file and open_space_file:
    try:
        endcaps_df = pd.read_excel(endcaps_file, sheet_name="Sheet1")
        open_space_df = pd.read_excel(open_space_file, sheet_name="Sheet1")
        
        # Make copies for the output
        updated_open_space_df = open_space_df.copy()
        updated_endcaps_df = endcaps_df.copy()
        
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
                    help="Only process these storage types from Endcaps"
                )
            with cols[1]:
                move_into_types = st.multiselect(
                    "Move into these storage types (Open Space):",
                    options=move_into_types,
                    default=move_into_types,
                    help="Only consider these storage types in Open Space"
                )
            
            # Add toggle for full/partial moves
            move_type = st.radio(
                "Move Type:",
                options=["Full Moves (Keep locations together)", "Partial Moves (Allow splitting)"],
                index=0,
                help="Full moves keep all SUs from a source location together. Partial moves allow splitting across targets but only move if all can be moved."
            )
            partial_moves = move_type == "Partial Moves (Allow splitting)"
        
        if st.button("🚀 Process Files", type="primary", help="Run the consolidation algorithm"):
            with st.spinner("Crunching numbers..."):
                # --- CORE PROCESSING ---
                # 1. Filter VIR locations
                open_space_df = open_space_df[open_space_df["Storage Type"] != "VIR"].copy()
                
                # 2. Filter Endcaps by selected types
                endcaps_df = endcaps_df[endcaps_df["Storage Type"].isin(selected_types)].copy()
                
                # 3. Calculate SU count per storage bin (count unique Storage Units)
                endcaps_df["Storage Unit"] = endcaps_df["Storage Unit"].astype(str).str.strip()
                endcaps_df["Storage Bin"] = endcaps_df["Storage Bin"].astype(str).str.strip()
                
                # Get all batches for each Storage Unit
                su_batches = endcaps_df.groupby(["Storage Bin", "Storage Unit"])["Batch"].apply(list).reset_index()
                su_count_per_bin = endcaps_df.groupby("Storage Bin")["Storage Unit"].nunique().reset_index()
                su_count_per_bin.columns = ["Storage Bin", "Total Unique SU Count"]
                endcaps_df = endcaps_df.merge(su_count_per_bin, on="Storage Bin", how="left")
                endcaps_df.sort_values("Total Unique SU Count", ascending=True, inplace=True)
                
                # 4. Sort Open Space by SU Count (descending)
                open_space_df.sort_values("SU Count", ascending=False, inplace=True)
                
                # 5. Standardize and parse batches
                endcaps_df["Material"] = endcaps_df["Material"].astype(str).str.strip()
                open_space_df["Material Number"] = open_space_df["Material Number"].astype(str).str.strip()
                endcaps_df["Batch"] = endcaps_df["Batch"].astype(str).str.strip()
                open_space_df["Batch Number"] = open_space_df["Batch Number"].astype(str).str.strip()
                
                endcaps_df[["Batch Prefix", "Batch Date"]] = endcaps_df["Batch"].apply(parse_batch).apply(pd.Series)
                open_space_df[["Batch Prefix", "Batch Date"]] = open_space_df["Batch Number"].apply(parse_batch).apply(pd.Series)
                
                endcaps_df["Batch Date"] = pd.to_datetime(endcaps_df["Batch Date"], errors='coerce')
                open_space_df["Batch Date"] = pd.to_datetime(open_space_df["Batch Date"], errors='coerce')
                
                # --- DYNAMIC ASSIGNMENT LOGIC ---
                assignments = []
                summary_data = []
                used_source_bins = set()  # Tracks bins that have been fully moved
                excluded_target_bins = set()  # Tracks bins that can't be used as targets
                
                # Create working copy that will track remaining capacity
                available_bins = open_space_df[
                    open_space_df["Storage Type"].isin(move_into_types) & 
                    (open_space_df["Utilization %"] < 100) &
                    (open_space_df["Avail SU"] > 0) &
                    (~open_space_df["Storage Bin"].isin(used_source_bins))
                ].copy()
                
                # Sort endcaps by smallest bins first to optimize space utilization
                sorted_endcap_bins = endcaps_df.groupby("Storage Bin").first().sort_values("Total Unique SU Count").index
                
                for storage_bin in sorted_endcap_bins:
                    if storage_bin in used_source_bins:
                        continue
                        
                    bin_group = endcaps_df[endcaps_df["Storage Bin"] == storage_bin].copy()
                    total_su_in_bin = bin_group["Total Unique SU Count"].iloc[0]
                    
                    # Get all batches for each SU in this bin
                    bin_su_batches = su_batches[su_batches["Storage Bin"] == storage_bin]
                    
                    if partial_moves:
                        # PARTIAL MOVES LOGIC (must move all SUs)
                        # First find all matching target bins (excluding any used sources)
                        matching_bins = available_bins[
                            (available_bins["Material Number"] == bin_group["Material"].iloc[0]) & 
                            (available_bins["Batch Prefix"] == bin_group["Batch Prefix"].iloc[0]) & 
                            (available_bins["Storage Bin"] != storage_bin) &
                            (~available_bins["Storage Bin"].isin(used_source_bins))
                        ].copy()
                        
                        matching_bins = matching_bins.dropna(subset=["Batch Date"])
                        matching_bins.sort_values("Avail SU", ascending=False, inplace=True)
                        
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
                                
                        if not valid_match:
                            continue
                            
                        # Check if we have enough total capacity across all matching bins
                        total_available = matching_bins["Avail SU"].sum()
                        if total_available < total_su_in_bin:
                            continue
                            
                        # Now assign SUs to targets with real-time capacity tracking
                        remaining_su = total_su_in_bin
                        su_assignments = []
                        assigned_sus = set()
                        
                        # Create a temporary copy of matching bins that we'll modify
                        temp_available_bins = matching_bins.copy()
                        
                        for _, open_space_bin in temp_available_bins.iterrows():
                            if remaining_su <= 0:
                                break
                                
                            # Get current available capacity (may have been updated by previous assignments)
                            current_avail = temp_available_bins.loc[
                                temp_available_bins["Storage Bin"] == open_space_bin["Storage Bin"], 
                                "Avail SU"].values[0]
                                
                            su_to_move = min(remaining_su, current_avail)
                            if su_to_move <= 0:
                                continue
                                
                            target_batches = temp_available_bins[
                                (temp_available_bins["Storage Bin"] == open_space_bin["Storage Bin"]) & 
                                (temp_available_bins["Material Number"] == open_space_bin["Material Number"]) & 
                                (temp_available_bins["Batch Prefix"] == open_space_bin["Batch Prefix"])
                            ]
                            oldest_target = target_batches.loc[target_batches["Batch Date"].idxmin(), "Batch Number"]
                            newest_target = target_batches.loc[target_batches["Batch Date"].idxmax(), "Batch Number"]
                            
                            # Assign SUs (ensuring we don't duplicate)
                            for _, su_info in bin_su_batches.iterrows():
                                if su_info["Storage Unit"] in assigned_sus:
                                    continue
                                    
                                if su_to_move <= 0:
                                    break
                                    
                                # Get all batches for this SU
                                su_batch_list = su_info["Batch"]
                                for batch in su_batch_list:
                                    assignments.append([
                                        open_space_bin["Storage Type"],
                                        open_space_bin["Storage Bin"],
                                        storage_bin,
                                        bin_group["Storage Type"].iloc[0],
                                        bin_group["Material"].iloc[0],
                                        oldest_target,
                                        batch,
                                        open_space_bin["SU Capacity"],
                                        1,
                                        current_avail - 1,  # Updated remaining capacity
                                        su_info["Storage Unit"],
                                        bin_group["Total Stock"].iloc[0]
                                    ])
                                
                                assigned_sus.add(su_info["Storage Unit"])
                                remaining_su -= 1
                                su_to_move -= 1
                                
                                # Update the temporary available bins
                                temp_available_bins.loc[
                                    temp_available_bins["Storage Bin"] == open_space_bin["Storage Bin"], 
                                    "Avail SU"] -= 1
                                    
                                # Also update the main available_bins
                                available_bins.loc[
                                    available_bins["Storage Bin"] == open_space_bin["Storage Bin"], 
                                    "Avail SU"] -= 1
                                    
                        if remaining_su == 0:
                            used_source_bins.add(storage_bin)
                            summary_data.append([
                                "Multiple" if len(set(a[1] for a in assignments[-total_su_in_bin:])) > 1 else assignments[-1][0],
                                bin_group["Storage Type"].iloc[0],
                                "Multiple" if len(set(a[1] for a in assignments[-total_su_in_bin:])) > 1 else assignments[-1][1],
                                storage_bin,
                                bin_group["Material"].iloc[0],
                                oldest_target,
                                newest_target,
                                bin_group.loc[bin_group["Batch Date"].idxmin(), "Batch"],
                                bin_group.loc[bin_group["Batch Date"].idxmax(), "Batch"],
                                open_space_bin["SU Capacity"],
                                open_space_bin["SU Count"],
                                current_avail + 1,  # Original available before this assignment
                                total_su_in_bin
                            ])
                            
                    else:
                        # FULL MOVES LOGIC (original working version - UNTOUCHED)
                        # Find matching bins with enough capacity for the entire bin
                        matching_bins = available_bins[
                            (available_bins["Material Number"] == bin_group["Material"].iloc[0]) & 
                            (available_bins["Batch Prefix"] == bin_group["Batch Prefix"].iloc[0]) & 
                            (available_bins["Storage Bin"] != storage_bin) &
                            (available_bins["Avail SU"] >= total_su_in_bin) &
                            (~available_bins["Storage Bin"].isin(used_source_bins))
                        ].copy()
                        
                        matching_bins = matching_bins.dropna(subset=["Batch Date"])
                        matching_bins.sort_values("Avail SU", ascending=False, inplace=True)
                        
                        for _, open_space_bin in matching_bins.iterrows():
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
                                # Get target batch info
                                target_batches = available_bins[
                                    (available_bins["Storage Bin"] == open_space_bin["Storage Bin"]) & 
                                    (available_bins["Material Number"] == open_space_bin["Material Number"]) & 
                                    (available_bins["Batch Prefix"] == open_space_bin["Batch Prefix"])
                                ]
                                oldest_target = target_batches.loc[target_batches["Batch Date"].idxmin(), "Batch Number"]
                                newest_target = target_batches.loc[target_batches["Batch Date"].idxmax(), "Batch Number"]
                                
                                # Create assignments for each SU and all its batches
                                for _, su_info in bin_su_batches.iterrows():
                                    for batch in su_info["Batch"]:
                                        assignments.append([
                                            open_space_bin["Storage Type"],
                                            open_space_bin["Storage Bin"],
                                            storage_bin,
                                            bin_group["Storage Type"].iloc[0],
                                            bin_group["Material"].iloc[0],
                                            oldest_target,
                                            batch,
                                            open_space_bin["SU Capacity"],
                                            1,
                                            open_space_bin["Avail SU"] - total_su_in_bin,
                                            su_info["Storage Unit"],
                                            bin_group["Total Stock"].iloc[0]
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
                                    oldest_target,
                                    newest_target,
                                    oldest_source,
                                    newest_source,
                                    open_space_bin["SU Capacity"],
                                    open_space_bin["SU Count"],
                                    open_space_bin["Avail SU"],
                                    total_su_in_bin
                                ])
                                
                                # Update tracking
                                used_source_bins.add(storage_bin)
                                available_bins.loc[available_bins["Storage Bin"] == open_space_bin["Storage Bin"], "Avail SU"] -= total_su_in_bin
                                break
                
                # Update the main dataframes with all changes
                # Update target locations in open space
                for _, row in available_bins.iterrows():
                    updated_open_space_df.loc[updated_open_space_df["Storage Bin"] == row["Storage Bin"], "Avail SU"] = row["Avail SU"]
                    updated_open_space_df.loc[updated_open_space_df["Storage Bin"] == row["Storage Bin"], "SU Count"] = row["SU Capacity"] - row["Avail SU"]
                    updated_open_space_df.loc[updated_open_space_df["Storage Bin"] == row["Storage Bin"], "Utilization %"] = (
                        (row["SU Capacity"] - row["Avail SU"]) / row["SU Capacity"] * 100
                    )
                
                # Remove all moved source bins from endcaps
                updated_endcaps_df = updated_endcaps_df[~updated_endcaps_df["Storage Bin"].isin(used_source_bins)]
                
                # --- OUTPUT GENERATION ---
                if assignments:
                    # Create DataFrames
                    final_output = pd.DataFrame(assignments, columns=[
                        "Open Space Storage Type", "Storage Bin", "Bin Moving From",
                        "Endcap Storage Type", "Material", "Open Space Batch", 
                        "Original Batch", "SU Capacity", "SU Count", 
                        "Remaining Avail SU", "Storage Unit", "Total Stock"
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
                        updated_open_space_df.to_excel(writer, sheet_name='Updated Open Space', index=False)
                        updated_endcaps_df.to_excel(writer, sheet_name='Updated Endcaps', index=False)
                    
                    output.seek(0)
                    
                    # Display Results
                    st.success(f"✅ Successfully created {len(assignments)} assignments across {len(set(a[2] for a in assignments))} source locations!")
                    if partial_moves:
                        st.info("Partial moves enabled - pallets split across targets but only when all can be moved")
                    
                    # Download Button
                    st.download_button(
                        label="📥 Download Complete Report Package",
                        data=output,
                        file_name="inventory_assignments.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        help="Contains four sheets: Final Assignments, Summary Report, Updated Open Space, and Updated Endcaps"
                    )
                    
                    # Preview Sections
                    with st.expander("🔍 View Assignment Details", expanded=False):
                        st.dataframe(final_output.head(20))
                        st.info(f"Showing first 20 of {len(final_output)} assignments")
                        
                    with st.expander("📊 View Summary Report", expanded=False):
                        st.dataframe(summary_output)
                        
                    with st.expander("🔄 View Updated Open Space", expanded=False):
                        st.dataframe(updated_open_space_df.head(20))
                        
                    with st.expander("📦 View Updated Endcaps", expanded=False):
                        st.dataframe(updated_endcaps_df.head(20))
                else:
                    st.warning("⚠️ No valid assignments found with current filters and inventory")
                    
    except Exception as e:
        st.error(f"❌ Processing failed: {str(e)}")
        st.exception(e)
