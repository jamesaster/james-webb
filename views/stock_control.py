import pandas as pd
import streamlit as st
from io import BytesIO
from pathlib import Path
from openpyxl.worksheet.datavalidation import DataValidation
from src.database import insert_product, insert_ledger
from core import get_sys_brief_cache as briefcache
SS = st.session_state
CL = "#779179"
SS.page_name  = Path(__file__).stem
st.html("""
    <style>
    .st-key-bottom_container {
        background-color: transparent !important;
        padding: 0rem;
    }
    .st-key-left_stock_metric,
    .st-key-right_stock_metric {
        border: 3px solid #D0EBD2 !important;
        padding: 2rem;
    }
    .st-key-execute_stock button p {
        font-family: monospace !important;
        font-size: 17px !important;
        font-weight: 600 !important;
        color: #fff !important;
    }
    </style>
""")
stock_df = briefcache().get('inventory')

@st.cache_data(max_entries=10)
def read_sheet(kind, byte, header=0):
    if kind == 'csv':
        return pd.read_csv(byte)
    elif kind == 'parquet':
        return pd.read_parquet(byte)
    elif kind == 'xlsx':
        try:
            return pd.read_excel(byte, sheet_name=None, header=header)
        except ValueError:
            return pd.read_excel(byte, sheet_name=None, header=0)
def upload():
    with st.sidebar:
        st.write('**Choose File**')
        file = st.file_uploader(
            label            = 'Upload file',
            type             = ['csv', 'xlsx', 'parquet'],
            key              = 'upload_stock_file',
            label_visibility = 'collapsed'
        )
        if st.button('Use sample', width='stretch'):
            return pd.read_excel('data/universal_upsert _demo.xlsx')
        if not file:
            return
        data = file.getvalue()
        kind = file.name.rsplit('.', 1)[-1]
        byte = BytesIO(data)
        header = 0
        if kind == 'xlsx':
            header = st.number_input('Header (Default 0)', 0, 3, 0, 1)
        res  = read_sheet(kind, byte, header)
        if isinstance(res, dict):
            if len(res) == 1:
                return res[list(res)[0]]
            sheet = st.selectbox('**Select sheet**', options=list(res))
            return res[sheet]
        return res

def the_guardian(
    df: pd.DataFrame, 
    columns: list, 
    actions: list
    ):
    empty = pd.DataFrame()
    if isinstance(df, pd.DataFrame) and not df.empty:
        df = df.replace('', None)
        if 'transaction_id' in df.columns:
            df['transaction_id'] = df['transaction_id'].astype('string')
        if 'subcat' in df.columns:
            df['subcat'] = df['subcat'].astype('string')
        df = df.convert_dtypes(dtype_backend='pyarrow')
    else:
        st.info('Upload a file')
        return empty
    if not set(df.columns) == set(columns):
        st.error('The columns did not match the requirements')
        return empty
    
    if (null_id  := df['id'].isnull()).any():
        st.error(f'Ignored {null_id.sum()} Null "id"')
        df = df.loc[~null_id, :]
    if (null_ean := df['ean'].isnull()).any():
        st.error(f'Ignored {null_ean.sum()} Null "ean"')
        df = df.loc[~null_ean, :]
    if not set(df['type'].replace('', None).dropna().unique().tolist()).issubset(actions):
        st.error('Detected invalid action in column "type"')
        return empty

    # Serial force correction
    df.loc[df['serial'].notnull(), 'quantity'] = 1
    if df['serial'].dropna().duplicated().any():
        st.error('Detected duplicate serial')
        return empty
    if df.groupby('id')['serial'].apply(lambda x: x.notnull().any() & x.isnull().any()).any():
        st.error('Each product ID must contain either serial or non-serial, not both')
        return empty
    # ----------------
    
    if (df['quantity'] <= 0).any():
        st.error('Quantity must be greater than 0')
        return empty
    if (~df['quantity'].notnull() & df['type'].notnull()).any():
        st.error('"type" requires a "quantity" value')
        return empty

    return df
def after_agg_qc(
    df: pd.DataFrame
    ):
    no_price = df['price'].isnull() | df['price'].le(0)
    dupl_id  = df['id'].duplicated()
    dupl_ean = df['ean'].duplicated()
    if no_price.any():
        st.error(f'Ignored {no_price.sum()} Invalid "price"')
        df = df.loc[~no_price, :]
    if dupl_id.any():
        st.error(f'Detected {dupl_id.sum()} duplicate "id" after aggregated')
        st.dataframe(df.loc[dupl_id, 'id'])
    if dupl_ean.any():
        st.error(f'Detected {dupl_ean.sum()} duplicate "ean" after aggregated')
        st.dataframe(df.loc[dupl_ean, 'ean'])
    if dupl_id.any() or dupl_ean.any():
        return pd.DataFrame()
    return df

@st.fragment
def stock_button(
    product_df: pd.DataFrame,
    ledger_df: pd.DataFrame,
    proceed_product: bool,
    proceed_ledger: bool
    ):
    with st.container(horizontal_alignment='center', key='bottom_container_1'):
        st.space()
        if st.button('Demo Execute', type='primary', width=150):
            st.balloons()
            st.info('Executed', width=150)
    return
    if SS.get('log_product'):
        st.info(SS.log_product)
        SS.log_product = False
    if SS.get('log_ledger'):
        st.info(SS.log_ledger)
        SS.log_ledger = False
    with st.container(horizontal_alignment='center', key='bottom_container'):
        st.space()
        if st.button('Execute', width=200, key='execute_stock', type='primary', disabled=bool(SS.get('click', False))):
            SS.click = 'ready'
        if SS.get('click') == 'ready':
            if st.button(':green[**Abort**]', width=200):
                SS.click = False
                st.rerun(scope='fragment')
            if st.button(':red[**Just do it**]', width=200):
                SS.click = True
                if proceed_product:
                    SS.log_product = insert_product(product_df)
                if proceed_ledger and (
                    not proceed_product
                    or (SS.log_product.get('status') == 'success')
                    ):
                    SS.log_ledger = insert_ledger(ledger_df)
                briefcache().clear('inventory', 'serial')
                st.rerun(scope='fragment')
@st.fragment
def stock_input(stock_data: pd.DataFrame):
    _product = ['ean', 'id', 'cat', 'subcat', 'name', 'price']
    _ledger  = ['serial', 'quantity', 'type', 'transaction_id']
    columns  = _product + _ledger
    actions  = ['import_po', 'import_do', 'adjust_in', 'adjust_out', 'transfer', 'rtv']

    #region Sidebar UI
    st.sidebar.space()
    with st.sidebar.expander('**Tools**', icon=':material/handyman:', expanded=True):
        @st.cache_data(max_entries=1)
        def xlsx(stock_data):
            byte = BytesIO()
            with pd.ExcelWriter(byte, engine='openpyxl') as writer:
                pd.DataFrame(columns=columns).to_excel(writer, index=False, sheet_name='add_stock')
                stock_data.to_excel(writer, index=False, sheet_name='product_master')
                ws = writer.sheets['add_stock']
                ws['B2'] = '=ArrayFormula(IFERROR(VLOOKUP($A$2:$A,product_master!$A$2:$F, {2, 3, 4, 5, 6}, FALSE),))'
                dv = DataValidation(
                    type='list',
                    formula1=f'"{",".join(actions)}"'
                )
                ws.add_data_validation(dv)
                dv.add('I2:I1000')
            byte.seek(0)
            return byte
        st.link_button(
            'Open Database Diagram',
            'https://dbdiagram.io/d/James-DB-6a78405c35ee2e87b05f129a',
            icon=':material/account_tree:', width='stretch'
        )
        st.download_button(
            label     = ':violet[:material/file_save: **Download form.xlsx**]',
            data      = xlsx(stock_data),
            file_name = 'universal_upsert.xlsx',
            on_click  = 'ignore',
            width     = 'stretch',
            mime      = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

        mode = st.pills('mode',
            options  = ['Upload', 'Lock'],
            default  = 'Lock',
            required = True,
            key      = 'isolated_cache',
            width    = 'stretch',
            label_visibility = 'collapsed')
        if mode == 'Upload':
            SS.iso_df = upload()
        df = SS.get('iso_df', pd.DataFrame(columns=columns))
        
        if st.button('Button', icon=':material/lock_open_right:', width='stretch', type='tertiary'):
            SS.click = False
    #endregion

    #region Data Guardian
    if (df:=the_guardian(df, columns, actions)).empty:
        return
    #endregion

    #region Execution
    left, right = st.columns(2, gap='medium')
    left.subheader(f":color[**Product Upsert**]{{foreground={CL}}}", text_alignment='center')
    with left.container(border=True, key='left_stock_metric'):
        left_empty = st.container(horizontal=True)
        product_df = df[_product].groupby(['id', 'ean'], as_index=False).agg({
            'cat'   : 'first',
            'subcat': 'first',
            'name'  : 'first',
            'price' : 'max'
            })
        product_df = after_agg_qc(product_df)
        if product_df.empty:
            return
        st.dataframe(product_df, hide_index=True, height=750)
        old_price = product_df['id'].map(stock_data[['id', 'price']].set_index('id')['price'])
        l_metrics = {
            'Records'    : product_df['id'].nunique(),
            'New Product': (~ product_df['id'].isin(stock_data['id'].dropna())).sum(),
            'New Price'  : (~ (product_df['price'] == old_price)).sum()
        }
        for m, v in l_metrics.items():
            left_empty.metric(label=f'**{m}**', value=v)
    right.subheader(f":color[**Ledger Insert**]{{foreground={CL}}}", text_alignment='center')
    with right.container(border=True, key='right_stock_metric'):
        right_empty = st.container(horizontal=True)
        ledger_df = df.loc[df['type'].notnull(), ['id', *_ledger]].rename(columns={'id': 'product_id'})
        st.dataframe(ledger_df, hide_index=True, height=750)
        changes   = ledger_df[['type', 'quantity']].groupby('type').agg(total=('quantity', 'sum')).to_dict()
        r_metrics = {'Lines': len(ledger_df), **changes['total']}
        for m, v in r_metrics.items():
            right_empty.metric(label=f'**{m}**', value=v)

    bool_product = (l_metrics['New Product'] + l_metrics['New Price']) > 0
    bool_ledger  = r_metrics['Lines'] > 0
    stock_button(product_df, ledger_df, bool_product, bool_ledger)
    #endregion


sub = """
    <div style="font-size: 0.85rem; color: #6880AA; line-height: 1.5; margin-bottom: 35px; margin-top: 0px;">
        <strong>Sidebar Tools explain:</strong>
        <br>
        - Click <strong>Database Diagram</strong> to redirect to dbdiagram.io.
        <br>
        - <strong>Download</strong> button save stock control form with current inventory for reference and infomation lookup.
        <br>
        - Select <strong>Upload</strong> and choose files, accept xlsx with multiple tab for difference task / batch.
        <br>
        - <strong>Execute</strong> to finish.
    </div>
    """
st.title('Inventory Hub')
st.markdown(sub, unsafe_allow_html=True)
stock_input(stock_df)

