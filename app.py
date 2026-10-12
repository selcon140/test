from datetime import date, datetime
import html
import io
import posixpath
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# -----------------------------------------------------------------------------
# Google 連携・Drive API / スプレッドシート最適化
# -----------------------------------------------------------------------------
def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def get_drive_service():
    """Secrets の認証情報から Google Drive API クライアントを初期化"""
    try:
        secrets = st.secrets["connections"]["gsheets"]
        creds_dict = {
            "type": secrets.get("type", "service_account"),
            "project_id": secrets["project_id"],
            "private_key_id": secrets.get("private_key_id"),
            "private_key": secrets["private_key"],
            "client_email": secrets["client_email"],
            "client_id": secrets.get("client_id"),
            "auth_uri": secrets.get("auth_uri", "https://accounts.google.com/o/oauth2/auth"),
            "token_uri": secrets.get("token_uri", "https://oauth2.googleapis.com/token"),
            "auth_provider_x509_cert_url": secrets.get("auth_provider_x509_cert_url"),
            "client_x509_cert_url": secrets.get("client_x509_cert_url"),
        }
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        st.error(f"Google Drive API の認証初期化に失敗しました: {e}")
        return None

def upload_file_to_drive(uploaded_file, target_folder_id: str) -> dict:
    """ファイルを Google ドライブにアップロードし、ファイルIDと表示用URLを取得"""
    service = get_drive_service()
    if not service:
        raise RuntimeError("Drive サービスを初期化できませんでした。")

    file_metadata = {
        "name": uploaded_file.name,
        "parents": [target_folder_id]
    }
    media = MediaIoBaseUpload(
        io.BytesIO(uploaded_file.getvalue()),
        mimetype=uploaded_file.type,
        resumable=True
    )

    created_file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, name, webViewLink, webContentLink"
    ).execute()

    # サービスアカウント以外もリンクから閲覧可能にする権限設定（Reader）
    try:
        service.permissions().create(
            fileId=created_file.get("id"),
            body={"type": "anyone", "role": "reader"}
        ).execute()
    except Exception:
        pass

    return created_file

@st.cache_data(ttl=60)
def get_problems_df() -> pd.DataFrame:
    """問題マスタ（problems シート）をキャッシュして取得（folder_path, file_id などを自動補完）"""
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
    """演習履歴（attempts シート）をキャッシュして取得"""
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

def save_problems_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="problems", data=df)
    st.cache_data.clear()

def save_attempts_df(df: pd.DataFrame):
    conn = get_connection()
    conn.update(worksheet="attempts", data=df)
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

    .error-card {
        background: #FFFFFF;
        border-radius: 16px;
        border-left: 6px solid #E60012;
        border-right: 1px solid #ECECEC;
        border-top: 1px solid #ECECEC;
        border-bottom: 1px solid #ECECEC;
        padding: 20px;
        margin: 20px 0;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.04);
    }
    .error-card-title {
        font-size: 18px;
        font-weight: 800;
        color: #E60012;
        margin-bottom: 8px;
    }
    .error-card-desc {
        font-size: 14px;
        color: #3F3F46;
        line-height: 1.6;
        margin-bottom: 12px;
    }
    .error-card-action {
        font-size: 13px;
        font-weight: 700;
        color: #71717A;
        background: #F4F4F5;
        padding: 8px 12px;
        border-radius: 8px;
    }

    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent;
        border-bottom: 2px solid #E5E7EB;
        gap: 8px;
        padding-left: 0;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
        border: none !important;
        padding: 12px 16px !important;
        font-size: 16px !important;
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
        padding: 12px;
        margin-bottom: 14px;
    }
    .file-preview-title {
        font-size: 13px;
        font-weight: 800;
        color: #1F2937;
        margin-bottom: 8px;
    }
    .file-btn-link {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        background-color: #2563EB;
        color: #FFFFFF !important;
        font-weight: 700;
        font-size: 13px;
        padding: 8px 14px;
        border-radius: 8px;
        text-decoration: none;
        margin-top: 6px;
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
    <div class="nintendo-badge">Drive + Explorer</div>
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
    load_success = True
except Exception as e:
    load_success = False
    err_str = str(e)
    st.error(f"データ取得エラー: {err_str}")
    if st.button("🔄 再読み込み"):
        st.rerun()

if load_success:
    tab_catalog, tab_entry, tab_manage = st.tabs(["📁 エクスプローラー", "✏️ 演習記録", "⚙️ マスタ管理"])

    # -----------------------------------------------------------------------------
    # タブ 1: エクスプローラー（フォルダ階層 & ファイル閲覧）
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

            # サブフォルダ一覧表示
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

            # 問題カード一覧表示
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
                    f_id_raw = str(r.get("file_id", "")).strip()
                    f_name_raw = str(r.get("file_name", "")).strip()

                    file_badge = ""
                    if f_id_raw and f_id_raw.lower() not in ["nan", "none", ""]:
                        is_pdf = f_name_raw.lower().endswith(".pdf")
                        file_badge = f'<span class="tag-file-badge">{"📄 PDF" if is_pdf else "🖼️ 画像"}</span>'

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

                    # 添付ファイルの表示ブロック
                    file_block_html = ""
                    if f_id_raw and f_id_raw.lower() not in ["nan", "none", ""]:
                        is_pdf = f_name_raw.lower().endswith(".pdf")
                        drive_view_url = f"https://drive.google.com/file/d/{f_id_raw}/view"
                        drive_thumb_url = f"https://lh3.googleusercontent.com/d/{f_id_raw}"

                        if is_pdf:
                            file_block_html = f"""
                            <div class="file-preview-box">
                                <div class="file-preview-title">📎 添付資料（PDF）: {html.escape(f_name_raw)}</div>
                                <a href="{drive_view_url}" target="_blank" class="file-btn-link">📄 ドライブで PDF を開く</a>
                            </div>
                            """
                        else:
                            file_block_html = f"""
                            <div class="file-preview-box">
                                <div class="file-preview-title">📎 添付画像: {html.escape(f_name_raw)}</div>
                                <div style="text-align:center; margin-bottom:8px;">
                                    <img src="{drive_thumb_url}" style="max-width:100%; max-height:260px; border-radius:8px; border:1px solid #E5E7EB;" loading="lazy" />
                                </div>
                                <a href="{drive_view_url}" target="_blank" class="file-btn-link">🔍 原寸大で開く</a>
                            </div>
                            """

                    # 演習履歴
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
    # タブ 2: 演習ログ登録
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
    # タブ 3: マスタ管理（問題登録 & ファイルアップロード）
    # -----------------------------------------------------------------------------
    with tab_manage:
        sub_action = st.radio(
            "操作を選択",
            ["新規問題の追加（ファイル添付対応）", "問題マスタ・添付ファイルの編集", "演習履歴の編集・削除"],
            horizontal=True
        )
        st.write("---")

        if sub_action == "新規問題の追加（ファイル添付対応）":
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

            # ファイルアップロード（JPEG / PNG / PDF）
            st.write("---")
            uploaded_file = st.file_uploader(
                "📎 問題の図面・解答 PDF をアップロード（任意）",
                type=["jpg", "jpeg", "png", "pdf"]
            )

            st.write("")
            if st.button("問題を Google ドライブ＆スプレッドシートに登録"):
                if new_id and new_subject and new_unit and new_title:
                    clean_id = new_id.strip()
                    if not problems_df.empty and clean_id in problems_df["problem_id"].values:
                        st.error("その問題IDは既に存在しています。")
                    else:
                        file_id = ""
                        file_name = ""
                        target_drive_folder = st.secrets["connections"]["gsheets"].get("drive_folder_id", "")

                        if uploaded_file and target_drive_folder:
                            with st.spinner("Google ドライブへファイルをアップロード中..."):
                                try:
                                    uploaded_res = upload_file_to_drive(uploaded_file, target_drive_folder)
                                    file_id = uploaded_res.get("id", "")
                                    file_name = uploaded_file.name
                                    st.success(f"ドライブへの保存が完了しました: {file_name}")
                                except Exception as upload_err:
                                    st.error(f"ファイル保存に失敗しました: {upload_err}")

                        new_problem = pd.DataFrame([{
                            "problem_id": clean_id,
                            "subject": new_subject.strip(),
                            "folder_path": target_f_path,
                            "unit": new_unit.strip(),
                            "title": new_title.strip(),
                            "file_id": file_id,
                            "file_name": file_name
                        }])
                        updated_problems = pd.concat([problems_df, new_problem], ignore_index=True)
                        save_problems_df(updated_problems)
                        st.success(f"問題 [{clean_id}] を登録しました。")
                        st.rerun()
                else:
                    st.error("必須項目（ID、科目、単元、問題名）をすべて入力してください。")

        elif sub_action == "問題マスタ・添付ファイルの編集":
            st.subheader("問題定義の修正 & 添付ファイルの追加・更新")
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

                curr_file_id = str(target_p.get("file_id", "")).strip()
                curr_file_name = str(target_p.get("file_name", "")).strip()
                if curr_file_id and curr_file_id.lower() not in ["nan", "none", ""]:
                    st.caption(f"現在の添付ファイル: `{curr_file_name}`（ID: {curr_file_id}）")
                else:
                    st.caption("現在ファイルは添付されていません。")

                new_edit_file = st.file_uploader(
                    "新しいファイルに差し替える / 新規追加（JPEG, PNG, PDF）",
                    type=["jpg", "jpeg", "png", "pdf"],
                    key="edit_file_uploader"
                )

                st.write("")
                col_psav, col_pdel = st.columns(2)
                with col_psav:
                    if st.button("更新を保存"):
                        p_idx = problems_df[problems_df["problem_id"] == selected_p_id].index
                        problems_df.loc[p_idx, "subject"] = edit_subject.strip()
                        problems_df.loc[p_idx, "folder_path"] = "/" + edit_folder.strip("/") if edit_folder.strip("/") else "/"
                        problems_df.loc[p_idx, "unit"] = edit_unit.strip()
                        problems_df.loc[p_idx, "title"] = edit_title.strip()

                        if new_edit_file:
                            target_drive_folder = st.secrets["connections"]["gsheets"].get("drive_folder_id", "")
                            with st.spinner("新しいファイルを Google ドライブへ保存中..."):
                                uploaded_res = upload_file_to_drive(new_edit_file, target_drive_folder)
                                problems_df.loc[p_idx, "file_id"] = uploaded_res.get("id", "")
                                problems_df.loc[p_idx, "file_name"] = new_edit_file.name

                        save_problems_df(problems_df)
                        st.success("問題定義と添付情報を更新しました。")
                        st.rerun()

                with col_pdel:
                    if st.button("この問題を削除"):
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
