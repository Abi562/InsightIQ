"""All data analysis logic. Only safe, predefined pandas / scikit-learn operations."""
import re
import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import accuracy_score, mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

warnings.filterwarnings("ignore")
COLORS = ["#2563eb", "#0ea5e9", "#1e3a8a", "#38bdf8", "#6366f1", "#14b8a6", "#f59e0b", "#ef4444"]


class DataError(Exception):
    """User-facing data problem."""


# ---------------------------------------------------------------- loading
_DATE_RE = r"^\d{4}-\d{1,2}-\d{1,2}|^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"


def load_df(path):
    ext = path.rsplit(".", 1)[-1].lower()
    try:
        if ext == "csv":
            try:
                df = pd.read_csv(path)
            except UnicodeDecodeError:
                df = pd.read_csv(path, encoding="latin-1")
            except pd.errors.ParserError:
                df = pd.read_csv(path, sep=None, engine="python")
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(path)
        else:
            raise DataError("Unsupported file type. Use CSV or XLSX.")
    except DataError:
        raise
    except pd.errors.EmptyDataError:
        raise DataError("The file is empty.")
    except Exception as e:
        raise DataError(f"Could not read this file: {str(e)[:150]}")
    df = df.dropna(how="all").dropna(axis=1, how="all")
    if df.empty or df.shape[1] == 0:
        raise DataError("The file contains no usable data.")
    df.columns = [str(c).strip() or f"column_{i}" for i, c in enumerate(df.columns)]
    for c in df.columns:
        s = df[c]
        if pd.api.types.is_numeric_dtype(s) or pd.api.types.is_datetime64_any_dtype(s) or pd.api.types.is_bool_dtype(s):
            continue
        sample = s.dropna().astype(str).head(200)
        if len(sample) and sample.str.match(_DATE_RE).mean() >= 0.8:
            parsed = pd.to_datetime(s, errors="coerce")
            if parsed.notna().mean() >= 0.9:
                df[c] = parsed
    return df


def kind_of(s):
    if pd.api.types.is_datetime64_any_dtype(s):
        return "datetime"
    if pd.api.types.is_bool_dtype(s):
        return "categorical"
    if pd.api.types.is_numeric_dtype(s):
        return "numeric"
    n, u = len(s), s.nunique()
    return "categorical" if (u <= 30 or u / max(n, 1) < 0.3) else "text"


def cols_by_kind(df):
    out = {"numeric": [], "categorical": [], "datetime": [], "text": []}
    for c in df.columns:
        out[kind_of(df[c])].append(c)
    return out


def main_numeric(df):
    nums = cols_by_kind(df)["numeric"]
    for hint in ("sales", "revenue", "amount", "profit", "price", "total", "value", "income", "cost"):
        for c in nums:
            if hint in c.lower():
                return c
    return nums[0] if nums else None


def fmt(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if np.isnan(v):
        return "—"
    return f"{v:,.0f}" if abs(v) >= 1000 else f"{v:,.2f}"


def _num(x, nd=2):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) or np.isinf(x) else round(x, nd)


def lst(x):
    s = pd.Series(x)
    if pd.api.types.is_datetime64_any_dtype(s):
        return [None if pd.isna(v) else v.strftime("%Y-%m-%d") for v in s]
    if s.dtype.kind in "iuf":
        cast = int if s.dtype.kind in "iu" else float
        return [None if pd.isna(v) else cast(v) for v in s]
    return [None if pd.isna(v) else str(v) for v in s]


def rows_for_table(d, max_cols=10):
    d = d.iloc[:, :max_cols]
    out = []
    for _, r in d.iterrows():
        row = []
        for v in r:
            if pd.isna(v):
                row.append("—")
            elif isinstance(v, pd.Timestamp):
                row.append(v.strftime("%Y-%m-%d"))
            elif isinstance(v, (float, np.floating)):
                row.append(f"{v:,.2f}")
            else:
                row.append(str(v))
        out.append(row)
    return list(d.columns), out


# ---------------------------------------------------------------- profiling
def quality_score(df):
    size = df.size or 1
    missing = int(df.isna().sum().sum())
    dups = int(df.duplicated().sum())
    completeness = 1 - missing / size
    uniqueness = 1 - dups / max(len(df), 1)
    bad = sum(1 for c in df.columns if df[c].isna().mean() > 0.5 or df[c].nunique() <= 1)
    validity = 1 - bad / df.shape[1]
    score = round(100 * (0.6 * completeness + 0.25 * uniqueness + 0.15 * validity), 1)
    label = "Excellent" if score >= 90 else "Good" if score >= 75 else "Fair" if score >= 60 else "Poor"
    return score, label, {"Completeness": round(completeness * 100, 1),
                          "Uniqueness": round(uniqueness * 100, 1),
                          "Column validity": round(validity * 100, 1)}


def profile(df):
    cols = []
    for c in df.columns:
        s = df[c]
        miss = int(s.isna().sum())
        sample = ", ".join(str(v) for v in s.dropna().unique()[:3])
        cols.append(dict(name=c, kind=kind_of(s), dtype=str(s.dtype), missing=miss,
                         missing_pct=round(miss / max(len(df), 1) * 100, 1),
                         unique=int(s.nunique()), sample=sample[:60]))
    nums = cols_by_kind(df)["numeric"]
    stats = []
    for c in nums:
        s = df[c].dropna()
        if s.empty:
            continue
        stats.append(dict(name=c, mean=_num(s.mean()), std=_num(s.std()), min=_num(s.min()),
                          q1=_num(s.quantile(.25)), median=_num(s.median()),
                          q3=_num(s.quantile(.75)), max=_num(s.max())))
    score, label, parts = quality_score(df)
    return dict(rows=len(df), cols=df.shape[1], missing=int(df.isna().sum().sum()),
                duplicates=int(df.duplicated().sum()), columns=cols, stats=stats,
                score=score, label=label, parts=parts)


def base_layout(title="", **kw):
    grid = dict(gridcolor="#e2e8f0", zerolinecolor="#e2e8f0")
    layout = dict(title=dict(text=title, font=dict(size=15, color="#0b1f3a")),
                  paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                  font=dict(family="Inter, Segoe UI, sans-serif", color="#334155"),
                  margin=dict(l=55, r=20, t=50, b=50), colorway=COLORS,
                  xaxis=dict(**grid), yaxis=dict(**grid),
                  legend=dict(orientation="h", y=-0.2))
    for k, v in kw.items():
        if k in ("xaxis", "yaxis"):
            layout[k] = {**grid, **v}
        else:
            layout[k] = v
    return layout


# ---------------------------------------------------------------- insights
def insights(df):
    out, k = [], cols_by_kind(df)
    nums, cats, dates = k["numeric"], k["categorical"], k["datetime"]

    def add(icon, title, text, level="info"):
        out.append(dict(icon=icon, title=title, text=text, level=level))

    add("table", "Dataset overview", f"{len(df):,} rows and {df.shape[1]} columns: {len(nums)} numeric, "
        f"{len(cats)} categorical, {len(dates)} date, {len(k['text'])} text.")
    for c in nums[:6]:
        s = df[c].dropna()
        if s.empty:
            continue
        add("bar-chart-line", f"{c}: key numbers",
            f"Average {fmt(s.mean())}, median {fmt(s.median())}, minimum {fmt(s.min())}, maximum {fmt(s.max())}.")
    if len(nums) >= 2:
        corr = df[nums].corr()
        pairs = []
        for i, a in enumerate(nums):
            for b in nums[i + 1:]:
                r = corr.loc[a, b]
                if not np.isnan(r) and abs(r) >= 0.5:
                    pairs.append((abs(r), r, a, b))
        pairs.sort(reverse=True)
        for _, r, a, b in pairs[:4]:
            word = "positively" if r > 0 else "negatively"
            strength = "strongly" if abs(r) >= 0.7 else "moderately"
            add("diagram-3", f"Correlation: {a} & {b}",
                f"{a} and {b} are {strength} {word} correlated (r = {r:.2f}).", "good")
        if not pairs:
            add("diagram-3", "Correlations", "No strong linear correlations (|r| ≥ 0.5) were found between numeric columns.")
    for c in nums:
        s = df[c].dropna()
        if len(s) > 10 and s.nunique() > 5 and abs(s.skew()) > 1:
            add("graph-up", f"Skewed distribution: {c}",
                f"{c} is {'right' if s.skew() > 0 else 'left'}-skewed (skew {s.skew():.1f}); the mean differs "
                f"noticeably from the median, so a few extreme values may be driving it.", "warn")
            break
    for c in cats[:3]:
        vc = df[c].value_counts()
        if len(vc):
            add("tags", f"Most common {c}", f"'{vc.index[0]}' appears {vc.iloc[0]:,} times ({vc.iloc[0] / vc.sum() * 100:.0f}% of values).")
    tgt = main_numeric(df)
    if tgt:
        for c in cats:
            if 2 <= df[c].nunique() <= 20:
                g = df.groupby(c)[tgt].mean().dropna()
                if len(g) >= 2:
                    add("trophy", f"Best & weakest {c}",
                        f"'{g.idxmax()}' has the highest average {tgt} ({fmt(g.max())}); '{g.idxmin()}' has the lowest ({fmt(g.min())}).", "good")
                    break
        if dates:
            d = df[[dates[0], tgt]].dropna().sort_values(dates[0])
            if len(d) >= 10:
                h = len(d) // 2
                a, b = d[tgt].iloc[:h].mean(), d[tgt].iloc[h:].mean()
                if a:
                    ch = (b - a) / abs(a) * 100
                    add("graph-up-arrow" if ch >= 0 else "graph-down-arrow", f"Trend in {tgt}",
                        f"Average {tgt} in the second half of the period is {abs(ch):.1f}% {'higher' if ch >= 0 else 'lower'} than in the first half.",
                        "good" if ch >= 0 else "warn")
    for c in df.columns:
        p = df[c].isna().mean() * 100
        if p >= 5:
            add("exclamation-triangle", f"Missing values in {c}", f"{p:.1f}% of {c} is missing; consider cleaning or filling it.", "warn")
    d = int(df.duplicated().sum())
    if d:
        add("copy", "Duplicate rows", f"{d:,} duplicate rows detected.", "warn")
    return out


# ---------------------------------------------------------------- charts
def make_chart(df, ctype, x=None, y=None, agg="mean"):
    k = cols_by_kind(df)
    if agg not in ("mean", "sum", "count", "median", "max", "min"):
        agg = "mean"

    def need(c):
        if not c or c not in df.columns:
            raise DataError("Please choose a valid column for this chart.")
        return c

    def numeric(c):
        s = pd.to_numeric(df[need(c)], errors="coerce")
        if s.notna().sum() == 0:
            raise DataError(f"'{c}' is not numeric.")
        return s

    if ctype == "histogram":
        s = numeric(x).dropna()
        return dict(data=[dict(type="histogram", x=lst(s), nbinsx=30, marker=dict(color=COLORS[0]))],
                    layout=base_layout(f"Distribution of {x}", xaxis=dict(title=x), yaxis=dict(title="Count")))
    if ctype in ("bar", "pie"):
        need(x)
        if y and y in df.columns and kind_of(df[y]) == "numeric" and agg != "count":
            g = df.groupby(x)[y].agg(agg).dropna()
            label = f"{agg.title()} of {y} by {x}"
        else:
            g = df[x].value_counts()
            label, y = f"Count by {x}", None
        g = g.sort_values(ascending=False).head(20 if ctype == "bar" else 8)
        if g.empty:
            raise DataError("No data to plot.")
        if ctype == "pie":
            return dict(data=[dict(type="pie", labels=[str(i) for i in g.index], values=lst(g.values), hole=.45,
                                   marker=dict(colors=COLORS))], layout=base_layout(label))
        return dict(data=[dict(type="bar", x=[str(i) for i in g.index], y=lst(g.values), marker=dict(color=COLORS[0]))],
                    layout=base_layout(label, xaxis=dict(title=x), yaxis=dict(title=y or "Count")))
    if ctype == "line":
        need(x)
        numeric(y)
        d = df[[x, y]].dropna()
        if d.empty:
            raise DataError("No data to plot.")
        if kind_of(df[x]) == "datetime":
            span = (d[x].max() - d[x].min()).days
            freq = "D" if span <= 90 else "W" if span <= 500 else "MS"
            g = d.set_index(x)[y].sort_index().resample(freq).agg(agg if agg != "count" else "count").dropna()
        else:
            g = d.groupby(x)[y].agg(agg).sort_index().head(500)
        return dict(data=[dict(type="scatter", mode="lines+markers", x=lst(g.index), y=lst(g.values),
                               line=dict(color=COLORS[0], width=2), marker=dict(size=4))],
                    layout=base_layout(f"{agg.title()} of {y} over {x}", xaxis=dict(title=x), yaxis=dict(title=y)))
    if ctype == "scatter":
        xs, ys = numeric(x), numeric(y)
        d = pd.DataFrame({"x": xs, "y": ys}).dropna()
        if len(d) > 3000:
            d = d.sample(3000, random_state=1)
        return dict(data=[dict(type="scatter", mode="markers", x=lst(d.x), y=lst(d.y),
                               marker=dict(color=COLORS[0], opacity=.6, size=6))],
                    layout=base_layout(f"{y} vs {x}", xaxis=dict(title=x), yaxis=dict(title=y)))
    if ctype == "box":
        numeric(y)
        traces = []
        if x and x in df.columns and df[x].nunique() <= 15:
            for i, (name, grp) in enumerate(df.groupby(x)):
                traces.append(dict(type="box", name=str(name), y=lst(pd.to_numeric(grp[y], errors="coerce").dropna()),
                                   marker=dict(color=COLORS[i % len(COLORS)])))
        else:
            traces.append(dict(type="box", name=y, y=lst(pd.to_numeric(df[y], errors="coerce").dropna()), marker=dict(color=COLORS[0])))
        return dict(data=traces, layout=base_layout(f"Spread of {y}", yaxis=dict(title=y), showlegend=False))
    if ctype == "heatmap":
        nums = k["numeric"]
        if len(nums) < 2:
            raise DataError("A correlation heatmap needs at least two numeric columns.")
        c = df[nums].corr().round(2)
        return dict(data=[dict(type="heatmap", z=[[None if pd.isna(v) else float(v) for v in r] for r in c.values],
                               x=nums, y=nums, zmin=-1, zmax=1, texttemplate="%{z:.2f}",
                               colorscale=[[0, "#ef4444"], [.5, "#ffffff"], [1, "#2563eb"]])],
                    layout=base_layout("Correlation heatmap", margin=dict(l=110, r=20, t=50, b=100)))
    raise DataError("Unknown chart type.")


def auto_charts(df):
    k = cols_by_kind(df)
    tgt = main_numeric(df)
    charts = []
    tries = []
    if k["datetime"] and tgt:
        tries.append(("line", k["datetime"][0], tgt, "sum"))
    if k["categorical"] and tgt:
        tries.append(("bar", k["categorical"][0], tgt, "sum"))
    if tgt:
        tries.append(("histogram", tgt, None, "mean"))
    if len(k["numeric"]) >= 3:
        tries.append(("heatmap", None, None, "mean"))
    for t, x, y, a in tries:
        try:
            charts.append(make_chart(df, t, x, y, a))
        except DataError:
            pass
    return charts


# ---------------------------------------------------------------- anomaly detection
def detect_anomalies(df, contamination=0.05):
    nums = [c for c in cols_by_kind(df)["numeric"] if df[c].nunique() > 1]
    if not nums:
        raise DataError("Anomaly detection needs at least one numeric column with varying values.")
    if len(df) < 10:
        raise DataError("Anomaly detection needs at least 10 rows.")
    contamination = min(max(float(contamination), 0.01), 0.25)
    X = df[nums].copy()
    X = X.fillna(X.median())
    std = X.std(ddof=0).replace(0, 1)
    Z = (X - X.mean()) / std
    iso = IsolationForest(n_estimators=150, contamination=contamination, random_state=42)
    flag = iso.fit_predict(Z) == -1
    score = -iso.score_samples(Z)
    res = df.copy()
    res["anomaly_score"] = np.round(score, 3)
    res["reason"] = [f"Unusual {Z.columns[np.argmax(np.abs(r))]} ({'high' if r[np.argmax(np.abs(r))] > 0 else 'low'}, z={r[np.argmax(np.abs(r))]:.1f})"
                     for r in Z.values]
    an = res[flag].sort_values("anomaly_score", ascending=False)
    show = an.head(50)
    cols, rows = rows_for_table(show[[c for c in df.columns[:7]] + ["anomaly_score", "reason"]], 9)
    # chart
    if len(nums) >= 2:
        a, b = nums[0], nums[1]
        xa, xb = X[a], X[b]
        title = f"{b} vs {a}"
        ax = dict(xaxis=dict(title=a), yaxis=dict(title=b))
    else:
        a = "row index"
        xa, xb = pd.Series(np.arange(len(df))), X[nums[0]]
        title = f"{nums[0]} by row"
        ax = dict(xaxis=dict(title=a), yaxis=dict(title=nums[0]))
    fig = dict(data=[
        dict(type="scatter", mode="markers", name="Normal", x=lst(xa[~flag]), y=lst(xb[~flag]),
             marker=dict(color="#93c5fd", size=6, opacity=.7)),
        dict(type="scatter", mode="markers", name="Anomaly", x=lst(xa[flag]), y=lst(xb[flag]),
             marker=dict(color="#ef4444", size=10, symbol="diamond", line=dict(color="#7f1d1d", width=1)))],
        layout=base_layout(f"Anomalies: {title}", **ax))
    return dict(count=int(flag.sum()), pct=round(flag.mean() * 100, 1), features=nums, cols=cols, rows=rows,
                fig=fig, total=len(df), shown=len(show))


# ---------------------------------------------------------------- forecasting
def forecast(df, target, date_col=None, periods=6, agg="sum"):
    if not target or target not in df.columns or kind_of(df[target]) != "numeric":
        raise DataError("Choose a numeric column to forecast.")
    periods = int(min(max(periods, 1), 36))
    if agg not in ("sum", "mean"):
        agg = "sum"
    dates_used = bool(date_col and date_col in df.columns and kind_of(df[date_col]) == "datetime")
    if dates_used:
        d = df[[date_col, target]].dropna().sort_values(date_col)
        if len(d) < 6:
            raise DataError("Not enough rows with both a date and a value (need at least 6).")
        span = (d[date_col].max() - d[date_col].min()).days
        freq, flabel = ("D", "day") if span <= 60 else ("W", "week") if span <= 400 else ("MS", "month")
        g = d.set_index(date_col)[target].resample(freq).agg(agg).dropna()
        if freq != "D" and len(g) > 6:      # drop a trailing, incomplete period so it doesn't skew the trend
            end = g.index[-1] + (pd.offsets.MonthEnd(0) if freq == "MS" else pd.Timedelta(0))
            if d[date_col].max().normalize() < end.normalize():
                g = g.iloc[:-1]
        if len(g) < 4:
            raise DataError("Not enough time periods to build a forecast.")
        labels = list(g.index)
        fut = list(pd.date_range(start=g.index[-1], periods=periods + 1, freq=freq)[1:])
        xs, fx = lst(pd.Series(labels)), lst(pd.Series(fut))
    else:
        s = df[target].dropna().reset_index(drop=True)
        if len(s) < 6:
            raise DataError("Not enough values to build a forecast (need at least 6).")
        g, flabel = s, "row"
        xs, fx = list(range(1, len(s) + 1)), list(range(len(s) + 1, len(s) + periods + 1))
    y = g.values.astype(float)
    t = np.arange(len(y)).reshape(-1, 1)
    model = LinearRegression().fit(t, y)
    fitted = model.predict(t)
    tf = np.arange(len(y), len(y) + periods).reshape(-1, 1)
    pred = model.predict(tf)
    resid = float(np.std(y - fitted))
    r2 = float(r2_score(y, fitted))
    slope = float(model.coef_[0])
    fig = dict(data=[
        dict(type="scatter", mode="lines+markers", name="Actual", x=xs, y=lst(y), line=dict(color=COLORS[0], width=2), marker=dict(size=4)),
        dict(type="scatter", mode="lines", name="Trend line", x=xs, y=lst(fitted), line=dict(color="#94a3b8", dash="dash")),
        dict(type="scatter", mode="lines", name="Upper range", x=fx, y=lst(pred + 1.96 * resid), line=dict(width=0), showlegend=False, hoverinfo="skip"),
        dict(type="scatter", mode="lines", name="Likely range", x=fx, y=lst(pred - 1.96 * resid), fill="tonexty",
             fillcolor="rgba(245,158,11,.18)", line=dict(width=0), hoverinfo="skip"),
        dict(type="scatter", mode="lines+markers", name="Forecast", x=fx, y=lst(pred),
             line=dict(color="#f59e0b", width=3), marker=dict(size=6))],
        layout=base_layout(f"Forecast of {target} ({periods} {flabel}s ahead)", yaxis=dict(title=target)))
    change = (pred[-1] - fitted[-1]) / abs(fitted[-1]) * 100 if fitted[-1] else 0
    return dict(fig=fig, r2=round(r2, 3), slope=round(slope, 3), flabel=flabel, points=len(y), dates_used=dates_used,
                direction="upward" if slope > 0 else "downward" if slope < 0 else "flat", change=round(change, 1),
                table=[(str(a), fmt(b)) for a, b in zip(fx, pred)])


# ---------------------------------------------------------------- random forest prediction
_MODELS = {}


def build_model(df, target, key=None):
    if key and key in _MODELS:
        return _MODELS[key]
    if not target or target not in df.columns:
        raise DataError("Choose a valid target column.")
    k = cols_by_kind(df)
    d = df.dropna(subset=[target]).copy()
    if len(d) < 30:
        raise DataError("Need at least 30 rows with a value in the target column.")
    if len(d) > 20000:
        d = d.sample(20000, random_state=42)
    n_t = d[target].nunique()
    is_reg = kind_of(d[target]) == "numeric" and n_t > 10
    if kind_of(d[target]) in ("datetime", "text"):
        raise DataError("Choose a numeric or categorical target column.")
    if n_t < 2:
        raise DataError("The target column has only one distinct value.")
    if not is_reg and n_t > 30:
        raise DataError("Target has too many categories. Choose a numeric column or one with fewer categories.")
    nums = [c for c in k["numeric"] if c != target and d[c].nunique() > 1
            and not (d[c].nunique() == len(d) and pd.api.types.is_integer_dtype(d[c]))]
    cats = [c for c in k["categorical"] if c != target and 1 < d[c].nunique() <= 20]
    if not nums and not cats:
        raise DataError("No usable feature columns found for this target.")
    medians = {c: float(d[c].median()) for c in nums}
    parts, owner = [], {}
    Xn = d[nums].copy()
    for c in nums:
        Xn[c] = Xn[c].fillna(medians[c])
    parts.append(Xn)
    for c in nums:
        owner[c] = c
    options, modes = {}, {}
    for c in cats:
        col = d[c].astype(object).where(d[c].notna(), "Missing").astype(str)
        options[c] = sorted(col.unique())[:20]
        modes[c] = col.mode().iloc[0]
        dm = pd.get_dummies(col, prefix=c, dtype=float)
        for cc in dm.columns:
            owner[cc] = c
        parts.append(dm)
    X = pd.concat(parts, axis=1)
    y = d[target] if is_reg else d[target].astype(str)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42)
    Model = RandomForestRegressor if is_reg else RandomForestClassifier
    model = Model(n_estimators=100, max_depth=12, random_state=42, n_jobs=1).fit(Xtr, ytr)
    pred = model.predict(Xte)
    imp = {}
    for col, v in zip(X.columns, model.feature_importances_):
        imp[owner[col]] = imp.get(owner[col], 0) + float(v)
    imp = sorted(imp.items(), key=lambda kv: kv[1], reverse=True)
    if is_reg:
        mae, base_mae = mean_absolute_error(yte, pred), mean_absolute_error(yte, np.full(len(yte), ytr.mean()))
        metrics = [("R² score", f"{r2_score(yte, pred):.3f}"), ("Mean abs. error", fmt(mae)), ("Baseline error (mean guess)", fmt(base_mae))]
        lo, hi = float(min(yte.min(), pred.min())), float(max(yte.max(), pred.max()))
        fig2 = dict(data=[dict(type="scatter", mode="markers", name="Test rows", x=lst(yte), y=lst(pred), marker=dict(color=COLORS[0], opacity=.6, size=6)),
                          dict(type="scatter", mode="lines", name="Perfect prediction", x=[lo, hi], y=[lo, hi], line=dict(color="#f59e0b", dash="dash"))],
                    layout=base_layout("Actual vs predicted (unseen test rows)", xaxis=dict(title="Actual"), yaxis=dict(title="Predicted")))
    else:
        base = float((yte == ytr.mode().iloc[0]).mean())
        metrics = [("Accuracy", f"{accuracy_score(yte, pred) * 100:.1f}%"), ("Baseline (always most common)", f"{base * 100:.1f}%")]
        vc = pd.crosstab(yte, pd.Series(pred, index=yte.index))
        fig2 = dict(data=[dict(type="heatmap", z=vc.values.tolist(), x=[str(c) for c in vc.columns], y=[str(i) for i in vc.index],
                               colorscale="Blues", texttemplate="%{z}")],
                    layout=base_layout("Confusion matrix (actual rows vs predicted columns)", xaxis=dict(title="Predicted"), yaxis=dict(title="Actual")))
    top = imp[:10][::-1]
    fig1 = dict(data=[dict(type="bar", orientation="h", x=[round(v * 100, 1) for _, v in top], y=[n for n, _ in top], marker=dict(color=COLORS[0]))],
                layout=base_layout("Feature importance (%)", margin=dict(l=130, r=20, t=50, b=40)))
    bundle = dict(model=model, columns=list(X.columns), nums=nums, cats=cats, medians=medians, options=options, modes=modes,
                  is_reg=is_reg, metrics=metrics, importance=imp, fig_imp=fig1, fig_fit=fig2, target=target,
                  top_features=[n for n, _ in imp[:8]], task="Regression" if is_reg else "Classification", rows=len(d))
    if key:
        if len(_MODELS) > 20:
            _MODELS.clear()
        _MODELS[key] = bundle
    return bundle


def predict_one(b, inputs):
    row = {c: 0.0 for c in b["columns"]}
    for c in b["nums"]:
        try:
            row[c] = float(inputs.get(c, b["medians"][c]))
        except (TypeError, ValueError):
            row[c] = b["medians"][c]
    for c in b["cats"]:
        v = str(inputs.get(c, b["modes"][c]))
        if f"{c}_{v}" in row:
            row[f"{c}_{v}"] = 1.0
    X = pd.DataFrame([row])[b["columns"]]
    p = b["model"].predict(X)[0]
    if b["is_reg"]:
        return dict(value=fmt(p), extra=None)
    proba = sorted(zip(b["model"].classes_, b["model"].predict_proba(X)[0]), key=lambda t: -t[1])[:3]
    return dict(value=str(p), extra=[(str(c), f"{q * 100:.0f}%") for c, q in proba])


# ---------------------------------------------------------------- ask your data
def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("_", " "))).strip()


def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") else w


def _match_cols(qn, df):
    found = {}
    qwords = {_stem(w) for w in qn.split()}
    for c in df.columns:
        cn = _norm(c)
        if not cn:
            continue
        m = re.search(r"\b" + re.escape(_stem(cn)) + r"s?\b", qn)
        if m:
            found[c] = m.start()
    if not found:
        for c in df.columns:
            toks = [_stem(t) for t in _norm(c).split() if len(t) >= 4]
            if any(t in qwords for t in toks):
                found[c] = qn.find(toks[0]) if toks[0] in qn else 999
    return sorted(found, key=found.get)


def _tbl(d, index=True):
    return d.to_html(classes="table table-sm table-hover align-middle", border=0, na_rep="—", index=index,
                     float_format=lambda v: f"{v:,.2f}")


def ask(df, question):
    q = (question or "").strip()
    if not q:
        raise DataError("Please type a question.")
    qn = _norm(q)
    k = cols_by_kind(df)
    nums, cats = k["numeric"], k["categorical"]
    mentioned = _match_cols(qn, df)
    d, notes = df, []
    for c in cats:                                   # optional filters, e.g. "in North"
        if df[c].nunique() <= 50:
            for v in df[c].dropna().unique():
                vn = _norm(v)
                if len(vn) >= 3 and re.search(r"\b" + re.escape(vn) + r"\b", qn):
                    d = d[d[c].astype(str) == str(v)]
                    notes.append(f"{c} = {v}")
                    break
    note = f" (where {', '.join(notes)})" if notes else ""
    if d.empty:
        return dict(answer="No rows match those filters.", table=None, fig=None)
    m_nums = [c for c in mentioned if c in nums]

    def has(*ws):
        return bool(re.search(r"\b(?:" + "|".join(ws) + ")", qn))

    agg = None
    for name, words in (("mean", ("average", "avg", "mean")), ("max", ("maximum", "max", "highest", "largest", "biggest", "greatest", "best")),
                        ("min", ("minimum", "min", "lowest", "smallest", "least", "worst")), ("sum", ("total", "sum")),
                        ("median", ("median",)), ("std", ("std", "standard deviation", "deviation")), ("count", ("count",))):
        if re.search(r"\b(?:" + "|".join(words) + r")s?\b", qn):
            agg = name
            break
    verb = {"mean": "average", "max": "maximum", "min": "minimum", "sum": "total", "median": "median", "std": "standard deviation", "count": "count"}

    if has("correlat", "relationship", "related"):
        if len(m_nums) >= 2:
            r = d[m_nums[0]].corr(d[m_nums[1]])
            strength = "strong" if abs(r) >= .7 else "moderate" if abs(r) >= .4 else "weak"
            return dict(answer=f"The correlation between {m_nums[0]} and {m_nums[1]} is {r:.2f} ({strength} {'positive' if r > 0 else 'negative'}).{note}",
                        table=None, fig=make_chart(d, "scatter", m_nums[0], m_nums[1]))
        if len(nums) >= 2:
            c = d[nums].corr()
            pairs = [(abs(c.loc[a, b]), c.loc[a, b], a, b) for i, a in enumerate(nums) for b in nums[i + 1:] if not np.isnan(c.loc[a, b])]
            if pairs:
                _, r, a, b = max(pairs)
                return dict(answer=f"The strongest correlation is between {a} and {b} (r = {r:.2f}).", table=None, fig=make_chart(d, "heatmap"))
        return dict(answer="I need at least two numeric columns to compute correlations.", table=None, fig=None)
    if has("missing", "null", "empty", "blank", "nan"):
        if mentioned:
            c = mentioned[0]
            n = int(d[c].isna().sum())
            return dict(answer=f"'{c}' has {n:,} missing values ({n / len(d) * 100:.1f}%).{note}", table=None, fig=None)
        m = d.isna().sum()
        m = m[m > 0].rename("Missing values").to_frame()
        if m.empty:
            return dict(answer="Great news: there are no missing values.", table=None, fig=None)
        return dict(answer=f"{int(d.isna().sum().sum()):,} missing values across {len(m)} columns.{note}", table=_tbl(m), fig=None)
    if has("duplicate"):
        return dict(answer=f"There are {int(d.duplicated().sum()):,} duplicate rows.{note}", table=None, fig=None)
    if re.search(r"\b(how many|number of|count of|total)\s+(rows|records|entries|observations)\b", qn) or has("row count", "rows"):
        if not (agg and m_nums):
            return dict(answer=f"The dataset has {len(d):,} rows{note}.", table=None, fig=None)
    if re.search(r"\b(how many|number of|count of)\s+(columns|fields|variables)\b", qn) or has("column names", "list columns", "what columns", "columns", "fields"):
        return dict(answer=f"There are {df.shape[1]} columns.", table=_tbl(pd.DataFrame({"Column": df.columns, "Type": [kind_of(df[c]) for c in df.columns]}), index=False), fig=None)
    if has("unique", "distinct", "different") and mentioned:
        c = mentioned[0]
        vals = d[c].dropna().unique()
        extra = ", ".join(map(str, vals[:15])) + ("…" if len(vals) > 15 else "")
        return dict(answer=f"'{c}' has {len(vals):,} unique values. {extra if len(vals) <= 15 else 'Examples: ' + extra}", table=None, fig=None)
    if has("most common", "most frequent", "mode", "frequent", "popular", "top category", "common"):
        c = next((m for m in mentioned if m not in nums), None) or (cats[0] if cats else None)
        if c is None:
            return dict(answer="I couldn't find a categorical column to analyse.", table=None, fig=None)
        vc = d[c].value_counts().head(8)
        return dict(answer=f"The most common {c} is '{vc.index[0]}' with {vc.iloc[0]:,} occurrences ({vc.iloc[0] / d[c].notna().sum() * 100:.0f}%).{note}",
                    table=_tbl(vc.rename("Count").to_frame()), fig=make_chart(d, "bar", c))
    by_cat = [c for c in mentioned if c not in nums]
    if m_nums and by_cat and (has("by", "per", "each", "which", "what") or agg):
        ncol, gcol = m_nums[0], by_cat[0]
        a = agg if agg in ("mean", "sum", "max", "min", "median", "count") else ("sum" if has("which", "what") else "mean")
        a_eff = "sum" if a in ("max", "min") and has("which", "what") and not has("average") else a
        g = d.groupby(gcol)[ncol].agg(a_eff).dropna().sort_values(ascending=(a == "min"))
        if not g.empty:
            head = f"'{g.index[0]}' has the {'lowest' if a == 'min' else 'highest'} {verb.get(a_eff, a_eff)} {ncol} ({fmt(g.iloc[0])}).{note}"
            return dict(answer=head, table=_tbl(g.rename(f"{verb.get(a_eff, a_eff).title()} {ncol}").to_frame()),
                        fig=make_chart(d, "bar", gcol, ncol, a_eff))
    mt = re.search(r"\b(top|bottom)\s+(\d+)", qn)
    if mt and (m_nums or nums):
        c = m_nums[0] if m_nums else main_numeric(d)
        n = min(int(mt.group(2)), 50)
        r = d.nlargest(n, c) if mt.group(1) == "top" else d.nsmallest(n, c)
        cols, _ = rows_for_table(r, 8)
        return dict(answer=f"{mt.group(1).title()} {len(r)} rows by {c}:{note}", table=_tbl(r[cols], index=False), fig=None)
    if agg and agg != "count" and (m_nums or nums):
        targets = m_nums[:1] or nums
        if len(targets) == 1:
            c = targets[0]
            s = d[c].dropna()
            if s.empty:
                return dict(answer=f"'{c}' has no values.", table=None, fig=None)
            val = getattr(s, agg)()
            ans = f"The {verb[agg]} {c} is {fmt(val)}.{note}"
            tbl = None
            if agg in ("max", "min"):
                row = d.loc[[s.idxmax() if agg == "max" else s.idxmin()]]
                cols, _ = rows_for_table(row, 8)
                tbl = _tbl(row[cols], index=False)
            return dict(answer=ans, table=tbl, fig=None)
        res = d[targets].agg(agg).rename(verb[agg].title()).to_frame()
        return dict(answer=f"The {verb[agg]} of each numeric column{note}:", table=_tbl(res), fig=None)
    if agg == "count" and mentioned:
        return dict(answer=f"'{mentioned[0]}' has {int(d[mentioned[0]].notna().sum()):,} non-empty values.{note}", table=None, fig=None)
    if has("summary", "describe", "overview", "statistics", "stats"):
        if nums:
            desc = d[nums].describe().T.rename(columns={"50%": "median"})
            return dict(answer=f"Summary statistics for {len(nums)} numeric columns{note}:", table=_tbl(desc[["count", "mean", "std", "min", "median", "max"]]), fig=None)
    return dict(answer="I couldn't understand that question. Try one of the example questions below, and mention a column name "
                       f"(e.g. {', '.join(df.columns[:3])}).", table=None, fig=None)
