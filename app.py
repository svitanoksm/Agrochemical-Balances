import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

# 1. Налаштування сторінки (на весь екран)
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

# 3. Підключення та завантаження даних із Google Таблиць через st.secrets
@st.cache_data(ttl=30) # Кешування на 30 секунд, кнопка оновлюватиме примусово
def load_and_process_data():
    try:
        # Авторизація через сервісний акаунт із секретів Streamlit
        scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(creds)

        # -----------------------------------------------------------------
        # НАЛАШТУВАННЯ ДОСТУПУ ДО ОДНІЄЇ ТАБЛИЦІ ТА РІЗНИХ АРКУШІВ
        # -----------------------------------------------------------------
        # 1. Вставте сюди єдиний ID вашої Google Таблиці (з її URL-посилання)
        MAIN_SHEET_ID = "1QUh9y-FL_qiYMCRAko8KLxUKjdAdlF63jukcLu45djc"
        
        # 2. Вкажіть точні назви аркушів (як вони написано у вас у вкладках внизу)
        SHEET_NAME_WH = "Рух_по_складам_Агроному"          # Наприклад, аркуш видачі зі складу
        SHEET_NAME_FIELD = "ЛМТ"        # Наприклад, аркуш польових робіт
        # -----------------------------------------------------------------

        # Відкриваємо саму таблицю
        spreadsheet = gc.open_by_key(MAIN_SHEET_ID)

        # Зчитування даних з аркуша «Склад»
        sh_wh = spreadsheet.worksheet(SHEET_NAME_WH)
        df_wh = pd.DataFrame(sh_wh.get_all_records())

        # Зчитування даних з аркуша «Поля»
        sh_field = spreadsheet.worksheet(SHEET_NAME_FIELD)
        df_field = pd.DataFrame(sh_field.get_all_records())

        # Агрегація Отриманого (Склад)
        # Очікувані назви колонок у таблиці: 'Агроном', 'Назва_ТМЦ', 'Кількість'
        wh_agg = df_wh.groupby(['Агроном', 'Назва_ТМЦ'], as_index=False)['Кількість'].sum()
        wh_agg.rename(columns={'Кількість': 'Отримано'}, inplace=True)

        # Агрегація Внесеного (Поля)
        field_agg = df_field.groupby(['Агроном', 'Назва_ТМЦ'], as_index=False)['Кількість'].sum()
        field_agg.rename(columns={'Кількість': 'Внесено'}, inplace=True)

        # Зведення двох аркушів в один датасет (Left Join)
        merged = pd.merge(wh_agg, field_agg, on=['Агроном', 'Назва_ТМЦ'], how='left')
        merged['Внесено'] = merged['Внесено'].fillna(0)

        # Розрахунок залишку на руках
        merged['Залишок'] = merged['Отримано'] - merged['Внесено']

        # ГОЛОВНИЙ ФІЛЬТР: залишаємо лише залишки > 0 (з урахуванням похибки 0.01)
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
df_active, error_msg = load_and_process_data()

if error_msg:
    st.error(f"Помилка завантаження даних: {error_msg}")
    st.info("Перевірте ID таблиці, назви аркушів у коді та чи надано доступ пошті сервісного акаунта.")
else:
    if df_active.empty:
        st.success("🎉 Усі агрономи повністю закрили свої звіти! Незписаних залишків немає, таблиці порожні.")
    else:
        # Отримуємо список агрономів, у яких є залишки
        agronomists_list = df_active['Агроном'].unique()

        # Виводимо блок для кожного агронома
        for agronomist in agronomists_list:
            st.markdown(f"### 👤 Агроном: **{agronomist}**")
            
            # Фільтруємо таблицю по конкретному агроному
            agri_df = df_active[df_active['Агроном'] == agronomist][['Назва_ТМЦ', 'Залишок']]
            agri_df.columns = ['Назва препарату / ТМЦ', 'Залишок на руках']
            
            # Сортуємо за об'ємом залишку
            agri_df = agri_df.sort_values(by='Залишок на руках', ascending=False)

            # Виводимо чисту таблицю
            st.dataframe(
                agri_df,
                use_container_width=True,
                hide_index=True
            )
            st.markdown("")
