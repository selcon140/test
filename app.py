import sqlite3
from datetime import date, datetime
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
            p.problem_id AS "問題ID",
            p.subject AS "科目",
            p.unit AS "単元",
            p.title AS "問題名",
            COUNT(a.attempt_id) AS "演習回数",
            SUM(CASE WHEN a.is_correct = 1 THEN 1 ELSE 0 END) AS "正解数",
            MAX(a.attempt_date) AS "最終実施日"
        FROM problems p
        LEFT JOIN attempts a ON p.problem_id = a.problem_id
        GROUP BY p.problem_id;
    """
    with get_connection() as conn:
        df = pd.read_sql_query(query, conn)

    today = date.today()
    df["正答率(%)"] = df.apply(
        lambda row: round((row["正解数"] / row["演習回数"]) * 100, 1) if row["演習回数"] > 0 else None,
        axis=1
    )

    def calc_elapsed_days(last_date_str):
        if pd.isna(last_date_str) or not last_date_str:
            return None
        last_d = datetime.strptime(last_date_str, "%Y-%m-%d").date()
        return (today - last_d).days

    df["経過日数(日)"] = df["最終実施日"].apply(calc_elapsed_days)
    return df

# -----------------------------------------------------------------------------
# ページ設定と iOS 風スタイルシート（CSS Injection）
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Study Tracker", layout="centered")
init_db()

# iOS デザインシステムの注入
st.markdown("""
<style>
    /* 全体の背景色とフォントを iOS 風に指定 */
    .stApp {
        background-color: #F2F2F7;
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", sans-serif;
        color: #1C1C1E;
    }

    /* 上部ヘッダーの余白調整 */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 700px; /* iPhoneで見やすい横幅 */
    }

    /* iOS 風カードコンテナ */
    div[data-testid="stVerticalBlock"] > div.css-card {
        background: #FFFFFF;
        border-radius: 18px;
        padding: 20px;
        box-shadow: 0 4px 14px rgba(0, 0, 0, 0.05);
        margin-bottom: 16px;
        border: 1px solid rgba(0, 0, 0, 0.03);
    }

    /* タブ（セグメントコントロール風） */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #E5E5EA;
        padding: 4px;
        border-radius: 12px;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 9px;
        padding: 6px 16px;
        font-weight: 600;
        font-size: 14px;
        color: #8E8E93;
        background-color: transparent;
        border: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFFFFF !important;
        color: #000000 !important;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.12);
    }

    /* ボタン（iOS プライマリブルー & 角丸カプセル型） */
    .stButton > button {
        background-color: #007AFF;
        color: white;
        border: none;
        border-radius: 14px;
        font-weight: 600;
        font-size: 16px;
        padding: 12px 24px;
        width: 100%;
        transition: all 0.2s ease;
    }
    .stButton > button:hover {
        background-color: #0062CC;
        color: white;
    }
    .stButton > button:active {
        transform: scale(0.98);
    }

    /* 入力フォームの角丸化 */
    input, select, textarea, div[data-baseweb="select"] {
        border-radius: 12px !important;
    }
</style>
""", unsafe_allow_html=True)

# アプリヘッダー
st.title("📚 演習トラッカー")

# タブナビゲーション（スマホで見やすい上部タブ）
tab_dash, tab_log, tab_manage = st.tabs(["📊 ダッシュボード", "✍️ 演習記録", "⚙️ 設定・管理"])

# -----------------------------------------------------------------------------
# タブ 1: ダッシュボード（集計・一覧）
# -----------------------------------------------------------------------------
with tab_dash:
    data = fetch_aggregated_data()
    if data.empty:
        st.info("登録されている問題がありません。「設定・管理」タブから問題を追加してください。")
    else:
        # 簡易サマリーカード
        c1, c2, c3 = st.columns(3)
        c1.metric("総問題数", f"{len(data)} 問")
        solved_count = len(data[data["演習回数"] > 0])
        c2.metric("着手済み", f"{solved_count} 問")
        avg_acc = data["正答率(%)"].dropna().mean()
        c3.metric("平均正答率", f"{avg_acc:.1f}%" if pd.notna(avg_acc) else "-")

        st.write("")
        # フィルタ & ソート
        filter_sub = st.selectbox("科目で絞り込み", ["全科目"] + sorted(list(data["科目"].unique())))
        sort_target = st.selectbox(
            "並び替え",
            ["経過日数が長い順（復習優先）", "正答率が低い順（弱点克服）", "科目・単元順", "演習回数が少ない順"]
        )

        view_df = data.copy()
        if filter_sub != "全科目":
            view_df = view_df[view_df["科目"] == filter_sub]

        if sort_target == "経過日数が長い順（復習優先）":
            view_df = view_df.sort_values(by="経過日数(日)", ascending=False, na_position="first")
        elif sort_target == "正答率が低い順（弱点克服）":
            view_df = view_df.sort_values(by="正答率(%)", ascending=True, na_position="last")
        elif sort_target == "科目・単元順":
            view_df = view_df.sort_values(by=["科目", "単元", "問題ID"])
        elif sort_target == "演習回数が少ない順":
            view_df = view_df.sort_values(by="演習回数", ascending=True)

        st.dataframe(
            view_df,
            column_config={
                "正答率(%)": st.column_config.ProgressColumn(
                    "正答率",
                    format="%.1f%%",
                    min_value=0,
                    max_value=100,
                ),
                "経過日数(日)": st.column_config.NumberColumn(
                    "最終演習",
                    format="%d 日前",
                ),
                "演習回数": st.column_config.NumberColumn(format="%d 回"),
                "正解数": st.column_config.NumberColumn(format="%d 回"),
            },
            hide_index=True,
            use_container_width=True,
        )

# -----------------------------------------------------------------------------
# タブ 2: 演習ログの記録
# -----------------------------------------------------------------------------
with tab_log:
    st.subheader("解いた問題を記録")
    with get_connection() as conn:
        problems_df = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

    if problems_df.empty:
        st.warning("先に問題マスタを登録してください。")
    else:
        with st.container():
            selected_subject = st.selectbox("科目", problems_df["subject"].unique())
            filtered_units = problems_df[problems_df["subject"] == selected_subject]["unit"].unique()
            selected_unit = st.selectbox("単元", filtered_units)

            selectable_problems = problems_df[
                (problems_df["subject"] == selected_subject) & (problems_df["unit"] == selected_unit)
            ]
            problem_options = {
                f"[{row['problem_id']}] {row['title']}": row['problem_id']
                for _, row in selectable_problems.iterrows()
            }
            selected_label = st.selectbox("問題", list(problem_options.keys()))
            selected_problem_id = problem_options[selected_label]

            col_d, col_r = st.columns(2)
            with col_d:
                attempt_date_val = st.date_input("実施日", value=date.today())
            with col_r:
                result_str = st.radio("結果", ["正解 (◯)", "不正解 (✕)"], horizontal=True)

            memo_val = st.text_input("メモ（つまずいた箇所など）")

            if st.button("記録を保存する"):
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
# タブ 3: 設定・管理（マスタ追加・編集・削除）
# -----------------------------------------------------------------------------
with tab_manage:
    manage_mode = st.radio(
        "管理項目",
        ["問題の新規登録", "過去ログの修正・削除", "問題マスタの修正・削除"],
        horizontal=True
    )
    st.write("---")

    # 1. 新規問題の登録
    if manage_mode == "問題の新規登録":
        st.subheader("新しい問題を追加")
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT subject FROM problems;")
            existing_subjects = [row[0] for row in cursor.fetchall()]

        new_id = st.text_input("問題ID（例: EM-001）")
        sub_mode = st.radio("科目の指定", ["既存から選択", "新規入力"], horizontal=True)
        if sub_mode == "既存から選択" and existing_subjects:
            new_subject = st.selectbox("既存科目", existing_subjects)
        else:
            new_subject = st.text_input("科目名")

        new_unit = st.text_input("単元名（例: ガウスの法則）")
        new_title = st.text_input("問題名（例: 点電荷の電界）")

        if st.button("問題をデータベースに登録"):
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
                    st.error("その問題IDはすでに存在しています。")
            else:
                st.error("すべての必須項目を入力してください。")

    # 2. 過去履歴の編集・削除
    elif manage_mode == "過去ログの修正・削除":
        st.subheader("演習ログの編集・削除")
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
            selected_att_label = st.selectbox("編集する履歴", list(attempt_choices.keys()))
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

            col_u, col_d = st.columns(2)
            if col_u.button("更新を保存"):
                with get_connection() as conn:
                    conn.execute("""
                        UPDATE attempts
                        SET attempt_date = ?, is_correct = ?, memo = ?
                        WHERE attempt_id = ?
                    """, (edit_date.strftime("%Y-%m-%d"), 1 if edit_result == "正解 (◯)" else 0, edit_memo, selected_att_id))
                    conn.commit()
                st.success("履歴を更新しました。")
                st.rerun()

            if col_d.button("この履歴を削除"):
                with get_connection() as conn:
                    conn.execute("DELETE FROM attempts WHERE attempt_id = ?", (selected_att_id,))
                    conn.commit()
                st.warning("履歴を削除しました。")
                st.rerun()

    # 3. 問題マスタの編集・削除
    elif manage_mode == "問題マスタの修正・削除":
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
            selected_p_label = st.selectbox("編集する問題", list(p_choices.keys()))
            selected_p_id = p_choices[selected_p_label]
            target_p = problems_raw[problems_raw["problem_id"] == selected_p_id].iloc[0]

            edit_subject = st.text_input("科目名", value=target_p["subject"])
            edit_unit = st.text_input("単元名", value=target_p["unit"])
            edit_title = st.text_input("問題名", value=target_p["title"])

            col_pu, col_pd = st.columns(2)
            if col_pu.button("問題定義を更新"):
                with get_connection() as conn:
                    conn.execute("""
                        UPDATE problems
                        SET subject = ?, unit = ?, title = ?
                        WHERE problem_id = ?
                    """, (edit_subject.strip(), edit_unit.strip(), edit_title.strip(), selected_p_id))
                    conn.commit()
                st.success("問題定義を更新しました。")
                st.rerun()

            if col_pd.button("この問題を削除"):
                with get_connection() as conn:
                    conn.execute("DELETE FROM problems WHERE problem_id = ?", (selected_p_id,))
                    conn.commit()
                st.warning(f"問題 [{selected_p_id}] を削除しました。")
                st.rerun()
