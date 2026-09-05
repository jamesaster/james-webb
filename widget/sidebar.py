import polars as pl
import streamlit as st
from pathlib import Path
from core import supreme
from src import Schema, custom_sort
from datetime import date, timedelta
S  = Schema.Sales
SS = st.session_state

def page_config(title: str = 'Streamlit POS', icon: str = '🏪'):
    with st.sidebar:
        views  = {':material/monitor: Desktop': 'wide', ':material/mobile_3: Mobile': 'centered'}
        views  = ['wide', 'centered'][int(SS.get('page_name') == 'dashboard')]
        st.set_page_config(
            page_title  = title,
            page_icon   = icon,
            layout      = views,
            menu_items  = {'About': '### This is an extremely cool app!'}
        )
    chart_height = 320 if views == 'wide' else 320
    return {'height': chart_height}

class Filter:
    def __init__(self, df: pl.DataFrame):
        """ Lưu ý: Không return self các hàm bên dưới """
        self.df = df

    @supreme
    def _date_bundles(self):
        df = self.df
        DATE  = pl.col(S.date)
        DTAIL = DATE.last()
        MONTH = DATE.dt.strftime(Schema.Format.month)
        utils = df.select([
            DTAIL.dt.strftime('%B').alias('this_month_name'),
            DTAIL.dt.strftime(Schema.Format.month).alias('this_month_year'),
            DTAIL.dt.offset_by('-1mo').dt.days_in_month().alias('prev_month_count'),
            DATE.min().alias('min_date'),
            DATE.max().alias('max_date')
        ]).row(0, named=True)

        return {
            'DATE': DATE, 'DTAIL': DTAIL, 'MONTH': MONTH, 'utils': utils
        }

    @supreme
    def _temporal_config(*, DATE, DTAIL, MONTH, utils, x, y, z):
        m_y     = utils['this_month_year']
        m_n     = utils['this_month_name']
        p_m     = utils['prev_month_count']
        start   = utils['min_date']
        end     = utils['max_date']
        
        xyz_Expr = []
        if 'Head' in z and y != 'd':
            xyz_Expr.append(DATE >= DTAIL.dt.offset_by(f'-{x}{y}').dt.truncate(f'1{y}'))
        else:
            xyz_Expr.append(DATE > DTAIL.dt.offset_by(f'-{x}{y}'))
        if 'Tail' in z and y != 'd':
            xyz_Expr.append(DATE < DTAIL.dt.truncate(f'1{y}'))
        Last_XY = pl.all_horizontal(xyz_Expr)

        return {
            f'{m_n} So Far'     : MONTH == m_y,
            f'Last {p_m} days'  : DATE > DTAIL.dt.offset_by(f'-{p_m}d'),
            'Last X Y'          : Last_XY,
            'All Time'          : DATE.is_not_null(),
            'Custom'            : DATE.is_between(start, end)
        }

    @supreme
    def _date_branch(df: pl.DataFrame, config: dict, mode: str, adv_list: list):
        df_dated    = df.filter(config[mode])
        prev_anchor = df_dated.select([
            (pl.col(S.date).min()                       # Đầu kỳ trước
                - (pl.col(S.date).max() - pl.col(S.date).min() + timedelta(1))
                ).alias('lower_bound'),
            pl.col(S.date).min().alias('upper_bound'),  # Điểm chia 2 kỳ
            pl.col(S.date).max().alias('current_end')   # Ngày cuối kỳ hiện tại
        ]).row(0, named=True)
        current_end = prev_anchor.pop('current_end')
        df_prev     = df.filter(pl.col(S.date).is_between(**prev_anchor, closed='left'))
        adv_utils   = df_dated.select([pl.col(column).drop_nulls().unique().implode() for column in adv_list]).row(0, named=True)
        return {
            'df_dated'    : df_dated,
            'df_prev'     : df_prev,
            '3_anchors'   : {
                '1': prev_anchor['lower_bound'],
                '2': prev_anchor['upper_bound'],
                '3': current_end,
                },
            'adv_utils'   : adv_utils,        # Nhét tạm logic adv vì tối ưu flow
            'date_Expr'   : str(config[mode]) # Nhét vào vì str cần gọi polars
        }

    @supreme
    def _adv_final(df_dated: pl.DataFrame, adv_res: dict):
        adv_masks = [pl.col(k) == v for k, v in adv_res.items() if not v.startswith('All ')] or [pl.lit(True)]
        adv_Expr  = pl.all_horizontal(adv_masks)
        df_final  = df_dated.filter(adv_Expr)
        return {
            'df_final': df_final,
            'adv_Expr': str(adv_Expr), # Dù là str() nhưng bản chất vẫn là polars
        }

    @supreme
    def _date_range(start, end):
        return pl.date_range(start, end).alias(S.date)
@st.fragment
def sideBar_filter(df: pl.DataFrame, adv_list: list=[S.staff, S.cat]):
    """
    ### Sidebar filter subsystem implementing a One-Way Valve pattern using Fragments.
    - Isolates all temporal and advanced filtering dynamics within a local reactive boundary.
    - Prevents main-page reruns on empty combinations by validating the final Polars expression 
        state via its string layout (`str(Expr)`) before committing to the global session state.
    - Guarantees the main application layout remains fully intact with valid data at all times.
    ### Windows fatal exception: access violation
        # copy.deepcopy() - tried
        # max_thread = 1 - tried
        # python 3.12 - tried
        # df = df.filter(True) - tried
        # df = pl.arrow - tried
        # threading.Lock() - tried
        - Custom Pool - Solved
    """

    if not isinstance(df, pl.DataFrame) or df.is_empty():
        st.error('Empty Source')
        st.stop()
    supreme_obj = Filter(df)

    #region # Date
    date_bundles = supreme_obj._date_bundles()
    utils      = date_bundles['utils']
    month_name = utils['this_month_name']
    prev_month = utils['prev_month_count']
    min_date   = utils['min_date']
    max_date   = utils['max_date']

    last_ops   = {'d': 'Day', 'w': 'Week', 'mo': 'Month'}
    last_x_key = 'last_x_key'
    last_y_key = 'last_y_key'
    last_z_key = 'last_z_key'

    with st.sidebar:
        st.title(':blue[:material/filter_alt: Filters]')
        with st.container(border=True):
            st.caption(
                f":material/event_available: **Avail: {min_date.strftime('%b %Y')}** :material/chevron_forward: **{max_date.strftime('%b %Y')}**"
                )
        mode  = st.selectbox(
            label   = '**:blue[\\*] Select Period**',
            options = [f'{month_name} So Far', f'Last {prev_month} days', 'Last X Y', 'All Time', 'Custom']
            )
        if mode == 'Custom':
            with st.expander('Default: Last 7 days', expanded=True, icon=':material/edit_calendar:'):
                start = st.date_input('Start',
                    value     = max_date - timedelta(6),
                    min_value = min_date,
                    max_value = max_date,
                    format    = 'DD-MM-YYYY'
                    )
                end   = st.date_input('End',
                    value     = max_date,
                    min_value = start,
                    max_value = max_date,
                    format    = 'DD-MM-YYYY',
                    )
                date_bundles['utils']['min_date'] = start
                date_bundles['utils']['max_date'] = end
        if mode == 'Last X Y':
            st.number_input(
                label     = 'X: Time Value',
                value     = 1,
                min_value = 1,
                # max_value = 31,
                key       = last_x_key
                )
            st.segmented_control(
                label       = 'Y: Time Unit',
                options     = list(last_ops),
                format_func = lambda y: last_ops[y],
                default     = 'mo',
                required    = True,
                width       = 'stretch',
                key         = last_y_key
                )
            st.segmented_control(
                label       = 'Snap & Trim',
                options     = ['Head', 'Tail'],
                width       = 'stretch',
                key         = last_z_key,
                help        = '- **Head**: Snap :material/fast_rewind: :red[backward] to the beginning of the period.\n\n'
                            '- **Tail**: Trim the incomplete current period to remove the tail.',
                selection_mode = 'multi'
                )
            st.space()

    x, y, z = SS.get(last_x_key, 0), SS.get(last_y_key, 'mo'), SS.get(last_z_key, [])
    config = Filter._temporal_config(**date_bundles, x=x, y=y, z=z)
    #endregion

    #region # Branching
    date_branch = Filter._date_branch(df, config, mode, adv_list)
    df_prev     = date_branch['df_prev']
    df_dated    = date_branch['df_dated']
    tri_anchors = date_branch['3_anchors']
    information = st.sidebar.empty()
    information.write(
        ':green[:material/filter_arrow_right:]\u2000 :green-badge[Loading...]'
        )
    #endregion

    #region # Advanced
    adv_res = {}
    for col_name, vals in date_branch['adv_utils'].items():
        default_all = f'All {col_name.title()}'
        vals = [default_all] + vals
        res  = st.sidebar.selectbox(
            label    = f'**:red[\\*] {col_name.title()}**',
            options  = sorted(vals, key=custom_sort),
            key      = f'adv_{col_name}',
            index    = 0
            )
        adv_res[col_name] = res
    adv_final = Filter._adv_final(df_dated, adv_res)
    df_final  = adv_final['df_final']
    #endregion

    #region # Rerun Control
    dfe_key  = 'date_filter_expression'
    afe_key  = 'advanced_filter_expression'
    date_Expr :str = date_branch['date_Expr']
    adva_Expr :str = adv_final['adv_Expr']
    if df_final.is_empty(): # NOTE - Xem check is_empty có sập k | Không sập :)
        information.write(':violet-badge[:material/filter_alt_off: No results, page intact.]')
        st.toast('No results found.', icon=':material/search_off:')
        SS[dfe_key] = SS[afe_key] = 'do_nothing'
    else:
        badge = 'green' if mode in ['Last X Y'] else 'grey'
        information.write(
            f':{badge}[:material/filter_arrow_right:]\u2000\
            :{badge}-badge[{tri_anchors['2'].strftime('%d-%m-%Y')}]\
            :{badge}[:material/chevron_forward:]\
            :{badge}-badge[{tri_anchors['3'].strftime('%d-%m-%Y')}]'
            )
        if dfe_key not in SS:
            SS[dfe_key]  = date_Expr
            SS[afe_key]  = adva_Expr
        elif SS[dfe_key] != date_Expr:
            SS[dfe_key] = date_Expr
            st.rerun(scope='app')
        elif SS[afe_key] != adva_Expr:
            SS[afe_key] = adva_Expr
            st.rerun(scope='app')
    #endregion
    
    return {
        'df_prev' : df_prev,
        'df_dated': df_dated,
        'df_final': df_final,
        'period'  : Filter._date_range(tri_anchors['2'], tri_anchors['3']),
    }

def sideBar_view_control(label = ':violet[*] **Chart Period**'):
    st.sidebar.space()
    st.sidebar.title(':orange[:material/monitoring: Charts]')
    options = {'1d': 'Day', '1w': 'Week', '1mo': 'Month'}
    view    = st.sidebar.selectbox(
        label       = label,
        options     = list(options),
        format_func = lambda x: options[x],
    )
    return view

@st.fragment
def sidebar_signature():
    with st.sidebar:
        st.html("""
        <style>
            @keyframes complex-collision {
            0%  { transform: translateX(-150px) rotate(-90deg) scale(1.0);
                animation-timing-function: linear;}                             /* Phi ra */
            6%  { transform: translateX(28px)   rotate(20deg)  scale(1.0)}      /* Crash */
            10% { transform: translateX(18px)   scale(0.5, 1.5)}                /* Nhún */
            15% { transform: translateX(8px)    scale(1.3, 1.0)}                /* Re-bounce */
            20% { transform: translateX(0px)    scale(1.0)}                     /* Back to Normal*/
            30% { transform: translateY(5px)    rotate(-5deg)}                  /* stay */
                
            34% { transform: translateY(-20px)  rotate(5deg)}                   /* small jump */
            40% { transform: translateX(0px)    rotate(-8deg)}
            46% { transform: translateX(0px)}
            50% { transform: translateY(-15px)  rotate(-7deg)}                  /* small jump */
            55% { transform: translateX(0px)    rotate(5deg)}
            70% { transform: translateX(0px)}
                
            75% { transform: translateX(0px)    scale(1.1)}                     /* To ra*/
            80% { transform: translateY(10px)   scale(1.0, 0.65)}               /* Lấy đà*/  
            84% { transform: translateY(-60px)  rotate(-330deg) scale(1);       /* Jump + Flip*/
                animation-timing-function: ease-out;}
            90% { transform: translateX(0px)    rotate(30deg);                  /* Landing */
                animation-timing-function: ease-in;}
            93% { transform: translateX(0px)}                                   /* Nghỉ */
            100% { transform: translateX(300px) rotate(-90deg) scale(1);
                opacity: 1;
                animation-timing-function: linear;}
            }

            @keyframes toggle-icon-1 {
                0%, 84% { opacity: 1; } 
                85%, 100% { opacity: 0; } 
            }
            @keyframes toggle-icon-2 {
                0%, 84% { opacity: 0; }
                85%, 100% { opacity: 1; } 
            }

            .animated-icon {
                position: absolute; /* Đè 2 icon lên nhau */
                top: 0; left: 0;
                display: inline-block;
                font-size: 42px;
                line-height: 1;
                transform-origin: center;
            }
            
            /* Gán toggle animation cho từng icon */
            .icon-1 { animation: complex-collision 10s infinite ease-out, toggle-icon-1 10s infinite; }
            .icon-2 { animation: complex-collision 10s infinite ease-out, toggle-icon-2 10s infinite; }
        </style>
        """) 
        st.html("""
        <div style="overflow: hidden; width: 100%;">
            <div id="dynamic-logo-container" style="margin-top: 50px; padding-bottom: 10px;">
                
                <div style="display: flex; align-items: center; justify-content: center; gap: 15px;">
                    <div style="position: relative; width: 42px; height: 42px; display: flex; align-items: center; justify-content: center;">
                        <span class="animated-icon icon-1">⚡</span>
                        <span class="animated-icon icon-2">💡</span>
                    </div>
                    
                    <div style="display: flex; flex-direction: column; align-items: flex-start;">
                        <span style="font-weight: 700; color: #FAFAFA; font-family: 'Source Sans Pro', sans-serif; font-size: 24px; line-height: 1.1;">
                            Meo
                        </span>
                        <span style="font-weight: 700; color: #5A94E8; font-family: 'Source Sans Pro', sans-serif; font-size: 24px; line-height: 1.1; margin-left: 25px; margin-top: 2px;">
                            🐈
                        </span>
                    </div>
                </div>
                
                <div style="text-align: center; margin-top: 18px;">
                    <p style="font-size: 11px; color: #808495; font-style: italic; margin: 0; letter-spacing: 0.6px;">
                        Crafted by Tran Anh Hieu
                    </p>
                </div>
            </div>
        </div>
        """)
