import pandas as pd
import numpy as np

print("Loading dataset...")
df = pd.read_csv('backend/data/raw/mars_express/data15.csv')

targets = [c for c in df.columns if 'NPWD' in c]
context = [c for c in df.columns if 'NPWD' not in c]

print(f"Total Rows: {len(df)}")
print(f"Total Columns: {len(df.columns)}")
print(f"Target Columns (NPWD): {len(targets)}")
print(f"Context Columns: {len(context)}")

constant_cols = [c for c in context if df[c].nunique(dropna=False) == 1]
print(f"Constant Context Columns: {len(constant_cols)}")

usable_context = [c for c in context if c not in constant_cols]
print(f"Usable Context Columns: {len(usable_context)}")

# Check for identical duplicated columns
print("Checking for duplicate columns in usable context...")
# Sampling to save time on exact duplicate check
sample_df = df[usable_context].sample(1000, random_state=42)
duplicated_cols = set()
for i in range(len(usable_context)):
    col_i = usable_context[i]
    if col_i in duplicated_cols: continue
    for j in range(i+1, len(usable_context)):
        col_j = usable_context[j]
        if col_j in duplicated_cols: continue
        if sample_df[col_i].equals(sample_df[col_j]):
            # Verify on full data if sample matches
            if df[col_i].equals(df[col_j]):
                duplicated_cols.add(col_j)

print(f"Duplicated Context Columns: {len(duplicated_cols)}")
final_context = [c for c in usable_context if c not in duplicated_cols]
print(f"Final Context Columns after deduplication: {len(final_context)}")

mem = df[targets + final_context].memory_usage(deep=True).sum() / (1024**2)
print(f"Optimized Memory Footprint: {mem:.2f} MB")
