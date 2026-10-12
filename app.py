from datetime import date, datetime, timedelta
import altair as alt
import base64
import html
import json
import posixpath
import requests
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# -----------------------------------------------------------------------------
# Google 連携・GAS 中継 API / スプレッドシート関数
# -----------------------------------------------------------------------------
def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def upload_file_to_drive(uploaded_file, target_folder_id: str) -> dict:
    """Google Apps Script (GAS) 経由で個人の Google ドライブへ保存"""
    gas_url = st.secrets["connections"]["gsheets"].get("gas_upload_url", "")
    if not gas_url:
        raise ValueError("Secrets に gas_upload_url が設定されていません。")

    raw_folder_id = target_folder_id.strip().strip('"').strip("'")
    if "/folders/" in raw_folder_id:
        raw_folder_id = raw_folder_id.split("/folders/")[-1].split("?")[0].split("/")[0]

    file_bytes = uploaded_file.getvalue()
    b64_str = base64.b64encode(file_bytes).decode("utf-8")

    payload = {
        "action": "upload",
        "folderId": raw_folder_id,
        "fileName": uploaded_file.name,
        "mimeType": uploaded_file.type or "application/octet-stream",
        "base64Data": b64_str
    }

    resp = requests.post(gas_url, json=payload, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"GAS サーバーとの通信に失敗しました (Status: {resp.status_code})")

    res_json = resp.json()
    if res_json.get("status") != "success":
        raise RuntimeError(f"ドライブ保存エラー: {res_json.get('message')}")

    return {
        "id": res_json.get("fileId"),
        "webViewLink": res_json.get("url")
    }

def delete_file_from_drive(file_id: str):
    """Google Apps Script (GAS) 経由で Google ドライブ上の実ファイルをゴミ箱へ移動"""
    if not file_id or str(file_id).lower() in ["nan", "none", ""]:
        return
    gas_url = st.secrets["connections"]["gsheets"].get("gas_upload_url", "")
    if not gas_url:
        return

    payload = {
        "action": "delete",
        "fileId": str(file_id).strip()
    }
    try:
        requests.post(gas_url, json=payload, timeout=30)
    except Exception as e:
        st.warning(f"Google ドライブ上の旧ファイル削除時に警告が発生しました: {e}")

# -----------------------------------------------------------------------------
# 添付ファイルデータ構造化ヘルパー
# -----------------------------------------------------------------------------
def parse_attached_files(raw_file_id: str, raw_file_name: str) -> list:
    if not raw_file_id or str(raw_file_id).lower() in ["nan", "none", ""]:
        return []
    val = str(raw_file_id).strip()
    if val.startswith("[") and val.endswith("]"):
        try:
            return json.loads(val)
        except Exception:
            pass
    name = str(raw_file_name).strip() if (raw_file_name and str(raw_file_name).lower() not in ["nan", "none"]) else "添付資料"
    return [{"id": val, "name": name}]

def dump_attached_files(files_list: list) -> str:
    if not files_list:
        return ""
    return json.dumps(files_list, ensure_ascii=False)

# -----------------------------------------------------------------------------
# データ取得・保存関数（キャッシュ制御）
# -----------------------------------------------------------------------------
@st.cache_data(ttl=60)
def get_problems_df() -> pd.DataFrame:
    conn = get_connection()
    df = conn.read(worksheet="problems")
    if df is None or df.empty:
        return pd.DataFrame(columns=["problem_id", "subject", "unit", "title", "folder_path", "file_id", "file_name"])
    df = df.dropna(how="all")
    for col in ["problem_id", "subject", "unit", "title"]:
        if col not in df.columns:
            df[col] = ""

    if "folder_path" not in df.columns:
        if "group_name" in df.columns:
            df["folder_path"] = "/" + df["group_name"].replace("デフォルト", "").str.strip()
        else:
            df["folder_path"] = "/"

    df["folder_path"] = df["folder_path"].fillna("/").replace("", "/")
    df["folder_path"] = df["folder_path"].apply(
        lambda p: "/" + p.strip("/") if p.strip("/") else "/"
    )

    for col in ["file_id", "file_name"]:
        if col not in df.columns:
            df[col] = ""
        else:
            df[col] = df[col].fillna("").astype(str)

    df = df.astype(str)
    df = df[df["problem_id"].str.strip() != ""]
    return df

@st.cache_data(ttl=60)
def get_attempts_df() -> pd.DataFrame:
    conn = get_connection()
    df = conn.read(worksheet="attempts")
    if df is None or df.empty:
        return pd.DataFrame(columns=["attempt_id", "problem_id", "attempt_date", "is_correct", "memo"])
    df = df.dropna(how="all")
    for col in ["attempt_id", "problem_id", "attempt_date", "is_correct", "memo"]:
        if col not in df.columns:
            df[col] = ""
    df = df[df["attempt_id"].astype(str).str.strip() != ""]
    return df

@st.cache_data(ttl=60)
def get_todos_df() -> pd.DataFrame:
    try:
        conn = get_connection()
        df = conn.read(worksheet="todos")
        if df is None or df.empty:
            return pd.DataFrame(columns=["todo_id", "problem_id", "subject", "unit", "task_desc", "due_date", "status", "created_at"])
        df = df.dropna(how="all")
        for col in ["todo_id", "problem_id", "subject", "unit", "task_desc", "due_date", "status", "created_at"]:
            if col not in df.columns:
                df[col] = ""
        df = df[df["todo_id"].astype(str).str.strip() != ""]
        return df
    except Exception:
        return pd.DataFrame(columns=["todo_id", "problem_id", "subject", "unit", "task_desc", "due_date", "status", "created_at"])

@st.cache_data(ttl=60)
def get_books_df() -> pd.DataFrame:
    try:
        conn = get_connection()
        df = conn.read(worksheet="books")
        if df is None or df.empty:
            return pd.DataFrame(columns=["book_id", "title", "subject", "total_pages", "current_pages", "structure_json", "created_at"])
        df = df.dropna(how="all")
        for col in ["book_id", "title", "subject", "total_pages", "current_pages", "structure_json", "created_at"]:
            if col not in df.columns:
                df[col] = ""
        df = df[df["book_id"].astype(str).str.strip() != ""]
        return df
    except Exception:
        return pd.DataFrame(columns=["book_id", "title", "subject", "total_pages", "current_pages", "structure_json", "created_at"])

@st.cache_data(ttl=60)
def get_book_logs_df() -> pd.DataFrame:
    try:
        conn = get_connection()
        df = conn.read(worksheet="book_logs")
        if df is None or df.empty:
            return pd.DataFrame(columns=["log_id", "book_id", "log_date", "chapter", "unit", "pages_read", "cumulative_page", "memo"])
        df = df.dropna(how="all")
        for col in ["log_id", "book_id", "log_date", "chapter", "unit", "pages_read", "cumulative_page", "memo"]:
            if col not in df.columns:
                df[col] = ""
        df = df[df["log_id"].astype(str).str.strip() != ""]
        return df
    except Exception:
        return pd.DataFrame(columns=["log_id", "book_id", "log_date", "chapter", "unit", "pages_read", "cumulative_page", "memo"])

def save_problems_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="problems", data=df)
    st.cache_data.clear()

def save_attempts_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="attempts", data=df)
    st.cache_data.clear()

def save_todos_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="todos", data=df)
    st.cache_data.clear()

def save_books_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="books", data=df)
    st.cache_data.clear()

def save_book_logs_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="book_logs", data=df)
    st.cache_data.clear()

def fetch_aggregated_data(problems_df: pd.DataFrame, attempts_df: pd.DataFrame) -> pd.DataFrame:
    if problems_df.empty:
        return pd.DataFrame()

    if attempts_df.empty:
        df = problems_df.copy()
        df["total_attempts"] = 0
        df["correct_count"] = 0
        df["last_date"] = None
    else:
        attempts_clean = attempts_df.dropna(subset=["problem_id"]).copy()
        attempts_clean["is_correct"] = pd.to_numeric(attempts_clean["is_correct"], errors="coerce").fillna(0).astype(int)

        agg = attempts_clean.groupby("problem_id").agg(
            total_attempts=("attempt_id", "count"),
            correct_count=("is_correct", lambda x: (x == 1).sum()),
            last_date=("attempt_date", "max")
        ).reset_index()

        df = pd.merge(problems_df, agg, on="problem_id", how="left")
        df["total_attempts"] = df["total_attempts"].fillna(0).astype(int)
        df["correct_count"] = df["correct_count"].fillna(0).astype(int)

    today = date.today()
    df["accuracy"] = df.apply(
        lambda row: round((row["correct_count"] / row["total_attempts"]) * 100, 1)
        if row["total_attempts"] > 0 else None,
        axis=1
    )

    def calc_elapsed(d_str):
        if pd.isna(d_str) or not d_str:
            return None
        try:
            if isinstance(d_str, (datetime, pd.Timestamp)):
                last_d = d_str.date()
            else:
                last_d = datetime.strptime(str(d_str)[:10], "%Y-%m-%d").date()
            return (today - last_d).days
        except Exception:
            return None

    df["elapsed_days"] = df["last_date"].apply(calc_elapsed)
    return df

# -----------------------------------------------------------------------------
# スタイルシート設定（Mobile-Optimized UI）
# -----------------------------------------------------------------------------
st.set_page_config(page_title="演習ダッシュボード", layout="centered")

st.markdown("""
<style>
    .stApp {
        background-color: #F8F9FA;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "Hiragino Sans", "Yu Gothic", sans-serif;
        color: #1A1A1A;
        -webkit-text-size-adjust: 100%;
    }
    header[data-testid="stHeader"] {
        background: transparent !important;
    }
    .block-container {
        padding-top: 4.5rem !important;
        padding-bottom: 5rem !important;
        padding-left: 14px !important;
        padding-right: 14px !important;
        max-width: 820px !important;
        width: 100% !important;
    }
    .nintendo-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 16px;
        padding-bottom: 12px;
        border-bottom: 2px solid #EBEBEB;
    }
    .nintendo-badge {
        background-color: #E60012;
        color: #FFFFFF;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.5px;
        padding: 4px 10px;
        border-radius: 6px;
        text-transform: uppercase;
    }
    .nintendo-title {
        font-size: 22px;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #1A1A1A;
    }

    div.folder-btn > button {
        background: #FFFFFF !important;
        color: #1F2937 !important;
        border: 1.5px solid #E5E7EB !important;
        border-radius: 14px !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02) !important;
        font-weight: 800 !important;
        font-size: 15px !important;
        min-height: 48px !important;
        text-align: left !important;
        display: flex !important;
        justify-content: flex-start !important;
        align-items: center !important;
        transition: all 0.2s ease !important;
    }
    div.folder-btn > button:hover {
        border-color: #E60012 !important;
        background: #FFF5F5 !important;
        color: #E60012 !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent;
        border-bottom: 2px solid #E5E7EB;
        gap: 6px;
        padding-left: 0;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
        border: none !important;
        padding: 12px 14px !important;
        font-size: 14.5px !important;
        font-weight: 700;
        color: #71717A;
        white-space: nowrap;
        min-height: 48px;
    }
    .stTabs [aria-selected="true"] {
        color: #1A1A1A !important;
    }
    .stTabs [aria-selected="true"]::after {
        content: "";
        position: absolute;
        bottom: -2px;
        left: 0;
        right: 0;
        height: 3px;
        background-color: #E60012;
        border-radius: 3px 3px 0 0;
    }

    .summary-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 8px;
        margin-bottom: 18px;
    }
    .summary-card {
        background: #FFFFFF;
        border-radius: 14px;
        padding: 14px 6px;
        border: 1px solid #EAEAEA;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.02);
        text-align: center;
    }
    .summary-card.primary {
        background: linear-gradient(135deg, #E60012 0%, #BA000F 100%);
        color: #FFFFFF;
        border: none;
    }
    .summary-label {
        font-size: 11px;
        font-weight: 700;
        color: #8E8E93;
        margin-bottom: 4px;
    }
    .summary-card.primary .summary-label {
        color: rgba(255, 255, 255, 0.9);
    }
    .summary-value {
        font-size: 20px;
        font-weight: 800;
    }

    .cards-grid {
        display: grid;
        grid-template-columns: 1fr;
        gap: 14px;
        margin-top: 14px;
    }
    @media (min-width: 800px) {
        .cards-grid {
            grid-template-columns: repeat(2, 1fr);
        }
    }

    details.nintendo-accordion {
        background: #FFFFFF;
        border-radius: 18px;
        border: 1px solid #ECECEC;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.03);
        overflow: hidden;
        transition: border-color 0.25s ease, box-shadow 0.25s ease, transform 0.25s cubic-bezier(0.25, 1, 0.5, 1);
    }
    details.nintendo-accordion[open] {
        border-color: #E60012;
        box-shadow: 0 10px 24px -4px rgba(230, 0, 18, 0.12);
    }

    summary.nintendo-card-summary {
        list-style: none;
        cursor: pointer;
        padding: 20px 20px 14px 20px;
        outline: none;
        user-select: none;
    }
    summary.nintendo-card-summary::-webkit-details-marker {
        display: none;
    }

    .card-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 8px;
    }
    .tag-subject {
        background-color: #F1F2F5;
        color: #27272A;
        font-size: 13px;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 8px;
    }
    .tag-file-badge {
        background-color: #EFF6FF;
        color: #2563EB;
        font-size: 11px;
        font-weight: 700;
        padding: 3px 8px;
        border-radius: 6px;
        border: 1px solid #DBEAFE;
    }
    .tag-unit {
        font-size: 13px;
        font-weight: 600;
        color: #71717A;
    }
    .card-title {
        font-size: 20px;
        font-weight: 800;
        color: #1A1A1A;
        line-height: 1.4;
        margin-bottom: 16px;
    }

    .progress-wrapper {
        margin-bottom: 14px;
    }
    .progress-label-row {
        display: flex;
        justify-content: space-between;
        font-size: 13px;
        font-weight: 700;
        margin-bottom: 6px;
    }
    .progress-bar-bg {
        width: 100%;
        height: 10px;
        background-color: #EAEAEA;
        border-radius: 6px;
        overflow: hidden;
    }
    .progress-bar-fill {
        height: 100%;
        border-radius: 6px;
        transition: width 0.4s ease;
    }
    .fill-green { background-color: #10B981; }
    .fill-orange { background-color: #F59E0B; }
    .fill-red { background-color: #EF4444; }
    .fill-gray { background-color: #D1D5DB; }

    .card-footer {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-top: 14px;
        border-top: 1px solid #F3F4F6;
        font-size: 13px;
        font-weight: 600;
        color: #71717A;
    }
    .alert-pill {
        background-color: #FEE2E2;
        color: #DC2626;
        font-size: 12px;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 12px;
    }
    .safe-pill {
        background-color: #E0F2FE;
        color: #0284C7;
        font-size: 12px;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 12px;
    }

    .toggle-hint-bar {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        font-size: 12px;
        font-weight: 700;
        color: #A1A1AA;
        padding-top: 12px;
        margin-top: 12px;
        border-top: 1px dashed #EAEAEA;
    }
    details.nintendo-accordion[open] .toggle-hint-bar {
        color: #E60012;
    }
    .toggle-icon {
        display: inline-block;
        transition: transform 0.25s ease;
        font-size: 11px;
    }
    details.nintendo-accordion[open] .toggle-icon {
        transform: rotate(180deg);
    }

    .history-drawer {
        background: #F8F9FA;
        border-top: 1px solid #EBEBEB;
        padding: 16px 20px 20px 20px;
    }
    .file-preview-box {
        background: #FFFFFF;
        border: 1px solid #E5E7EB;
        border-radius: 12px;
        padding: 14px;
        margin-bottom: 14px;
    }
    .file-preview-header {
        font-size: 13px;
        font-weight: 800;
        color: #1F2937;
        margin-bottom: 10px;
    }
    .file-item-chip {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background-color: #2563EB;
        color: #FFFFFF !important;
        font-weight: 700;
        font-size: 12px;
        padding: 8px 12px;
        border-radius: 8px;
        text-decoration: none;
        margin: 4px 6px 4px 0;
    }
    .history-header {
        font-size: 13px;
        font-weight: 800;
        color: #52525B;
        margin-bottom: 10px;
    }
    .history-row {
        background: #FFFFFF;
        border-radius: 12px;
        padding: 12px 14px;
        margin-bottom: 8px;
        border: 1px solid #EAEAEA;
    }
    .history-row:last-child {
        margin-bottom: 0;
    }
    .history-meta-line {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .history-date {
        font-size: 13px;
        font-weight: 700;
        color: #27272A;
    }
    .badge-pass {
        background: #DCFCE7;
        color: #16A34A;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .badge-fail {
        background: #FEE2E2;
        color: #DC2626;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .history-memo-box {
        font-size: 13px;
        color: #4B5563;
        background: #F3F4F6;
        padding: 8px 10px;
        border-radius: 8px;
        margin-top: 8px;
        line-height: 1.5;
        word-break: break-all;
    }

    .todo-card {
        background: #FFFFFF;
        border-radius: 16px;
        border: 1px solid #ECECEC;
        padding: 18px;
        margin-bottom: 12px;
        box-shadow: 0 2px 6px rgba(0,0,0,0.02);
    }
    .todo-card.done {
        background: #FAFAFA;
        border-color: #E5E7EB;
        opacity: 0.75;
    }
    .todo-card-top {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }
    .todo-scope-pill {
        background: #F1F2F5;
        color: #374151;
        font-size: 12px;
        font-weight: 700;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .badge-due-danger {
        background: #FEE2E2;
        color: #DC2626;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .badge-due-warning {
        background: #FEF3C7;
        color: #D97706;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .badge-due-safe {
        background: #EFF6FF;
        color: #2563EB;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .badge-due-done {
        background: #E5E7EB;
        color: #6B7280;
        font-size: 12px;
        font-weight: 800;
        padding: 3px 10px;
        border-radius: 8px;
    }
    .todo-desc-text {
        font-size: 16px;
        font-weight: 800;
        color: #1A1A1A;
        line-height: 1.5;
        margin-bottom: 12px;
    }
    .todo-desc-text.done {
        text-decoration: line-through;
        color: #9CA3AF;
    }

    .stButton > button {
        background-color: #E60012;
        color: #FFFFFF;
        border: none;
        border-radius: 14px;
        font-weight: 700;
        font-size: 16px !important;
        min-height: 52px !important;
        padding: 12px 24px;
        width: 100%;
        box-shadow: 0 4px 14px rgba(230, 0, 18, 0.25);
    }
    div[data-baseweb="select"] > div, input, textarea {
        min-height: 50px !important;
        font-size: 16px !important;
        border-radius: 12px !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# ヘッダー
# -----------------------------------------------------------------------------
st.markdown("""
<div class="nintendo-header">
    <div class="nintendo-badge">Denki Studio</div>
    <div class="nintendo-title">演習ダッシュボード</div>
</div>
""", unsafe_allow_html=True)

if "current_folder" not in st.session_state:
    st.session_state.current_folder = "/"
if "created_folders" not in st.session_state:
    st.session_state.created_folders = set()

# -----------------------------------------------------------------------------
# データ取得部
# -----------------------------------------------------------------------------
try:
    problems_df = get_problems_df()
    attempts_df = get_attempts_df()
    todos_df = get_todos_df()
    books_df = get_books_df()
    book_logs_df = get_book_logs_df()
    load_success = True
except Exception as e:
    load_success = False
    st.error(f"データ取得エラー: {e}")
    if st.button("🔄 再読み込み"):
        st.rerun()

if load_success:
    tab_catalog, tab_books, tab_todo, tab_entry, tab_manage = st.tabs([
        "📁 エクスプローラー",
        "📖 参考書進捗",
        "✅ ToDoタスク",
        "✏️ 演習記録",
        "⚙️ マスタ管理"
    ])

    # -----------------------------------------------------------------------------
    # タブ 1: エクスプローラー
    # -----------------------------------------------------------------------------
    with tab_catalog:
        data = fetch_aggregated_data(problems_df, attempts_df)

        if data.empty:
            st.info("登録されている問題がありません。「マスタ管理」タブから新しい問題を追加してください。")
        else:
            total_p = len(data)
            solved_p = len(data[data["total_attempts"] > 0])
            avg_acc = data["accuracy"].dropna().mean()
            avg_str = f"{avg_acc:.1f}%" if pd.notna(avg_acc) else "-"

            summary_html = f"""
            <div class="summary-grid">
                <div class="summary-card primary">
                    <div class="summary-label">総問題数</div>
                    <div class="summary-value">{total_p} <span style="font-size:13px;">問</span></div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">着手済み</div>
                    <div class="summary-value">{solved_p} <span style="font-size:13px;">問</span></div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">平均正答率</div>
                    <div class="summary-value">{avg_str}</div>
                </div>
            </div>
            """
            st.markdown("\n".join(line.strip() for line in summary_html.splitlines()), unsafe_allow_html=True)

            curr = st.session_state.current_folder
            parts = [p for p in curr.strip("/").split("/") if p]

            b_cols = st.columns(len(parts) + 2)
            with b_cols[0]:
                if st.button("🏠 ホーム", key="bc_root", use_container_width=True):
                    st.session_state.current_folder = "/"
                    st.rerun()

            acc_path = ""
            for idx, part in enumerate(parts):
                acc_path += "/" + part
                with b_cols[idx + 1]:
                    if st.button(f"📁 {part}", key=f"bc_{idx}_{part}", use_container_width=True):
                        st.session_state.current_folder = acc_path
                        st.rerun()

            st.caption(f"現在のディレクトリ: `{st.session_state.current_folder}`")

            all_known_paths = sorted(list(set(data["folder_path"].unique()).union(st.session_state.created_folders)))
            current_problems = data[data["folder_path"] == curr].copy()

            # 上部ツールバー
            with st.expander("🛠️ フォルダ操作・問題の移動（上部ツールバー）", expanded=False):
                tb_action = st.radio("操作を選択", ["📂 問題を別のフォルダへ移動", "➕ 新しいフォルダを作成"], horizontal=True)

                if tb_action == "📂 問題を別のフォルダへ移動":
                    p_scope = st.radio("移動対象の絞り込み", ["現在のフォルダ内の問題", "全フォルダの問題から選択"], horizontal=True)
                    candidate_df = current_problems if p_scope == "現在のフォルダ内の問題" else data

                    if candidate_df.empty:
                        st.caption("移動対象となる問題が存在しません。")
                    else:
                        p_move_options = {
                            f"[{row['problem_id']}] {row['title']} (現在: {row.get('folder_path', '/')})": row['problem_id']
                            for _, row in candidate_df.iterrows()
                        }
                        sel_mv_label = st.selectbox("移動させる問題を選択", list(p_move_options.keys()))
                        sel_mv_id = p_move_options[sel_mv_label]

                        col_dest1, col_dest2 = st.columns(2)
                        with col_dest1:
                            mv_dest_mode = st.radio("移動先の指定", ["既存フォルダから選択", "新規パス入力"], horizontal=True)
                        with col_dest2:
                            if mv_dest_mode == "既存フォルダから選択":
                                dest_folder = st.selectbox("移動先フォルダ", all_known_paths)
                            else:
                                dest_folder = st.text_input("新規フォルダパス（例: /電磁気学/ガウスの法則）", value="/")

                        st.write("")
                        if st.button("🚀 この問題を移動する", key="btn_move_upper"):
                            clean_dest = "/" + dest_folder.strip("/") if dest_folder.strip("/") else "/"
                            try:
                                problems_df.loc[problems_df["problem_id"] == sel_mv_id, "folder_path"] = clean_dest
                                save_problems_df(problems_df)
                                st.success(f"問題 [{sel_mv_id}] を `{clean_dest}` へ移動しました。")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"移動エラー: {ex}")

                elif tb_action == "➕ 新しいフォルダを作成":
                    new_folder_name = st.text_input("新規フォルダ名（例: ビオ・サバールの法則）")
                    if st.button("この階層に作成", key="btn_create_folder_upper"):
                        if new_folder_name.strip():
                            target_dir = posixpath.join(st.session_state.current_folder, new_folder_name.strip())
                            st.session_state.created_folders.add(target_dir)
                            st.success(f"フォルダ「{new_folder_name.strip()}」を作成しました。")
                            st.rerun()

            st.write("")

            sub_folders = set()
            for p in all_known_paths:
                p_clean = "/" + p.strip("/") if p.strip("/") else "/"
                if p_clean != curr and p_clean.startswith(curr if curr == "/" else curr + "/"):
                    rel = p_clean[len(curr):].strip("/")
                    direct_child = rel.split("/")[0]
                    sub_folders.add(direct_child)
            sub_folders = sorted(list(sub_folders))

            if sub_folders:
                st.write("**📁 フォルダ**")
                f_cols = st.columns(2)
                for f_idx, s_folder in enumerate(sub_folders):
                    next_path = posixpath.join(curr, s_folder)
                    count_in_sub = len(data[data["folder_path"].str.startswith(next_path)])
                    with f_cols[f_idx % 2]:
                        st.markdown('<div class="folder-btn">', unsafe_allow_html=True)
                        if st.button(f"📁 {s_folder} ({count_in_sub}問)", key=f"folder_goto_{s_folder}", use_container_width=True):
                            st.session_state.current_folder = next_path
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                st.write("")

            if current_problems.empty and not sub_folders:
                st.info("このフォルダには問題がありません。")
            elif not current_problems.empty:
                st.write(f"**📄 問題一覧（{len(current_problems)}問）**")

                cards_html = '<div class="cards-grid">\n'
                for _, r in current_problems.iterrows():
                    p_id_raw = str(r["problem_id"])
                    title_s = html.escape(str(r["title"]))
                    subject_s = html.escape(str(r["subject"]))
                    unit_s = html.escape(str(r["unit"]))
                    p_id_s = html.escape(p_id_raw)

                    files_list = parse_attached_files(r.get("file_id", ""), r.get("file_name", ""))
                    file_badge = f'<span class="tag-file-badge">📎 資料 ({len(files_list)}件)</span>' if files_list else ""

                    if pd.isna(r["accuracy"]):
                        acc_text = "未実施"
                        bar_width = 0
                        fill_color = "fill-gray"
                    else:
                        acc_val = int(r["accuracy"])
                        acc_text = f"{acc_val}%"
                        bar_width = acc_val
                        fill_color = "fill-green" if acc_val >= 80 else ("fill-orange" if acc_val >= 50 else "fill-red")

                    if pd.isna(r["elapsed_days"]):
                        status_badge = '<span class="alert-pill">未着手</span>'
                        elapsed_text = "-"
                    elif r["elapsed_days"] == 0:
                        status_badge = '<span class="safe-pill">本日実施</span>'
                        elapsed_text = "今日"
                    elif r["elapsed_days"] >= 7:
                        status_badge = '<span class="alert-pill">要復習</span>'
                        elapsed_text = f"{int(r['elapsed_days'])}日前"
                    else:
                        status_badge = '<span class="safe-pill">定着中</span>'
                        elapsed_text = f"{int(r['elapsed_days'])}日前"

                    file_block_html = ""
                    if files_list:
                        chips_html = ""
                        images_html = ""
                        for f_item in files_list:
                            f_id = f_item.get("id", "")
                            f_name = f_item.get("name", "添付ファイル")
                            is_pdf = f_name.lower().endswith(".pdf")
                            drive_view_url = f"https://drive.google.com/file/d/{f_id}/view"

                            if is_pdf:
                                chips_html += f'<a href="{drive_view_url}" target="_blank" class="file-item-chip">📄 {html.escape(f_name)}</a>'
                            else:
                                drive_thumb_url = f"https://lh3.googleusercontent.com/d/{f_id}"
                                chips_html += f'<a href="{drive_view_url}" target="_blank" class="file-item-chip">🖼️ {html.escape(f_name)}</a>'
                                images_html += f"""
                                <div style="display:inline-block; margin:4px; text-align:center;">
                                    <img src="{drive_thumb_url}" style="max-height:140px; max-width:200px; border-radius:6px; border:1px solid #E5E7EB;" loading="lazy" />
                                </div>
                                """

                        file_block_html = f"""
                        <div class="file-preview-box">
                            <div class="file-preview-header">📎 添付資料（{len(files_list)}件）</div>
                            <div style="margin-bottom:8px;">{chips_html}</div>
                            {"<div style='margin-top:6px; overflow-x:auto; white-space:nowrap;'>" + images_html + "</div>" if images_html else ""}
                        </div>
                        """

                    p_att = attempts_df[attempts_df["problem_id"].astype(str) == p_id_raw].copy() if not attempts_df.empty else pd.DataFrame()
                    history_rows_html = ""
                    if p_att.empty:
                        history_rows_html = '<div style="font-size:13px; color:#A1A1AA; text-align:center; padding:10px 0;">まだ演習履歴がありません</div>'
                    else:
                        p_att = p_att.sort_values(by=["attempt_date", "attempt_id"], ascending=[False, False])
                        for _, att_row in p_att.iterrows():
                            att_date_s = html.escape(str(att_row["attempt_date"]))
                            try:
                                is_corr = int(float(att_row["is_correct"])) == 1
                            except Exception:
                                is_corr = False
                            corr_badge = '<span class="badge-pass">◯ 正解</span>' if is_corr else '<span class="badge-fail">✕ 不正解</span>'

                            memo_raw = str(att_row["memo"]).strip() if pd.notna(att_row["memo"]) else ""
                            memo_html = f'<div class="history-memo-box">📝 {html.escape(memo_raw)}</div>' if (memo_raw and memo_raw.lower() not in ["nan", "none"]) else ""

                            history_rows_html += f"""
                            <div class="history-row">
                                <div class="history-meta-line">
                                    <span class="history-date">{att_date_s}</span>
                                    {corr_badge}
                                </div>
                                {memo_html}
                            </div>
                            """

                    cards_html += f"""
<details class="nintendo-accordion">
<summary class="nintendo-card-summary">
<div>
<div class="card-top">
<span class="tag-subject">[{p_id_s}] {subject_s}</span>
<div style="display:flex; gap:6px; align-items:center;">
{file_badge}
<span class="tag-unit">{unit_s}</span>
</div>
</div>
<div class="card-title">{title_s}</div>
</div>
<div>
<div class="progress-wrapper">
<div class="progress-label-row">
<span>正答率</span>
<span>{acc_text}</span>
</div>
<div class="progress-bar-bg">
<div class="progress-bar-fill {fill_color}" style="width: {bar_width}%;"></div>
</div>
</div>
<div class="card-footer">
<span>最終: {elapsed_text} ({r['total_attempts']}回)</span>
{status_badge}
</div>
<div class="toggle-hint-bar">
<span>タップしてファイル・演習履歴を見る</span>
<span class="toggle-icon">▼</span>
</div>
</div>
</summary>
<div class="history-drawer">
{file_block_html}
<div class="history-header">📖 過去の演習履歴（{r['total_attempts']}件）</div>
{history_rows_html}
</div>
</details>
"""
                cards_html += '\n</div>'
                clean_cards_html = "\n".join(line.strip() for line in cards_html.splitlines())
                st.markdown(clean_cards_html, unsafe_allow_html=True)

    # -----------------------------------------------------------------------------
    # タブ 2: 参考書進捗管理
    # -----------------------------------------------------------------------------
    with tab_books:
        st.subheader("参考書・テキスト進行度管理")

        if books_df.empty:
            st.info("登録されている参考書がありません。下の「➕ 参考書を新規登録する」から登録してください。")
        else:
            book_options = {
                f"[{r['book_id']}] {r['title']} ({r['subject']})": r['book_id']
                for _, r in books_df.iterrows()
            }
            selected_book_label = st.selectbox("管理する参考書を選択", list(book_options.keys()))
            selected_book_id = book_options[selected_book_label]
            target_book = books_df[books_df["book_id"] == selected_book_id].iloc[0]

            total_pg = int(pd.to_numeric(target_book.get("total_pages", 0), errors="coerce") or 1)
            curr_pg = int(pd.to_numeric(target_book.get("current_pages", 0), errors="coerce") or 0)
            curr_pg = min(curr_pg, total_pg)
            remain_pg = max(total_pg - curr_pg, 0)
            rate = round((curr_pg / total_pg) * 100, 1)

            b_summary_html = f"""
            <div class="summary-grid">
                <div class="summary-card primary">
                    <div class="summary-label">現在の進行度</div>
                    <div class="summary-value">{rate}%</div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">消化ページ</div>
                    <div class="summary-value">{curr_pg} / {total_pg} <span style="font-size:12px;">p</span></div>
                </div>
                <div class="summary-card">
                    <div class="summary-label">残りページ</div>
                    <div class="summary-value">{remain_pg} <span style="font-size:12px;">p</span></div>
                </div>
            </div>
            """
            st.markdown("\n".join(line.strip() for line in b_summary_html.splitlines()), unsafe_allow_html=True)

            st.write(f"**全体進捗（{curr_pg} / {total_pg} ページ完了）**")
            st.progress(rate / 100.0)

            # --- 進捗追記フォーム ---
            with st.expander("✏️ 進捗を追記・記録する", expanded=False):
                struct_raw = str(target_book.get("structure_json", "[]")).strip()
                try:
                    struct_data = json.loads(struct_raw) if struct_raw else []
                except Exception:
                    struct_data = []

                chapter_names = [ch.get("chapter_name", "") for ch in struct_data if ch.get("chapter_name")]

                c_ch, c_un = st.columns(2)
                with c_ch:
                    if chapter_names:
                        sel_chapter = st.selectbox("対象の章（任意）", ["（指定なし）"] + chapter_names)
                    else:
                        sel_chapter = st.text_input("対象の章（任意）", placeholder="例: 第1章 ガウスの法則")

                with c_un:
                    unit_candidates = []
                    if chapter_names and sel_chapter != "（指定なし）":
                        for ch in struct_data:
                            if ch.get("chapter_name") == sel_chapter:
                                unit_candidates = [u.get("unit_name", "") for u in ch.get("units", []) if u.get("unit_name")]
                    if unit_candidates:
                        sel_unit = st.selectbox("対象の単元（任意）", ["（指定なし）"] + unit_candidates)
                    else:
                        sel_unit = st.text_input("対象の単元（任意）", placeholder="例: 同軸円筒の電界")

                c_mode, c_val = st.columns([1, 1])
                with c_mode:
                    entry_mode = st.radio("入力形式", ["今日進めたページ数（＋加算）", "到達したページ数（直接指定）"], horizontal=True)
                with c_val:
                    if entry_mode == "今日進めたページ数（＋加算）":
                        pages_input = st.number_input("進めたページ数", min_value=1, max_value=total_pg, value=10, step=1)
                    else:
                        pages_input = st.number_input("現在の到達ページ", min_value=0, max_value=total_pg, value=curr_pg, step=1)

                col_log_date, col_log_memo = st.columns([1, 2])
                with col_log_date:
                    log_date_val = st.date_input("記録日", value=date.today(), key="b_log_date")
                with col_log_memo:
                    log_memo_val = st.text_input("学習メモ", placeholder="例: 章末問題5問完答、定理の導出完了")

                st.write("")
                if st.button("この進捗を保存する"):
                    if entry_mode == "今日進めたページ数（＋加算）":
                        new_curr = min(curr_pg + int(pages_input), total_pg)
                        added_pages = int(pages_input)
                    else:
                        new_curr = min(int(pages_input), total_pg)
                        added_pages = max(new_curr - curr_pg, 0)

                    b_idx = books_df[books_df["book_id"] == selected_book_id].index
                    books_df.loc[b_idx, "current_pages"] = new_curr
                    save_books_df(books_df)

                    if book_logs_df.empty or "log_id" not in book_logs_df.columns:
                        next_log_id = 1
                    else:
                        ex_ids = pd.to_numeric(book_logs_df["log_id"], errors="coerce").dropna()
                        next_log_id = int(ex_ids.max() + 1) if not ex_ids.empty else 1

                    new_log_row = pd.DataFrame([{
                        "log_id": next_log_id,
                        "book_id": selected_book_id,
                        "log_date": log_date_val.strftime("%Y-%m-%d"),
                        "chapter": sel_chapter if sel_chapter != "（指定なし）" else "",
                        "unit": sel_unit if sel_unit != "（指定なし）" else "",
                        "pages_read": added_pages,
                        "cumulative_page": new_curr,
                        "memo": log_memo_val.strip()
                    }])
                    updated_logs = pd.concat([book_logs_df, new_log_row], ignore_index=True)
                    save_book_logs_df(updated_logs)

                    st.success(f"進捗を記録しました（現在: {new_curr} / {total_pg} p）")
                    st.rerun()

            # --- 読破ページ数の推移チャート ---
            st.write("---")
            st.write("**📈 読破ページ数の推移（Cumulative progress）**")

            target_logs = book_logs_df[book_logs_df["book_id"] == selected_book_id].copy() if not book_logs_df.empty else pd.DataFrame()
            if not target_logs.empty:
                target_logs["log_date"] = pd.to_datetime(target_logs["log_date"])
                target_logs["cumulative_page"] = pd.to_numeric(target_logs["cumulative_page"], errors="coerce").fillna(0).astype(int)

                chart_df = target_logs.sort_values(by="log_date").groupby(target_logs["log_date"].dt.strftime("%Y-%m-%d"))["cumulative_page"].max().reset_index()
                chart_df.columns = ["日付", "到達ページ数"]

                y_max_limit = max(total_pg, int(chart_df["到達ページ数"].max()) + 10)

                base = alt.Chart(chart_df).encode(
                    x=alt.X("日付:T", title="日付", axis=alt.Axis(format="%Y-%m-%d", labelAngle=-30)),
                    y=alt.Y(
                        "到達ページ数:Q",
                        title="到達ページ数 (p)",
                        scale=alt.Scale(domain=[0, y_max_limit], clamp=True),
                        axis=alt.Axis(
                            minExtent=55,
                            labelPadding=8,
                            titlePadding=12,
                            gridColor="#ECECEC"
                        )
                    )
                )

                chart_lines = base.mark_line(color="#E60012", strokeWidth=3)
                chart_points = base.mark_circle(size=70, color="#E60012")
                final_chart = (chart_lines + chart_points).encode(
                    tooltip=[
                        alt.Tooltip("日付:T", title="記録日", format="%Y-%m-%d"),
                        alt.Tooltip("到達ページ数:Q", title="到達ページ (p)")
                    ]
                ).properties(height=280)

                st.altair_chart(final_chart, use_container_width=True)
            else:
                st.caption("進捗ログが蓄積されると、ここに時系列の読破推移グラフが表示されます。")

            # --- 章・単元構成の表示 ---
            struct_raw = str(target_book.get("structure_json", "[]")).strip()
            try:
                struct_data = json.loads(struct_raw) if struct_raw else []
            except Exception:
                struct_data = []

            if struct_data:
                st.write("---")
                st.write("**📑 章・単元ごとの構成と目安**")
                for ch_item in struct_data:
                    ch_title = ch_item.get("chapter_name", "章")
                    ch_pages = ch_item.get("chapter_pages", 0)
                    ch_info = f"（総 {ch_pages}p）" if ch_pages > 0 else ""
                    st.write(f"📁 **{ch_title}** {ch_info}")

                    u_list = ch_item.get("units", [])
                    if u_list:
                        for u_item in u_list:
                            u_name = u_item.get("unit_name", "単元")
                            u_pages = u_item.get("unit_pages", 0)
                            u_info = f" — {u_pages}p" if u_pages > 0 else ""
                            st.caption(f" └ 📄 {u_name}{u_info}")

            # --- ★ 新設: 参考書をその場で削除するアコーディオン ---
            st.write("---")
            with st.expander("🗑️ この参考書を削除する", expanded=False):
                st.warning(f"参考書「{target_book['title']}」および紐付いている進捗ログが完全に削除されます。よろしいですか？")
                if st.button("この参考書を完全に削除する", key=f"btn_del_book_in_tab_{selected_book_id}"):
                    updated_b = books_df[books_df["book_id"] != selected_book_id]
                    save_books_df(updated_b)
                    if not book_logs_df.empty:
                        updated_bl = book_logs_df[book_logs_df["book_id"] != selected_book_id]
                        save_book_logs_df(updated_bl)
                    st.success(f"参考書「{target_book['title']}」を削除しました。")
                    st.rerun()

        # --- 参考書新規登録パネル ---
        st.write("---")
        with st.expander("➕ 参考書を新規登録する", expanded=False):
            st.subheader("新しい参考書の登録")
            new_b_id = st.text_input("参考書ID（例: BK-001）")
            new_b_title = st.text_input("参考書名（例: 詳解 電磁気学演習）")
            new_b_sub = st.text_input("科目名（例: 電磁気学）")
            new_b_total = st.number_input("参考書全体の総ページ数（必須）", min_value=1, max_value=5000, value=300, step=10)

            st.write("**章・単元構成（任意: JSON形式 または 簡易定義）**")
            st.caption("章や単元の目安ページ数を設定したい場合は記述してください（空欄でも問題ありません）。")
            default_struct_sample = json.dumps([
                {
                    "chapter_name": "第1章 静電場",
                    "chapter_pages": 50,
                    "units": [
                        {"unit_name": "クーロンの法則", "unit_pages": 20},
                        {"unit_name": "ガウスの法則", "unit_pages": 30}
                    ]
                },
                {
                    "chapter_name": "第2章 電位と導体",
                    "chapter_pages": 40,
                    "units": []
                }
            ], ensure_ascii=False, indent=2)

            struct_input = st.text_area("構成定義（JSON）", value=default_struct_sample, height=180)

            st.write("")
            if st.button("この参考書を登録する"):
                if new_b_id.strip() and new_b_title.strip() and new_b_total > 0:
                    clean_b_id = new_b_id.strip()
                    if not books_df.empty and clean_b_id in books_df["book_id"].values:
                        st.error("その参考書IDは既に登録されています。")
                    else:
                        parsed_struct = []
                        if struct_input.strip():
                            try:
                                parsed_struct = json.loads(struct_input.strip())
                            except Exception as j_err:
                                st.warning(f"JSON構文に不備があるため空構成として登録します: {j_err}")
                                parsed_struct = []

                        new_b_row = pd.DataFrame([{
                            "book_id": clean_b_id,
                            "title": new_b_title.strip(),
                            "subject": new_b_sub.strip() if new_b_sub.strip() else "一般",
                            "total_pages": int(new_b_total),
                            "current_pages": 0,
                            "structure_json": json.dumps(parsed_struct, ensure_ascii=False),
                            "created_at": date.today().strftime("%Y-%m-%d")
                        }])
                        updated_b_df = pd.concat([books_df, new_b_row], ignore_index=True)
                        save_books_df(updated_b_df)
                        st.success(f"参考書「{new_b_title.strip()}」を登録しました。")
                        st.rerun()
                else:
                    st.error("参考書ID、参考書名、総ページ数は必須です。")

    # -----------------------------------------------------------------------------
    # タブ 3: ToDoタスク
    # -----------------------------------------------------------------------------
    with tab_todo:
        st.subheader("学習 ToDo タスク管理")

        today_date = date.today()
        if not todos_df.empty:
            open_todos = todos_df[todos_df["status"] != "done"].copy()
            done_todos = todos_df[todos_df["status"] == "done"].copy()

            def is_overdue(d_str):
                try:
                    target_d = datetime.strptime(str(d_str)[:10], "%Y-%m-%d").date()
                    return (today_date - target_d).days > 0
                except Exception:
                    return False

            overdue_count = len(open_todos[open_todos["due_date"].apply(is_overdue)])
            total_open = len(open_todos)
            total_done = len(done_todos)
        else:
            total_open = 0
            overdue_count = 0
            total_done = 0

        todo_summary_html = f"""
        <div class="summary-grid">
            <div class="summary-card primary">
                <div class="summary-label">進行中タスク</div>
                <div class="summary-value">{total_open} <span style="font-size:13px;">件</span></div>
            </div>
            <div class="summary-card">
                <div class="summary-label">期限切れ警告</div>
                <div class="summary-value" style="color: {'#DC2626' if overdue_count > 0 else '#1A1A1A'};">{overdue_count} <span style="font-size:13px;">件</span></div>
            </div>
            <div class="summary-card">
                <div class="summary-label">完了済み</div>
                <div class="summary-value">{total_done} <span style="font-size:13px;">件</span></div>
            </div>
        </div>
        """
        st.markdown("\n".join(line.strip() for line in todo_summary_html.splitlines()), unsafe_allow_html=True)

        with st.expander("➕ 新しい ToDo タスクを計画する", expanded=False):
            if problems_df.empty:
                st.warning("先に問題マスタを追加してください。")
            else:
                target_scope = st.radio("タスクの対象範囲", ["特定の問題を指定", "科目・単元全体を指定"], horizontal=True)

                c_tsub, c_tunit = st.columns(2)
                with c_tsub:
                    todo_sub = st.selectbox("対象科目", problems_df["subject"].unique(), key="todo_sub_sel")
                with c_tunit:
                    todo_units = problems_df[problems_df["subject"] == todo_sub]["unit"].unique()
                    todo_unit = st.selectbox("対象単元", todo_units, key="todo_unit_sel")

                selected_p_id_for_todo = ""
                if target_scope == "特定の問題を指定":
                    cand_probs = problems_df[(problems_df["subject"] == todo_sub) & (problems_df["unit"] == todo_unit)]
                    prob_choices = {
                        f"[{row['problem_id']}] {row['title']}": row['problem_id']
                        for _, row in cand_probs.iterrows()
                    }
                    if prob_choices:
                        sel_p_label = st.selectbox("対象問題", list(prob_choices.keys()), key="todo_prob_sel")
                        selected_p_id_for_todo = prob_choices[sel_p_label]
                    else:
                        st.caption("この単元には登録された問題がありません。")

                col_tdue, _ = st.columns([1, 1])
                with col_tdue:
                    target_due = st.date_input("完了目標日（いつまでに）", value=today_date + timedelta(days=3))

                target_desc = st.text_input("達成目標・タスク内容（何を終わらせるか）", placeholder="例: ノーヒントで解答を再現できるようにする")

                st.write("")
                if st.button("この目標を ToDo に追加する"):
                    if target_desc.strip():
                        if todos_df.empty or "todo_id" not in todos_df.columns:
                            next_todo_id = 1
                        else:
                            exist_t_ids = pd.to_numeric(todos_df["todo_id"], errors="coerce").dropna()
                            next_todo_id = int(exist_t_ids.max() + 1) if not exist_t_ids.empty else 1

                        new_todo_row = pd.DataFrame([{
                            "todo_id": next_todo_id,
                            "problem_id": selected_p_id_for_todo,
                            "subject": todo_sub,
                            "unit": todo_unit,
                            "task_desc": target_desc.strip(),
                            "due_date": target_due.strftime("%Y-%m-%d"),
                            "status": "open",
                            "created_at": today_date.strftime("%Y-%m-%d")
                        }])

                        updated_todos = pd.concat([todos_df, new_todo_row], ignore_index=True)
                        save_todos_df(updated_todos)
                        st.success("新しい ToDo タスクを追加しました。")
                        st.rerun()
                    else:
                        st.warning("タスク内容を入力してください。")

        st.write("---")

        if todos_df.empty:
            st.info("現在登録されている ToDo タスクはありません。上のフォームから目標を追加してください。")
        else:
            filter_mode = st.radio("表示切り替え", ["進行中のみ", "すべて", "完了済み"], horizontal=True)

            display_todos = todos_df.copy()
            if filter_mode == "進行中のみ":
                display_todos = display_todos[display_todos["status"] != "done"]
            elif filter_mode == "完了済み":
                display_todos = display_todos[display_todos["status"] == "done"]

            display_todos = display_todos.sort_values(by=["due_date", "todo_id"], ascending=[True, True])

            if display_todos.empty:
                st.caption("該当するタスクはありません。")
            else:
                for _, t_row in display_todos.iterrows():
                    t_id_str = str(t_row["todo_id"])
                    is_done = str(t_row.get("status", "open")).lower() == "done"
                    due_str = str(t_row["due_date"])
                    desc_s = html.escape(str(t_row["task_desc"]))
                    sub_s = html.escape(str(t_row["subject"]))
                    unit_s = html.escape(str(t_row["unit"]))
                    p_id_raw = str(t_row.get("problem_id", "")).strip()

                    p_title_str = ""
                    if p_id_raw and p_id_raw.lower() not in ["nan", "none", ""]:
                        match_prob = problems_df[problems_df["problem_id"] == p_id_raw]
                        if not match_prob.empty:
                            p_title_str = f"[{p_id_raw}] " + match_prob.iloc[0]["title"]
                        else:
                            p_title_str = f"[{p_id_raw}]"

                    try:
                        due_d = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
                        diff_days = (due_d - today_date).days
                    except Exception:
                        diff_days = 99

                    if is_done:
                        due_badge = '<span class="badge-due-done">✓ 達成済み</span>'
                    elif diff_days < 0:
                        due_badge = f'<span class="badge-due-danger">⚠️ 期限切れ ({abs(diff_days)}日前)</span>'
                    elif diff_days == 0:
                        due_badge = '<span class="badge-due-warning">🔥 本日締切</span>'
                    elif diff_days == 1:
                        due_badge = '<span class="badge-due-warning">⏳ 明日締切</span>'
                    else:
                        due_badge = f'<span class="badge-due-safe">📅 残り {diff_days}日 ({due_str})</span>'

                    scope_label = f"📁 {sub_s} / {unit_s}"
                    if p_title_str:
                        scope_label += f" → 📄 {p_title_str}"

                    card_class = "todo-card done" if is_done else "todo-card"
                    desc_class = "todo-desc-text done" if is_done else "todo-desc-text"

                    st.markdown(f"""
                    <div class="{card_class}">
                        <div class="todo-card-top">
                            <span class="todo-scope-pill">{scope_label}</span>
                            {due_badge}
                        </div>
                        <div class="{desc_class}">{desc_s}</div>
                    </div>
                    """, unsafe_allow_html=True)

                    c_act1, c_act2, _ = st.columns([1.2, 1, 2])
                    t_idx = todos_df[todos_df["todo_id"].astype(str) == t_id_str].index

                    with c_act1:
                        if not is_done:
                            if st.button("✓ 完了にする", key=f"btn_done_{t_id_str}"):
                                todos_df.loc[t_idx, "status"] = "done"
                                save_todos_df(todos_df)
                                st.success("タスクを完了にしました！")
                                st.rerun()
                        else:
                            if st.button("↩️ 未完了に戻す", key=f"btn_reopen_{t_id_str}"):
                                todos_df.loc[t_idx, "status"] = "open"
                                save_todos_df(todos_df)
                                st.info("タスクを未完了に戻しました。")
                                st.rerun()
                    with c_act2:
                        if st.button("🗑️ 削除", key=f"btn_del_todo_{t_id_str}"):
                            updated_td = todos_df[todos_df["todo_id"].astype(str) != t_id_str]
                            save_todos_df(updated_td)
                            st.warning("タスクを削除しました。")
                            st.rerun()
                    st.write("")

    # -----------------------------------------------------------------------------
    # タブ 4: 演習ログ登録
    # -----------------------------------------------------------------------------
    with tab_entry:
        st.subheader("演習結果を記録する")
        if problems_df.empty:
            st.warning("先に問題マスタを追加してください。")
        else:
            c_sub, c_unit = st.columns(2)
            with c_sub:
                selected_sub = st.selectbox("科目", problems_df["subject"].unique())
            with c_unit:
                filtered_units = problems_df[problems_df["subject"] == selected_sub]["unit"].unique()
                selected_unit = st.selectbox("単元", filtered_units)

            selectable_problems = problems_df[
                (problems_df["subject"] == selected_sub) & (problems_df["unit"] == selected_unit)
            ]
            problem_options = {
                f"[{row['problem_id']}] {row['title']}": row['problem_id']
                for _, row in selectable_problems.iterrows()
            }
            selected_label = st.selectbox("問題", list(problem_options.keys()))
            selected_problem_id = problem_options[selected_label]

            col_date, col_res = st.columns(2)
            with col_date:
                attempt_date_val = st.date_input("実施日", value=date.today())
            with col_res:
                result_str = st.radio("結果判定", ["正解 (◯)", "不正解 (✕)"], horizontal=True)

            memo_val = st.text_input("演習メモ（公式・定理の条件やミスの原因）")

            st.write("")
            if st.button("この記録を保存する"):
                try:
                    is_correct_val = 1 if result_str == "正解 (◯)" else 0
                    if attempts_df.empty or "attempt_id" not in attempts_df.columns:
                        next_id = 1
                    else:
                        existing_ids = pd.to_numeric(attempts_df["attempt_id"], errors="coerce").dropna()
                        next_id = int(existing_ids.max() + 1) if not existing_ids.empty else 1

                    new_attempt = pd.DataFrame([{
                        "attempt_id": next_id,
                        "problem_id": selected_problem_id,
                        "attempt_date": attempt_date_val.strftime("%Y-%m-%d"),
                        "is_correct": is_correct_val,
                        "memo": memo_val
                    }])
                    updated_attempts = pd.concat([attempts_df, new_attempt], ignore_index=True)
                    save_attempts_df(updated_attempts)
                    st.success("演習結果を保存しました。")
                    st.rerun()
                except Exception as ex:
                    st.error(f"保存エラー: {ex}")

    # -----------------------------------------------------------------------------
    # タブ 5: マスタ管理（参考書マスタの編集・削除を追加）
    # -----------------------------------------------------------------------------
    with tab_manage:
        sub_action = st.radio(
            "操作を選択",
            [
                "新規問題の追加（複数ファイル添付対応）",
                "問題マスタ・添付ファイルの編集・削除",
                "演習履歴の編集・削除",
                "参考書マスタの編集・削除"
            ],
            horizontal=True
        )
        st.write("---")

        if sub_action == "新規問題の追加（複数ファイル添付対応）":
            st.subheader("新規問題の追加")
            existing_subjects = list(problems_df["subject"].unique()) if not problems_df.empty else []
            all_known_paths = sorted(list(set(problems_df["folder_path"].unique()).union(st.session_state.created_folders)))

            new_id = st.text_input("問題ID（例: EM-001）")
            sub_mode = st.radio("科目の指定方法", ["既存から選択", "新規入力"], horizontal=True)
            if sub_mode == "既存から選択" and existing_subjects:
                new_subject = st.selectbox("既存の科目", existing_subjects)
            else:
                new_subject = st.text_input("新規科目名")

            target_f_path = st.selectbox("配置フォルダ", all_known_paths)
            new_unit = st.text_input("単元名（例: ガウスの法則）")
            new_title = st.text_input("問題名（例: 同軸円筒導体の電界計算）")

            st.write("---")
            uploaded_files = st.file_uploader(
                "📎 PDF や画像ファイルをアップロード（複数選択可）",
                type=["jpg", "jpeg", "png", "pdf"],
                accept_multiple_files=True
            )

            st.write("")
            if st.button("問題を Google ドライブ＆スプレッドシートに登録"):
                if new_id and new_subject and new_unit and new_title:
                    clean_id = new_id.strip()
                    if not problems_df.empty and clean_id in problems_df["problem_id"].values:
                        st.error("その問題IDは既に存在しています。")
                    else:
                        target_drive_folder = st.secrets["connections"]["gsheets"].get("drive_folder_id", "")
                        attached_list = []

                        if uploaded_files and target_drive_folder:
                            with st.spinner(f"ファイルを Google ドライブへ保存中（計 {len(uploaded_files)} 件）..."):
                                for up_file in uploaded_files:
                                    try:
                                        uploaded_res = upload_file_to_drive(up_file, target_drive_folder)
                                        attached_list.append({
                                            "id": uploaded_res.get("id", ""),
                                            "name": up_file.name
                                        })
                                    except Exception as up_err:
                                        st.error(f"ファイル保存失敗 ({up_file.name}): {up_err}")

                        file_id_val = dump_attached_files(attached_list)
                        file_name_val = f"{len(attached_list)}件のファイル" if attached_list else ""

                        new_problem = pd.DataFrame([{
                            "problem_id": clean_id,
                            "subject": new_subject.strip(),
                            "folder_path": target_f_path,
                            "unit": new_unit.strip(),
                            "title": new_title.strip(),
                            "file_id": file_id_val,
                            "file_name": file_name_val
                        }])
                        updated_problems = pd.concat([problems_df, new_problem], ignore_index=True)
                        save_problems_df(updated_problems)
                        st.success(f"問題 [{clean_id}] を登録しました（添付: {len(attached_list)} 件）。")
                        st.rerun()
                else:
                    st.error("必須項目（ID、科目、単元、問題名）をすべて入力してください。")

        elif sub_action == "問題マスタ・添付ファイルの編集・削除":
            st.subheader("問題定義の修正 & 添付ファイルの追加・個別削除")
            if problems_df.empty:
                st.info("登録済みの問題がありません。")
            else:
                p_choices = {
                    f"[{row['problem_id']}] {row['subject']} - {row['title']}": str(row['problem_id'])
                    for _, row in problems_df.iterrows()
                }
                selected_p_label = st.selectbox("対象の問題を選択", list(p_choices.keys()))
                selected_p_id = p_choices[selected_p_label]
                target_p = problems_df[problems_df["problem_id"] == selected_p_id].iloc[0]

                edit_subject = st.text_input("科目名", value=target_p["subject"])
                edit_folder = st.text_input("フォルダパス", value=target_p.get("folder_path", "/"))
                edit_unit = st.text_input("単元名", value=target_p["unit"])
                edit_title = st.text_input("問題名", value=target_p["title"])

                st.write("---")
                st.write("**📎 添付資料リスト（個別削除・閲覧）**")

                curr_files = parse_attached_files(target_p.get("file_id", ""), target_p.get("file_name", ""))
                p_idx = problems_df[problems_df["problem_id"] == selected_p_id].index

                if curr_files:
                    st.caption(f"現在 {len(curr_files)} 件のファイルが添付されています。")
                    for f_i, f_obj in enumerate(curr_files):
                        f_id = f_obj.get("id", "")
                        f_name = f_obj.get("name", f"ファイル {f_i+1}")
                        is_pdf = f_name.lower().endswith(".pdf")
                        icon = "📄" if is_pdf else "🖼️"

                        c_label, c_view, c_del = st.columns([3, 1, 1])
                        with c_label:
                            st.write(f"{icon} **{f_name}**")
                        with c_view:
                            st.link_button("開く", f"https://drive.google.com/file/d/{f_id}/view")
                        with c_del:
                            if st.button("🗑️ 削除", key=f"del_single_file_{f_i}"):
                                with st.spinner(f"ドライブから「{f_name}」を削除中..."):
                                    delete_file_from_drive(f_id)
                                    updated_files = [f for idx, f in enumerate(curr_files) if idx != f_i]
                                    problems_df.loc[p_idx, "file_id"] = dump_attached_files(updated_files)
                                    problems_df.loc[p_idx, "file_name"] = f"{len(updated_files)}件のファイル" if updated_files else ""
                                    save_problems_df(problems_df)
                                    st.success(f"「{f_name}」を削除しました。")
                                    st.rerun()
                else:
                    st.caption("現在添付されているファイルはありません。")

                st.write("")
                new_add_files = st.file_uploader(
                    "➕ さらにファイルを追加する（複数選択可）",
                    type=["jpg", "jpeg", "png", "pdf"],
                    accept_multiple_files=True,
                    key="add_more_files_uploader"
                )

                st.write("")
                col_psav, col_pdel = st.columns(2)
                with col_psav:
                    if st.button("問題定義・追加ファイルの保存"):
                        problems_df.loc[p_idx, "subject"] = edit_subject.strip()
                        problems_df.loc[p_idx, "folder_path"] = "/" + edit_folder.strip("/") if edit_folder.strip("/") else "/"
                        problems_df.loc[p_idx, "unit"] = edit_unit.strip()
                        problems_df.loc[p_idx, "title"] = edit_title.strip()

                        if new_add_files:
                            target_drive_folder = st.secrets["connections"]["gsheets"].get("drive_folder_id", "")
                            with st.spinner(f"新規ファイルを保存中（計 {len(new_add_files)} 件）..."):
                                for add_f in new_add_files:
                                    try:
                                        res = upload_file_to_drive(add_f, target_drive_folder)
                                        curr_files.append({"id": res.get("id", ""), "name": add_f.name})
                                    except Exception as a_err:
                                        st.error(f"ファイル保存失敗 ({add_f.name}): {a_err}")

                                problems_df.loc[p_idx, "file_id"] = dump_attached_files(curr_files)
                                problems_df.loc[p_idx, "file_name"] = f"{len(curr_files)}件のファイル"

                        save_problems_df(problems_df)
                        st.success("問題定義と添付情報を更新しました。")
                        st.rerun()

                with col_pdel:
                    if st.button("この問題を完全に削除"):
                        if curr_files:
                            for f_obj in curr_files:
                                delete_file_from_drive(f_obj.get("id", ""))

                        updated_p = problems_df[problems_df["problem_id"] != selected_p_id]
                        save_problems_df(updated_p)
                        if not attempts_df.empty:
                            updated_a = attempts_df[attempts_df["problem_id"] != selected_p_id]
                            save_attempts_df(updated_a)
                        st.warning(f"問題 [{selected_p_id}] を削除しました。")
                        st.rerun()

        elif sub_action == "演習履歴の編集・削除":
            st.subheader("演習履歴の修正・削除")
            if attempts_df.empty:
                st.info("修正可能な演習履歴がありません。")
            else:
                merged_att = pd.merge(attempts_df, problems_df[["problem_id", "title"]], on="problem_id", how="left")
                merged_att["title"] = merged_att["title"].fillna("（不明な問題）")
                merged_att = merged_att.sort_values(by=["attempt_date", "attempt_id"], ascending=False)

                attempt_choices = {
                    f"ID:{row['attempt_id']} | {row['attempt_date']} | [{row['problem_id']}] {row['title']}": str(row['attempt_id'])
                    for _, row in merged_att.iterrows()
                }
                selected_att_label = st.selectbox("修正対象の履歴", list(attempt_choices.keys()))
                selected_att_id = attempt_choices[selected_att_label]
                target_row = attempts_df[attempts_df["attempt_id"].astype(str) == selected_att_id].iloc[0]

                try:
                    def_date = datetime.strptime(str(target_row["attempt_date"])[:10], "%Y-%m-%d").date()
                except Exception:
                    def_date = date.today()

                edit_date = st.date_input("日付を変更", value=def_date)
                try:
                    curr_is_corr = int(float(target_row["is_correct"])) == 1
                except Exception:
                    curr_is_corr = False

                edit_result = st.radio("結果を変更", ["正解 (◯)", "不正解 (✕)"], index=0 if curr_is_corr else 1, horizontal=True)
                edit_memo = st.text_input("メモを変更", value=str(target_row["memo"]) if pd.notna(target_row["memo"]) else "")

                st.write("")
                col_sav, col_del = st.columns(2)
                with col_sav:
                    if st.button("履歴を更新"):
                        target_idx = attempts_df[attempts_df["attempt_id"].astype(str) == selected_att_id].index
                        attempts_df.loc[target_idx, "attempt_date"] = edit_date.strftime("%Y-%m-%d")
                        attempts_df.loc[target_idx, "is_correct"] = 1 if edit_result == "正解 (◯)" else 0
                        attempts_df.loc[target_idx, "memo"] = edit_memo
                        save_attempts_df(attempts_df)
                        st.success("履歴を更新しました。")
                        st.rerun()

                with col_del:
                    if st.button("この履歴を削除"):
                        updated_att = attempts_df[attempts_df["attempt_id"].astype(str) != selected_att_id]
                        save_attempts_df(updated_att)
                        st.warning("履歴を削除しました。")
                        st.rerun()

        # --- ★ 新設: 参考書マスタの編集・削除サブアクション ---
        elif sub_action == "参考書マスタの編集・削除":
            st.subheader("参考書マスタの編集・削除")
            if books_df.empty:
                st.info("登録済みの参考書がありません。")
            else:
                b_choices = {
                    f"[{row['book_id']}] {row['title']} ({row['subject']})": str(row['book_id'])
                    for _, row in books_df.iterrows()
                }
                selected_b_label_m = st.selectbox("対象の参考書を選択", list(b_choices.keys()), key="sel_b_manage")
                selected_b_id_m = b_choices[selected_b_label_m]
                target_b_m = books_df[books_df["book_id"] == selected_b_id_m].iloc[0]

                edit_b_title = st.text_input("参考書名", value=target_b_m["title"])
                edit_b_subject = st.text_input("科目名", value=target_b_m["subject"])
                edit_b_total = st.number_input(
                    "総ページ数",
                    min_value=1,
                    max_value=5000,
                    value=int(target_b_m["total_pages"]),
                    step=10
                )
                edit_b_curr = st.number_input(
                    "現在の到達ページ数",
                    min_value=0,
                    max_value=int(edit_b_total),
                    value=int(target_b_m["current_pages"]),
                    step=1
                )

                b_m_idx = books_df[books_df["book_id"] == selected_b_id_m].index

                st.write("")
                col_bsav, col_bdel = st.columns(2)
                with col_bsav:
                    if st.button("参考書情報を更新"):
                        books_df.loc[b_m_idx, "title"] = edit_b_title.strip()
                        books_df.loc[b_m_idx, "subject"] = edit_b_subject.strip()
                        books_df.loc[b_m_idx, "total_pages"] = int(edit_b_total)
                        books_df.loc[b_m_idx, "current_pages"] = int(edit_b_curr)
                        save_books_df(books_df)
                        st.success("参考書情報を更新しました。")
                        st.rerun()

                with col_bdel:
                    if st.button("この参考書を完全に削除"):
                        updated_b = books_df[books_df["book_id"] != selected_b_id_m]
                        save_books_df(updated_b)
                        # カスケード削除
                        if not book_logs_df.empty:
                            updated_bl = book_logs_df[book_logs_df["book_id"] != selected_b_id_m]
                            save_book_logs_df(updated_bl)
                        st.warning(f"参考書 [{selected_b_id_m}] および関連ログを削除しました。")
                        st.rerun()
