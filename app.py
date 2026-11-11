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

st.markdown("""
    <style>
        .stButton>button { width: 100%; border-radius: 6px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

def clean_name(val):
    """Стандартизація назв номенклатури"""
    if pd.isna(val):
        return ""
    text = str(val).upper().strip()
    text = re.sub(r'[®™©]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text

def parse_ukrainian_number(val):
    """Корректне перетворення українських чисел з комами та пробілами у float"""
    if pd.isna(val) or val == "":
        return 0.0
    val_str = str(val).strip()
    # Прибираємо нерозривні та звичайні пробіли (типу "10 500" -> "10500")
    val_str = val_str.replace('\xa0', '').replace(' ', '')
    # Замінюємо кому на крапку для дробових чисел ("69,9" -> "69.9")
    val_str = val_str.replace(',', '.')
    try:
        return float(val_str)
    except ValueError:
        return 0.0

@st.cache_data(ttl=30)
def load_and_process_data():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(creds)

        MAIN_SHEET_ID = "1QUh9y-FL_qiYMCRAko8KLxUKjdAdlF63jukcLu45djc"
        SHEET_NAME_WH = "Рух_по_складам_Агроному"
        SHEET_NAME_FIELD = "ЛМТ"

        spreadsheet = gc.open_by_key(MAIN_SHEET_ID)

        # Зчитування даних
        df_wh = pd.DataFrame(spreadsheet.worksheet(SHEET_NAME_WH).get_all_records())
        df_field = pd.DataFrame(spreadsheet.worksheet(SHEET_NAME_FIELD).get_all_records())

        # 1. ОБРОБКА СКЛАДУ
        df_wh['Видано_зі_складу'] = df_wh['Видано_зі_складу'].apply(parse_ukrainian_number) if 'Видано_зі_складу' in df_wh.columns else 0.0
        df_wh['Повернення_в_склад'] = df_wh['Повернення_в_склад'].apply(parse_ukrainian_number) if 'Повернення_в_склад' in df_wh.columns else 0.0

        # Відкидаємо порожні назви
        df_wh = df_wh[df_wh['Номенклатура'].astype(str).str.strip() != ""]
        df_wh['Clean_Name'] = df_wh['Номенклатура'].apply(clean_name)
        
        name_mapping = df_wh[['Clean_Name', 'Номенклатура']].drop_duplicates().set_index('Clean_Name')['Номенклатура'].to_dict()

        wh_grouped = df_wh.groupby('Clean_Name', as_index=False)[
            ['Видано_зі_складу', 'Повернення_в_склад']
        ].sum()

        # 2. ОБРОБКА ЛМТ
        field_col = 'Факт_внесення_на_поле_Добрива_ЗЗР_Насіння_(л_або_т)'
        name_col_field = 'Найменування_добрив_ЗЗР_сорт_насіння'

        if field_col in df_field.columns:
            df_field['Внесено_Число'] = df_field[field_col].apply(parse_ukrainian_number)
        else:
            df_field['Внесено_Число'] = 0.0

        if name_col_field in df_field.columns:
            df_field = df_field[df_field[name_col_field].astype(str).str.strip() != ""]
            df_field['Clean_Name'] = df_field[name_col_field].apply(clean_name)
            
            field_name_mapping = df_field[['Clean_Name', name_col_field]].drop_duplicates().set_index('Clean_Name')[name_col_field].to_dict()
            name_mapping.update(field_name_mapping)
        else:
            df_field['Clean_Name'] = ""

        field_grouped = df_field.groupby('Clean_Name', as_index=False)['Внесено_Число'].sum()
        field_grouped.rename(columns={'Внесено_Число': 'Внесено'}, inplace=True)

        # 3. ЗВЕДЕННЯ ТА РОЗРАХУНОК
        merged = pd.merge(wh_grouped, field_grouped, on='Clean_Name', how='outer')
        merged['Видано_зі_складу'] = merged['Видано_зі_складу'].fillna(0.0)
        merged['Повернення_в_склад'] = merged['Повернення_в_склад'].fillna(0.0)
        merged['Внесено'] = merged['Внесено'].fillna(0.0)

        merged['Препарат'] = merged['Clean_Name'].map(name_mapping)
        merged['Залишок'] = merged['Видано_зі_складу'] - merged['Повернення_в_склад'] - merged['Внесено']

        # Фільтр: приховуємо тільки чіткі нулі
        active_rests = merged[abs(merged['Залишок']) > 0.001].copy()

        return active_rests, None
    except Exception as e:
        return None, str(e)

# --------------------------------------------------------
# ВЕРХНЯ ПАНЕЛЬ
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
# ДАШБОРД
# --------------------------------------------------------
st.markdown("## 📊 Залишок ТМЦ на руках (Видано зі складу - Повернення - Внесено)")

df_active, error_msg = load_and_process_data()

if error_msg:
    st.error(f"Помилка завантаження даних: {error_msg}")
else:
    if df_active.empty:
        st.success("🎉 Усі ТМЦ повністю зписані або використані! Залишків на руках немає.")
    else:
        display_df = df_active[['Препарат', 'Видано_зі_складу', 'Повернення_в_склад', 'Внесено', 'Залишок']].copy()
        display_df.columns = ['Назва препарату / ТМЦ', 'Видано зі складу', 'Повернення', 'Внесено на поля', 'Залишок на руках']
        display_df = display_df.sort_values(by='Залишок на руках', ascending=False)

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True
        )
