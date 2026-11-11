import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
import re

# ============================================================
# 1. НАЛАШТУВАННЯ СТОРІНКИ
# ============================================================

st.set_page_config(
    page_title="Agrochemical Balances",
    page_icon="🌾",
    layout="wide"
)

st.markdown("""
    <style>
        .stButton>button {
            width: 100%;
            border-radius: 6px;
            font-weight: bold;
        }
    </style>
""", unsafe_allow_html=True)


# ============================================================
# 2. НОРМАЛІЗАЦІЯ НАЗВ
# ============================================================

def clean_name(val):

    if pd.isna(val):
        return ""

    text = str(val).upper().strip()

    # Нерозривні пробіли замінюємо звичайними
    text = text.replace('\xa0', ' ')

    # Прибираємо реєстраційні символи
    text = re.sub(r'[®™©]', '', text)

    # Прибираємо зайві пробіли
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


# ============================================================
# 3. ЗАВАНТАЖЕННЯ ТА ОБРОБКА ДАНИХ
# ============================================================

@st.cache_data(ttl=30)
def load_and_process_data():

    try:

        # ----------------------------------------------------
        # ПІДКЛЮЧЕННЯ GOOGLE SHEETS
        # ----------------------------------------------------

        scope = [
            "https://www.googleapis.com/auth/spreadsheets.readonly"
        ]

        creds_dict = dict(st.secrets["gcp_service_account"])

        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=scope
        )

        gc = gspread.authorize(creds)

        MAIN_SHEET_ID = "1QUh9y-FL_qiYMCRAko8KLxUKjdAdlF63jukcLu45djc"

        SHEET_NAME_WH = "Рух_по_складам_Агроному"
        SHEET_NAME_FIELD = "ЛМТ"

        spreadsheet = gc.open_by_key(MAIN_SHEET_ID)

        # ----------------------------------------------------
        # ЗЧИТУВАННЯ ДАНИХ
        # ----------------------------------------------------

        df_wh = pd.DataFrame(
            spreadsheet.worksheet(SHEET_NAME_WH).get_all_records()
        )

        df_field = pd.DataFrame(
            spreadsheet.worksheet(SHEET_NAME_FIELD).get_all_records()
        )

        # ----------------------------------------------------
        # ПЕРЕВІРКА ОБОВ'ЯЗКОВИХ КОЛОНОК
        # ----------------------------------------------------

        required_wh = [
            'Номенклатура',
            'Видано_зі_складу',
            'Повернення_в_склад'
        ]

        required_field = [
            'Номенклатура',
            'Факт_внесення_на_поле_Добрива_ЗЗР_Насіння_(л_або_т)'
        ]

        missing_wh = [
            col for col in required_wh
            if col not in df_wh.columns
        ]

        missing_field = [
            col for col in required_field
            if col not in df_field.columns
        ]

        if missing_wh:
            raise ValueError(
                f"Відсутні колонки на аркуші складу: {missing_wh}"
            )

        if missing_field:
            raise ValueError(
                f"Відсутні колонки на аркуші ЛМТ: {missing_field}"
            )

        # ----------------------------------------------------
        # ПЕРЕТВОРЕННЯ ЧИСЛОВИХ ДАНИХ
        # ----------------------------------------------------

        def convert_numeric(series):

            # Підтримка десяткової коми
            series = series.astype(str).str.replace(
                ',', '.', regex=False
            )

            return pd.to_numeric(
                series,
                errors='coerce'
            ).fillna(0)

        df_wh['Видано_зі_складу'] = convert_numeric(
            df_wh['Видано_зі_складу']
        )

        df_wh['Повернення_в_склад'] = convert_numeric(
            df_wh['Повернення_в_склад']
        )

        field_col = (
            'Факт_внесення_на_поле_Добрива_ЗЗР_Насіння_(л_або_т)'
        )

        df_field[field_col] = convert_numeric(
            df_field[field_col]
        )

        # ----------------------------------------------------
        # НОРМАЛІЗАЦІЯ НОМЕНКЛАТУРИ
        # ----------------------------------------------------

        df_wh['Clean_Name'] = df_wh['Номенклатура'].apply(
            clean_name
        )

        df_field['Clean_Name'] = df_field['Номенклатура'].apply(
            clean_name
        )

        # Прибираємо порожню номенклатуру
        df_wh = df_wh[df_wh['Clean_Name'] != ""].copy()

        df_field = df_field[
            df_field['Clean_Name'] != ""
        ].copy()

        # ----------------------------------------------------
        # АГРЕГАЦІЯ СКЛАДУ
        # ----------------------------------------------------

        wh_grouped = df_wh.groupby(
            'Clean_Name',
            as_index=False
        )[
            ['Видано_зі_складу', 'Повернення_в_склад']
        ].sum()

        # ----------------------------------------------------
        # АГРЕГАЦІЯ ФАКТИЧНОГО ВНЕСЕННЯ
        # ----------------------------------------------------

        field_grouped = df_field.groupby(
            'Clean_Name',
            as_index=False
        )[field_col].sum()

        field_grouped.rename(
            columns={field_col: 'Внесено'},
            inplace=True
        )

        # ----------------------------------------------------
        # ФОРМУВАННЯ ДОВІДНИКА НАЗВ
        # ----------------------------------------------------

        name_mapping = {}

        for _, row in df_wh.iterrows():

            key = row['Clean_Name']

            if key not in name_mapping:
                name_mapping[key] = row['Номенклатура']

        for _, row in df_field.iterrows():

            key = row['Clean_Name']

            if key not in name_mapping:
                name_mapping[key] = row['Номенклатура']

        # ----------------------------------------------------
        # ОБ'ЄДНАННЯ ДАНИХ
        # ----------------------------------------------------

        merged = pd.merge(
            wh_grouped,
            field_grouped,
            on='Clean_Name',
            how='outer',
            indicator=True
        )

        merged['Видано_зі_складу'] = (
            merged['Видано_зі_складу'].fillna(0)
        )

        merged['Повернення_в_склад'] = (
            merged['Повернення_в_склад'].fillna(0)
        )

        merged['Внесено'] = (
            merged['Внесено'].fillna(0)
        )

        # ----------------------------------------------------
        # РОЗРАХУНОК ЗАЛИШКУ
        # ----------------------------------------------------

        merged['Препарат'] = merged['Clean_Name'].map(
            name_mapping
        )

        merged['Залишок'] = (
            merged['Видано_зі_складу']
            - merged['Повернення_в_склад']
            - merged['Внесено']
        )

        # ----------------------------------------------------
        # ДІАГНОСТИКА АГРІТОКСУ
        # ----------------------------------------------------

        test_name = clean_name("АГРІТОКС®")

        diagnostic = merged[
            merged['Clean_Name'] == test_name
        ].copy()

        # ----------------------------------------------------
        # ФОРМУВАННЯ РЕЗУЛЬТАТІВ
        # ----------------------------------------------------

        active_rests = merged[
            merged['Залишок'] > 0.01
        ].copy()

        negative_rests = merged[
            merged['Залишок'] < -0.01
        ].copy()

        unmatched = merged[
            merged['_merge'] != 'both'
        ].copy()

        return {
            'active': active_rests,
            'negative': negative_rests,
            'merged': merged,
            'diagnostic': diagnostic,
            'unmatched': unmatched,
            'wh_grouped': wh_grouped,
            'field_grouped': field_grouped
        }, None

    except Exception as e:

        return None, str(e)


# ============================================================
# 4. ВЕРХНЯ ПАНЕЛЬ
# ============================================================

col_date, col_btn = st.columns([5, 1])

with col_date:

    current_time = datetime.now().strftime(
        "%d.%m.%Y | %H:%M:%S"
    )

    st.markdown(
        f"### 📅 Дата оновлення: `{current_time}`"
    )

with col_btn:

    if st.button("🔄 Оновити дані", type="primary"):

        st.cache_data.clear()
        st.rerun()

st.divider()


# ============================================================
# 5. ОСНОВНИЙ ДАШБОРД
# ============================================================

st.markdown(
    "## 📊 Залишок ТМЦ на руках"
)

st.caption(
    "Розрахунок: Видано зі складу − Повернення в склад − Фактичне внесення"
)

data, error_msg = load_and_process_data()


if error_msg:

    st.error(
        f"Помилка завантаження даних: {error_msg}"
    )

    st.info(
        "Перевірте Google Sheets, доступ сервісного акаунта "
        "та назви колонок."
    )

else:

    df_active = data['active']

    # --------------------------------------------------------
    # ОСНОВНА ТАБЛИЦЯ
    # --------------------------------------------------------

    if df_active.empty:

        st.success(
            "🎉 Залишків ТМЦ на руках немає."
        )

    else:

        display_df = df_active[
            ['Препарат', 'Залишок']
        ].copy()

        display_df.columns = [
            'Назва препарату / ТМЦ',
            'Залишок на руках'
        ]

        display_df = display_df.sort_values(
            by='Залишок на руках',
            ascending=False
        )

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )

    # --------------------------------------------------------
    # ДІАГНОСТИКА АГРІТОКСУ
    # --------------------------------------------------------

    with st.expander(
        "🔍 Діагностика Агрітоксу",
        expanded=True
    ):

        diagnostic = data['diagnostic']

        if diagnostic.empty:

            st.warning(
                "Агрітокс не знайдений у результатах об'єднання."
            )

        else:

            st.dataframe(
                diagnostic[
                    [
                        'Препарат',
                        'Видано_зі_складу',
                        'Повернення_в_склад',
                        'Внесено',
                        'Залишок',
                        '_merge'
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

        st.caption(
            "Статус об'єднання: both — назва знайдена на обох аркушах; "
            "left_only — тільки склад; right_only — тільки ЛМТ."
        )

    # --------------------------------------------------------
    # ПОЗИЦІЇ З НЕЗБІГОМ НОМЕНКЛАТУРИ
    # --------------------------------------------------------

    with st.expander(
        "⚠️ Номенклатура, яка не збіглася між аркушами"
    ):

        unmatched = data['unmatched']

        if unmatched.empty:

            st.success(
                "Уся номенклатура збігається."
            )

        else:

            st.dataframe(
                unmatched[
                    [
                        'Препарат',
                        'Видано_зі_складу',
                        'Повернення_в_склад',
                        'Внесено',
                        'Залишок',
                        '_merge'
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

    # --------------------------------------------------------
    # ВІД'ЄМНІ ЗАЛИШКИ
    # --------------------------------------------------------

    with st.expander(
        "🔴 Контроль від'ємних залишків"
    ):

        negative = data['negative']

        if negative.empty:

            st.success(
                "Від'ємних залишків немає."
            )

        else:

            st.dataframe(
                negative[
                    [
                        'Препарат',
                        'Видано_зі_складу',
                        'Повернення_в_склад',
                        'Внесено',
                        'Залишок'
                    ]
                ],
                use_container_width=True,
                hide_index=True
            )

    # --------------------------------------------------------
    # КОНТРОЛЬНИЙ ПІДСУМОК
    # --------------------------------------------------------

    with st.expander(
        "📊 Загальний контроль розрахунків"
    ):

        total_issued = data['merged'][
            'Видано_зі_складу'
        ].sum()

        total_returned = data['merged'][
            'Повернення_в_склад'
        ].sum()

        total_used = data['merged'][
            'Внесено'
        ].sum()

        total_balance = data['merged'][
            'Залишок'
        ].sum()

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Видано",
            f"{total_issued:,.2f}"
        )

        col2.metric(
            "Повернуто",
            f"{total_returned:,.2f}"
        )

        col3.metric(
            "Внесено",
            f"{total_used:,.2f}"
        )

        col4.metric(
            "Загальний залишок",
            f"{total_balance:,.2f}"
        )
