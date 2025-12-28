import pandas as pd
import nfl_data_py as nfl
from datetime import datetime

# 1. SETUP: Get the 'Next Man Up' Roster Data
print("Loading current rosters...")
depth_charts = nfl.import_depth_charts([2024])

target_positions = ['QB', 'RB', 'WR', 'TE']
depth_charts = depth_charts[depth_charts['position'].isin(target_positions)]
depth_charts['depth_team'] = pd.to_numeric(depth_charts['depth_team'], errors='coerce')

# 2. THE LIVE SCRAPE
url = "https://www.cbssports.com/nfl/injuries/"
print(f"Scraping live injury data from {url}...")

try:
    # Read HTML directly
    tables = pd.read_html(url)
except Exception as e:
    print(f"\nCRITICAL ERROR: {e}")
    exit()

print(f"Analyzing {len(tables)} tables found on CBS...")

# 3. PROCESS THE SCRAPED DATA
live_injuries = []

for table in tables:
    if table.empty:
        continue
    
    # Clean up columns (strip whitespace)
    table.columns = [str(c).strip() for c in table.columns]
    
    # 3a. Find the Correct Columns
    # Priority: Find a column with "Status" in the name (e.g. "Injury Status")
    # If not, fallback to "Injury" (but this is risky as we saw)
    status_col = None
    player_col = None
    
    for col in table.columns:
        if 'Player' in col:
            player_col = col
        # FIX: Prioritize 'Status' to avoid picking the Body Part column
        if 'Status' in col:
            status_col = col
            
    # If we couldn't find 'Status', try looking for 'Injury' as a backup
    if not status_col:
        for col in table.columns:
            if 'Injury' in col:
                status_col = col

    # 3b. Filter Data
    if player_col and status_col:
        # Filter for bad news (Include 'Inactive' this time)
        bad_news = table[
            table[status_col].astype(str).str.contains('Out|Doubtful|IR|Reserve|Inactive', case=False, na=False)
        ].copy()
        
        # Standardize Names for the merger
        bad_news['Standardized_Player'] = bad_news[player_col]
        bad_news['Standardized_Status'] = bad_news[status_col]
        
        live_injuries.append(bad_news)

# Combine all teams
if live_injuries:
    injury_df = pd.concat(live_injuries)
    print(f"Found {len(injury_df)} active major injuries.")
else:
    print("No injuries found! (Is the season over?)")
    exit()

# 4. CROSS-REFERENCE ("Next Man Up")
print("\n--- 🏥 LIVE INJURY REPORT & REPLACEMENTS 🚑 ---")
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")

for index, row in injury_df.iterrows():
    messy_name = str(row['Standardized_Player'])
    status = row['Standardized_Status']
    
    # Heuristic: Filter roster by first letter of messy name to speed it up
    if len(messy_name) > 0:
        first_letter = messy_name[0]
        potential_matches = depth_charts[depth_charts['full_name'].str.startswith(first_letter, na=False)]
    else:
        potential_matches = depth_charts

    # Fuzzy Match: Check if Roster Name is INSIDE the Messy Scraped Name
    # e.g. "Blake Gillikin" is inside "B. GillikinBlake Gillikin"
    found_player = None
    for _, roster_player in potential_matches.iterrows():
        if roster_player['full_name'] in messy_name:
            found_player = roster_player
            break
            
    if found_player is not None:
        team = found_player['club_code']
        position = found_player['position']
        rank = found_player['depth_team']
        real_name = found_player['full_name']
        
        if rank <= 1:
            print(f"🚨 {real_name} ({team} - {position}) is {status}")
            
            # Find Backup
            backups = depth_charts[
                (depth_charts['club_code'] == team) & 
                (depth_charts['position'] == position) & 
                (depth_charts['depth_team'] == rank + 1)
            ]
            
            if not backups.empty:
                print(f"   👉 NEXT MAN UP: {backups.iloc[0]['full_name']}")
            else:
                print("   👉 NEXT MAN UP: Unknown / Committee")
            print("-" * 40)