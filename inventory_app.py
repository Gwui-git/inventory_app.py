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

def validate_excel_file(uploaded_file):
    """Helper function to validate Excel files with case-insensitive extension check"""
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
            type=None,  # Accept any file but we'll validate manually
            help="Upload the Endcaps inventory Excel file (.xlsx)"
        )
        endcaps_file = validate_excel_file(endcaps_file)  # Apply validation
        
    with col2:
        open_space_file = st.file_uploader(
            "Open Space File", 
            type=None,  # Accept any file but we'll validate manually
            help="Upload the Open Space inventory Excel file (.xlsx)"
        )
        open_space_file = validate_excel_file(open_space_file)  # Apply validation

# Only proceed if both files are valid
if endcaps_file and open_space_file:
    try:
        # Rest of your processing code remains exactly the same...
        endcaps_df = pd.read_excel(endcaps_file, sheet_name="Sheet1")
        open_space_df = pd.read_excel(open_space_file, sheet_name="Sheet1")
        
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
        
        if st.button("🚀 Process Files", type="primary", help="Run the consolidation algorithm"):
            with st.spinner("Crunching numbers..."):
                # --- CORE PROCESSING ---
                # 1. Filter VIR locations
                open_space_df = open_space_df[open_space_df["Storage Type"] != "VIR"].copy()
                
                # 2. Filter Endcaps by selected types
                endcaps_df = endcaps_df[endcaps_df["Storage Type"].isin(selected_types)].copy()
                
                # 3. Calculate SU count per storage bin
                endcaps_df["Storage Unit"] = endcaps_df["Storage Unit"].astype(str).str.strip()
                endcaps_df["Storage Bin"] = endcaps_df["Storage Bin"].astype(str).str.strip()
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
                used_source_bins = set()  # Tracks bins that have been used as sources
                excluded_target_bins = set()  # Tracks bins that can't be used as targets
                
                # Create working copy that will track remaining capacity
                available_bins = open_space_df[
                    open_space_df["Storage Type"].isin(move_into_types) & 
                    (open_space_df["Utilization %"] < 100) &
                    (open_space_df["Avail SU"] > 0) &
                    (~open_space_df["Storage Bin"].isin(excluded_target_bins))  # Exclude bins that can't be targets
                ].copy()
                
                # Sort endcaps by smallest bins first to optimize space utilization
                sorted_endcap_bins = endcaps_df.groupby("Storage Bin").first().sort_values("Total Unique SU Count").index
                
                for storage_bin in sorted_endcap_bins:
                    if storage_bin in used_source_bins:
                        continue
                        
                    bin_group = endcaps_df[endcaps_df["Storage Bin"] == storage_bin]
                    total_su_in_bin = bin_group["Total Unique SU Count"].iloc[0]
                    
                    # Find matching bins with CURRENT availability
                    matching_bins = available_bins[
                        (available_bins["Material Number"] == bin_group["Material"].iloc[0]) & 
                        (available_bins["Batch Prefix"] == bin_group["Batch Prefix"].iloc[0]) & 
                        (available_bins["Storage Bin"] != storage_bin) &
                        (available_bins["Avail SU"] >= total_su_in_bin)  # Current capacity check
                    ].copy()
                    
                    matching_bins = matching_bins.dropna(subset=["Batch Date"])
                    
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
                            # Additional check to ensure we're not moving into a bin that will have 0 capacity
                            if open_space_bin["Avail SU"] - total_su_in_bin < 0:
                                continue
                                
                            # Get target batch info
                            target_batches = available_bins[
                                (available_bins["Storage Bin"] == open_space_bin["Storage Bin"]) & 
                                (available_bins["Material Number"] == open_space_bin["Material Number"]) & 
                                (available_bins["Batch Prefix"] == open_space_bin["Batch Prefix"])
                            ]
                            oldest_target = target_batches.loc[target_batches["Batch Date"].idxmin(), "Batch Number"]
                            newest_target = target_batches.loc[target_batches["Batch Date"].idxmax(), "Batch Number"]
                            
                            # Create assignments for each SU
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
                                    1,  # Each SU counts as 1
                                    open_space_bin["Avail SU"] - total_su_in_bin,  # Remaining capacity
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
                                oldest_target,
                                newest_target,
                                oldest_source,
                                newest_source,
                                open_space_bin["SU Capacity"],
                                open_space_bin["SU Count"],
                                open_space_bin["Avail SU"],  # Pre-assignment availability
                                total_su_in_bin
                            ])
                            
                            # Update tracking
                            used_source_bins.add(storage_bin)  # Mark this bin as used as source
                            excluded_target_bins.add(storage_bin)  # Now exclude it from being a target
                            
                            # Update available capacity in the working copy
                            available_bins.loc[available_bins["Storage Bin"] == open_space_bin["Storage Bin"], "Avail SU"] -= total_su_in_bin
                            
                            # Refresh available bins to exclude newly excluded targets
                            available_bins = available_bins[~available_bins["Storage Bin"].isin(excluded_target_bins)]
                            
                            break  # Move to next source bin after finding first valid target
                
                # Update the main open_space_df with all capacity changes
                for _, row in available_bins.iterrows():
                    open_space_df.loc[open_space_df["Storage Bin"] == row["Storage Bin"], "Avail SU"] = row["Avail SU"]
                
                # --- OUTPUT GENERATION ---
                if assignments:
                    # Create DataFrames with new column names and order
                    final_output = pd.DataFrame(
                        data={
                             "FROM STORAGE TYPE": [x[3] for x in assignments],  # Endcap Storage Type
                            "TO STORAGE TYPE": [x[0] for x in assignments],    # Open Space Storage Type
                            "Material": [x[4] for x in assignments],           # Material
                            "TO BATCH": [x[5] for x in assignments],           # Open Space Batch
                            "FROM BATCH": [x[6] for x in assignments],         # Original Batch
                            "SU CAPACITY": [x[7] for x in assignments],        # SU Capacity
                            "SU COUNT": [x[8] for x in assignments],           # SU Count
                            "AVAILABLE SU": [x[9] for x in assignments],       # Remaining Avail SU
                            "LP#": [x[10] for x in assignments],               # Storage Unit
                            "RACK QTY": [x[11] for x in assignments],          # Total Stock
                            "FROM LOC": [x[2] for x in assignments],           # Bin Moving From
                            "TO LOC": [x[1] for x in assignments]              # Storage Bin
                        }
                    )
    
                    summary_output = pd.DataFrame(
                        data={
                            "FROM STORAGE TYPE": [x[1] for x in summary_data],  # Endcap Storage Type
                            "TO STORAGE TYPE": [x[0] for x in summary_data],    # Open Space Storage Type
                            "Material": [x[4] for x in summary_data],           # Material
                            "FROM OLDEST BATCH": [x[7] for x in summary_data],  # Endcap Oldest Batch
                            "FROM NEWEST BATCH": [x[8] for x in summary_data],  # Endcap Newest Batch
                            "TO OLDEST BATCH": [x[5] for x in summary_data],   # Open Space Oldest Batch
                            "TO NEWEST BATCH": [x[6] for x in summary_data],    # Open Space Newest Batch
                            "SU CAPACITY": [x[9] for x in summary_data],        # SU Capacity
                            "CURRENT SU COUNT": [x[10] for x in summary_data],  # Starting SU Count
                            "AVAILABLE SU": [x[11] for x in summary_data],      # Starting Avail SU
                            "SUs TO MOVE": [x[12] for x in summary_data],       # SUs Being Moved
                            "FROM LOC": [x[3] for x in summary_data],           # Endcap Storage Bin
                            "TO LOC": [x[2] for x in summary_data]              # Open Space Storage Bin
                        }
                    )
                    
                    # Create Excel with all sheets
                    output = BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        final_output.to_excel(writer, sheet_name='Final Assignments', index=False)
                        summary_output.to_excel(writer, sheet_name='Summary Report', index=False)
                        open_space_df.to_excel(writer, sheet_name='Updated Open Space', index=False)
                    output.seek(0)
                    
                    # Display Results
                    st.success(f"✅ Successfully created {len(assignments)} assignments across {len(summary_data)} target locations!")
                    
                    # Download Button
                    st.download_button(
                        label="📥 Download Complete Report Package",
                        data=output,
                        file_name="inventory_assignments.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        help="Contains three sheets: Final Assignments, Summary Report, and Updated Open Space"
                    )
                    
                    # Preview Sections
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
