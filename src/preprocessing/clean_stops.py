import pandas as pd


input_file="data/bustop/ctu_stops.csv"
output_file="data/bustop/ctu_stops_clean.csv"


print("Loading CTU stop data...")

df=pd.read_csv(input_file)

print("Original rows:",len(df))


# Remove "N buses" from stop names
df["stop_name"]=df["stop_name"].str.replace(
    r"\s+\d+\s+buses$",
    "",
    regex=True
)


# Remove extra spaces
df["stop_name"]=df["stop_name"].str.replace(
    r"\s+",
    " ",
    regex=True
).str.strip()


# Keep only required columns
df=df[
    [
        "stop_id",
        "stop_name",
        "latitude",
        "longitude"
    ]
]


# Remove duplicate stop IDs
df=df.drop_duplicates(subset="stop_id")


# Check for missing values
print()
print("Missing values:")
print(df.isna().sum())


# Check duplicate stop names
duplicates=df[df.duplicated("stop_name",keep=False)]

print()
print("Duplicate stop names:",len(duplicates))


# Save cleaned data
df.to_csv(
    output_file,
    index=False
)


print()
print("Cleaned rows:",len(df))
print("Saved to:",output_file)
print()
print(df.head(10).to_string(index=False))