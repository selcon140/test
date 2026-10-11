import sqlite3
from datetime import date, datetime
import pandas as pd
import streamlit as st

DB_NAME = "study_tracker.db"

# -----------------------------------------------------------------------------
# データベース制御関数（Database Operations）
# -----------------------------------------------------------------------------
def get_connection():
    """データベース接続（database connection）を取得します。"""
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """テーブルの初期化（initialization）を行います。"""
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
    """演習履歴を集計（aggregation）したデータフレームを取得します。"""
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
# アプリケーションUI（Streamlit Interface）
# -----------------------------------------------------------------------------
st.set_page_config(page_title="演習進捗マネージャー", layout="wide")
init_db()

st.title("演習進捗・定着度ダッシュボード")

# サイドバー: 操作選択
st.sidebar.header("メニュー")
action = st.sidebar.radio(
    "操作を選択",
    ["演習の記録", "問題マスタの追加", "演習履歴の管理（編集・削除）", "問題マスタの管理（編集・削除）"]
)

# 1. 演習ログの登録
if action == "演習の記録":
    st.sidebar.subheader("演習結果の記録")
    with get_connection() as conn:
        problems_df = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

    if problems_df.empty:
        st.sidebar.warning("先に問題マスタを登録してください。")
    else:
        selected_subject = st.sidebar.selectbox("科目を選択", problems_df["subject"].unique())
        filtered_units = problems_df[problems_df["subject"] == selected_subject]["unit"].unique()
        selected_unit = st.sidebar.selectbox("単元を選択", filtered_units)

        selectable_problems = problems_df[
            (problems_df["subject"] == selected_subject) & (problems_df["unit"] == selected_unit)
        ]
        problem_options = {
            f"[{row['problem_id']}] {row['title']}": row['problem_id']
            for _, row in selectable_problems.iterrows()
        }
        selected_label = st.sidebar.selectbox("問題を選択", list(problem_options.keys()))
        selected_problem_id = problem_options[selected_label]

        attempt_date_val = st.sidebar.date_input("実施日", value=date.today())
        result_str = st.sidebar.radio("結果", ["正解 (◯)", "不正解 (✕)"])
        is_correct_val = 1 if result_str == "正解 (◯)" else 0
        memo_val = st.sidebar.text_input("メモ（任意）")

        if st.sidebar.button("記録を保存"):
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO attempts (problem_id, attempt_date, is_correct, memo) VALUES (?, ?, ?, ?)",
                    (selected_problem_id, attempt_date_val.strftime("%Y-%m-%d"), is_correct_val, memo_val)
                )
                conn.commit()
            st.sidebar.success("演習ログを保存しました。")
            st.rerun()

# 2. 問題マスタの追加
elif action == "問題マスタの追加":
    st.sidebar.subheader("新規問題の定義")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT subject FROM problems;")
        existing_subjects = [row[0] for row in cursor.fetchall()]

    new_id = st.sidebar.text_input("問題ID（例: EM-001）")
    subject_input_mode = st.sidebar.radio("科目の指定", ["既存から選択", "新規入力"])
    if subject_input_mode == "既存から選択" and existing_subjects:
        new_subject = st.sidebar.selectbox("既存科目", existing_subjects)
    else:
        new_subject = st.sidebar.text_input("科目名")

    new_unit = st.sidebar.text_input("単元名（例: ガウスの法則）")
    new_title = st.sidebar.text_input("問題名（例: 同軸円筒導体の電界計算）")

    if st.sidebar.button("問題を登録"):
        if new_id and new_subject and new_unit and new_title:
            try:
                with get_connection() as conn:
                    conn.execute(
                        "INSERT INTO problems (problem_id, subject, unit, title) VALUES (?, ?, ?, ?)",
                        (new_id.strip(), new_subject.strip(), new_unit.strip(), new_title.strip())
                    )
                    conn.commit()
                st.sidebar.success(f"問題 [{new_id}] を登録しました。")
                st.rerun()
            except sqlite3.IntegrityError:
                st.sidebar.error("その問題IDは既に存在しています。")
        else:
            st.sidebar.error("すべての項目を入力してください。")

# 3. 演習履歴の編集・削除
elif action == "演習履歴の管理（編集・削除）":
    st.sidebar.subheader("演習履歴の修正・削除")
    with get_connection() as conn:
        attempts_raw = pd.read_sql_query("""
            SELECT a.attempt_id, a.attempt_date, a.problem_id, p.title, a.is_correct, a.memo
            FROM attempts a
            JOIN problems p ON a.problem_id = p.problem_id
            ORDER BY a.attempt_date DESC, a.attempt_id DESC;
        """, conn)

    if attempts_raw.empty:
        st.sidebar.info("演習履歴が存在しません。")
    else:
        attempt_choices = {
            f"ID:{row['attempt_id']} | {row['attempt_date']} | [{row['problem_id']}] {row['title']}": row['attempt_id']
            for _, row in attempts_raw.iterrows()
        }
        selected_att_label = st.sidebar.selectbox("対象の履歴を選択", list(attempt_choices.keys()))
        selected_att_id = attempt_choices[selected_att_label]
        target_row = attempts_raw[attempts_raw["attempt_id"] == selected_att_id].iloc[0]

        edit_date = st.sidebar.date_input(
            "実施日を変更",
            value=datetime.strptime(target_row["attempt_date"], "%Y-%m-%d").date()
        )
        edit_result = st.sidebar.radio(
            "結果を変更",
            ["正解 (◯)", "不正解 (✕)"],
            index=0 if target_row["is_correct"] == 1 else 1
        )
        edit_memo = st.sidebar.text_input("メモを変更", value=target_row["memo"] or "")

        col_up, col_del = st.sidebar.columns(2)
        if col_up.button("変更を保存"):
            with get_connection() as conn:
                conn.execute("""
                    UPDATE attempts
                    SET attempt_date = ?, is_correct = ?, memo = ?
                    WHERE attempt_id = ?
                """, (edit_date.strftime("%Y-%m-%d"), 1 if edit_result == "正解 (◯)" else 0, edit_memo, selected_att_id))
                conn.commit()
            st.sidebar.success("履歴を更新しました。")
            st.rerun()

        if col_del.button("この履歴を削除", type="primary"):
            with get_connection() as conn:
                conn.execute("DELETE FROM attempts WHERE attempt_id = ?", (selected_att_id,))
                conn.commit()
            st.sidebar.warning("履歴を削除しました。")
            st.rerun()

# 4. 問題マスタの編集・削除
elif action == "問題マスタの管理（編集・削除）":
    st.sidebar.subheader("問題マスタの修正・削除")
    with get_connection() as conn:
        problems_raw = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

    if problems_raw.empty:
        st.sidebar.info("登録済みの問題がありません。")
    else:
        p_choices = {
            f"[{row['problem_id']}] {row['subject']} - {row['title']}": row['problem_id']
            for _, row in problems_raw.iterrows()
        }
        selected_p_label = st.sidebar.selectbox("対象問題を選択", list(p_choices.keys()))
        selected_p_id = p_choices[selected_p_label]
        target_p = problems_raw[problems_raw["problem_id"] == selected_p_id].iloc[0]

        edit_subject = st.sidebar.text_input("科目名", value=target_p["subject"])
        edit_unit = st.sidebar.text_input("単元名", value=target_p["unit"])
        edit_title = st.sidebar.text_input("問題名", value=target_p["title"])

        col_p_up, col_p_del = st.sidebar.columns(2)
        if col_p_up.button("問題情報を更新"):
            with get_connection() as conn:
                conn.execute("""
                    UPDATE problems
                    SET subject = ?, unit = ?, title = ?
                    WHERE problem_id = ?
                """, (edit_subject.strip(), edit_unit.strip(), edit_title.strip(), selected_p_id))
                conn.commit()
            st.sidebar.success("問題情報を更新しました。")
            st.rerun()

        if col_p_del.button("問題を削除", type="primary"):
            with get_connection() as conn:
                # CASCADE制約により、関連する演習履歴も同時に削除されます
                conn.execute("DELETE FROM problems WHERE problem_id = ?", (selected_p_id,))
                conn.commit()
            st.sidebar.warning(f"問題 [{selected_p_id}] および関連履歴を削除しました。")
            st.rerun()

# -----------------------------------------------------------------------------
# メイン画面: フィルタリング・ソート・データ表示
# -----------------------------------------------------------------------------
data = fetch_aggregated_data()

if data.empty:
    st.info("登録されている問題がありません。左のサイドバーから問題マスタを追加してください。")
else:
    col1, col2, col3 = st.columns(3)
    with col1:
        subjects_list = ["全科目"] + sorted(list(data["科目"].unique()))
        filter_sub = st.selectbox("科目フィルタ", subjects_list)

    with col2:
        if filter_sub != "全科目":
            units_list = ["全単元"] + sorted(list(data[data["科目"] == filter_sub]["単元"].unique()))
        else:
            units_list = ["全単元"] + sorted(list(data["単元"].unique()))
        filter_unit = st.selectbox("単元フィルタ", units_list)

    with col3:
        sort_target = st.selectbox(
            "優先ソート条件",
            ["科目・単元順", "経過日数が長い順（復習優先）", "正答率が低い順（弱点克服）", "演習回数が少ない順"]
        )

    view_df = data.copy()
    if filter_sub != "全科目":
        view_df = view_df[view_df["科目"] == filter_sub]
    if filter_unit != "全単元":
        view_df = view_df[view_df["単元"] == filter_unit]

    if sort_target == "科目・単元順":
        view_df = view_df.sort_values(by=["科目", "単元", "問題ID"])
    elif sort_target == "経過日数が長い順（復習優先）":
        view_df = view_df.sort_values(by="経過日数(日)", ascending=False, na_position="first")
    elif sort_target == "正答率が低い順（弱点克服）":
        view_df = view_df.sort_values(by="正答率(%)", ascending=True, na_position="last")
    elif sort_target == "演習回数が少ない順":
        view_df = view_df.sort_values(by="演習回数", ascending=True)

    st.subheader(f"対象問題一覧 ({len(view_df)} 件)")
    st.dataframe(
        view_df,
        column_config={
            "正答率(%)": st.column_config.ProgressColumn(
                "正答率",
                help="過去の全取り組みに対する正解の割合",
                format="%.1f%%",
                min_value=0,
                max_value=100,
            ),
            "経過日数(日)": st.column_config.NumberColumn(
                "最終演習からの経過",
                help="最後に取り組んでからの日数（未実施は空欄）",
                format="%d 日前",
            ),
            "演習回数": st.column_config.NumberColumn(format="%d 回"),
            "正解数": st.column_config.NumberColumn(format="%d 回"),
        },
        hide_index=True,
        use_container_width=True,
    )
