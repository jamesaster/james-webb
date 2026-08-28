import streamlit as st
from widget import page_config
from src import init_brief_cache
SS = st.session_state

init_brief_cache()
cashier   = st.Page('views/cashier.py', title='Cashier', icon=':material/point_of_sale:')
dashboard = st.Page('views/dashboard.py', title='Dashboard', icon=':material/analytics:')
stock     = st.Page('views/stock_control.py', title='Stock Control', icon=':material/box_add:')
page_list = [dashboard, cashier, stock]
pages     = st.navigation(page_list, position='sidebar', expanded=True)
pages.run()

SS.height = page_config()
