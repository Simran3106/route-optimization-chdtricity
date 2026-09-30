import requests
import pandas as pd
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import time


# Website containing CTU stop information
base_url="https://whereismyctu.com"

input_file="data/bustop/ctu_stops_directory.csv"
output_file="data/bustop/ctu_stops.csv"


# Read CTU stop directory
df=pd.read_csv(input_file)

print("Total CTU stops:",len(df))
print("Getting latitude and longitude...")


stops=[]

headers={
    "User-Agent":"Mozilla/5.0"
}


for i,row in df.iterrows():

    stop_name=row["stop_name"]
    stop_url=row["url"]

    page_url=urljoin(base_url,stop_url)

    try:

        response=requests.get(
            page_url,
            headers=headers,
            timeout=20
        )

        if response.status_code!=200:

            print(
                f"[{i+1}/{len(df)}] {stop_name} -> HTTP {response.status_code}"
            )

            continue


        soup=BeautifulSoup(response.text,"html.parser")


        latitude=None
        longitude=None


        # Find Google Maps link
        for link in soup.find_all("a",href=True):

            href=link["href"]

            if "google.com/maps" in href:

                # Look for coordinates in:
                # ?q=30.7306,76.77496

                match=re.search(
                    r"[?&]q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)",
                    href
                )

                if match:

                    latitude=float(match.group(1))
                    longitude=float(match.group(2))

                    break


        if latitude is not None and longitude is not None:

            stops.append({
                "stop_name":stop_name,
                "latitude":latitude,
                "longitude":longitude,
                "url":page_url
            })

            print(
                f"[{i+1}/{len(df)}] {stop_name} -> {latitude}, {longitude}"
            )

        else:

            print(
                f"[{i+1}/{len(df)}] {stop_name} -> COORDINATES NOT FOUND"
            )


        # Small delay between requests
        time.sleep(0.2)


    except Exception as e:

        print(
            f"[{i+1}/{len(df)}] {stop_name} -> ERROR: {e}"
        )


# Create dataframe
stops_df=pd.DataFrame(stops)


# Add stop ID
stops_df.insert(
    0,
    "stop_id",
    ["S"+str(i+1).zfill(3) for i in range(len(stops_df))]
)


# Save
stops_df.to_csv(
    output_file,
    index=False
)


print()
print("CTU STOP DATA COMPLETE")
print("Stops with coordinates:",len(stops_df))
print("Saved to:",output_file)
