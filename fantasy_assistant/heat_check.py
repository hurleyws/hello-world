import pandas as pd
import numpy as np

# 1. SETUP
# We use the "Leaders Report" which has columns for Week 1, 2, 3...
# This lets us do the math ourselves rather than trusting the website's filters.
url = "https://www.fantasypros.com/nfl/reports/leaders/ppr.php?year=2025"

print("--- 🏈 STARTING 2025 HEAT CHECK (Game Log Method) 🏈 ---")
print(f"Scraping weekly matrix from: {url}")

try:
    # Read the table. It might take a moment as it's a large table.
    dfs = pd.read_html(url)
    if not dfs:
        raise ValueError("No tables found.")
    
    # The stats table is usually the main one
    df = dfs[0]
    
except Exception as e:
    print(f"\n❌ CRITICAL ERROR: {e}")
    print("Try running: py -m pip install lxml html5lib")
    exit()

# 2. FIND WEEK COLUMNS DYNAMICALLY
# We look for columns that are simple numbers (1, 2, 3...) representing weeks
week_cols = []
for col in df.columns:
    col_str = str(col).strip()
    if col_str.isdigit():
        week_cols.append(col)

# Sort them to be sure we have order 1, 2, 3...
week_cols.sort(key=int)

if not week_cols:
    print("❌ Could not identify week columns. The website layout might have changed.")
    exit()

print(f"   -> Found data for Weeks: {week_cols}")

# 3. DEFINE "RECENT" vs "BASELINE"
# We define "Recent" as the last 4 played weeks
recent_weeks = week_cols[-4:]
baseline_weeks = week_cols[:-4]

print(f"   -> Analyzing Trend: Weeks {recent_weeks} vs Baseline ({baseline_weeks})")

# 4. CALCULATE STATS
# Convert all week columns to numeric (coerce errors to NaN for bye weeks)
for col in week_cols:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Calculate Averages (ignoring NaNs/Byes)
df['Recent_Avg'] = df[recent_weeks].mean(axis=1)
df['Baseline_Avg'] = df[baseline_weeks].mean(axis=1)
df['Diff'] = df['Recent_Avg'] - df['Baseline_Avg']

# 5. FILTERING
# Must be a relevant player (Avg > 5 pts)
# Must have played in at least 2 of the recent weeks (to avoid 1-game wonders)
df['Recent_Games_Played'] = df[recent_weeks].count(axis=1)

active_players = df[
    (df['Baseline_Avg'] > 5) & 
    (df['Recent_Games_Played'] >= 2)
].copy()

# Sort by hottest
heating_up = active_players.sort_values(by='Diff', ascending=False)

# 6. REPORTING
print(f"\n🔥 PLAYERS HEATING UP (Last 4 Weeks vs Season Avg) 🔥")
print(f"{'Player':<25} | {'Pos':<4} | {'Recent':<6} | {'Usual':<6} | {'Diff':<5}")
print("-" * 65)

count = 0
for index, row in heating_up.iterrows():
    # Only show positive trends
    if row['Diff'] > 2.0: # Filter for at least +2.0 improvement
        # Clean up name if needed
        player_name = str(row['Player']).split('(')[0].strip()
        pos = str(row['Pos'])
        
        print(f"{player_name:<25} | {pos:<4} | {row['Recent_Avg']:<6.1f} | {row['Baseline_Avg']:<6.1f} | +{row['Diff']:<4.1f}")
        
        count += 1
        if count >= 30: break

if count == 0:
    print("No players found heating up.")