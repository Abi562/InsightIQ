# InsightIQ
**AI-Powered Business Intelligence & Decision Intelligence Platform** — a simple Flask MVP.

Upload a dataset → profile it → get insights & charts → detect anomalies → forecast → predict → ask questions in plain English → analyse documents → export a report.
No API keys and no generative AI are required. Everything runs locally with pandas and scikit-learn.

## Quick start
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py
```
Open **http://127.0.0.1:5000**

**Demo login:** `demo@insightiq.com` / `demo1234` (comes with the *Retail Sales Demo* dataset already loaded).
Or register your own account — then click **Load demo data** to try the sample data.

> The pages load Bootstrap, Bootstrap Icons, Plotly.js and a Google font from CDNs, so an internet connection is needed in the browser.

## Features
| Page | What it does |
|---|---|
| Login / Register | Accounts stored in SQLite, hashed passwords |
| Dashboard | KPIs, workflow shortcuts, active dataset summary, auto charts, recent activity |
| Upload Dataset | CSV / XLSX upload (drag & drop), manage datasets, load demo data |
| Data Profiling | Rows/columns, data types, missing & unique values, statistics, **data quality score** |
| Insights | Averages, min/max, correlations, skew, best/worst categories, trends, data-quality warnings |
| Charts | Automatic charts + custom builder (bar, line, scatter, histogram, box, pie, heatmap) with Plotly |
| Anomaly Detection | **Isolation Forest** with adjustable sensitivity; shows why each row is unusual |
| Forecasting | **Linear Regression** trend on a date column (or row order) with a likely-range band |
| ML Prediction | **Random Forest** regressor/classifier, metrics vs baseline, feature importance, try-your-own prediction |
| Ask Your Data | Rule-based questions → safe, predefined pandas operations (no `eval`, no SQL) |
| Documents | PDF / DOCX / TXT text extraction, statistics, top keywords, keyword search |
| Reports | Printable / downloadable (HTML) analysis summary |
| History | Log of uploads and analyses |
| Settings | Name, default anomaly share & forecast horizon, password, delete data |

### Example questions for "Ask Your Data"
`How many rows?` · `What is the average sales?` · `What is the maximum profit?` · `What is the most common category?` ·
`Average sales by region` · `Which region has the highest sales?` · `Top 5 sales` · `Total sales in North` ·
`Correlation between sales and profit` · `Any missing values?`

## Project structure
```
run.py                  # entry point:  python run.py
app/
  __init__.py           # app factory
  db.py                 # SQLite schema & connection
  routes.py             # all pages and API routes
  analytics.py          # profiling, insights, charts, anomaly, forecast, ML, Ask Your Data
  docs.py               # document extraction, stats, search
  templates/  static/   # Bootstrap 5 UI
sample_data/            # demo CSV + sample document (+ generator script)
uploads/                # uploaded files (git-ignored)
instance/insightiq.db   # SQLite database (created automatically, git-ignored)
```

## Notes
- Limits: 25 MB per upload. Random Forest training samples at most 20,000 rows.
- Set a real `SECRET_KEY` environment variable before deploying anywhere public. This MVP is meant for local demos.
- To reset everything, delete the `instance/` folder and the files in `uploads/`.
