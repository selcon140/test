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
# スタイルシート設定（LINE Style Injection）
# -----------------------------------------------------------------------------
st.set_page_config(page_title="演習マネージャー", layout="centered")
init_db()

st.markdown("""
<style>
    /* 全体背景 & タイポグラフィ */
    .stApp {
        background-color: #F7F8FA;
        font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Yu Gothic", sans-serif;
        color: #111111;
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 4rem;
        max-width: 680px;
    }

    /* LINE風 ヘッダー */
    .line-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 8px 4px 16px 4px;
        border-bottom: 1px solid #ECEEF0;
        margin-bottom: 16px;
    }
    .line-header-title {
        font-size: 22px;
        font-weight: 800;
        color: #111111;
        letter-spacing: -0.5px;
    }
    .line-header-badge {
        background-color: #06C755;
        color: #FFFFFF;
        font-size: 11px;
        font-weight: 700;
        padding: 4px 10px;
        border-radius: 20px;
    }

    /* タブバー（LINEのセグメントスイッチ風） */
    .stTabs [data-baseweb="tab-list"] {
        background-color: #ECEEF2;
        padding: 3px;
        border-radius: 12px;
        gap: 3px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 9px;
        padding: 8px 14px;
        font-weight: 700;
        font-size: 13px;
        color: #8E9297;
        background-color: transparent;
        border: none;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFFFFF !important;
        color: #111111 !important;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
    }

    /* メトリックカード（LINE Pay / ウォレット風の洗練された数値ボックス） */
    .metrics-container {
        display: flex;
        gap: 10px;
        margin-bottom: 18px;
    }
    .metric-card {
        flex: 1;
        background: #FFFFFF;
        border: 1px solid #EBECEF;
        border-radius: 16px;
        padding: 12px 14px;
        text-align: center;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
    }
    .metric-label {
        font-size: 11px;
        font-weight: 600;
        color: #8E9297;
        margin-bottom: 4px;
    }
    .metric-value {
        font-size: 18px;
        font-weight: 800;
        color: #111111;
    }
    .metric-highlight {
        color: #06C755;
    }

    /* LINE トークルーム一覧風 リストカード */
    .talk-item {
        background: #FFFFFF;
        border: 1px solid #ECEEF0;
        border-radius: 16px;
        padding: 14px 16px;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        transition: transform 0.1s ease, box-shadow 0.1s ease;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
    }
    .talk-item:hover {
        border-color: #DDE0E5;
        box-shadow: 0 3px 8px rgba(0, 0, 0, 0.05);
    }

    /* アイコンバッジ（正答率） */
    .avatar-badge {
        width: 48px;
        height: 48px;
        border-radius: 16px;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        font-size: 13px;
        font-weight: 800;
        margin-right: 14px;
        flex-shrink: 0;
    }
    .badge-high {
        background-color: #E8F9EE;
        color: #06C755;
    }
    .badge-mid {
        background-color: #FFF6E5;
        color: #FF9500;
    }
    .badge-low {
        background-color: #FFEBEF;
        color: #FF334B;
    }
    .badge-none {
        background-color: #F0F1F3;
        color: #8E9297;
    }
    .avatar-label {
        font-size: 9px;
        font-weight: 600;
        margin-top: -2px;
    }

    /* トーク内容（中央） */
    .talk-main {
        flex: 1;
        min-width: 0;
    }
    .talk-title-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 4px;
    }
    .talk-title {
        font-size: 15px;
        font-weight: 700;
        color: #111111;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        padding-right: 8px;
    }
    .talk-time {
        font-size: 11px;
        color: #9E9E9E;
        font-weight: 500;
        white-space: nowrap;
    }
    .talk-tags {
        display: flex;
        align-items: center;
        gap: 6px;
        flex-wrap: wrap;
    }
    .tag-pill {
        background-color: #F2F3F5;
        color: #4A4D52;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 6px;
    }
    .tag-sub {
        font-size: 11px;
        color: #8E9297;
    }

    /* 未読風バッジ（要復習アラート） */
    .review-alert {
        background-color: #FF334B;
        color: #FFFFFF;
        font-size: 10px;
        font-weight: 700;
        padding: 2px 7px;
        border-radius: 10px;
        margin-left: 6px;
    }

    /* LINE Green ボタン */
    .stButton > button {
        background-color: #06C755;
        color: #FFFFFF;
        border: none;
        border-radius: 12px;
        font-weight: 700;
        font-size: 15px;
        padding: 12px 20px;
        width: 100%;
        transition: background-color 0.15s ease;
    }
    .stButton > button:hover {
        background-color: #05B34C;
        color: #FFFFFF;
    }
    .stButton > button:active {
        background-color: #049B41;
        transform: scale(0.99);
    }

    /* フォームパーツのモダン化 */
    div[data-baseweb="select"], input, textarea {
        border-radius: 10px !important;
        border-color: #E2E4E8 !important;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# アプリケーションヘッダー
# -----------------------------------------------------------------------------
st.markdown("""
<div class="line-header">
    <div class="line-header-title">演習ノート</div>
    <div class="line-header-badge">Study LINE</div>
</div>
""", unsafe_allow_html=True)

tab_talks, tab_record, tab_settings = st.tabs(["💬 問題一覧", "✏️ 記録する", "⚙️ 設定"])

# -----------------------------------------------------------------------------
# タブ 1: LINEトーク風 問題一覧
# -----------------------------------------------------------------------------
with tab_talks:
    data = fetch_aggregated_data()

    if data.empty:
        st.info("まだ問題が登録されていません。「設定」タブから新しい問題を追加してください。")
    else:
        # 上部サマリー（メトリックカード）
        total_p = len(data)
        done_p = len(data[data["total_attempts"] > 0])
        avg_p = data["accuracy"].dropna().mean()
        avg_text = f"{avg_p:.0f}%" if pd.notna(avg_p) else "-"

        st.markdown(f"""
        <div class="metrics-container">
            <div class="metric-card">
                <div class="metric-label">全問題</div>
                <div class="metric-value">{total_p}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">着手済み</div>
                <div class="metric-value metric-highlight">{done_p}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">平均正答率</div>
                <div class="metric-value">{avg_text}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # 絞り込み & 並び替え
        col_s, col_sort = st.columns([1, 1])
        with col_s:
            sub_filter = st.selectbox(
                "科目フィルター",
                ["すべて"] + sorted(list(data["subject"].unique())),
                label_visibility="collapsed"
            )
        with col_sort:
            sort_opt = st.selectbox(
                "並び替え",
                ["復習優先（経過日数順）", "弱点優先（正答率順）", "科目・単元順"],
                label_visibility="collapsed"
            )

        # フィルタ適用
        filtered = data.copy()
        if sub_filter != "すべて":
            filtered = filtered[filtered["subject"] == sub_filter]

        # ソート適用
        if sort_opt == "復習優先（経過日数順）":
            filtered = filtered.sort_values(by="elapsed_days", ascending=False, na_position="first")
        elif sort_opt == "弱点優先（正答率順）":
            filtered = filtered.sort_values(by="accuracy", ascending=True, na_position="last")
        elif sort_opt == "科目・単元順":
            filtered = filtered.sort_values(by=["subject", "unit", "problem_id"])

        # トークリスト生成
        cards_html = ""
        for _, r in filtered.iterrows():
            # 正答率とアイコンスタイル判定
            if pd.isna(r["accuracy"]):
                badge_class = "badge-none"
                badge_val = "-"
                badge_lbl = "未実施"
            elif r["accuracy"] >= 80:
                badge_class = "badge-high"
                badge_val = f"{int(r['accuracy'])}%"
                badge_lbl = "得意"
            elif r["accuracy"] >= 50:
                badge_class = "badge-mid"
                badge_val = f"{int(r['accuracy'])}%"
                badge_lbl = "要復習"
            else:
                badge_class = "badge-low"
                badge_val = f"{int(r['accuracy'])}%"
                badge_lbl = "苦手"

            # 経過日数テキスト & 要復習バッジ
            if pd.isna(r["elapsed_days"]):
                time_text = "未着手"
                alert_html = '<span class="review-alert">NEW</span>'
            elif r["elapsed_days"] == 0:
                time_text = "今日"
                alert_html = ""
            elif r["elapsed_days"] >= 7:
                time_text = f"{int(r['elapsed_days'])}日前"
                alert_html = '<span class="review-alert">要復習</span>'
            else:
                time_text = f"{int(r['elapsed_days'])}日前"
                alert_html = ""

            title_safe = html.escape(str(r["title"]))
            sub_safe = html.escape(str(r["subject"]))
            unit_safe = html.escape(str(r["unit"]))
            attempts_text = f"{r['total_attempts']}回実施" if r["total_attempts"] > 0 else "演習なし"

            cards_html += f"""
            <div class="talk-item">
                <div class="avatar-badge {badge_class}">
                    <span>{badge_val}</span>
                    <span class="avatar-label">{badge_lbl}</span>
                </div>
                <div class="talk-main">
                    <div class="talk-title-row">
                        <span class="talk-title">{title_safe}</span>
                        <div>
                            <span class="talk-time">{time_text}</span>
                            {alert_html}
                        </div>
                    </div>
                    <div class="talk-tags">
                        <span class="tag-pill">{sub_safe}</span>
                        <span class="tag-sub">{unit_safe}</span>
                        <span class="tag-sub">・</span>
                        <span class="tag-sub">{attempts_text}</span>
                    </div>
                </div>
            </div>
            """

        st.markdown(cards_html, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# タブ 2: 演習の記録
# -----------------------------------------------------------------------------
with tab_record:
    st.subheader("解いた問題を記録")
    with get_connection() as conn:
        problems_df = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

    if problems_df.empty:
        st.warning("先に問題を追加してください。")
    else:
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
            result_str = st.radio("判定", ["正解 (◯)", "不正解 (✕)"], horizontal=True)

        memo_val = st.text_input("復習メモ（任意）", placeholder="解法のポイントや間違えた理由")

        st.write("")
        if st.button("記録を保存する"):
            is_correct_val = 1 if result_str == "正解 (◯)" else 0
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO attempts (problem_id, attempt_date, is_correct, memo) VALUES (?, ?, ?, ?)",
                    (selected_problem_id, attempt_date_val.strftime("%Y-%m-%d"), is_correct_val, memo_val)
                )
                conn.commit()
            st.success("演習結果を保存しました！")
            st.rerun()

# -----------------------------------------------------------------------------
# タブ 3: 設定・管理（マスタ追加・編集・削除）
# -----------------------------------------------------------------------------
with tab_settings:
    sub_action = st.radio(
        "設定項目",
        ["問題の追加", "履歴の修正・削除", "問題の修正・削除"],
        horizontal=True
    )
    st.write("---")

    if sub_action == "問題の追加":
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT subject FROM problems;")
            existing_subjects = [row[0] for row in cursor.fetchall()]

        new_id = st.text_input("問題ID", placeholder="例: EM-001")
        sub_mode = st.radio("科目の指定", ["既存から選択", "新規入力"], horizontal=True)
        if sub_mode == "既存から選択" and existing_subjects:
            new_subject = st.selectbox("既存の科目", existing_subjects)
        else:
            new_subject = st.text_input("科目名", placeholder="例: 電磁気学")

        new_unit = st.text_input("単元名", placeholder="例: ガウスの法則")
        new_title = st.text_input("問題名", placeholder="例: 球対称電荷の電界")

        if st.button("この問題を登録する"):
            if new_id and new_subject and new_unit and new_title:
                try:
                    with get_connection() as conn:
                        conn.execute(
                            "INSERT INTO problems (problem_id, subject, unit, title) VALUES (?, ?, ?, ?)",
                            (new_id.strip(), new_subject.strip(), new_unit.strip(), new_title.strip())
                        )
                        conn.commit()
                    st.success(f"問題 [{new_id}] を登録しました。")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("その問題IDは既に存在しています。")
            else:
                st.error("すべての必須項目を入力してください。")

    elif sub_action == "履歴の修正・削除":
        with get_connection() as conn:
            attempts_raw = pd.read_sql_query("""
                SELECT a.attempt_id, a.attempt_date, a.problem_id, p.title, a.is_correct, a.memo
                FROM attempts a
                JOIN problems p ON a.problem_id = p.problem_id
                ORDER BY a.attempt_date DESC, a.attempt_id DESC;
            """, conn)

        if attempts_raw.empty:
            st.info("修正可能な履歴がありません。")
        else:
            attempt_choices = {
                f"ID:{row['attempt_id']} | {row['attempt_date']} | [{row['problem_id']}] {row['title']}": row['attempt_id']
                for _, row in attempts_raw.iterrows()
            }
            selected_att_label = st.selectbox("修正する履歴を選択", list(attempt_choices.keys()))
            selected_att_id = attempt_choices[selected_att_label]
            target_row = attempts_raw[attempts_raw["attempt_id"] == selected_att_id].iloc[0]

            edit_date = st.date_input(
                "日付の変更",
                value=datetime.strptime(target_row["attempt_date"], "%Y-%m-%d").date()
            )
            edit_result = st.radio(
                "結果の変更",
                ["正解 (◯)", "不正解 (✕)"],
                index=0 if target_row["is_correct"] == 1 else 1,
                horizontal=True
            )
            edit_memo = st.text_input("メモの変更", value=target_row["memo"] or "")

            c_save, c_del = st.columns(2)
            if c_save.button("変更を保存"):
                with get_connection() as conn:
                    conn.execute("""
                        UPDATE attempts
                        SET attempt_date = ?, is_correct = ?, memo = ?
                        WHERE attempt_id = ?
                    """, (edit_date.strftime("%Y-%m-%d"), 1 if edit_result == "正解 (◯)" else 0, edit_memo, selected_att_id))
                    conn.commit()
                st.success("履歴を更新しました。")
                st.rerun()

            if c_del.button("この履歴を削除"):
                with get_connection() as conn:
                    conn.execute("DELETE FROM attempts WHERE attempt_id = ?", (selected_att_id,))
                    conn.commit()
                st.warning("履歴を削除しました。")
                st.rerun()

    elif sub_action == "問題の修正・削除":
        with get_connection() as conn:
            problems_raw = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

        if problems_raw.empty:
            st.info("登録済みの問題がありません。")
        else:
            p_choices = {
                f"[{row['problem_id']}] {row['subject']} - {row['title']}": row['problem_id']
                for _, row in problems_raw.iterrows()
            }
            selected_p_label = st.selectbox("修正する問題を選択", list(p_choices.keys()))
            selected_p_id = p_choices[selected_p_label]
            target_p = problems_raw[problems_raw["problem_id"] == selected_p_id].iloc[0]

            edit_subject = st.text_input("科目名", value=target_p["subject"])
            edit_unit = st.text_input("単元名", value=target_p["unit"])
            edit_title = st.text_input("問題名", value=target_p["title"])

            cp_save, cp_del = st.columns(2)
            if cp_save.button("問題情報を更新"):
                with get_connection() as conn:
                    conn.execute("""
                        UPDATE problems
                        SET subject = ?, unit = ?, title = ?
                        WHERE problem_id = ?
                    """, (edit_subject.strip(), edit_unit.strip(), edit_title.strip(), selected_p_id))
                    conn.commit()
                st.success("問題情報を更新しました。")
                st.rerun()

            if cp_del.button("この問題を削除"):
                with get_connection() as conn:
                    conn.execute("DELETE FROM problems WHERE problem_id = ?", (selected_p_id,))
                    conn.commit()
                st.warning(f"問題 [{selected_p_id}] を削除しました。")
                st.rerun()
