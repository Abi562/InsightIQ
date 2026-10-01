import os
import shutil
import uuid
from datetime import datetime
from functools import wraps

from flask import (Blueprint, Response, current_app, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from . import analytics as an
from . import docs as dc
from .db import get_db

bp = Blueprint("main", __name__)
DATA_EXT = {"csv", "xlsx", "xls"}
DOC_EXT = {"pdf", "docx", "txt"}
DEMO_EMAIL, DEMO_PASS = "demo@insightiq.com", "demo1234"


# ------------------------------------------------------------------ helpers
def uid():
    return session.get("user_id")


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not uid():
            return redirect(url_for("main.login", next=request.path))
        return f(*a, **kw)
    return wrapper


def user_row():
    return get_db().execute("SELECT * FROM users WHERE id=?", (uid(),)).fetchone()


def upload_path(stored):
    return os.path.join(current_app.config["UPLOAD_FOLDER"], stored)


def get_dataset(ds_id):
    return get_db().execute("SELECT * FROM datasets WHERE id=? AND user_id=?", (ds_id, uid())).fetchone()


def active_dataset():
    db = get_db()
    sid = session.get("ds")
    ds = get_dataset(sid) if sid else None
    if ds is None:
        ds = db.execute("SELECT * FROM datasets WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid(),)).fetchone()
        if ds:
            session["ds"] = ds["id"]
    return ds


def dataset_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not uid():
            return redirect(url_for("main.login", next=request.path))
        ds = active_dataset()
        if not ds:
            return render_template("no_dataset.html")
        try:
            df = an.load_df(upload_path(ds["stored"]))
        except (an.DataError, FileNotFoundError) as e:
            flash(f"Could not open dataset '{ds['name']}': {e}", "danger")
            return redirect(url_for("main.upload"))
        g.ds, g.df = ds, df
        return f(*a, **kw)
    return wrapper


def log(action, detail="", ref_type=None, ref_id=None):
    db = get_db()
    last = db.execute("SELECT action, detail, ref_id, (strftime('%s','now') - strftime('%s', created_at)) AS age "
                      "FROM history WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid(),)).fetchone()
    if last and last["action"] == action and last["detail"] == detail and last["ref_id"] == ref_id and last["age"] < 60:
        return
    db.execute("INSERT INTO history (user_id, action, detail, ref_type, ref_id) VALUES (?,?,?,?,?)",
               (uid(), action, detail, ref_type, ref_id))
    db.commit()


def add_dataset(user_id, src_path, display_name, copy=False):
    """Validate a file, store metadata. Raises DataError on bad data."""
    df = an.load_df(src_path)
    score = an.quality_score(df)[0]
    ext = src_path.rsplit(".", 1)[-1].lower()
    stored = f"{uuid.uuid4().hex}.{ext}"
    if copy:
        shutil.copy(src_path, upload_path(stored))
    else:
        os.replace(src_path, upload_path(stored))
    db = get_db()
    cur = db.execute("INSERT INTO datasets (user_id,name,stored,rows,cols,quality) VALUES (?,?,?,?,?,?)",
                     (user_id, display_name, stored, len(df), df.shape[1], score))
    db.commit()
    return cur.lastrowid


def seed_demo():
    db = get_db()
    if db.execute("SELECT id FROM users WHERE email=?", (DEMO_EMAIL,)).fetchone():
        return
    cur = db.execute("INSERT INTO users (name,email,password_hash) VALUES (?,?,?)",
                     ("Demo User", DEMO_EMAIL, generate_password_hash(DEMO_PASS)))
    db.commit()
    sample = os.path.join(current_app.config["SAMPLE_DIR"], "sales_demo.csv")
    if os.path.exists(sample):
        try:
            ds_id = add_dataset(cur.lastrowid, sample, "Retail Sales Demo", copy=True)
            db.execute("INSERT INTO history (user_id,action,detail,ref_type,ref_id) VALUES (?,?,?,?,?)",
                       (cur.lastrowid, "upload", "Loaded demo dataset 'Retail Sales Demo'", "dataset", ds_id))
            db.commit()
        except an.DataError:
            pass


@bp.app_context_processor
def inject():
    if not uid():
        return {}
    ds = get_db().execute("SELECT id,name FROM datasets WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()
    act = active_dataset()
    return dict(all_datasets=ds, active_id=act["id"] if act else None, user_name=session.get("user_name", ""),
                now=datetime.utcnow().strftime("%Y-%m-%d %H:%M"))


# ------------------------------------------------------------------ auth
@bp.route("/")
def index():
    return redirect(url_for("main.dashboard" if uid() else "main.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        if not name or "@" not in email or "." not in email:
            flash("Enter your name and a valid email address.", "danger")
        elif len(pw) < 6:
            flash("Password must be at least 6 characters.", "danger")
        elif pw != request.form.get("confirm", ""):
            flash("Passwords do not match.", "danger")
        else:
            db = get_db()
            if db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
                flash("An account with this email already exists.", "danger")
            else:
                cur = db.execute("INSERT INTO users (name,email,password_hash) VALUES (?,?,?)",
                                 (name, email, generate_password_hash(pw)))
                db.commit()
                session.clear()
                session.update(user_id=cur.lastrowid, user_name=name)
                flash("Welcome to InsightIQ! Upload a dataset or load the demo data to begin.", "success")
                return redirect(url_for("main.dashboard"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        u = get_db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if u and check_password_hash(u["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=u["id"], user_name=u["name"])
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.dashboard"))
        flash("Incorrect email or password.", "danger")
    return render_template("login.html", demo_email=DEMO_EMAIL, demo_pass=DEMO_PASS)


@bp.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("main.login"))


# ------------------------------------------------------------------ dashboard
@bp.route("/dashboard")
@login_required
def dashboard():
    db = get_db()
    stats = dict(
        datasets=db.execute("SELECT COUNT(*) FROM datasets WHERE user_id=?", (uid(),)).fetchone()[0],
        docs=db.execute("SELECT COUNT(*) FROM documents WHERE user_id=?", (uid(),)).fetchone()[0],
        analyses=db.execute("SELECT COUNT(*) FROM history WHERE user_id=? AND action NOT IN ('upload','document')", (uid(),)).fetchone()[0],
        quality=db.execute("SELECT AVG(quality) FROM datasets WHERE user_id=?", (uid(),)).fetchone()[0])
    recent = db.execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 6", (uid(),)).fetchall()
    ds, charts, prof, ins = active_dataset(), [], None, []
    if ds:
        try:
            df = an.load_df(upload_path(ds["stored"]))
            prof = an.profile(df)
            charts = an.auto_charts(df)[:2]
            ins = an.insights(df)[:4]
        except (an.DataError, FileNotFoundError):
            ds = None
    return render_template("dashboard.html", stats=stats, recent=recent, ds=ds, charts=charts, prof=prof, ins=ins)


# ------------------------------------------------------------------ datasets
@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            flash("Please choose a CSV or XLSX file.", "danger")
        else:
            name = secure_filename(f.filename)
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in DATA_EXT:
                flash("Unsupported file type. Please upload a .csv or .xlsx file.", "danger")
            else:
                tmp = upload_path(f"tmp_{uuid.uuid4().hex}.{ext}")
                f.save(tmp)
                try:
                    ds_id = add_dataset(uid(), tmp, name)
                    session["ds"] = ds_id
                    log("upload", f"Uploaded dataset '{name}'", "dataset", ds_id)
                    flash(f"'{name}' uploaded successfully.", "success")
                    return redirect(url_for("main.profile"))
                except an.DataError as e:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    flash(str(e), "danger")
    rows = get_db().execute("SELECT * FROM datasets WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()
    return render_template("upload.html", datasets=rows)


@bp.route("/upload/demo", methods=["POST"])
@login_required
def load_demo():
    sample = os.path.join(current_app.config["SAMPLE_DIR"], "sales_demo.csv")
    try:
        ds_id = add_dataset(uid(), sample, "Retail Sales Demo", copy=True)
    except (an.DataError, FileNotFoundError) as e:
        flash(f"Could not load demo data: {e}", "danger")
        return redirect(url_for("main.upload"))
    session["ds"] = ds_id
    log("upload", "Loaded demo dataset 'Retail Sales Demo'", "dataset", ds_id)
    flash("Demo dataset loaded.", "success")
    return redirect(url_for("main.profile"))


@bp.route("/dataset/<int:ds_id>/select", methods=["GET", "POST"])
@login_required
def select_dataset(ds_id):
    if get_dataset(ds_id):
        session["ds"] = ds_id
    nxt = request.args.get("next", "")
    return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("main.profile"))


@bp.route("/dataset/<int:ds_id>/delete", methods=["POST"])
@login_required
def delete_dataset(ds_id):
    ds = get_dataset(ds_id)
    if ds:
        try:
            os.remove(upload_path(ds["stored"]))
        except OSError:
            pass
        db = get_db()
        db.execute("DELETE FROM datasets WHERE id=?", (ds_id,))
        db.commit()
        if session.get("ds") == ds_id:
            session.pop("ds", None)
        flash(f"Deleted '{ds['name']}'.", "info")
    return redirect(url_for("main.upload"))


# ------------------------------------------------------------------ analysis pages
@bp.route("/profile")
@dataset_required
def profile():
    prof = an.profile(g.df)
    miss = [c for c in prof["columns"] if c["missing"] > 0]
    kinds = {}
    for c in prof["columns"]:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    return render_template("profile.html", ds=g.ds, p=prof, miss_fig=(
        dict(data=[dict(type="bar", x=[c["name"] for c in miss], y=[c["missing_pct"] for c in miss], marker=dict(color="#f59e0b"))],
             layout=an.base_layout("Missing values by column (%)", yaxis=dict(title="% missing"))) if miss else None),
        kind_fig=dict(data=[dict(type="pie", labels=list(kinds), values=list(kinds.values()), hole=.55, marker=dict(colors=an.COLORS))],
                      layout=an.base_layout("Column types", margin=dict(l=10, r=10, t=50, b=10))),
        gauge=dict(data=[dict(type="indicator", mode="gauge+number", value=prof["score"], number=dict(suffix="%"),
                              gauge=dict(axis=dict(range=[0, 100]), bar=dict(color="#2563eb"),
                                         steps=[dict(range=[0, 60], color="#fee2e2"), dict(range=[60, 75], color="#fef3c7"),
                                                dict(range=[75, 100], color="#dbeafe")]))],
                   layout=an.base_layout("", margin=dict(l=20, r=20, t=20, b=10), height=230)))


@bp.route("/insights")
@dataset_required
def insights():
    log("insights", f"Generated insights for '{g.ds['name']}'", "dataset", g.ds["id"])
    return render_template("insights.html", ds=g.ds, items=an.insights(g.df))


@bp.route("/charts")
@dataset_required
def charts():
    k = an.cols_by_kind(g.df)
    return render_template("charts.html", ds=g.ds, k=k, cols=list(g.df.columns), auto=an.auto_charts(g.df))


@bp.route("/api/chart")
@login_required
def api_chart():
    ds = active_dataset()
    if not ds:
        return jsonify(error="No dataset selected."), 400
    try:
        df = an.load_df(upload_path(ds["stored"]))
        fig = an.make_chart(df, request.args.get("type", ""), request.args.get("x"), request.args.get("y") or None,
                            request.args.get("agg", "mean"))
        log("chart", f"Built a {request.args.get('type')} chart on '{ds['name']}'", "dataset", ds["id"])
        return jsonify(fig)
    except an.DataError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        return jsonify(error="Could not build this chart with the selected columns."), 400


@bp.route("/anomalies")
@dataset_required
def anomalies():
    try:
        cont = float(request.args.get("contamination", user_row()["contamination"] or 0.05))
    except ValueError:
        cont = 0.05
    cont = min(max(cont, 0.01), 0.25)
    res, error = None, None
    try:
        res = an.detect_anomalies(g.df, cont)
        log("anomaly", f"Found {res['count']} anomalies in '{g.ds['name']}'", "dataset", g.ds["id"])
    except an.DataError as e:
        error = str(e)
    return render_template("anomalies.html", ds=g.ds, res=res, error=error, cont=cont)


@bp.route("/forecast")
@dataset_required
def forecast():
    k = an.cols_by_kind(g.df)
    target = request.args.get("target") or an.main_numeric(g.df)
    date_col = request.args.get("date", k["datetime"][0] if k["datetime"] else "")
    agg = request.args.get("agg", "sum")
    try:
        periods = int(request.args.get("periods", user_row()["horizon"] or 6))
    except ValueError:
        periods = 6
    periods = min(max(periods, 1), 36)
    res, error = None, None
    try:
        res = an.forecast(g.df, target, date_col, periods, agg)
        log("forecast", f"Forecast {target} for '{g.ds['name']}'", "dataset", g.ds["id"])
    except an.DataError as e:
        error = str(e)
    return render_template("forecast.html", ds=g.ds, k=k, res=res, error=error, target=target, date_col=date_col,
                           agg=agg, periods=periods)


@bp.route("/prediction", methods=["GET", "POST"])
@dataset_required
def prediction():
    k = an.cols_by_kind(g.df)
    target = request.values.get("target") or an.main_numeric(g.df) or (k["categorical"][0] if k["categorical"] else None)
    mtime = int(os.path.getmtime(upload_path(g.ds["stored"])))
    bundle, error, result = None, None, None
    try:
        bundle = an.build_model(g.df, target, key=(g.ds["id"], target, mtime))
        log("prediction", f"Random Forest predicting '{target}' on '{g.ds['name']}'", "dataset", g.ds["id"])
        if request.method == "POST" and request.form.get("predict"):
            inputs = {f: request.form.get(f"f_{f}") for f in bundle["top_features"] if request.form.get(f"f_{f}") not in (None, "")}
            result = an.predict_one(bundle, inputs)
    except an.DataError as e:
        error = str(e)
    return render_template("prediction.html", ds=g.ds, k=k, cols=[c for c in g.df.columns if an.kind_of(g.df[c]) in ("numeric", "categorical")],
                           b=bundle, error=error, target=target, result=result, form=request.form)


@bp.route("/ask", methods=["GET", "POST"])
@dataset_required
def ask():
    q, res, error = "", None, None
    if request.method == "POST":
        q = request.form.get("question", "")
        try:
            res = an.ask(g.df, q)
            log("ask", q[:120], "dataset", g.ds["id"])
        except an.DataError as e:
            error = str(e)
        except Exception:
            error = "Sorry, I couldn't answer that question with this dataset."
    nums = an.cols_by_kind(g.df)
    examples = ["How many rows?", "How many columns?", "Are there any missing values?"]
    if nums["numeric"]:
        n = an.main_numeric(g.df)
        examples += [f"What is the average {n}?", f"What is the maximum {n}?", f"Show top 5 {n}"]
        if nums["categorical"]:
            examples += [f"What is the total {n} by {nums['categorical'][0]}?", f"What is the most common {nums['categorical'][0]}?"]
        if len(nums["numeric"]) >= 2:
            examples.append("Which columns are most correlated?")
    return render_template("ask.html", ds=g.ds, q=q, res=res, error=error, examples=examples)


# ------------------------------------------------------------------ documents
@bp.route("/documents", methods=["GET", "POST"])
@login_required
def documents():
    db = get_db()
    if request.method == "POST":
        f = request.files.get("file")
        name = secure_filename(f.filename) if f and f.filename else ""
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if not name:
            flash("Please choose a PDF, DOCX or TXT file.", "danger")
        elif ext not in DOC_EXT:
            flash("Unsupported file type. Please upload PDF, DOCX or TXT.", "danger")
        else:
            tmp = upload_path(f"tmp_{uuid.uuid4().hex}.{ext}")
            f.save(tmp)
            try:
                text, pages = dc.extract_text(tmp, ext)
                cur = db.execute("INSERT INTO documents (user_id,name,ext,text,pages) VALUES (?,?,?,?,?)", (uid(), name, ext, text, pages))
                db.commit()
                log("document", f"Analysed document '{name}'", "document", cur.lastrowid)
                flash(f"'{name}' processed.", "success")
                return redirect(url_for("main.document_view", doc_id=cur.lastrowid))
            except dc.DocError as e:
                flash(str(e), "danger")
            finally:
                if os.path.exists(tmp):
                    os.remove(tmp)
    q = request.args.get("q", "").strip()
    rows = db.execute("SELECT id,name,ext,text,pages,created_at FROM documents WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()
    docs = []
    for r in rows:
        cnt, snips = dc.search(r["text"], q, limit=3) if q else (0, [])
        if q and not cnt:
            continue
        docs.append(dict(id=r["id"], name=r["name"], ext=r["ext"], words=len(r["text"].split()), pages=r["pages"],
                         created=r["created_at"], hits=cnt, snips=snips))
    return render_template("documents.html", docs=docs, q=q)


@bp.route("/documents/demo", methods=["POST"])
@login_required
def document_demo():
    path = os.path.join(current_app.config["SAMPLE_DIR"], "sample_document.txt")
    try:
        text, pages = dc.extract_text(path, "txt")
    except (dc.DocError, FileNotFoundError):
        flash("Sample document is unavailable.", "danger")
        return redirect(url_for("main.documents"))
    db = get_db()
    cur = db.execute("INSERT INTO documents (user_id,name,ext,text,pages) VALUES (?,?,?,?,?)",
                     (uid(), "quarterly_business_review.txt", "txt", text, pages))
    db.commit()
    log("document", "Analysed document 'quarterly_business_review.txt'", "document", cur.lastrowid)
    return redirect(url_for("main.document_view", doc_id=cur.lastrowid))


@bp.route("/documents/<int:doc_id>")
@login_required
def document_view(doc_id):
    d = get_db().execute("SELECT * FROM documents WHERE id=? AND user_id=?", (doc_id, uid())).fetchone()
    if not d:
        flash("Document not found.", "danger")
        return redirect(url_for("main.documents"))
    q = request.args.get("q", "").strip()
    st = dc.stats(d["text"], d["pages"])
    kw = st["keywords"][:12][::-1]
    fig = dict(data=[dict(type="bar", orientation="h", x=[v for _, v in kw], y=[k for k, _ in kw], marker=dict(color="#2563eb"))],
               layout=an.base_layout("Top keywords", margin=dict(l=100, r=20, t=50, b=40)))
    count, snips = dc.search(d["text"], q)
    return render_template("document_view.html", d=d, st=st, fig=fig, q=q, count=count, snips=snips, preview=d["text"][:3000])


@bp.route("/documents/<int:doc_id>/delete", methods=["POST"])
@login_required
def document_delete(doc_id):
    db = get_db()
    db.execute("DELETE FROM documents WHERE id=? AND user_id=?", (doc_id, uid()))
    db.commit()
    flash("Document deleted.", "info")
    return redirect(url_for("main.documents"))


# ------------------------------------------------------------------ reports
def build_report(ds, df):
    r = dict(ds=ds, p=an.profile(df), ins=an.insights(df), anomaly=None, fc=None, model=None)
    try:
        a = an.detect_anomalies(df, 0.05)
        r["anomaly"] = dict(count=a["count"], pct=a["pct"], cols=a["cols"], rows=a["rows"][:5])
    except an.DataError:
        pass
    k = an.cols_by_kind(df)
    tgt = an.main_numeric(df)
    if tgt:
        try:
            f = an.forecast(df, tgt, k["datetime"][0] if k["datetime"] else None, 6)
            r["fc"] = dict(target=tgt, **{x: f[x] for x in ("r2", "direction", "change", "flabel", "table", "dates_used")})
        except an.DataError:
            pass
        try:
            b = an.build_model(df, tgt, key=(ds["id"], tgt, int(os.path.getmtime(upload_path(ds["stored"])))))
            r["model"] = dict(target=tgt, task=b["task"], metrics=b["metrics"], top=[(n, round(v * 100, 1)) for n, v in b["importance"][:5]])
        except an.DataError:
            pass
    return r


@bp.route("/reports")
@login_required
def reports():
    rows = get_db().execute("SELECT * FROM datasets WHERE user_id=? ORDER BY id DESC", (uid(),)).fetchall()
    return render_template("reports.html", datasets=rows)


def _report(ds_id):
    ds = get_dataset(ds_id)
    if not ds:
        return None, None
    try:
        return ds, build_report(ds, an.load_df(upload_path(ds["stored"])))
    except (an.DataError, FileNotFoundError):
        return ds, None


@bp.route("/report/<int:ds_id>")
@login_required
def report_view(ds_id):
    ds, r = _report(ds_id)
    if not ds or not r:
        flash("Could not build a report for that dataset.", "danger")
        return redirect(url_for("main.reports"))
    log("report", f"Generated report for '{ds['name']}'", "dataset", ds_id)
    return render_template("report.html", r=r, standalone=False)


@bp.route("/report/<int:ds_id>/download")
@login_required
def report_download(ds_id):
    ds, r = _report(ds_id)
    if not ds or not r:
        flash("Could not build a report for that dataset.", "danger")
        return redirect(url_for("main.reports"))
    log("report", f"Downloaded report for '{ds['name']}'", "dataset", ds_id)
    html = render_template("report_standalone.html", r=r, now=datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
    fname = secure_filename(f"insightiq_report_{ds['name']}") + ".html"
    return Response(html, mimetype="text/html", headers={"Content-Disposition": f"attachment; filename={fname}"})


# ------------------------------------------------------------------ history & settings
@bp.route("/history")
@login_required
def history():
    rows = get_db().execute("SELECT * FROM history WHERE user_id=? ORDER BY id DESC LIMIT 200", (uid(),)).fetchall()
    return render_template("history.html", rows=rows)


@bp.route("/history/clear", methods=["POST"])
@login_required
def history_clear():
    db = get_db()
    db.execute("DELETE FROM history WHERE user_id=?", (uid(),))
    db.commit()
    flash("Analysis history cleared.", "info")
    return redirect(url_for("main.history"))


@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    db = get_db()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "profile":
            name = request.form.get("name", "").strip()
            try:
                cont = min(max(float(request.form.get("contamination", 0.05)), 0.01), 0.25)
                hor = min(max(int(request.form.get("horizon", 6)), 1), 36)
            except ValueError:
                flash("Please enter valid numbers.", "danger")
                return redirect(url_for("main.settings"))
            if not name:
                flash("Name cannot be empty.", "danger")
            else:
                db.execute("UPDATE users SET name=?, contamination=?, horizon=? WHERE id=?", (name, cont, hor, uid()))
                db.commit()
                session["user_name"] = name
                flash("Settings saved.", "success")
        elif action == "password":
            u = user_row()
            new = request.form.get("new", "")
            if not check_password_hash(u["password_hash"], request.form.get("current", "")):
                flash("Current password is incorrect.", "danger")
            elif len(new) < 6:
                flash("New password must be at least 6 characters.", "danger")
            else:
                db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new), uid()))
                db.commit()
                flash("Password updated.", "success")
        elif action == "wipe":
            for d in db.execute("SELECT stored FROM datasets WHERE user_id=?", (uid(),)).fetchall():
                try:
                    os.remove(upload_path(d["stored"]))
                except OSError:
                    pass
            for t in ("datasets", "documents", "history"):
                db.execute(f"DELETE FROM {t} WHERE user_id=?", (uid(),))
            db.commit()
            session.pop("ds", None)
            flash("All your datasets, documents and history were deleted.", "info")
        return redirect(url_for("main.settings"))
    return render_template("settings.html", u=user_row())
