import polars as pl
from datetime import datetime
from zoneinfo import ZoneInfo

class Schema:
    class Format:
        week  = '%y-W%V (%d %b)'
        month = '%Y-%m'

    class Sales:
        store_id   = 'store_id'
        time       = 'time'
        date       = 'date'
        week       = 'week'
        month      = 'month'
        year       = 'year'

        invoice    = 'invoice'
        staff      = 'staff'
        ean        = 'ean'
        sku        = 'sku'
        prod_name  = 'product_name'
        lot        = 'lot_number'
        cat        = 'cat'
        subcat     = 'sub_cat'

        qty        = 'qty'
        price      = 'price'
        revenue    = 'revenue'

        disc_pct   = 'disc_percent'
        disc_amt   = 'disc_amount' 

        cash       = 'cash'
        card       = 'card'
        payoo      = 'payoo'
        banking    = 'banking'
        mkt        = 'mkt_promo'
        vnpay      = 'vnpay'
        trade_in   = 'trade_in'

        cus_id     = 'id'
        cus_name   = 'name'
        cus_email  = 'email'
        traffic    = 'date_traffic'
        event_name = 'event_name'

        name_mapping = {
            0: date,
            1: invoice,
            2: staff,
            3: ean,
            4: cat,
            5: lot,
            6: sku,
            7: prod_name,
            8: price,
            9: qty,
            10: disc_pct,
            11: disc_amt,
            12: revenue,
            13: cash,
            14: card,
            15: payoo,
            16: banking,
            17: mkt,
            18: vnpay,
            19: trade_in,
            20: cus_email,
            21: cus_name,
            22: cus_id,
            23: time,
            24: traffic,
            25: event_name,
            26: subcat
        }

    class Stock:
        date       = 'date'
        prod_name  = 'product_name'
        lot        = 'lot_number'
        start      = 'start'
        import_po  = 'import_po'
        import_do  = 'import_do'
        stock_take = 'stock_take'
        transfer   = 'transfer'
        noname_1   = 'noname_1'
        noname_2   = 'noname_2'
        sell       = 'sell'
        returns    = 'return'
        rtv        = 'rtv'
        noname_3   = 'noname_3'
        noname_4   = 'noname_4'
        end        = 'end'
        sku        = 'sku'
        cat        = 'cat'
        subcat     = 'sub_cat'
        price      = 'price'

class Drive:
    folder_id   : str = '1f5YXBV-WgLJLfCsIDqIy5x_X2k2EhV5y'
    ledger_id   : str = '1EM0gi30at2Rb4cnxCr-C2vZ6CQl3PwpH'
    ledger_name : str = 'ETP_stock_ledger.parquet'
    sales_id    : str = '18Y60_QRa2n_XYoBy4NdZ_0WHDYOMU8MU'
    sales_name  : str = 'apple_sales_data.csv'
    file_list   : list = ['ETP_stock_ledger.parquet', 'apple_sales_data.csv']

def pl_info(df: pl.DataFrame):
    if isinstance(df, pl.LazyFrame):
        df_eager = df.collect()
    else:
        df_eager = df

    # Ép nó print đầy đủ dòng
    pl.Config.set_tbl_rows(-1)

    df_info = pl.DataFrame({
        'Column': df_eager.schema.names(),
        'Dtype' : df_eager.schema.dtypes(),
        'Null'  : df_eager.null_count().row()
    })
    print(f'Rows: {df_eager.height} | Columns: {df_eager.width}')
    print(df_info)

def custom_sort(char):
    if not isinstance(char, str) or not char: return (5, char)
    c = char.upper()
    
    if c.startswith('ALL'): return (0, char)
    if c.startswith('IPH'): return (1, char)
    if c.startswith('IPA'): return (2, char)
    if c.startswith('MAC'): return (2, char)
    if c.startswith('WAT'): return (2, char)
    if c.startswith('A'):   return (4, char)
    if c[0].isalpha():      return (3, char)
    
    return (5, char)

def today_hanoi():
    """
    ### Không sợ lệch múi giờ server Streamlit.
    """
    return datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).date()
