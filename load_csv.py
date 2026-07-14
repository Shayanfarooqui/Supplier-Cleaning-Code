import pandas as pd
import os

file_path = r"C:\Users\muhammad.farooqui\Downloads\20260603_044612.csv"

print(f"Loading file: {file_path}")
print(f"File size: {os.path.getsize(file_path) / (1024 * 1024):.2f} MB")

df = pd.read_csv(file_path, low_memory=False)

print(f"\nShape: {df.shape[0]:,} rows x {df.shape[1]} columns")
print(f"\nColumns:\n{df.columns.tolist()}")
print(f"\nData types:\n{df.dtypes}")
print(f"\nFirst 5 rows:\n{df.head()}")
