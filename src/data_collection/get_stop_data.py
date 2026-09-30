import requests
from bs4 import BeautifulSoup
import pandas as pd


url="https://whereismyctu.com/stops"

print("Downloading CTU stop directory...")

response=requests.get(
    url,
    headers={
        "User-Agent":"Mozilla/5.0"
    },
    timeout=30
)

print("Status code:",response.status_code)

if response.status_code!=200:
    print("Failed to download stop directory")
    exit()

soup=BeautifulSoup(response.text,"html.parser")

stops=[]

# Find all links on the page
for link in soup.find_all("a"):

    name=link.get_text(" ",strip=True)
    href=link.get("href","")

    if name and href:

        stops.append({
            "stop_name":name,
            "url":href
        })


df=pd.DataFrame(stops)

df=df.drop_duplicates(subset="stop_name")

df=df.sort_values("stop_name")

output_file="data/raw/ctu_stops_directory.csv"

df.to_csv(output_file,index=False)

print()
print("Stops found:",len(df))
print("Saved to:",output_file)
print()
print(df.head(20))