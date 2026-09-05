from streamlit_echarts import st_echarts, JsCode
from typing import Literal, Union
import polars.selectors as cs
from core import supreme
from src import Schema
import streamlit as st
import polars as pl
import json
import hashlib
S  = Schema.Sales
SS = st.session_state
echart_Params = {
    'core' : {
        "name": "",
        "type": "bar",
        "yAxisIndex": 0,
        "xAxisIndex": 0,
        "silent": False,
        "datasetIndex": 0,
        "dimensions": None,
        "encode": None,
        "emphasis": {
            "focus": "none",
            "blurScope": "coordinateSystem",
            "disabled": False,
        }
    },
    'bar'  : {
        "barMinWidth": 1,
        "barMaxWidth": "45%",
        "barGap": "20%",
        "barCategoryGap": "30%",
        "large": True,
        "largeThreshold": 1000,
        "sampling": "lttb",
        "universalTransition": True,
        "itemStyle": {
            "color": None,
            "borderRadius": 0,
            "opacity": 1,
            "borderWidth": 0,
            "borderColor": "#000",
            "borderType": "solid",
            "decal": None,
        },
        "emphasis": {
            "focus": "series",
            "blurScope": "coordinateSystem", 
            "itemStyle": {
            "opacity": 1,
            "borderWidth": 7,
            "borderColor": None,
            "shadowOffsetX": 0,
            "shadowOffsetY": 0,
            "shadowBlur": 0,
            }
        },
    },
    'line' : {
        "smooth": 0.2,
        "smoothMonotone": None,
        "showSymbol": False,
        "triggerLineEvent": False,
        "step": False,
        "connectNulls": False,
        "lineStyle": {
            "width": 3,
            "color": None,
            "type": "solid",
            "opacity": 1,
            "dashOffset": 0,
            "cap": "butt",
            "join": "bevel",
        },
        "emphasis": {
            "lineStyle": {
                "width": 3,
                "type": "solid",
                "opacity": 1,
                "dashOffset": 0,
            },
            "itemStyle": {
                "color": None,
                "borderColor": None,
                "borderWidth": 4,
                "borderType": "solid",
            }
        }
    }
}
darken_Js     = """
    function darken(hex) {
        var n = parseInt(hex.slice(1), 16);
        var r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
        var max = Math.max(r, g, b), min = Math.min(r, g, b);
        var l = (max + min) / 2 / 255 * (1 - 0.4) * 255;
        var f = max === min ? [l, l, l] : [r, g, b].map(function (c) {
            return min + (max - min === 0 ? 0 : (c - min) * (l * 2 / (max + min || 1)));
        });
        return '#' + f.map(function (c) {
            return Math.round(Math.max(0, Math.min(255, c))).toString(16).padStart(2, '0').toUpperCase();
        }).join('');
    }
    """
num_format_Js = """
    function formatNumber(v) {
        if (v === undefined || v === null || isNaN(v)) return v;
        return v >= 1e9 ? (v / 1e9).toFixed(1) + 'B' :
                v >= 1e6 ? (v / 1e6).toFixed(1) + 'M' :
                v >= 1e3 ? (v / 1e3).toFixed(1) + 'K' : v;
    }
    """

#region
@supreme
def transformer(
    df      : pl.DataFrame,
    _period : pl.Expr,
    view    : str  = '1d',
    *,
    x_col   : str  = S.date,
    legends : list = None,
    y_cols  : list = None,
    y_aggs  : list[Union[Literal['sum', 'mean', 'first', 'n_unique'], str]] = None,
    units   : list[Union[Literal['qty', 'pct', 'decimal', 'vnd', 'kg', '...'], str]] = None,
    types   : list[Union[Literal['bar', 'line'], str]] = None,
    axs_idx : list = None,
    colors  : list = None
    ):
    #region Guardian
    if not isinstance(df, pl.DataFrame) or df.is_empty():
        raise ValueError('Dataframe is empty or invalid.')
    if x_col is None:
        raise ValueError('x_col must be given.')
    if y_cols is None:
        raise ValueError('y_cols must be given.')
    if y_aggs is None:
        y_aggs = ['sum' for _ in y_cols]
    if legends is None:
        legends = [n.replace('_', ' ').title() for n in y_cols]
    if units is None:
        units   = ['qty' for _ in y_cols]
    if types is None:
        types   = ['bar'] + ['line' for _ in range(len(y_cols) - 1)]
    if axs_idx is None:
        axs_idx = [0 for _ in y_cols]
    if len({len(legends), len(y_cols), len(types), len(units), len(axs_idx)}) > 1:
        raise ValueError('Length of legends, y_cols, types, and units must be equal.')
    if len(legends) != len(set(legends)):
        raise ValueError('Legends name must be unique.')
    if not set(y_cols).issubset(df.select(cs.numeric()).columns):
        raise ValueError('y_cols must be number format.')
    #endregion

    #region Aggregate - Lazy nhanh gấp 3
    lazy = df.lazy()
    agg_funcs   = {
        'sum'       : lambda x: pl.col(x).sum(),
        'mean'      : lambda x: pl.col(x).mean(),
        'first'     : lambda x: pl.col(x).first(),
        'n_unique'  : lambda x: pl.col(x).n_unique(),
    }
    y_agg_Expr  = [agg_funcs[f](x) for x, f in zip(y_cols, y_aggs)]
    pre_agg     = pl.select(_period).lazy().join(lazy.group_by(x_col).agg(y_agg_Expr), on=x_col, how='left')
    dynamic_agg = pre_agg.group_by_dynamic(
        x_col,
        every    = view,
        period   = view,
        group_by = None,
    ).agg(pl.col(y_cols).sum()
    ).sort(x_col
    ).collect()
    #endregion
    
    #region whatever
    colors   = colors or [
        '#A1C0D8', "#E0A9A9", '#96C8C5', '#BCAACF', "#B4C0C9",
        "#A1C7B0", "#AAB3D8", "#9FC8C5", "#B8B9D8", "#DFCC95"
    ]
    temporal = dynamic_agg.select(cs.temporal()).columns
    x_dtype  = dynamic_agg.get_column(x_col).dtype
    x_format = {
        '1d' : pl.col(x_col).dt.strftime('%a %d\n%b').str.to_titlecase(),
        '1w' : pl.concat_str([pl.col(x_col).dt.strftime('%y-W'), pl.col(x_col).dt.week(), pl.col(x_col).dt.truncate('1w').dt.strftime(' (%d %b)')]),
        '1mo': pl.col(x_col).dt.strftime('%b %Y')
    }
    if x_col in temporal and x_dtype != pl.Time:
        x_prs = x_format[view]
    elif x_dtype == pl.String:
        x_prs = pl.col(x_col).fill_null('')
    concat   = dynamic_agg.select(pl.concat_list([x_prs, y]).implode().alias(l) for l, y in zip(legends, y_cols)).row(named=True)
    key      = f'ultimate_chart_{'_'.join(legends).lower()}'
    #endregion

    return j_engine(
        concat  = concat,
        types   = types,
        units   = units,
        colors  = colors,
        axs_idx = axs_idx,
        view    = view,
        key     = key
        )
@supreme
def dynamic_pivot(
    df      : pl.DataFrame,
    _period : pl.Expr,
    config  : dict,
    metric  : str,
    view    : str
    ):

    pl_math = {
        'sum'       : lambda x: pl.col(x).sum(),
        'mean'      : lambda x: pl.col(x).mean(),
        'first'     : lambda x: pl.col(x).first(),
        'n_unique'  : lambda x: pl.col(x).n_unique(),
        }
    strtime = {
        '1d' : pl.col(S.date).dt.strftime('%a %d\n%b').str.to_titlecase(),
        '1w' : pl.concat_str([
               pl.col(S.date).dt.strftime('%y-W'), pl.col(S.date).dt.week(), pl.col(S.date).dt.truncate('1w').dt.strftime(' (%d %b)')]),
        '1mo': pl.col(S.date).dt.strftime('%b %Y')
    }
    groupby = config[metric].get('groupby', S.store_id)
    n_round = config[metric].get('round', 0)
    formula = config[metric]['formula']
    agg_how = config[metric]['agg_how']
    agg_day = [pl_math[how](col).alias(col) for col, how in agg_how.items()]
    aggview = formula(*[pl.col(c).sum() for c in agg_how.keys()]).alias(metric)
    lazy    = (
        df.lazy()
        .group_by([S.date, groupby], maintain_order=True).agg(agg_day)
        .group_by_dynamic(S.date, every=view, period=view, group_by=groupby).agg(aggview)
        )
    fill    = pl.select(_period.dt.truncate(view).unique(maintain_order=True)).lazy()
    join    = fill.join(lazy, on=S.date, how='left')
    x_cols  = join.select(pl.col(groupby).unique(maintain_order=True).drop_nulls()).collect().to_series()
    pivot   = join.pivot(on=groupby, on_columns=x_cols, index=S.date, values=metric)
    sortd   = pivot.sort(by=S.date).with_columns(strtime[view], cs.numeric().round(n_round)).fill_null(0)
    concat  = sortd.select(pl.concat_list([S.date, C]).implode().alias(C) for C in x_cols).collect().row(named=True)
    return concat
def transformer_2(
    df      : pl.DataFrame,
    _period : pl.Expr,
    _config : dict,
    metric  : str,
    view    : str,
    key     : str = ''
    ):
    concat = dynamic_pivot(df, _period, _config, metric, view)
    type__ = _config[metric].get('type', 'bar')
    unit__ = _config[metric].get('unit', 'qty')
    single = len(concat.keys()) == 1
    colors = [
        "#ABB5DB", '#A1C0D8', '#96C8C5', '#A1C7B0', '#C3D39E',
        '#DFCC95', '#DDB497', '#D5A3AC', '#BCAACF', '#B4C0C9'
    ]
    if single:
        index  = int(hashlib.md5(metric.encode()).hexdigest(), 16) % len(colors)
        colors = [colors[index]]
    return j_engine(
        concat = concat,
        types  = type__,
        units  = unit__,
        colors = colors,
        view   = view,
        key    = '2_'+key
        )

def j_engine(
    concat  : dict,
    types   : list,
    units   : list,
    colors  : list,
    axs_idx : list = None,
    view    : str  = '1d',
    key     : str  = 'dynamic_jchart'
    ):
    legends = list(concat)
    n = len(legends)
    z = list(reversed(range(n)))
    if isinstance(types, str):
        types = [types] * n
    if isinstance(units, str):
        units = [units] * n
    if not axs_idx:
        axs_idx = [0] * n
    series_list = [
        {
            **echart_Params["core"],
            "name": s,
            "type": types[i],
            "data": concat[s],
            "z"   : z[i],
            "yAxisIndex": axs_idx[i],
            **echart_Params[types[i]],

            "itemStyle": {
                "borderRadius": [2, 2, 0, 0],
                "opacity": 0.95,
                "borderWidth": 1,
                "borderColor": colors[i % len(colors)],
            }
            if types[i] == "bar" else {},

            "lineStyle": {
                "width": 2,
                "type": "solid",
                "opacity": 0.8
            }
            if types[i] == "line" else {},
        }
        for i, s in enumerate(legends)
    ]
    return {'series': series_list, 'colors': colors, 'units': units, 'view': view, 'key': key}
@st.fragment
def j_charts(
    series : list,
    colors : list,
    units  : list,
    view   : str='1d',
    key    : str='ultimate_v0',
    height : int=300,
    period : pl.Expr=None
    ):
    units_json = json.dumps(units)
    tooltip_formatter = JsCode(f"""
            function(params) {{
                const units = {units_json};

                let formattedDate = params[0].name;
                let res = '<div style="font-size:13px; font-weight:bold; margin-bottom:10px;">' + formattedDate + '</div>';

                params.forEach(item => {{
                    let val = Array.isArray(item.value) ? item.value[1] : item.value;
                    if (val === null || val === undefined) return;
                    
                    let idx = item.seriesIndex;
                    // Nếu units[idx] không tồn tại, mặc định là 'qty'
                    let type = (units && units[idx]) ? units[idx] : 'qty'; 
                    
                    let displayVal = '';

                    if (type === 'pct') {{
                        // Định dạng phần trăm
                        displayVal = (val * 100).toFixed(1) + '%';
                    }} else if (type === 'decimal') {{
                        // Định dạng số thập phân (2 chữ số)
                        displayVal = Number(val).toLocaleString(undefined, {{
                            minimumFractionDigits: 2, 
                            maximumFractionDigits: 2
                        }});
                    }} else if (type === 'qty') {{
                        // Định dạng số nguyên thuần túy
                        displayVal = Math.round(val).toLocaleString();
                    }} else {{
                        // (VNĐ, kg, USD...) 
                        // Tự hiểu là qty + suffix
                        displayVal = Math.round(val).toLocaleString() + ' ' + type;
                    }}
                    res += '<div style="display:flex;justify-content:space-between;gap:20px; margin-bottom: 6px;">' +
                        '<span style="font-weight:400;">' + item.marker + item.seriesName + '</span>' + 
                        '<span style="font-weight:550; font-size:13px; font-variant-numeric:tabular-nums;\
                            font-family: "JetBrains Mono", "Roboto Mono";\
                            ">' + displayVal + '</span>' + 
                        '</div>';
                }});

                return res;
            }}
        """)
    y_label_formatter = JsCode(f"""
        function(value) {{
            const units = {units_json};
            const type = units[0] || 'qty';
            if (type === 'pct') {{
                return (value * 100).toFixed(0) + '%';
            }}
            if (type === 'decimal') {{
                return value.toLocaleString(undefined, {{
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                }});
            }}
            var absVal = Math.abs(value);
            var sign = value < 0 ? '-' : '';
            if (absVal >= 1000000000)
                return sign + parseFloat((absVal / 1000000000).toFixed(1)) + 'B';
            if (absVal >= 1000000)
                return sign + parseFloat((absVal / 1000000).toFixed(1)) + 'M';
            if (absVal >= 1000)
                return sign + parseFloat((absVal / 1000).toFixed(1)) + 'k';
            return value % 1 === 0 ? value.toLocaleString() : value.toFixed(1);
        }}
    """)
    max_y = JsCode("""
        function (value) {
            const max = value.max * 1.1;
            const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
            const normalized = max / magnitude;
            if (normalized <= 1)      return 1 * magnitude;
            if (normalized <= 1.5)    return 1.5 * magnitude;
            if (normalized <= 2)      return 2 * magnitude;
            if (normalized <= 2.5)    return 2.5 * magnitude;
            if (normalized <= 5)      return 5 * magnitude;
            return 10 * magnitude;
        }
    """)
    options = {
        "color": colors,
        "animation": True,
        "animationDuration": 150,
        "animationDurationUpdate": 150,
        "animationEasingUpdate": "cubicOut",
        "backgroundColor": 'transparent',
        "tooltip": {
            "trigger": 'axis',
            "confine": True,
            "backgroundColor": 'rgba(255, 255, 255, 0.95)',
            "formatter": tooltip_formatter
        },
        "legend": {
            "width": "80%",
            "top": 5, 
            "icon": 'circle',
            "textStyle": {
                "fontSize": 12,
            }
        },
        "grid": {
            "left": '10', "right": '10', "bottom": '0', "top": '15%', "containLabel": False 
        },
        "xAxis": {
            "type": "category",
            "boundaryGap": True, # Cách 2 lề
            "axisLabel": {
                "color": '#999',
                "fontSize": 11,
                "lineHeight": 14,
                "hideOverlap": True,
                "interval": 6 if view == '1d' else 'auto'
            },
            "axisLine": { "lineStyle": { "color": '#eee' } }
        },
        "yAxis": [
            {
                "type": 'value',
                "max": max_y,
                "axisLabel": { "showMinLabel": False, "color": '#999', "fontSize": 12, "formatter": y_label_formatter},
                "splitLine": { "lineStyle": { "type": [4, 5], "color": "rgba(0,0,0,0.075)" }},
            },
            {
                "type": 'value',
                "splitLine": { "show": False },
                "axisLabel": { "showMinLabel": False, "color": '#AAA', "fontSize": 11, "formatter": y_label_formatter }
            }
        ],
        "series": series,
        "toolbox": {
            "show": False,
            "showTitle": False,
            "right": -10,
            "top": -12,
            "tooltip": {
                "show": True,
                "position": "top",
                "textStyle": {
                    "fontSize": 14
                }
            },
            "feature": {
                "magicType": {"show": True, "type": ["stack"]},
            }
        }
    }
    events  = {
        'click': 'function(params) { return {when: params.value[0]}; }'
        }
    if period is None:
        st_echarts(options=options, height=f'{height}px', key=key)
    else:
        st_echarts(
            options     = options,
            height      = f'{height}px',
            events      = events,
            key         = key,
            on_select   = 'rerun',
            on_change   = j_callback(key, view, period)
        )
@supreme
def _compute_range(
    period, view, idx, sales_data
) -> pl.DataFrame:
    spine = pl.select(period).with_columns(pl.all().dt.truncate(view)).unique()
    try:
        date_spine = spine[idx].to_series()
    except IndexError:
        date_spine = spine[0].to_series()
    start = date_spine.item()
    end   = date_spine.dt.offset_by(view).item()
    return sales_data.filter(pl.col(S.date).is_between(start, end, closed='left')).with_columns(pl.col(S.invoice).cast(pl.String()))
def j_callback(
        key    : str,
        view   : str,
        period : pl.Expr
        ):
    from core import get_sys_brief_cache
    sales     = get_sys_brief_cache().get('sales_data')
    event     = SS.get(key, {})
    selection = event.get('selection', {}).get('points', [])
    if not selection or not event.get('chart_event'):
        return
    
    idx = selection[0].get('point_index', 0)
    df  = _compute_range(period, view, idx, sales)  # pool

    @st.dialog(f'{event['chart_event']['when']}', width='large', icon=':material/event:')
    def j_dialog(df: pl.DataFrame):
        categorials = [S.date, S.invoice, S.staff, S.cat, S.sku]
        one, two, three, four = st.columns([2, 1, 1, 3], gap='medium')

        group_by = one.multiselect('Group by', options=categorials, placeholder='One or multiple columns')
        if group_by:
            df = supreme(lambda: df.group_by(group_by, maintain_order=True).agg([
                expr for col, expr in {
                    S.invoice : pl.col(S.invoice).n_unique(),
                    S.qty     : pl.col(S.qty).sum(),
                    S.revenue : pl.col(S.revenue).sum(),
                    S.traffic : pl.col(S.traffic).first()
                }.items() if col not in group_by
            ]))()

        result = df
        filter_by = two.selectbox('Filter by', options = ['All'] + supreme(lambda: [c for c in categorials if c in df.columns])())
        if filter_by != 'All':
            value = three.selectbox(
                label   = 'Value',
                options = ['All'] + supreme(lambda: df[filter_by].unique(maintain_order=True).sort().to_list())()
                )
            if value != 'All':
                result = supreme(lambda: df.filter(pl.col(filter_by) == value))()

        with four.container(horizontal=True):
            for k, v in supreme(lambda: [('Total ' + c.replace('_', ' ').title(), result[c].sum()) for c in [S.qty, S.revenue]])():
                st.metric(k, v, format='%,d')
        col_kinds  = supreme(lambda: {
            'numeric' : [c for c in result.select(cs.numeric()).columns],
            'temporal': [c for c in result.select(cs.temporal() - cs.time()).columns]
        })()
        col_config = {
            c:  st.column_config.NumberColumn(c, format='%,d')
                if kind == 'numeric' else
                st.column_config.DateColumn(c, format='DD-MM-YYYY')
            for kind, col in col_kinds.items()
            for c in col
        }
        st.dataframe(result, column_config=col_config, placeholder='-', height=700)

    j_dialog(df)

@supreme
def grow_tree(
    df       : pl.DataFrame,
    layers   : list[str],
    values   : dict,
    val_unit : list[str],
    sqrt     : bool = False
    ) -> dict:
    """
    Note: The first name in `values` will be main value for treemap chart
    - The second name in `values` if exist will be shows as secondary info
    """
    # region Guardian
    if len(values) != len(val_unit):
        raise ValueError('Length of values and val_unit must be equal.')
    if len(values) != len(set(values)):
        raise ValueError('Value name must be unique.')
    if not set(values).issubset(df.select(cs.numeric()).columns):
        raise ValueError('Value columns must be Numeric format.')
    if not set(layers).issubset(df.columns):
        raise ValueError('Layers columns must be String format.')
    # endregion

    re_values = values.copy()
    re_values[[*re_values.keys()][0]] = 'value'
    rename_df = df.rename(re_values)
    temp_vals = list(re_values.values()) 

    aggs   = rename_df.group_by(layers).agg(pl.col(temp_vals).sum())
    root   = {'children': {}}
    colors = [
        "#A2DBBB", "#DC9FA9", "#9ACAD9", "#BCE0B3", "#CDB2DC",
        "#94A9DC", "#B0A1DC", "#93D5C9", "#DCBCA0", "#A3B1DC",
        "#99DDD8", "#DCD29B", "#C5A4DC", "#E6B1BA", "#F5CDAC",
        "#DCB49A", "#A8DE9A", "#BCE098", "#A6DDD2", "#DCA59B"
    ]
    for row in aggs.to_dicts():
        cursor = root # Reset cursor to outter root
        for col in layers:
            child = cursor['children']
            if (item:=row[col]) is None:
                item = 'undefined'
            if item not in child:
                color = colors[int(hashlib.md5(item.encode()).hexdigest(), 16) % len(colors)]
                child[item] = {'name': item, **{v: 0 for v in temp_vals}, 'itemStyle' : {'color': color}, 'children': {}}
            for val in temp_vals:
                child[item][val] += row[val]
            cursor = child[item] # Set cursor to inner node

    def child_to_list(node: dict):
        if sqrt:
            val = node.get('value')
            if val is not None:
                node['rawValue'] = val
                node['value']    = val ** (1/2)
        node['children'] = [child_to_list(node=d) for d in node['children'].values()]
        return node
    return {
        'tree_data': child_to_list(root)['children'],
        'val_total': aggs.get_column('value').sum(),
        'val_names': [*values.values()],
        'val_unit' : val_unit
        }
@st.fragment(parallel=True)
def treemap_chart(
    tree_data : list,
    val_total : int,
    val_names : list[str],
    val_unit  : list[str],
    chart_id  : str = 'treemap_chart',
    height    : int = 370,
    home_name : str = 'Home',
    ):
    _1st_val,  *_rest_val  = val_names
    _1st_unit, *_rest_unit = val_unit
    val_total_js    = val_total if val_total else 0
    extra_fields_js = json.dumps([ 
        {'key': k, 'unit': u, 'title': k.title()}
            for k, u in zip(_rest_val, _rest_unit)
        ]) # (index 1 trở đi) -> tooltip tự loop và hiển thị theo đúng thứ tự
    _2nd_key_js     = json.dumps(_rest_val[0]) if _rest_val else 'null' # Dual purpose (key & bool check)
    formatter       = f"""
        {darken_Js}
        {num_format_Js}
        var val = (params.name === '{home_name}') 
        ? {val_total_js} 
        : ((params.data && params.data.rawValue) ? params.data.rawValue : params.data.value);
        if (val === undefined || isNaN(val)) return params.name;
        var totalVal   = {val_total_js};
        var percentStr = '';
        if (totalVal > 0) {{
            var percent = (val / totalVal) * 100;
            percentStr  = ' (' + percent.toFixed(1) + '%)';
        }}
        var formatted = formatNumber(val);
        var secondKey = {_2nd_key_js};
        var secondVal = (secondKey && params.data && params.data[secondKey]) ? params.data[secondKey] : 0;
        """
    tooltip_js      = JsCode(f"""
        function (params) {{
        {formatter}
            var itemColor = params.color ? darken(params.color) : '#0f172a';
            var extraFields = {extra_fields_js};
            var extraLines  = '';
            extraFields.forEach(function (f) {{
                var v = (params.data && params.data[f.key] !== undefined) ? params.data[f.key] : 0;
                extraLines += '<br/><span style="color:#64748b;">' + f.title + ':</span> ' +
                    '<b style="color:' + itemColor + '; font-size:15px; font-weight:550;">' + formatNumber(v) + ' ' + f.unit + '</b>';
            }});
            return '<div style="font-size:17px; font-weight:600; margin-bottom:6px; color:' + itemColor + ';">' + params.name + '</div>' +
                '<span style="color:#64748b;">{_1st_val.title()}:</span> ' +
                '<b style="color:' + itemColor + '; font-size:15px; font-weight:550;">' + formatted + ' {_1st_unit}' + percentStr + '</b>' +
                extraLines;
        }}
    """)
    label_js        = JsCode(f"""
        function (params) {{
            {formatter}
            var _2nd_str  = (secondVal && secondVal > 0) ? ' {{second_Style|' + formatNumber(secondVal) + ' {_rest_unit[0] if _rest_unit else ''}}}' : '';
            // *_Style là tham số tự đặt, tùy biến ở options.series.label.rich
            var separator = (secondVal && secondVal > 0) ? ' |' : '';
            return params.name + '\\n{{first_Style|' + formatted + percentStr + separator + '}}' + _2nd_str;
        }}
    """)
    options         = {
        "tooltip": {
            "show": True,
            "trigger": "item",
            # "position": ['77%', '-18%'],
            "position": JsCode("""
                function (pos) {
                    var shiftX = pos[0] - 50
                    return [shiftX, '-18%'];
                }
            """),
            "confine": False,
            "transitionDuration": 1,
            "backgroundColor": "rgba(255, 255, 255, 0.99)",
            "borderColor": "#eee",
            "borderWidth": 1,
            "textStyle": {"color": "#3A3A3A", "fontSize": 14, "fontWeight": "500"},
            "formatter": tooltip_js
        },
        "series": [
            {   
                "name": home_name,
                "type": "treemap",
                "data": tree_data,
                "sort": "desc",
                "left"  : "0%",
                "right" : "0%",
                "top"   : "0%",
                "leafDepth": 1,
                "nodeClick": "zoomToNode",
                "roam": True,
                "breadcrumb": {"show": True},
                "animation": True,
                "animationDuration": 300,
                "animationEasing": "cubicOut",
                "animationDurationUpdate": 200,
                "animationEasingUpdate": "elasticOut",
                "upperLabel": {
                    "show": True,
                    "height": 29,
                    "color": "#3E4D74",
                    "fontWeight": 700,
                    "fontSize": 12,
                    "formatter": label_js,
                    "rich": {
                        "first_Style": {
                            "fontWeight": "500",
                            "fontSize": 13,
                            "color": "#6D7C88"
                        },
                        "second_Style": {
                            "fontWeight": "600",
                            "fontSize": 13,
                            "color": "#676690",
                        }
                    }
                },
                "label": {
                    "show": True,
                    "icon": "none",
                    "position": "inside",
                    "formatter": label_js,
                    "textStyle": {
                        "color": "#ffffff",
                        "fontSize": 11.5
                    },
                    # Trong js label_js có tạo custom first_Style / second_Style
                    "rich": {
                        "first_Style": {
                            "fontWeight": "bold",
                            "fontSize": 12,
                            "color": "#fff",
                            "lineHeight": 24
                        },
                        "second_Style": {
                            "fontWeight": "600",
                            "fontSize": 12,
                            "color": "#3E4D74",
                        }
                    }
                },
                "itemStyle": {
                    "borderColor": "transparent",
                    "borderWidth": 1.5,
                    "gapWidth": 1,
                    "borderRadius": 6
                }
            }
        ],
    }
    st_echarts(options=options, key=chart_id, height=f'{height}px')
#endregion


