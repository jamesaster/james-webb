import streamlit as st
import polars as pl
from src import Schema, today_hanoi
from core import supreme
S = Schema.Sales
st_metric_style = """
    <style>
        [data-testid="stMetricLabel"] p {
            color: #49618D !important;
            font-weight: 500 !important;
            font-size: 18px !important;
        }
        # [data-testid="stMetricValue"] div {
        #     color: #3366cd !important;
        #     font-weight: 400 !important;
        #     font-size: 38px !important;
        # }
    </style>
    """

def format_metric(n, is_pct=False):
    """
    ### Định dạng số (for hiển thị only)
    - 1_000_000_000 = 1.0B
    - 1_000_000     = 1.0M
    - 1_000         = 1.0k
    """
    if is_pct: 
        return f'{n:.1%}' if n <= 1 else f'{n:.1f}%'
    if n >= 1_000_000_000:
        return f'{n / 1_000_000_000:.2f}B'
    if n >= 1_000_000:
        return f'{n / 1_000_000:.2f}M'
    if n >= 1_000:
        return f'{n / 1_000:.1f}k'
    if n >= 10:
        return f'{n:.0f}'
    return f'{n:.2f}'

@supreme
def dash_engine(df_dated: pl.DataFrame, df_prev: pl.DataFrame):
    height  = df_dated.get_column(S.date).n_unique()
    prev_lz = df_prev.lazy()
    curr_lz = df_dated.lazy()
    agg_cfg = [
        pl.col(S.revenue).sum(),
        pl.col(S.qty).sum(),
        pl.col(S.invoice).drop_nulls().n_unique(),
        pl.col(S.traffic).first(),
        pl.col(S.lot).drop_nulls().n_unique()
    ]
    formula = [
        pl.col(S.revenue).alias('Revenue'),
        (pl.col(S.qty) / pl.col(S.invoice)).alias('UPT'),
        (pl.col(S.revenue) / pl.col(S.invoice)).alias('ATV'),
        pl.col(S.invoice).alias('Invoice'),
        (pl.col(S.invoice) / pl.col(S.traffic)).alias('Conversion'),
        pl.col(S.traffic).alias('Traffic'),
        pl.col(S.qty).alias('Item'),
        pl.col(S.lot).alias('Device')
    ]
    prev_dict = prev_lz.group_by(S.date).agg(agg_cfg).fill_null(0).sum().select(formula).collect().row(0, named=True)
    curr_dict = curr_lz.group_by(S.date).agg(agg_cfg).fill_null(0).sum().select(formula).collect().row(0, named=True)
    last_sync = df_dated.get_column(S.date).tail(1).item()
    return height, prev_dict, curr_dict, last_sync

@st.fragment(parallel=True)
def dash_metric(df_prev: pl.DataFrame, df_dated: pl.DataFrame):
    st.markdown(st_metric_style, unsafe_allow_html=True)
    prev_empty = df_prev.is_empty()
    if df_dated.is_empty():
        return

    height, prev_dict, curr_dict, last_sync = dash_engine(df_dated=df_dated, df_prev=df_prev)
    metrics_dict = {
        name: {
            'prev': val,
            'curr': format_metric(curr_dict[name], is_pct = name == 'Conversion'),
            'delta': '&nbsp;-&nbsp;' if prev_empty else (f'{round(((curr_dict[name] / val - 1) * 100), 1):+}%' if val and val != 0 else '0.0%')
        }
        for name, val in prev_dict.items()
    }

    time_info, date_info = (st.session_state.get('fetch_trigger', 'first').split(maxsplit=1) + [None])[:2]
    last_update = 'Today' if last_sync == today_hanoi() else f'On {date_info}'
    current_ts  = f':violet-badge[:material/sync: **{last_update}** at  {time_info}] \u2000'
    if prev_empty:
        info = f':green-badge[:material/calendar_today: **Data duration:** Last {height} days (No historical baseline)]'
    elif height == 1:
        info = f':orange-badge[:material/compare: **Comparison Period**: Versus **Yesterday**]'
    else:
        info = f':blue-badge[:material/history: **Comparison Period:** Versus previous **{height} days**]'
    st.caption(current_ts + info)

    split      = lambda x: (x + 1) // 3
    m_keys     = list(metrics_dict)
    st_columns = st.columns(noc:=split(len(metrics_dict)))
    for idx, name in enumerate(m_keys):
        st_columns[idx % noc].metric(
            label  = name,
            value  = metrics_dict[name]['curr'],
            delta  = metrics_dict[name]['delta'],
            border = True,
            height = 'stretch',
            delta_arrow = 'off'
        )


