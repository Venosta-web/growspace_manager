import sqlite3
import json
import os

db_path = "/home/maxi/.homeassistant/strain_library.db"
if not os.path.exists(db_path):
    # Try another common path
    db_path = "/home/maxi/core/core/config/strain_library.db"

if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("--- Strains ---")
cursor.execute("SELECT * FROM strains LIMIT 5")
rows = cursor.fetchall()
for row in rows:
    print(f"Strain: {row['strain_name']}")
    for col in row.keys():
        val = row[col]
        print(f"  {col}: {val} ({type(val)})")
    print("-" * 20)

print("\n--- Any null percentages? ---")
cursor.execute("SELECT strain_name, sativa_percentage, indica_percentage FROM strains WHERE sativa_percentage IS NULL OR indica_percentage IS NULL")
for row in cursor.fetchall():
    print(f"Null Perc: {row['strain_name']} - S:{row['sativa_percentage']}, I:{row['indica_percentage']}")

conn.close()
