"""Generates the demo sales dataset (run once; output is committed)."""
import numpy as np, pandas as pd
rng = np.random.default_rng(42)
n = 720
dates = pd.date_range("2024-01-01", periods=n, freq="D")
region = rng.choice(["North", "South", "East", "West"], n, p=[.3, .25, .25, .2])
category = rng.choice(["Electronics", "Furniture", "Clothing", "Groceries"], n, p=[.3, .2, .3, .2])
base = {"Electronics": 320, "Furniture": 260, "Clothing": 90, "Groceries": 45}
price = np.array([base[c] for c in category]) * rng.uniform(.8, 1.3, n)
units = rng.integers(1, 20, n)
discount = rng.choice([0, 0.05, 0.1, 0.15, 0.2], n)
trend = np.linspace(1, 2.4, n)
sales = price * units * (1 - discount) * trend * (1 + .08 * np.sin(np.arange(n) / 58))
profit = sales * rng.uniform(.08, .3, n) - discount * 40
rating = np.clip(rng.normal(4.1, .6, n) - discount * 2, 1, 5).round(1)
df = pd.DataFrame({"Date": dates, "Region": region, "Category": category, "Units_Sold": units,
                   "Unit_Price": price.round(2), "Discount": discount, "Sales": sales.round(2),
                   "Profit": profit.round(2), "Customer_Rating": rating})
for i in rng.choice(n, 8, replace=False): df.loc[i, "Sales"] *= rng.choice([3, 4, 5])   # outliers
for i in rng.choice(n, 4, replace=False): df.loc[i, "Profit"] = -abs(df.loc[i, "Sales"]) * .5
for c, k in [("Customer_Rating", 25), ("Discount", 10), ("Region", 6)]:
    df.loc[rng.choice(n, k, replace=False), c] = np.nan
df.to_csv("sales_demo.csv", index=False)
print(df.shape)
