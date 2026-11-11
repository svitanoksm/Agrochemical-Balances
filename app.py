import streamlit as st
import pandas as pd
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread
import re

st.set_page_config(page_title="Agrochemical Balances", page_icon="🌾", layout="wide")

def clean_name(val):
    if pd.isna(val):
        return ""
    text = str(val).upper().strip()
    text = re.sub(r'[®™©]','', text)
    text = re.sub(r'\s+', ' ', text)
    return text

@st.cache_data(ttl=30)
def load_and_process_data():
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        gc = gspread.authorize(creds)

        MAIN_SHEET_ID = "1QUh9y-FL_qiYMCRAko8KLxUKjdAdlF63jukcLu45djc"
        spreadsheet = gc.open_by_key(MAIN_SHEET_ID)

        df_wh = pd.DataFrame(spreadsheet.worksheet("Рух_по_складам_Агроному").get_all_records())
        df_field = pd.DataFrame(spreadsheet.worksheet("ЛМТ").get_all_records())

        df_wh['Видано_зі_складу'] = pd.to_numeric(df_wh['Видано_зі_складу'], errors='coerce').fillna(0)
        df_wh['Повернення_в_склад'] = pd.to_numeric(df_wh['Повернення_в_склад'], errors='coerce').fillna(0)
        df_wh['Clean_Name'] = df_wh['Номенклатура'].apply(clean_name)
        
        name_mapping = df_wh[['Clean_Name', 'Номенклатура']].drop_duplicates().set_index('Clean_Name')['Номенклатура'].to_dict()

        wh_grouped = df_wh.groupby('Clean_Name', as_index=False)[['Видано_зі_складу', 'Повернення_в_склад']].sum()

        field_col = 'Факт_внесення_на_поле_Добрива_ЗЗР_Насіння_(л_або_т)'
        name_col_field = 'Найменування_добрив_ЗЗР_сорт_насіння'

        df_field[field_col] = pd.to_numeric(df_field[field_col], errors='coerce').fillna(0)
        df_field['Clean_Name'] = df_field[name_col_field].apply(clean_name)
        
        field_name_mapping = df_field[['Clean_Name', name_col_field]].drop_duplicates().set_index('Clean_Name')[name_col_field].to_dict()
        name_mapping.update(field_name_mapping)

        field_grouped = df_field.groupby('Clean_Name', as_index=False)[field_col].sum()
        field_grouped.rename(columns={field_col: 'Внесено'}, inplace=True)

        merged = pd.merge(wh_grouped, field_grouped, on='Clean_Name', how='outer')
        merged['Видано_зі_складу'] = merged['Видано_зі_складу'].fillna(0)
        merged['Повернення_в_склад'] = merged['Повернення_в_склад'].fillna(0)
        merged['Внесено'] = merged['Внесено'].fillna(0)

        merged['Препарат'] = merged['Clean_Name'].map(name_mapping)
        merged['Залишок'] = merged['Видано_зі_складу'] - merged['Повернення_в_склад'] - merged['Внесено']

        active_rests = merged[abs(merged['Залишок']) > 0.001].copy()
        return active_rests, None
    except Exception as e:
        return None, str(e)

st.markdown("## 📊 Детальний баланс ТМЦ (Діагностика)")

df_active, error_msg = load_and_process_data()

if error_msg:
    st.error(f"Помилка: {error_msg}")
else:
    if df_active.empty:
        st.success("Усі залишки нульові.")
    else:
        display_df = df_active[['Препарат', 'Видано_зі_складу', 'Повернення_в_склад', 'Внесено', 'Залишок']].copy()
        display_df.columns = ['Препарат', 'Видано зі складу', 'Повернення', 'Внесено на поля', 'Залишок (Баланс)']
        display_df = display_df.sort_values(by='Залишок (Баланс)', ascending=True) # Спочатку покажемо найвищі мінуси

        st.dataframe(display_df, use_container_width=True, hide_index=True)
