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
        # 問題マスタテーブル (problems)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS problems (
                problem_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                unit TEXT NOT NULL,
                title TEXT NOT NULL
            );
        """)
        # 演習履歴テーブル (attempts)
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

    # 派生指標の計算（Derived Metrics Calculation）
    today = date.today()

    # 正答率（Accuracy Rate [%]）
    df["正答率(%)"] = df.apply(
        lambda row: round((row["正解数"] / row["演習回数"]) * 100, 1) if row["演習回数"] > 0 else None,
        axis=1
    )

    # 経過日数（Elapsed Days: Δt）
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

# サイドバー: データ入力（Side Navigation）
st.sidebar.header("データ登録")
action = st.sidebar.radio("操作を選択", ["演習の記録", "問題マスタの追加"])

with get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT subject FROM problems;")
    existing_subjects = [row[0] for row in cursor.fetchall()]

# 1. 演習ログの登録
if action == "演習の記録":
    st.sidebar.subheader("演習結果の記録")
    with get_connection() as conn:
        problems_df = pd.read_sql_query("SELECT problem_id, subject, unit, title FROM problems", conn)

    if problems_df.empty:
        st.sidebar.warning("先に問題マスタを登録してください。")
    else:
        # 科目 → 単元 → 問題のカスケード選択（cascading selection）
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
        memo_val = st.sidebar.text_input("メモ（任意: 間違えた要因など）")

        if st.sidebar.button("記録を保存"):
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO attempts (problem_id, attempt_date, is_correct, memo) VALUES (?, ?, ?, ?)",
                    (selected_problem_id, attempt_date_val.strftime("%Y-%m-%d"), is_correct_val, memo_val)
                )
                conn.commit()
            st.sidebar.success("演習ログを保存しました。")
            st.rerun()

# 2. 問題マスタの登録
elif action == "問題マスタの追加":
    st.sidebar.subheader("新規問題の定義")
    new_id = st.sidebar.text_input("問題ID（一意の識別子: 例 EM-001）")

    # 既存科目からの選択または新規入力
    subject_input_mode = st.sidebar.radio("科目の指定", ["既存から選択", "新規入力"])
    if subject_input_mode == "既存から選択" and existing_subjects:
        new_subject = st.sidebar.selectbox("既存科目", existing_subjects)
    else:
        new_subject = st.sidebar.text_input("科目名")

    new_unit = st.sidebar.text_input("単元名（例: ガウスの法則、過渡現象）")
    new_title = st.sidebar.text_input("問題名・表題（例: 同軸円筒導体の電界計算）")

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
                st.sidebar.error("その問題IDは既に存在しています。別の一意なIDを指定してください。")
        else:
            st.sidebar.error("すべての項目を入力してください。")

# -----------------------------------------------------------------------------
# メイン画面: フィルタリング・ソート・データ表示
# -----------------------------------------------------------------------------
data = fetch_aggregated_data()

if data.empty:
    st.info("登録されている問題がありません。左のサイドバーから問題マスタを追加してください。")
else:
    # フィルタリング（Filtering）
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

    # フィルタ適用
    view_df = data.copy()
    if filter_sub != "全科目":
        view_df = view_df[view_df["科目"] == filter_sub]
    if filter_unit != "全単元":
        view_df = view_df[view_df["単元"] == filter_unit]

    # ソート適用（Sorting Logic）
    if sort_target == "科目・単元順":
        view_df = view_df.sort_values(by=["科目", "単元", "問題ID"])
    elif sort_target == "経過日数が長い順（復習優先）":
        # 実施履歴のない問題（NaN）を先頭（最も復習が必要）に配置
        view_df = view_df.sort_values(by="経過日数(日)", ascending=False, na_position="first")
    elif sort_target == "正答率が低い順（弱点克服）":
        view_df = view_df.sort_values(by="正答率(%)", ascending=True, na_position="last")
    elif sort_target == "演習回数が少ない順":
        view_df = view_df.sort_values(by="演習回数", ascending=True)

    # 表示レイアウト設定
    st.subheader(f"対象問題一覧 ({len(view_df)} 件)")

    # Streamlit のカラム設定（Column Configuration）で視認性を向上
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
