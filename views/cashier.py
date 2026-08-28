from pathlib import Path
from widget.pos import *


#region Page configs
SS.page_name  = Path(__file__).stem
metric_style  = """
    <style>
        [data-testid="stMetricLabel"] p {
            color: #49618D !important;
            font-weight: 500 !important;
            font-size: 18px !important;
        }
        [data-testid="stMetricValue"] div {
            color: #396996 !important;
            font-weight: 400 !important;
            font-size: 40px !important;
            letter-spacing: 2px !important;
            font-family: Inter !important;
        }
    </style>
    """
contain_style = """
    <style>
    .st-key-checkout_container,
    .st-key-barcode_container,
    .st-key-basket_container {
        # background-color: #6CA6DC !important;
        border: 1px solid #77AAD9 !important;
        padding: 1.2rem;
    }
    div[data-testid="stButton"] button p {
        font-family: monospace !important;
    }
    </style>
"""
off_scroll    = """
    <style>
    section[data-testid="stMain"] {
        scrollbar-width: none;
        -ms-overflow-style: none;
    }
    section[data-testid="stMain"]::-webkit-scrollbar {
        display: none;
    }
    </style>
    """
st.html(contain_style)
st.html(metric_style)
st.html(off_scroll)
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
                line-height:1;
                margin-top:2px;
            ">{sub.replace('\n', '<br>')}</div>
            '''
            if sub else ''
        }
        """
    )
#endregion

#region POS cached data / keys
bar_key     = 'Basket_barcode'
qty_key     = 'Basket_quantity'
serial_key  = 'Basket_serial'

Cached      = briefcache()
stock_df    = Cached.get('inventory')
inv_list    = Cached.get('invoice')
customer_df = Cached.get('customer')
serial_dict = Cached.get('serial')
staff_dict  = Cached.get('staff')
#endregion

@st.fragment
def the_cashier(
    stock_df     : pd.DataFrame,
    customer_df  : pd.DataFrame,
    serial_dict  : dict,
    staff_dict   : dict,
    invoice_list : list,
    bar_key      : str,
    qty_key      : str,
    serial_key   : str
    ):
    """
    Render the POS cashier interface.

    The product frame acts as the source context for product information,
    pricing, and stock availability. `basket_grid()` uses this context to
    construct an independent, constraint-aware basket that owns the complete
    checkout state.

    The basket is the checkout dataset itself; no separate cart-to-checkout
    transformation is required.
    """

    def random_barcode():
        has_stock   = stock_df[c.Stock] > 0
        SS[bar_key] = stock_df.loc[has_stock, 'id'].sample(1).item()

    ORDER, PAYMENT = st.columns([2.5, 1])

    with ORDER:
        if not 'empty_cart' in SS:
            SS.empty_cart   = pd.DataFrame(columns=c.Schema.keys()).astype(c.Schema)
        if not 'pre_cart' in SS:
            SS.pre_cart     = SS.empty_cart
        if SS.get('rerun'): # Rerun sau khi checkout
            SS.rerun = False
            st.rerun(scope='app')
        to_cart, barcode, p_name, p_price, p_stock = prep_to_cart(stock_df, bar_key, qty_key, serial_key)
        
        # Scanner UI
        with st.container(border=True, key='barcode_container'):
            # Barcode input
            with st.container(border=False, horizontal=True, vertical_alignment='bottom'):
                st.text_input(
                    label       = ":color[**Barcode**]{foreground='#6680B5'}",
                    max_chars   = 20,
                    placeholder = 'Scan',
                    key         = bar_key,
                    icon        = ':material/barcode_reader:',
                    label_visibility = 'visible'
                )
                if barcode in serial_dict:
                    st.selectbox(
                        label       = ":color[**Serial**]{foreground='#6680B5'}",
                        options     = sorted(serial_dict[SS[bar_key]]['serial_list']),
                        key         = serial_key,
                        placeholder = 'Select one',
                        width       = 200
                        )
                else:
                    st.number_input(
                        label       = ":color[**Quantity**]{foreground='#6680B5'}",
                        min_value   = min(p_stock, 1),
                        max_value   = max(p_stock, 1),
                        key         = qty_key,
                        width       = 200
                        )
                st.button(
                    label       = ":color[:material/shopping_bag: ADD]{foreground='#6680B5'}",
                    type        = 'secondary', 
                    key         = 'btn_add',
                    on_click    = add_to_cart,
                    args        = (to_cart, bar_key, qty_key, serial_key)
                    )
                st.button(
                    label       = ":color[:material/shuffle: Random item]{foreground='#6680B5'}",
                    type        = 'secondary', 
                    key         = 'btn_add_random',
                    on_click    = random_barcode
                    )

            # Show product name & price
            info_style = lambda x: f":color[{str(x).strip()}]{{foreground='#001A80'}}"
            with st.container(border=False, horizontal=True, horizontal_alignment='left'):
                st.caption(info_style(f'**{p_name}**'), width=815)
                st.caption(info_style(f'**{p_price:,.0f} VNĐ**') if isinstance(p_price, int) else p_price, width='content')
                st.caption(info_style(f'**{p_stock:02d} Pcs**' if p_stock else ':red[**OUT OF STOCK**]' if barcode else ''), width='content')
 
        # Basket Grid
        col_config = {
            'sku'           : 1.1,
            'product name'  : 3,
            'price'         : 1,
            'Qty / serial'  : 1,
            'disc'          : 1,
            c.Total         : 1,
            ''              : 0.4
        }
        ready_checkout = basket_grid(col_config, SS.empty_cart, 'pre_cart', bar_key)

    with PAYMENT:
        with st.container(border=True, height='stretch', key='checkout_container'):
            st.subheader(':material/shopping_cart_checkout: Checkout')
            lookup_invoice(invoice_list)
            #region Sales Person
            sp_key    = 'pos_sales_person'
            sp_label  = f':blue[**Sales Person:**] :orange-badge[{staff_dict.get(SS.get(sp_key))}]'
            sp_pander = st.expander(sp_label, icon=':material/manage_accounts:', key='expander_' + sp_key, on_change='rerun')
            sp_pander.caption(':blue[:material/edit: Confirm selection on collapsing]')
            staff_id  = pos_staff(staff_dict, expander=sp_pander, key=sp_key)
            #endregion
            with st.expander(
                # NOTE: Widget bên trong expander đổi state → flag rerun.
                # flag chỉ đánh dấu change, chưa rerun.
                # Đóng expander → mới kích hoạt rerun.
                label     = ':blue[**Customer**]',
                width     = 'stretch',
                icon      = ':material/id_card:',
                on_change = 'rerun'
                ):
                st.caption(':blue[:material/edit: Select a customer and collapse to confirm]')
                cus_dict  = lookup_customer(customer_df) or {}

            metrics = pos_metrics(ready_checkout, cus_dict)
            balance = metrics['balance']
            cus_id  = metrics['cus_id']
            payment = pos_payment(balance)
            if sum(payment.values()) == balance and balance and staff_id:
                pos_save_button(
                    checkout_df = ready_checkout,
                    customer_id = cus_id,
                    staff_id    = staff_id,
                    payment     = payment
                )

sub = """
    <div style="font-size: 0.85rem; color: #6880AA; line-height: 1.5; margin-bottom: 35px; margin-top: 0px;">
        Click <strong>'Random item'</strong> to mimick scanning a product.
        <br>
        Then <strong>'Add'</strong> to basket (Quantity input will switch to Serial selectbox if the product requires).
        <br>
        <div style="font-size: 0.75rem; font-style: normal; color: #8AA0C4; margin-top: 5px;">
        * Product info based on availability and simulated.
        </div>
    </div>
    """
st.title('Point of Sales')
st.markdown(sub, unsafe_allow_html=True)
the_cashier(stock_df, customer_df, serial_dict, staff_dict, inv_list, bar_key, qty_key, serial_key)






