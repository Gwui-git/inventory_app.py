import streamlit as st
import pandas as pd
from datetime import datetime

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

# --- Streamlit UI ---

st.title("Endcaps and Open Space Processor")

st.header("Step 1: Upload Files")
endcaps_file = st.file_uploader("Upload Endcaps Excel File", type=["xlsx"])
open_space_file = st.file_uploader("Upload Open Space Excel File", type=["xlsx"])

if endcaps_file and open_space_file:
    try:
        endcaps_df = pd.read_excel(endcaps_file, sheet_name="Sheet1")
        open_space_df = pd.read_excel(open_space_file, sheet_name="Sheet1")
    except Exception as e:
        st.error(f"Failed to read Excel files: {e}")
    else:
        # Storage Types (You may dynamically get this from file if needed)
        all_storage_types = sorted(endcaps_df["Storage Type"].dropna().unique())
        all_move_into_types = sorted(open_space_df["Storage Type"].dropna().unique())

        st.header("Step 2: Filter Options")

        selected_types = st.multiselect(
            "Select Storage Types to FILTER in Endcaps",
            options=all_storage_types,
            default=all_storage_types
        )

        move_into_types = st.multiselect(
            "Select Storage Types to MOVE INTO in Open Spaces",
            options=all_move_into_types,
            default=all_move_into_types
        )

        if st.button("Process Files"):
            with st.spinner("Processing..."):
                try:
                    # Step 1: Filter VIR
                    open_space_df = open_space_df[open_space_df["Storage Type"] != "VIR"].copy()

                    # Step 2: Filter Endcaps
                    endcaps_df = endcaps_df[endcaps_df["Storage Type"].isin(selected_types)].copy()

                    # Step 3: SU Count per Bin
                    endcaps_df["Storage Unit"] = endcaps_df["Storage Unit"].astype(str).str.strip()
                    endcaps_df["Storage Bin"] = endcaps_df["Storage Bin"].astype(str).str.strip()
                    su_count = endcaps_df.groupby("Storage Bin")["Storage Unit"].nunique().reset_index()
                    su_count.columns = ["Storage Bin", "Total Unique SU Count"]
                    endcaps_df = endcaps_df.merge(su_count, on="Storage Bin", how="left")
                    endcaps_df.sort_values("Total Unique SU Count", inplace=True)

                    # Step 4: Sort Open Space by SU Count
                    open_space_df.sort_values("SU Count", ascending=False, inplace=True)

                    # Step 5: Clean and parse batches
                    endcaps_df["Material"] = endcaps_df["Material"].astype(str).str.strip()
                    open_space_df["Material Number"] = open_space_df["Material Number"].astype(str).str.strip()
                    endcaps_df["Batch"] = endcaps_df["Batch"].astype(str).str.strip()
                    open_space_df["Batch Number"] = open_space_df["Batch Number"].astype(str).str.strip()

                    endcaps_df[["Batch Prefix", "Batch Date"]] = endcaps_df["Batch"].apply(lambda x: pd.Series(parse_batch(x)))
                    open_space_df[["Batch Prefix", "Batch Date"]] = open_space_df["Batch Number"].apply(lambda x: pd.Series(parse_batch(x)))

                    endcaps_df["Batch Date"] = pd.to_datetime(endcaps_df["Batch Date"], errors='coerce')
                    open_space_df["Batch Date"] = pd.to_datetime(open_space_df["Batch Date"], errors='coerce')

                    # Step 6: Filter open bins
                    available_bins = open_space_df[
                        (open_space_df["Storage Type"].isin(move_into_types)) &
                        (open_space_df["Utilization %"] < 100)
                    ].copy()

                    st.success("Files processed successfully! Next steps (like assigning bins) would be implemented here.")
                    st.dataframe(endcaps_df.head(10))
                    st.dataframe(open_space_df.head(10))

                except Exception as e:
                    st.error(f"An error occurred during processing: {e}")
