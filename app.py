import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
import re

# 1. Налаштування сторінки
st.set_page_config(
    page_title="Agrochemical Balances",
    page_icon="🌾",
    layout="wide"
)

# 2. Стилізація інтерфейсу
st.markdown("""
    <style>
        .stButton>button { width: 100%; border-radius: 6px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

def clean_name(val):
    """Функція для стандартизації назв: прибираємо спецсимволи, пробіли та переводимо у верхній регістр"""
    if pd.isna(val):
        return ""
    text = str(val).upper().strip()
    # Видаляємо знаки реєстрації типу ®, ™, © та зайві пробіли всередині
    text = re.sub(r'[®™©]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text

# 3. Підключення та завантаження даних із Google Таблиць
@st.cache_data(ttl=30)
def load_and_process_data():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(creds)

        # ID вашої Google Таблиці та назви аркушів
        MAIN_SHEET_ID = "1QUh9y-FL_qiYMCRAko8KLxUKjdAdlF63jukcLu45djc"
        SHEET_NAME_WH = "Рух_по_складам_Агроному"
        SHEET_NAME_FIELD = "ЛМТ"

        spreadsheet = gc.open_by_key(MAIN_SHEET_ID)

        # Зчитування даних з обох аркушів
        df_wh = pd.DataFrame(spreadsheet.worksheet(SHEET_NAME_WH).get_all_records())
        df_field = pd.DataFrame(spreadsheet.worksheet(SHEET_NAME_FIELD).get_all_records())

        # Конвертація числових полів складу
        df_wh['Видано_зі_складу'] = pd.to_numeric(df_wh['Видано_зі_складу'], errors='coerce').fillna(0) if 'Видано_зі_складу' in df_wh.columns else 0
        df_wh['Повернення_в_склад'] = pd.to_numeric(df_wh['Повернення_в_склад'], errors='coerce').fillna(0) if 'Повернення_в_склад' in df_wh.columns else 0

        # Створюємо чистий ключ для групування по складу
        df_wh['Clean_Name'] = df_wh['Номенклатура'].apply(clean_name)
        
        # Зберігаємо оригінальну гарну назву для виведення
        name_mapping = df_wh[['Clean_Name', 'Номенклатура']].drop_duplicates().set_index('Clean_Name')['Номенклатура'].to_dict()

        wh_grouped = df_wh.groupby('Clean_Name', as_index=False)[
            ['Видано_зі_складу', 'Повернення_в_склад']
        ].sum()

        # Конвертація та агрегація фактичного внесення з аркуша ЛМТ
        field_col = 'Факт_внесення_на_поле_Добрива_ЗЗР_Насіння_(л_або_т)'
        if field_col in df_field.columns:
            df_field[field_col] = pd.to_numeric(df_field[field_col], errors='coerce').fillna(0)
        else:
            df_field[field_col] = 0

        df_field['Clean_Name'] = df_field['Номенклатура'].apply(clean_name)
        
        # Зберігаємо також мапінг назв з ЛМТ на випадок, якщо номенклатури немає на складі, але є в полі
        field_name_mapping = df_field[['Clean_Name', 'Номенклатура']].drop_duplicates().set_index('Clean_Name')['Номенклатура'].to_dict()
        name_mapping.update(field_name_mapping)

        field_grouped = df_field.groupby('Clean_Name', as_index=False)[field_col].sum()
        field_grouped.rename(columns={field_col: 'Внесено'}, inplace=True)

        # Об'єднання даних по стандартизованому ключу (Clean_Name)
        merged = pd.merge(wh_grouped, field_grouped, on='Clean_Name', how='outer')
        merged['Видано_зі_складу'] = merged['Видано_зі_складу'].fillna(0)
        merged['Повернення_в_склад'] = merged['Повернення_в_склад'].fillna(0)
        merged['Внесено'] = merged['Внесено'].fillna(0)

        # Повертаємо нормальнучитану назву препарату
        merged['Препарат'] = merged['Clean_Name'].map(name_mapping)

        # Формула розрахунку залишку: Видано - Повернення - Внесено
        merged['Залишок'] = merged['Видано_зі_складу'] - merged['Повернення_в_склад'] - merged['Внесено']

        # Фільтруємо позиції, де залишок > 0 (з урахуванням похибки)
        active_rests = merged[merged['Залишок'] > 0.01].copy()

        return active_rests, None
    except Exception as e:
        return None, str(e)

# --------------------------------------------------------
# ВЕРХНЯ ПАНЕЛЬ: Дата ліворуч, Кнопка оновлення праворуч
# --------------------------------------------------------
col_date, col_btn = st.columns([5, 1])

with col_date:
    current_time = datetime.now().strftime("%d.%m.%Y | %H:%M:%S")
    st.markdown(f"### 📅 Дата оновлення: `{current_time}`")

with col_btn:
    if st.button("🔄 Оновити дані", type="primary"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# --------------------------------------------------------
# ОСНОВНИЙ БЛОК ДАШБОРДУ
# --------------------------------------------------------
st.markdown("## 📊 Залишок ТМЦ на руках (Видано зі складу - Повернення - Внесено)")

df_active, error_msg = load_and_process_data()

if error_msg:
    st.error(f"Помилка завантаження даних: {error_msg}")
    st.info("Перевірте назви аркушів, доступ сервісного акаунта та відповідність колонок у таблиці.")
else:
    if df_active.empty:
        st.success("🎉 Усі ТМЦ повністю зписані або використані! Залишків на руках немає.")
    else:
        # Сортуємо за об'ємом залишку
        display_df = df_active[['Препарат', 'Залишок']].copy()
        display_df.columns = ['Назва препарату / ТМЦ', 'Залишок на руках']
        display_df = display_df.sort_values(by='Загальний залишок' if 'Загальний залишок' in display_df.columns else 'Залишок на руках', ascending=False)

        # Виводимо зведену таблицю
        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
