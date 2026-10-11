from datetime import date, datetime
import html
import pandas as pd
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# -----------------------------------------------------------------------------
# Google スプレッドシート連携・データ操作関数（Spreadsheet Operations）
# -----------------------------------------------------------------------------
def get_connection():
    """Google Sheets への接続コネクション（connection）を取得します。"""
    return st.connection("gsheets", type=GSheetsConnection)

def get_problems_df() -> pd.DataFrame:
    """問題マスタ（problems シート）を取得します。"""
    conn = get_connection()
    df = conn.read(worksheet="problems", ttl=0)
    if df is None or df.empty:
        return pd.DataFrame(columns=["problem_id", "subject", "unit", "title"])
    df = df.dropna(how="all")
    for col in ["problem_id", "subject", "unit", "title"]:
        if col not in df.columns:
            df[col] = ""
    df = df.astype(str)
    df = df[df["problem_id"].str.strip() != ""]
    return df

def get_attempts_df() -> pd.DataFrame:
    """演習履歴（attempts シート）を取得します。"""
    conn = get_connection()
    df = conn.read(worksheet="attempts", ttl=0)
    if df is None or df.empty:
        return pd.DataFrame(columns=["attempt_id", "problem_id", "attempt_date", "is_correct", "memo"])
    df = df.dropna(how="all")
    for col in ["attempt_id", "problem_id", "attempt_date", "is_correct", "memo"]:
        if col not in df.columns:
            df[col] = ""
    df = df[df["attempt_id"].astype(str).str.strip() != ""]
    return df

def save_problems_df(df: pd.DataFrame):
    """問題マスタ（problems シート）を更新保存します。"""
    conn = get_connection()
    conn.update(worksheet="problems", data=df)

def save_attempts_df(df: pd.DataFrame):
    """演習履歴（attempts シート）を更新保存します。"""
    conn = get_connection()
    conn.update(worksheet="attempts", data=df)

def fetch_aggregated_data() -> pd.DataFrame:
    """スプレッドシートからデータを取得し、集計（aggregation）したデータフレームを生成します。"""
    problems_df = get_problems_df()
    attempts_df = get_attempts_df()

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

        # SQL の GROUP BY 処理を pandas で実行
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
# スタイルシート設定（Mobile-Optimized Nintendo UI）
# -----------------------------------------------------------------------------
st.set_page_config(page_title="演習ダッシュボード", layout="centered")

st.markdown("""
<style>
    /* 全体設定 */
    .stApp {
        background-color: #F8F9FA;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "Hiragino Sans", "Yu Gothic", sans-serif;
        color: #1A1A1A;
        -webkit-text-size-adjust: 100%;
    }

    header[data-testid="stHeader"] {
        background: transparent !important;
    }

    /* コンテナ余白（ヘッダー重なり防止のため上部に4.5rem確保） */
    .block-container {
        padding-top: 4.5rem !important;
        padding-bottom: 5rem !important;
        padding-left: 14px !important;
        padding-right: 14px !important;
        max-width: 820px !important;
        width: 100% !important;
    }

    /* ヘッダー */
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

    /* タブ切り替え（タッチ領域拡大 & 横スクロール） */
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

    /* サマリーカード */
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

    /* 問題カードグリッド: スマホでは1列、幅広端末で2列 */
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

    /* 個別問題カード */
    .nintendo-card {
        background: #FFFFFF;
        border-radius: 18px;
        padding: 20px;
        border: 1px solid #ECECEC;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.03);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        transition: transform 0.25s cubic-bezier(0.25, 1, 0.5, 1), box-shadow 0.25s cubic-bezier(0.25, 1, 0.5, 1);
    }
    .nintendo-card:active {
        transform: scale(0.985);
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

    /* 正答率バー */
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

    /* カード下部ステータス */
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

    /* ボタン（Nintendo Red: 52px高） */
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
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background-color: #CC0010;
        color: #FFFFFF;
    }

    /* フォーム入力要素（iOS自動拡大防止のため16px確保） */
    div[data-baseweb="select"] > div, input, textarea {
        min-height: 50px !important;
        font-size: 16px !important;
        border-radius: 12px !important;
        border-color: #E5E7EB !important;
    }
    div[data-testid="stRadio"] label {
        font-size: 15px !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# ヘッダー
# -----------------------------------------------------------------------------
st.markdown("""
<div class="nintendo-header">
    <div class="nintendo-badge">Study</div>
    <div class="nintendo-title">演習ダッシュボード</div>
</div>
""", unsafe_allow_html=True)

tab_catalog, tab_entry, tab_manage = st.tabs(["📚 カタログ（一覧）", "✏️ 演習記録", "⚙️ マスタ管理"])

# -----------------------------------------------------------------------------
# タブ 1: カタログ（問題一覧）
# -----------------------------------------------------------------------------
with tab_catalog:
    data = fetch_aggregated_data()

    if data.empty:
        st.info("登録されている問題がありません。「マスタ管理」タブから新しい問題を追加してください。")
    else:
        total_p = len(data)
        solved_p = len(data[data["total_attempts"] > 0])
        avg_acc = data["accuracy"].dropna().mean()
        avg_str = f"{avg_acc:.1f}%" if pd.notna(avg_acc) else "-"

        # サマリーカード
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

        # 絞り込み & 並び替え
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            subject_filter = st.selectbox(
                "科目絞り込み",
                ["全科目"] + sorted(list(data["subject"].unique()))
            )
        with col_f2:
            sort_metric = st.selectbox(
                "並び替え基準",
                ["復習優先（未着手・経過日数が長い順）", "弱点克服（正答率が低い順）", "科目・単元順", "演習回数が少ない順"]
            )

        filtered = data.copy()
        if subject_filter != "全科目":
            filtered = filtered[filtered["subject"] == subject_filter]

        if sort_metric == "復習優先（未着手・経過日数が長い順）":
            filtered = filtered.sort_values(by="elapsed_days", ascending=False, na_position="first")
        elif sort_metric == "弱点克服（正答率が低い順）":
            filtered = filtered.sort_values(by="accuracy", ascending=True, na_position="last")
        elif sort_metric == "科目・単元順":
            filtered = filtered.sort_values(by=["subject", "unit", "problem_id"])
        elif sort_metric == "演習回数が少ない順":
            filtered = filtered.sort_values(by="total_attempts", ascending=True)

        # カードグリッド生成
        cards_html = '<div class="cards-grid">\n'
        for _, r in filtered.iterrows():
            title_s = html.escape(str(r["title"]))
            subject_s = html.escape(str(r["subject"]))
            unit_s = html.escape(str(r["unit"]))
            p_id = html.escape(str(r["problem_id"]))

            if pd.isna(r["accuracy"]):
                acc_text = "未実施"
                bar_width = 0
                fill_color = "fill-gray"
            else:
                acc_val = int(r["accuracy"])
                acc_text = f"{acc_val}%"
                bar_width = acc_val
                if acc_val >= 80:
                    fill_color = "fill-green"
                elif acc_val >= 50:
                    fill_color = "fill-orange"
                else:
                    fill_color = "fill-red"

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

            cards_html += f"""
<div class="nintendo-card">
<div>
<div class="card-top">
<span class="tag-subject">[{p_id}] {subject_s}</span>
<span class="tag-unit">{unit_s}</span>
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
</div>
</div>
"""
        cards_html += '\n</div>'

        clean_cards_html = "\n".join(line.strip() for line in cards_html.splitlines())
        st.markdown(clean_cards_html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# タブ 2: 演習ログ登録
# -----------------------------------------------------------------------------
with tab_entry:
    st.subheader("演習結果を記録する")
    problems_df = get_problems_df()

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

        memo_val = st.text_input("演習メモ（公式・定理の条件やミスの原因）", placeholder="解法の要点やミスの理由")

        st.write("")
        if st.button("この記録を保存する"):
            is_correct_val = 1 if result_str == "正解 (◯)" else 0
            attempts_df = get_attempts_df()

            # 一意な attempt_id を生成（最大値+1）
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
            st.success("演習結果をスプレッドシートに保存しました。")
            st.rerun()

# -----------------------------------------------------------------------------
# タブ 3: マスタ・履歴管理
# -----------------------------------------------------------------------------
with tab_manage:
    sub_action = st.radio(
        "操作を選択",
        ["問題の新規作成", "演習履歴の編集・削除", "問題マスタの編集・削除"],
        horizontal=True
    )
    st.write("---")

    if sub_action == "問題の新規作成":
        st.subheader("新規問題の追加")
        problems_df = get_problems_df()
        existing_subjects = list(problems_df["subject"].unique()) if not problems_df.empty else []

        new_id = st.text_input("問題ID（例: EM-001）")
        sub_mode = st.radio("科目の指定方法", ["既存から選択", "新規入力"], horizontal=True)
        if sub_mode == "既存から選択" and existing_subjects:
            new_subject = st.selectbox("既存の科目", existing_subjects)
        else:
            new_subject = st.text_input("新規科目名")

        new_unit = st.text_input("単元名（例: ガウスの法則）")
        new_title = st.text_input("問題名（例: 同軸円筒導体の電界計算）")

        st.write("")
        if st.button("問題をカタログに追加"):
            if new_id and new_subject and new_unit and new_title:
                clean_id = new_id.strip()
                if not problems_df.empty and clean_id in problems_df["problem_id"].values:
                    st.error("その問題IDは既に存在しています。")
                else:
                    new_problem = pd.DataFrame([{
                        "problem_id": clean_id,
                        "subject": new_subject.strip(),
                        "unit": new_unit.strip(),
                        "title": new_title.strip()
                    }])
                    updated_problems = pd.concat([problems_df, new_problem], ignore_index=True)
                    save_problems_df(updated_problems)
                    st.success(f"問題 [{clean_id}] をスプレッドシートに追加しました。")
                    st.rerun()
            else:
                st.error("すべての必須項目を入力してください。")

    elif sub_action == "演習履歴の編集・削除":
        st.subheader("演習履歴の修正・削除")
        attempts_raw = get_attempts_df()
        problems_df = get_problems_df()

        if attempts_raw.empty:
            st.info("修正可能な演習履歴がありません。")
        else:
            # 表示用に問題タイトルを結合
            merged_att = pd.merge(attempts_raw, problems_df[["problem_id", "title"]], on="problem_id", how="left")
            merged_att["title"] = merged_att["title"].fillna("（不明な問題）")
            merged_att = merged_att.sort_values(by=["attempt_date", "attempt_id"], ascending=False)

            attempt_choices = {
                f"ID:{row['attempt_id']} | {row['attempt_date']} | [{row['problem_id']}] {row['title']}": str(row['attempt_id'])
                for _, row in merged_att.iterrows()
            }
            selected_att_label = st.selectbox("修正対象の履歴", list(attempt_choices.keys()))
            selected_att_id = attempt_choices[selected_att_label]
            target_row = attempts_raw[attempts_raw["attempt_id"].astype(str) == selected_att_id].iloc[0]

            try:
                def_date = datetime.strptime(str(target_row["attempt_date"])[:10], "%Y-%m-%d").date()
            except Exception:
                def_date = date.today()

            edit_date = st.date_input("日付を変更", value=def_date)
            edit_result = st.radio(
                "結果を変更",
                ["正解 (◯)", "不正解 (✕)"],
                index=0 if int(target_row["is_correct"]) == 1 else 1,
                horizontal=True
            )
            edit_memo = st.text_input("メモを変更", value=str(target_row["memo"]) if pd.notna(target_row["memo"]) else "")

            st.write("")
            col_sav, col_del = st.columns(2)
            with col_sav:
                if st.button("履歴を更新"):
                    target_idx = attempts_raw[attempts_raw["attempt_id"].astype(str) == selected_att_id].index
                    attempts_raw.loc[target_idx, "attempt_date"] = edit_date.strftime("%Y-%m-%d")
                    attempts_raw.loc[target_idx, "is_correct"] = 1 if edit_result == "正解 (◯)" else 0
                    attempts_raw.loc[target_idx, "memo"] = edit_memo
                    save_attempts_df(attempts_raw)
                    st.success("履歴を更新しました。")
                    st.rerun()

            with col_del:
                if st.button("この履歴を削除"):
                    updated_att = attempts_raw[attempts_raw["attempt_id"].astype(str) != selected_att_id]
                    save_attempts_df(updated_att)
                    st.warning("履歴を削除しました。")
                    st.rerun()

    elif sub_action == "問題マスタの編集・削除":
        st.subheader("問題定義の修正・削除")
        problems_raw = get_problems_df()

        if problems_raw.empty:
            st.info("登録済みの問題がありません。")
        else:
            p_choices = {
                f"[{row['problem_id']}] {row['subject']} - {row['title']}": str(row['problem_id'])
                for _, row in problems_raw.iterrows()
            }
            selected_p_label = st.selectbox("修正対象の問題", list(p_choices.keys()))
            selected_p_id = p_choices[selected_p_label]
            target_p = problems_raw[problems_raw["problem_id"] == selected_p_id].iloc[0]

            edit_subject = st.text_input("科目名", value=target_p["subject"])
            edit_unit = st.text_input("単元名", value=target_p["unit"])
            edit_title = st.text_input("問題名", value=target_p["title"])

            st.write("")
            col_psav, col_pdel = st.columns(2)
            with col_psav:
                if st.button("問題定義を更新"):
                    p_idx = problems_raw[problems_raw["problem_id"] == selected_p_id].index
                    problems_raw.loc[p_idx, "subject"] = edit_subject.strip()
                    problems_raw.loc[p_idx, "unit"] = edit_unit.strip()
                    problems_raw.loc[p_idx, "title"] = edit_title.strip()
                    save_problems_df(problems_raw)
                    st.success("問題定義を更新しました。")
                    st.rerun()

            with col_pdel:
                if st.button("この問題を削除"):
                    # 問題マスタから削除
                    updated_p = problems_raw[problems_raw["problem_id"] != selected_p_id]
                    save_problems_df(updated_p)
                    # 関連する履歴も連動削除（カスケード削除）
                    attempts_df = get_attempts_df()
                    if not attempts_df.empty:
                        updated_a = attempts_df[attempts_df["problem_id"] != selected_p_id]
                        save_attempts_df(updated_a)
                    st.warning(f"問題 [{selected_p_id}] および関連履歴を削除しました。")
                    st.rerun()
