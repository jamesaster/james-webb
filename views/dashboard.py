import logging
import colorsys
import polars as pl
import streamlit as st
from pathlib import Path
from src import Schema, read_mockup
from widget.metric import dash_metric
from widget.sidebar import sideBar_filter, sideBar_view_control
from widget.echart import transformer, transformer_2, j_charts

S  = Schema.Sales
K  = Schema.Stock
SS = st.session_state
SS.page_name = Path(__file__).stem
logging.basicConfig(
    level   = logging.INFO,
    format  = '%(asctime)s - %(levelname)s - %(message)s',
    datefmt = '%d-%m-%Y %H:%M:%S'
)

pivots_store = {
    'Average Ticket Value (ATV)': {
        'agg_how': {
            S.revenue: 'sum',
            S.invoice: 'n_unique'
        },
        'formula': lambda revenue, invoice: revenue / invoice,
        'type'   : 'bar',
        'unit'   : 'VNĐ',
        'round'  : 0
    },

    'Units Per Ticket (UPT)': {
        'agg_how': {
            S.qty: 'sum',
            S.invoice: 'n_unique'
        },
        'formula': lambda qty, invoice: qty / invoice,
        'type'   : 'bar',
        'unit'   : 'decimal',
        'round'  : 2
    },

    'Conversion Rate': {
        'agg_how': {
            S.invoice: 'n_unique',
            S.traffic: 'first'
        },
        'formula': lambda invoice, traffic: invoice / traffic,
        'type'   : 'bar',
        'unit'   : 'pct',
        'round'  : 3
    },

    'Visitors Per Ticket': {
        'agg_how': {
            S.traffic: 'first',
            S.invoice: 'n_unique'
        },
        'formula': lambda traffic, invoice: traffic / invoice,
        'type'   : 'bar',
        'unit'   : 'Visits',
        'round'  : 2
    },

    'Revenue Per Visitor': {
        'agg_how': {
            S.revenue: 'sum',
            S.traffic: 'first'
        },
        'formula': lambda revenue, traffic: revenue / traffic,
        'type'   : 'bar',
        'unit'   : 'VNĐ',
        'round'  : 0
    },

    'Average Selling Price': {
        'agg_how': {
            S.revenue: 'sum',
            S.qty: 'sum'
        },
        'formula': lambda revenue, qty: revenue / qty,
        'type'   : 'bar',
        'unit'   : 'VNĐ',
        'round'  : 0
    },

    'Devices Per Transaction': {
        'agg_how': {
            S.lot: 'n_unique',
            S.invoice: 'n_unique'
        },
        'formula': lambda lot, invoice: lot / invoice,
        'type'   : 'bar',
        'unit'   : 'decimal',
        'round'  : 2
    }
}
pivots_staff = {
    # --- Volume metrics
    'Performance (Revenue)': {
        'groupby': S.staff,
        'agg_how': {
            S.revenue: 'sum'
        },
        'formula': lambda revenue: revenue,
        'type'   : 'bar',
        'unit'   : 'VNĐ',
        'round'  : 0
    },

    'Devices Sold': {
        'groupby': S.staff,
        'agg_how': {S.lot: 'n_unique'},
        'formula': lambda imei: imei,
        'type'   : 'bar',
        'unit'   : 'Pcs',
        'round'  : 0
    },

    'Transactions': {
        'groupby': S.staff,
        'agg_how': {
            S.invoice: 'n_unique'
        },
        'formula': lambda invoice: invoice,
        'type'   : 'bar',
        'unit'   : 'Invoice',
        'round'  : 0
    },

    # --- Efficiency metrics
    'Attachment Rate': {
        'groupby': S.staff,
        'agg_how': {
            S.qty: 'sum',
            S.lot: 'n_unique'
        },
        'formula': lambda qty, imei: (qty - imei) / imei,
        'type'   : 'bar',
        'unit'   : 'pct',
        'round'  : 3
    },

    'Average Ticket Value (ATV)': {
        'groupby': S.staff,
        'agg_how': {
            S.revenue: 'sum',
            S.invoice: 'n_unique'
        },
        'formula': lambda revenue, invoice: revenue / invoice,
        'type'   : 'bar',
        'unit'   : 'VNĐ',
        'round'  : 0
    },

    'Units Per Transaction (UPT)': {
        'groupby': S.staff,
        'agg_how': {
            S.qty: 'sum',
            S.invoice: 'n_unique'
        },
        'formula': lambda qty, invoice: qty / invoice,
        'type'   : 'bar',
        'unit'   : 'decimal',
        'round'  : 2
    },

    'Revenue Per Unit': {
        'groupby': S.staff,
        'agg_how': {
            S.revenue: 'sum',
            S.qty: 'sum'
        },
        'formula': lambda revenue, qty: revenue / qty,
        'type'   : 'bar',
        'unit'   : 'VNĐ',
        'round'  : 0
    }
}
def header(
    title   : str,
    sub     : str | None = None,
    color   : str = "#83B4DD",
    size    : str = '1.85rem',
    weight  : int | str = 600,
    ):
    st.html(
        f"""
        <div style="
            font-size:{size};
            font-weight:{weight};
            color:{color};
            line-height:1.3;
        ">{title}</div>
        {
            f'''
            <div style="
                font-size:0.78rem;
                font-weight:400;
                color:#9AA0A6;
                line-height:1.4;
                margin-top:2px;
            ">{sub}</div>
            '''
            if sub else ''
        }
        """
    )
def darken(
    color: str,
    amount: float = 0.2
    ) -> str:
    color = color.lstrip('#')
    r, g, b = (int(color[i:i+2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0, l * (1 - amount))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return f'#{round(r*255):02X}{round(g*255):02X}{round(b*255):02X}'

if not isinstance(SS.get('df'), pl.DataFrame):
    SS.df = read_mockup()

def main(df_full: pl.DataFrame):
    st.title('Retail Store Demo Dashboard')
    # if not 'count' in SS:
    #     SS.count = 0
    # SS.count += 1
    # st.info(SS.count)

    #region Sidebar + Metrics
    height    = SS.get('height') or {'height': 320}
    f_bundles = sideBar_filter(df_full)
    df_prev   = f_bundles['df_prev']
    df_dated  = f_bundles['df_dated']
    df_final  = f_bundles['df_final']
    period    = f_bundles['period']
    view      = sideBar_view_control()
    dash_metric(df_prev, df_dated)
    st.space()
    #endregion

    config_1 = {
        '_period' : period,
        'view'    : view,
        'x_col'   : S.date,
        'y_cols'  : [S.revenue, S.traffic],
        'legends' : None,
        'y_aggs'  : ['sum', 'first'],
        'units'   : ['vnđ', 'qty'],
        'types'   : None,
        'axs_idx' : [0, 1],
        'colors'  : None,
    }
    params_1 = transformer(df_final, **config_1)
    header('Revenue vs. Traffic', color="#77A0C2")
    j_charts(**params_1, **height)
    st.space()

    config_2 = {
        '_period' : period,
        'view'    : view,
        'x_col'   : S.date,
        'y_cols'  : [S.mkt, S.invoice],
        'legends' : ['Promo Amount', 'Invoice Count'],
        'y_aggs'  : ['sum', 'n_unique'],
        'units'   : ['vnđ', 'qty'],
        'types'   : None,
        'axs_idx' : [0, 1],
        'colors'  : ["#A9D0C1", "#6899C7"],
    }
    params_2 = transformer(df_final, **config_2)
    header('Promotion vs. Invoice', color="#71AB97")
    j_charts(**params_2, **height)
    st.space()


    metric_3 = st.sidebar.selectbox(
        label   = ':orange[*] **Store Metric**',
        options = pivots_store.keys(),
        key     = (key_3:='sideBar_metrics_3'),
        help    = ':orange[**Pick a metric.**]'
        )
    params_3 = transformer_2(df_final, period, pivots_store, metric_3, view, key_3)
    color_3  = darken(params_3['colors'][0])
    header(metric_3, 'Select metric from the sidebar', color=color_3)
    j_charts(**params_3, **height)
    st.space()

    metric_4 = st.sidebar.selectbox(
        label   = ':orange[*] **Staff Metric**',
        options = pivots_staff.keys(),
        key     = (key_4:='sideBar_metrics_4'),
        help    = ':orange[**Period: Selecting "Day" auto-forces to "Week".**]'
        )
    params_4 = transformer_2(df_final, period, pivots_staff, metric_4, view.replace('1d', '1w'), key_4)
    header(metric_4, 'Select metric from the sidebar', color="#699AAE")
    j_charts(**params_4, **height)
    st.space()

    with st.sidebar:
        st.space('xxlarge')
        st.space('xxlarge')

if __name__ == '__main__':
    main(SS.df)
