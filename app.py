import sqlite3
from datetime import date, datetime
import html
import pandas as pd
import streamlit as st

DB_NAME = "study_tracker.db"

# -----------------------------------------------------------------------------
# データベース制御関数（Database Operations）
# -----------------------------------------------------------------------------
def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS problems (
                problem_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                unit TEXT NOT NULL,
                title TEXT NOT NULL
            );
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attempts (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                problem_id TEXT NOT NULL,
                attempt_date DATE NOT NULL,
                is_correct INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
                memo TEXT,
                FOREIGN KEY (problem_id) REFERENCES problems(problem_id) ON DELETE CASCADE
            );
        """)
        conn.commit()

def fetch_aggregated_data() -> pd.DataFrame:
    query = """
        SELECT
            p.problem_id AS problem_id,
            p.subject AS subject,
            p.unit AS unit,
            p.title AS title,
            COUNT(a.attempt_id) AS total_attempts,
            SUM(CASE WHEN a.is_correct = 1 THEN 1 ELSE 0 END) AS correct_count,
            MAX(a.attempt_date) AS last_date
        FROM problems p
        LEFT JOIN attempts a ON p.problem_id = a.problem_id
        GROUP BY p.problem_id;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)

    today = date.today()
    df["accuracy"] = df.apply(
        lambda row: round((row["correct_count"] / row["total_attempts"]) * 100, 1)
        if row["total_attempts"] > 0 else None,
        axis=1
    )

    def calc_elapsed(d_str):
        if pd.isna(d_str) or not d_str:
            return None
        last_d = datetime.strptime(d_str, "%Y-%m-%d").date()
        return (today - last_d).days

    df["elapsed_days"] = df["last_date"].apply(calc_elapsed)
    return df

# -----------------------------------------------------------------------------
# スタイルシート設定（Mobile / iPad Optimized Style Injection）
# -----------------------------------------------------------------------------
st.set_page_config(page_title="演習ダッシュボード", layout="wide")
init_db()

st.markdown("""
<style>
    /* 全体背景 & フォント設定 */
    .stApp {
        background-color: #F8F9FA;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "Hiragino Sans", "Yu Gothic", sans-serif;
        color: #1A1A1A;
        -webkit-text-size-adjust: 100%;
    }

    /* コンテナの余白（スマホでは画面幅をフル活用） */
    .block-container {
        padding-top: 1.2rem;
        padding-bottom: 5rem;
        max-width: 1000px;
    }
    @media (max-width: 768px) {
        .block-container {
            padding-left: 12px !important;
            padding-right: 12px !important;
            padding-top: 0.8rem !important;
        }
    }

    /* ヘッダー */
    .nintendo-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 16px;
        padding-bottom: 10px;
        border-bottom: 2px solid #EBEBEB;
    }
    .nintendo-badge {
        background-color: #E60012;
        color: #FFFFFF;
        font-size: 13px;
        font-weight: 800;
        letter-spacing: 0.5px;
        padding: 5px 12px;
        border-radius: 8px;
        text-transform: uppercase;
    }
    .nintendo-title {
        font-size: 22px;
        font-weight: 800;
        letter-spacing: -0.5px;
        color: #1A1A1A;
    }

    /* タブ（タッチターゲットの拡大 & 横スクロール対応） */
    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent;
        border-bottom: 2px solid #E5E7EB;
        gap: 12px;
        padding-left: 0;
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent !important;
        border: none !important;
        padding: 14px 16px !important;
        font-size: 16px !important;
        font-weight: 700;
        color: #71717A;
        position: relative;
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

    /* サマリーカード（モバイルでも見やすい均等レイアウト） */
    .summary-grid {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 10px;
        margin-bottom: 20px;
    }
    @media (max-width: 480px) {
        .summary-grid {
            grid-template-columns: 1fr;
            gap: 8px;
        }
    }
    .summary-card {
        background: #FFFFFF;
        border-radius: 16px;
        padding: 16px 14px;
        border: 1px solid #EAEAEA;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.02);
        text-align: center;
        transition: transform 0.25s cubic-bezier(0.25, 1, 0.5, 1);
    }
    .summary-card.primary {
        background: linear-gradient(135deg, #E60012 0%, #BA000F 100%);
        color: #FFFFFF;
        border: none;
    }
    .summary-label {
        font-size: 12px;
        font-weight: 700;
        color: #8E8E93;
        margin-bottom: 4px;
    }
    .summary-card.primary .summary-label {
        color: rgba(255, 255, 255, 0.9);
    }
    .summary-value {
        font-size: 24px;
        font-weight: 800;
        letter-spacing: -0.5px;
    }

    /* レスポンシブ カードグリッド（スマホは1列、iPadは2列、PCは3列） */
    .cards-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
        gap: 14px;
        margin-top: 14px;
    }
    @media (max-width: 600px) {
        .cards-grid {
            grid-template-columns: 1fr;
            gap: 12px;
        }
    }

    /* 個別問題カード */
    .nintendo-card {
        background: #FFFFFF;
        border-radius: 18px;
        padding: 18px 20px;
        border: 1px solid #ECECEC;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.03);
        transition: transform 0.25s cubic-bezier(0.25, 1, 0.5, 1),
                    box-shadow 0.25s cubic-bezier(0.25, 1, 0.5, 1);
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    @media (hover: hover) and (pointer: fine) {
        .nintendo-card:hover {
            transform: translateY(-4px) scale(1.01);
            box-shadow: 0 14px 28px -4px rgba(0, 0, 0, 0.10);
            border-color: #D6D6D6;
        }
    }

    .card-top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
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
        font-size: 18px;
        font-weight: 800;
        color: #1A1A1A;
        line-height: 1.45;
        margin-bottom: 16px;
    }

    /* 正答率バー（太く見やすく改善） */
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

    /* ボタン（大型タッチターゲット: 52px） */
    .stButton > button {
        background-color: #E60012;
        color: #FFFFFF;
        border: none;
        border-radius: 14px;
        font-weight: 700;
        font-size: 17px !important;
        min-height: 52px !important;
        padding: 12px 24px;
        width: 100%;
        box-shadow: 0 4px 14px rgba(230, 0, 18, 0.25);
        transition: all 0.2s cubic-bezier(0.25, 1, 0.5, 1);
    }
    .stButton > button:hover {
        background-color: #CC0010;
        color: #FFFFFF;
    }
    .stButton > button:active {
        transform: scale(0.98);
    }

    /* フォーム要素の大型化 & iOS自動ズーム防止（16px以上） */
    div[data-baseweb="select"] > div, input, textarea {
        min-height: 50px !important;
        font-size: 16px !important;
        border-radius: 12px !important;
        border-color: #E5E7EB !important;
    }
    div[data-testid="stRadio"] label {
        font-size: 15px !important;
        padding: 8px 12px !important;
    }
    label[data-testid="stWidgetLabel"] p {
        font-size: 15px !important;
        font-weight: 700 !important;
        margin-bottom: 6px !important;
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

tab_overview, tab_entry, tab_control = st.tabs(["📚 カタログ（一覧）", "✏️ 演習記録", "⚙️ マスタ管理"])

# -----------------------------------------------------------------------------
# タブ 1: カタログ（問題一覧カードグリッド）
# -----------------------------------------------------------------------------
with tab_overview:
    data = fetch_aggregated_data()

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
                <div class="summary-value">{total_p} <span style="font-size:15px;">問</span></div>
            </div>
            <div class="summary-card">
                <div class="summary-label">着手済み</div>
                <div class="summary-value">{solved_p} <span style="font-size:15px;">問</span></div>
            </div>
            <div class="summary-card">
                <div class="summary-label">平均正答率</div>
                <div class="summary-value">{avg_str}</div>
            </div>
        </div>
        """
        st.markdown("\n".join(line.strip() for line in summary_html.splitlines()), unsafe_allow_html=True)

        f_col1, f_col2 = st.columns([1, 1])
        with f_col1:
            subject_filter = st.selectbox(
                "科目で絞り込み",
                ["全科目"] + sorted(list(data["subject"].unique()))
            )
        with f_col2:
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
    with get_connection() as conn:
        problems_df = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

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

        memo_val = st.text_input("演習メモ（つまずいた定理・公式や解法の要点）", placeholder="公式の適用条件を間違えた、など")

        st.write("")
        if st.button("この記録を保存する"):
            is_correct_val = 1 if result_str == "正解 (◯)" else 0
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO attempts (problem_id, attempt_date, is_correct, memo) VALUES (?, ?, ?, ?)",
                    (selected_problem_id, attempt_date_val.strftime("%Y-%m-%d"), is_correct_val, memo_val)
                )
                conn.commit()
            st.success("演習結果を保存しました。")
            st.rerun()

# -----------------------------------------------------------------------------
# タブ 3: マスタ・履歴管理
# -----------------------------------------------------------------------------
with tab_control:
    sub_action = st.radio(
        "操作を選択",
        ["問題の新規作成", "演習履歴の編集・削除", "問題マスタの編集・削除"],
        horizontal=True
    )
    st.write("---")

    if sub_action == "問題の新規作成":
        st.subheader("新規問題の追加")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT subject FROM problems;")
            existing_subjects = [row[0] for row in cursor.fetchall()]

        new_id = st.text_input("問題ID（一意のコード: 例 EM-001）")
        sub_mode = st.radio("科目の指定方法", ["既存から選択", "新規入力"], horizontal=True)
        if sub_mode == "既存から選択" and existing_subjects:
            new_subject = st.selectbox("既存の科目", existing_subjects)
        else:
            new_subject = st.text_input("新規科目名")

        new_unit = st.text_input("単元名（例: ビオ・サバールの法則）")
        new_title = st.text_input("問題名（例: 円形電流の作る磁界）")

        st.write("")
        if st.button("問題をカタログに追加"):
            if new_id and new_subject and new_unit and new_title:
                try:
                    with get_connection() as conn:
                        conn.execute(
                            "INSERT INTO problems (problem_id, subject, unit, title) VALUES (?, ?, ?, ?)",
                            (new_id.strip(), new_subject.strip(), new_unit.strip(), new_title.strip())
                        )
                        conn.commit()
                    st.success(f"問題 [{new_id}] を追加しました。")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("その問題IDは既に存在しています。")
            else:
                st.error("すべての必須項目を入力してください。")

    elif sub_action == "演習履歴の編集・削除":
        st.subheader("演習履歴の修正・削除")
        with get_connection() as conn:
            attempts_raw = pd.read_sql_query("""
                SELECT a.attempt_id, a.attempt_date, a.problem_id, p.title, a.is_correct, a.memo
                FROM attempts a
                JOIN problems p ON a.problem_id = p.problem_id
                ORDER BY a.attempt_date DESC, a.attempt_id DESC;
            """, conn)

        if attempts_raw.empty:
            st.info("修正可能な演習履歴がありません。")
        else:
            attempt_choices = {
                f"ID:{row['attempt_id']} | {row['attempt_date']} | [{row['problem_id']}] {row['title']}": row['attempt_id']
                for _, row in attempts_raw.iterrows()
            }
            selected_att_label = st.selectbox("修正対象の履歴", list(attempt_choices.keys()))
            selected_att_id = attempt_choices[selected_att_label]
            target_row = attempts_raw[attempts_raw["attempt_id"] == selected_att_id].iloc[0]

            edit_date = st.date_input(
                "日付を変更",
                value=datetime.strptime(target_row["attempt_date"], "%Y-%m-%d").date()
            )
            edit_result = st.radio(
                "結果を変更",
                ["正解 (◯)", "不正解 (✕)"],
                index=0 if target_row["is_correct"] == 1 else 1,
                horizontal=True
            )
            edit_memo = st.text_input("メモを変更", value=target_row["memo"] or "")

            st.write("")
            col_sav, col_del = st.columns(2)
            with col_sav:
                if st.button("履歴を更新"):
                    with get_connection() as conn:
                        conn.execute("""
                            UPDATE attempts
                            SET attempt_date = ?, is_correct = ?, memo = ?
                            WHERE attempt_id = ?
                        """, (edit_date.strftime("%Y-%m-%d"), 1 if edit_result == "正解 (◯)" else 0, edit_memo, selected_att_id))
                        conn.commit()
                    st.success("履歴を更新しました。")
                    st.rerun()

            with col_del:
                if st.button("この履歴を削除"):
                    with get_connection() as conn:
                        conn.execute("DELETE FROM attempts WHERE attempt_id = ?", (selected_att_id,))
                        conn.commit()
                    st.warning("履歴を削除しました。")
                    st.rerun()

    elif sub_action == "問題マスタの編集・削除":
        st.subheader("問題定義の修正・削除")
        with get_connection() as conn:
            problems_raw = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

        if problems_raw.empty:
            st.info("登録済みの問題がありません。")
        else:
            p_choices = {
                f"[{row['problem_id']}] {row['subject']} - {row['title']}": row['problem_id']
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
                    with get_connection() as conn:
                        conn.execute("""
                            UPDATE problems
                            SET subject = ?, unit = ?, title = ?
                            WHERE problem_id = ?
                        """, (edit_subject.strip(), edit_unit.strip(), edit_title.strip(), selected_p_id))
                        conn.commit()
                    st.success("問題定義を更新しました。")
                    st.rerun()

            with col_pdel:
                if st.button("この問題を削除"):
                    with get_connection() as conn:
                        conn.execute("DELETE FROM problems WHERE problem_id = ?", (selected_p_id,))
                        conn.commit()
                    st.warning(f"問題 [{selected_p_id}] を削除しました。")
                    st.rerun()
