import pandas as pd
import string

# ===== CONFIG =====
INPUT_FILE = "results2.csv"      # or .csv
OUTPUT_FILE = "fake_run3.log"

FAM_COL = "x1-m1"
ROX_COL = "x4-m4"
# ==================

# Load data
if INPUT_FILE.endswith(".csv"):
    df = pd.read_csv(INPUT_FILE)
else:
    df = pd.read_excel(INPUT_FILE)

# Map well position (A1 → 1, A2 → 2, …, P24 → 384)
row_letters = list(string.ascii_uppercase[:16])  # A–P
row_index = {r: i for i, r in enumerate(row_letters)}

def well_to_position(well):
    token = str(well).strip()
    token = token.split("-")[-1]  # keep the A1/B3 part if there is a prefix
    row = token[0].upper()
    col = int(token[1:])
    return row_index[row] * 24 + col

df["position_id"] = df["Well Position"].apply(well_to_position)

lines = []
lines.append("timestamp line_idx fluorescence on_off dye cycle position")

t = 0

for _, r in df.iterrows():
    cycle = int(r["Cycle"])
    pos = int(r["position_id"])

    def clean_num(val):
        # Remove commas and whitespace before float conversion
        return float(str(val).replace(",", "").strip())

    fam = clean_num(r[FAM_COL])
    rox = clean_num(r[ROX_COL])

    # FAM row
    lines.append(f"{t} 0 {fam} 1 fam {cycle} {pos}")
    t += 1

    # ROX row
    lines.append(f"{t} 1 {rox} 1 rox {cycle} {pos}")
    t += 1

with open(OUTPUT_FILE, "w") as f:
    f.write("\n".join(lines))

print(f"Wrote {OUTPUT_FILE} with {len(lines)-1} data rows")
