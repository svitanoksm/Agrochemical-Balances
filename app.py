```python
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
# 2. НОРМАЛІЗАЦІЯ НАЗВ ПРЕПАРАТІВ
# ============================================================

def clean_name(val):

    if pd.isna(val):
        return ""

    text = str(val).upper().strip()

    # Заміна нерозривних пробілів
    text = text.replace('\xa0', ' ')

    # Видалення реєстраційних символів
    text = re.sub(r'[®™©]', '', text)

    # Видалення зайвих пробілів
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


# ============================================================
# 3. ПЕРЕТВОРЕННЯ ЧИСЛОВИХ ДАНИХ
# ============================================================

def convert_numeric(series):

    series = series.astype(str).str.strip()

    # Підтримка десяткової коми
    series = series.str.replace(',', '.', regex=False)

    return pd.to_numeric(
        series,
        errors='coerce'
    ).fillna(0)


# ============================================================
# 4. ЗАВАНТАЖЕННЯ ТА ОБРОБКА ДАНИХ
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

        creds_dict = dict(
            st.secrets["gcp_service_account"]
        )

        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=scope
        )

        gc = gspread.authorize(creds)

        # ID таблиці
        MAIN_SHEET_ID = "1QUh9y-FL_qiYMCRAko8KLxUKjdAdlF63jukcLu45djc"

        # Назви аркушів
        SHEET_NAME_WH = "Рух_по_складам_Агроному"
        SHEET_NAME_FIELD = "ЛМТ"

        spreadsheet = gc.open_by_key(
            MAIN_SHEET_ID
        )

        # ----------------------------------------------------
        # ЗЧИТУВАННЯ ДАНИХ
        # ----------------------------------------------------

        df_wh = pd.DataFrame(
            spreadsheet.worksheet(
                SHEET_NAME_WH
            ).get_all_records()
        )

        df_field = pd.DataFrame(
            spreadsheet.worksheet(
                SHEET_NAME_FIELD
            ).get_all_records()
        )

        # ----------------------------------------------------
        # НАЗВИ КОЛОНОК
        # ----------------------------------------------------

        # Аркуш складу
        wh_name_col = 'Номенклатура'
        wh_issued_col = 'Видано_зі_складу'
        wh_return_col = 'Повернення_в_склад'

        # Аркуш ЛМТ
        field_name_col = 'Найменування_добрив_ЗЗР_сорт_насіння'

        field_amount_col = (
            'Факт_внесення_на_поле_Добрива_ЗЗР_Насіння_(л_або_т)'
        )

        # ----------------------------------------------------
        # ПЕРЕВІРКА НАЯВНОСТІ КОЛОНОК
        # ----------------------------------------------------

        required_wh = [
            wh_name_col,
            wh_issued_col,
            wh_return_col
        ]

        required_field = [
            field_name_col,
            field_amount_col
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
                f"На аркуші складу відсутні колонки: {missing_wh}"
            )

        if missing_field:
            raise ValueError(
                f"На аркуші ЛМТ відсутні колонки: {missing_field}"
            )

        # ----------------------------------------------------
        # ОБРОБКА ЧИСЛОВИХ ДАНИХ
        # ----------------------------------------------------

        df_wh[wh_issued_col] = convert_numeric(
            df_wh[wh_issued_col]
        )

        df_wh[wh_return_col] = convert_numeric(
            df_wh[wh_return_col]
        )

        df_field[field_amount_col] = convert_numeric(
            df_field[field_amount_col]
        )

        # ----------------------------------------------------
        # НОРМАЛІЗАЦІЯ НАЗВ
        # ----------------------------------------------------

        df_wh['Clean_Name'] = df_wh[
            wh_name_col
        ].apply(clean_name)

        df_field['Clean_Name'] = df_field[
            field_name_col
        ].apply(clean_name)

        # Видалення порожніх назв
        df_wh = df_wh[
            df_wh['Clean_Name'] != ""
        ].copy()

        df_field = df_field[
            df_field['Clean_Name'] != ""
        ].copy()

        # ----------------------------------------------------
        # ГРУПУВАННЯ ДАНИХ СКЛАДУ
        # ----------------------------------------------------

        wh_grouped = df_wh.groupby(
            'Clean_Name',
            as_index=False
        )[
            [wh_issued_col, wh_return_col]
        ].sum()

        wh_grouped.rename(
            columns={
                wh_issued_col: 'Видано_зі_складу',
                wh_return_col: 'Повернення_в_склад'
            },
            inplace=True
        )

        # ----------------------------------------------------
        # ГРУПУВАННЯ ДАНИХ ЛМТ
        # ----------------------------------------------------

        field_grouped = df_field.groupby(
            'Clean_Name',
            as_index=False
        )[field_amount_col].sum()

        field_grouped.rename(
            columns={
                field_amount_col: 'Внесено'
            },
            inplace=True
        )

        # ----------------------------------------------------
        # ФОРМУВАННЯ НАЗВ ДЛЯ ВІДОБРАЖЕННЯ
        # ----------------------------------------------------

        name_mapping = {}

        for _, row in df_wh.iterrows():

            key = row['Clean_Name']

            if key not in name_mapping:
                name_mapping[key] = row[wh_name_col]

        for _, row in df_field.iterrows():

            key = row['Clean_Name']

            if key not in name_mapping:
                name_mapping[key] = row[field_name_col]

        # ----------------------------------------------------
        # ОБ'ЄДНАННЯ ДВОХ АРКУШІВ
        # ----------------------------------------------------

        merged = pd.merge(
            wh_grouped,
            field_grouped,
            on='Clean_Name',
            how='outer'
        )

        # Відсутні значення замінюємо нулями
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
        # ВІДНОВЛЕННЯ НАЗВ ПРЕПАРАТІВ
        # ----------------------------------------------------

        merged['Препарат'] = merged[
            'Clean_Name'
        ].map(name_mapping)

        # ----------------------------------------------------
        # РОЗРАХУНОК ЗАЛИШКІВ
        # ----------------------------------------------------

        merged['Залишок'] = (
            merged['Видано_зі_складу']
            - merged['Повернення_в_склад']
            - merged['Внесено']
        )

        # ----------------------------------------------------
        # ФОРМУВАННЯ РЕЗУЛЬТАТІВ
        # ----------------------------------------------------

        # Позитивні залишки
        active_rests = merged[
            merged['Залишок'] > 0.01
        ].copy()

        # Від'ємні залишки для контролю
        negative_rests = merged[
            merged['Залишок'] < -0.01
        ].copy()

        # Номенклатура, яка є тільки на одному аркуші
        unmatched_names = sorted(
            set(wh_grouped['Clean_Name'])
            .symmetric_difference(
                set(field_grouped['Clean_Name'])
            )
        )

        return (
            active_rests,
            negative_rests,
            unmatched_names,
            merged,
            None
        )

    except Exception as e:

        return None, None, None, None, str(e)


# ============================================================
# 5. ВЕРХНЯ ПАНЕЛЬ
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

    if st.button(
        "🔄 Оновити дані",
        type="primary"
    ):

        st.cache_data.clear()
        st.rerun()


st.divider()


# ============================================================
# 6. ОСНОВНИЙ ДАШБОРД
# ============================================================

st.markdown(
    "## 📊 Залишок ТМЦ на руках"
)

st.caption(
    "Видано зі складу − Повернення в склад − Фактичне внесення на поле"
)

(
    df_active,
    df_negative,
    unmatched_names,
    df_all,
    error_msg
) = load_and_process_data()


if error_msg:

    st.error(
        f"Помилка завантаження даних: {error_msg}"
    )

    st.info(
        "Перевірте назви аркушів, доступ сервісного акаунта "
        "та відповідність назв колонок Google Таблиці."
    )

else:

    # --------------------------------------------------------
    # ОСНОВНА ТАБЛИЦЯ ЗАЛИШКІВ
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
    # ВІД'ЄМНІ ЗАЛИШКИ
    # --------------------------------------------------------

    with st.expander(
        "🔴 Контроль від'ємних залишків"
    ):

        if df_negative.empty:

            st.success(
                "Від'ємних залишків немає."
            )

        else:

            negative_display = df_negative[
                [
                    'Препарат',
                    'Видано_зі_складу',
                    'Повернення_в_склад',
                    'Внесено',
                    'Залишок'
                ]
            ].copy()

            st.dataframe(
                negative_display,
                use_container_width=True,
                hide_index=True
            )

    # --------------------------------------------------------
    # КОНТРОЛЬ НЕЗБІГУ НОМЕНКЛАТУРИ
    # --------------------------------------------------------

    with st.expander(
        "⚠️ Номенклатура, яка є тільки на одному аркуші"
    ):

        if not unmatched_names:

            st.success(
                "Уся номенклатура присутня на обох аркушах."
            )

        else:

            st.warning(
                f"Знайдено позицій без відповідності: {len(unmatched_names)}"
            )

            st.dataframe(
                pd.DataFrame({
                    'Номенклатура': unmatched_names
                }),
                use_container_width=True,
                hide_index=True
            )

    # --------------------------------------------------------
    # ЗАГАЛЬНИЙ КОНТРОЛЬНИЙ ПІДСУМОК
    # --------------------------------------------------------

    with st.expander(
        "📊 Загальний контроль розрахунків"
    ):

        total_issued = df_all[
            'Видано_зі_складу'
        ].sum()

        total_returned = df_all[
            'Повернення_в_склад'
        ].sum()

        total_used = df_all[
            'Внесено'
        ].sum()

        total_balance = df_all[
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
```
