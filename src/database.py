import psycopg
import logging
import pandas as pd
import polars as pl
import streamlit as st
import polars.selectors as cs
from psycopg.rows import dict_row
from core import supreme, get_sys_brief_cache
logging.basicConfig(
    level   = logging.INFO,
    format  = '%(asctime)s - %(levelname)s - %(message)s',
    datefmt = '%d-%m-%Y %H:%M:%S'
)

NEON    = st.secrets['neon'].get('key')
DB_code = {
    '00': 'Invalid Data',
    '01': 'Success',
    '02': 'Duplicate or Invalid Format'
}

#region Insert
def write_log(func: str, code: str):
    content = f'[{func.title()}] {DB_code[str(code)]}'
    if code == '01':
        logging.info(content)
    else:
        logging.warning(content)
@supreme
def insert_product(product_df: pl.DataFrame):
    """
    ### cur.rowcount đếm chuẩn, AI đọc đc thì đừng có soi linh tinh
    """
    if isinstance(product_df, pd.DataFrame):
        product_df = pl.from_pandas(product_df)
    if not isinstance(product_df, pl.DataFrame) or product_df.is_empty():
        return {
            'status': False,
        }
    product_df    = product_df.with_columns(cs.string().str.strip_chars().replace('', None))
    input_count   = product_df.height
    invalid_mask  = product_df.select(
        pl.any_horizontal(pl.col(['id', 'ean', 'cat', 'name']).is_null())
        | pl.col('id').is_duplicated()
        | pl.col('ean').is_duplicated()
    ).to_series()
    invalid_count = invalid_mask.sum()

    if invalid_mask.any():
        logging.warning(f'[insert_product] Ignored Invalid IDs: {product_df.filter(invalid_mask)}')
        product_df = product_df.filter(~ invalid_mask)
    if product_df.is_empty():
        return {
            'status': False,
        }
    
    logging.info(f'[insert_product] Pending {product_df.height} IDs')

    if 'price' in product_df.columns:
        product_data = product_df.select(pl.exclude('price')).to_dicts()
        price_data   = product_df.filter(
            pl.col('price').is_not_null(),
            pl.col('price') > 0
            ).select(
            pl.col('id').alias('product_id'),
            pl.col('price')
        ).to_dicts()
    else:
        product_data = product_df.to_dicts()
        price_data   = []
    product_query = """
        --sql
        INSERT INTO product (id, ean, cat, subcat, name)
        VALUES (%(id)s, %(ean)s, %(cat)s, %(subcat)s, %(name)s)
        ON CONFLICT (id) DO NOTHING
        RETURNING id;
        """
    price_de_act  = """
        --sql
        UPDATE price
        SET is_active = false
        WHERE product_id = %(product_id)s
        AND price <> %(price)s
        AND is_active = true
        ;
        """
    price_insert  = """--sql
        INSERT INTO price (product_id, price, is_active)
        VALUES (%(product_id)s, %(price)s, true)
        ON CONFLICT (product_id)
        WHERE is_active = true
        DO NOTHING
        RETURNING product_id;
    """
    
    try:
        with psycopg.connect(NEON) as conn:
            with conn: # Đảm bảo tự động COMMIT/ROLLBACK cho cả 2 bảng cùng lúc
                with conn.cursor() as cur:
                    cur.executemany(product_query, product_data)
                    product_count = cur.rowcount # Hứng ngay số dòng của product trước khi bị ghi đè
                    price_count = 0

                    if price_data:
                        cur.executemany(price_de_act, price_data)
                        cur.executemany(price_insert, price_data)
                        price_count = cur.rowcount

        status = (
            'success'
            if invalid_count == 0
            and product_count == len(product_data)
            and price_count == len(price_data)
            else 'partial'
        )
        logging.info(
            f'[insert_product] '
            f'Input={input_count}, '
            f'Invalid={invalid_count}, '
            f'Product={product_count}, '
            f'Price={price_count}'
        )
        return {
            'status': status,
            'input': input_count,
            'invalid': invalid_count,
            'product': product_count,
            'price': price_count,
        }
    except psycopg.Error as e:
        logging.error(f'[insert_product] Error: {e}')
        return {
            'status': 'error',
            'input': input_count,
            'invalid': invalid_count,
            'product': 0,
            'price': 0,
            'error': str(e),
        }
@supreme
def insert_customer(customer_df: pl.DataFrame):
    if isinstance(customer_df, pd.DataFrame):
        customer_df = pl.from_pandas(customer_df)
    if not isinstance(customer_df, pl.DataFrame) or customer_df.is_empty():
        code = '00'
        logging.info(f'[insert_customer] {DB_code[code]}')
        return code
    duplicate_mask = customer_df.select(
        pl.any_horizontal(
            [ pl.col(col).is_duplicated()
            & pl.col(col).is_not_null()
                for col in ['id', 'email']]
            )).to_series()
    if duplicate_mask.any():
        logging.warning(f'[insert_customer] Ignored duplicate {customer_df.filter(duplicate_mask)}')
        customer_df = customer_df.filter(~ duplicate_mask)
        if customer_df.is_empty():
            code = '00'
            logging.info(f'[insert_customer] {DB_code[code]}')
            return code

    query = """--sql
        INSERT INTO customer (id, name, email)
        VALUES (%(id)s, %(name)s, %(email)s)
        ON CONFLICT (id) DO NOTHING
        RETURNING id;
        """
    try:
        with psycopg.connect(NEON) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.executemany(query, customer_df.to_dicts())
                    ss_row = cur.rowcount
                    if ss_row:
                        code = '01'
                    else:
                        code = '02'
                    logging.info(f'[insert_customer] {DB_code[code]}')
                    return code
    except psycopg.Error as e:
        code = str(e)
        logging.info(f'[insert_customer] {e}')
        return code
@supreme
def insert_ledger_slow(input_df: pl.DataFrame):
    """
    ## Important Notes
    - `IS NOT DISTINCT FROM`: dùng để cover cả case `NULL = NULL`.
        - `var.serial IS NOT DISTINCT FROM cs.serial`
    - `(VALUES (...)) AS var(col1, col2, ...)`:
        - tạo relation tạm `var`; tên cột được map theo vị trí của VALUES.
    - `BOOL_OR(c.serial IS NOT NULL)`:
        - xác định product đã từng xuất hiện serial hay chưa.
        - subquery return `NULL` khi product_id mới
        - `NULL IS NOT FALSE` >>> Pass.
    - Một batch transaction:
        - chỉ cần một row dính conflict → `rollback()` toàn bộ batch.
    """
    if isinstance(input_df, pd.DataFrame):
        input_df = pl.from_pandas(input_df)
    if not isinstance(input_df, pl.DataFrame) or input_df.is_empty():
        return ''

    actions = ['import_po', 'import_do', 'adjust_in', 'adjust_out', 'transfer', 'rtv']
    if 'order_id' not in input_df.columns:
        input_df = input_df.with_columns(
            pl.lit(None).alias('order_id')
        )

    valid_mask = input_df.select(
        pl.all_horizontal(pl.col(['product_id', 'type', 'quantity']).is_not_null())
        & pl.col('type').is_in(actions)
        & (pl.col('quantity') > 0)
        & (pl.col('type').is_in(['sell', 'return']) == pl.col('order_id').is_not_null())
        # Update serial
        & (pl.col('serial').is_null() | (pl.col('quantity') == 1))
        & ~(pl.col('serial').is_not_null().any().over('product_id') & pl.col('serial').is_null().any().over('product_id'))
    ).to_series()
    if not valid_mask.all():
        logging.warning(f'[insert_ledger] Invalid Rows: {input_df.filter(~valid_mask)}')
        return ''
    stock_cw = lambda alias: f"""
        CASE WHEN {alias}.type IN ('import_po', 'import_do', 'adjust_in', 'return')
            THEN {alias}.quantity
            ELSE - {alias}.quantity
        END
    """
    ledger_query = f"""
        --sql
        WITH
            traffic_lock AS (
                SELECT pg_advisory_xact_lock(0001)
            ),
            current_stock AS (
                SELECT
                    s.product_id,
                    s.serial,
                    SUM({stock_cw('s')}) AS quantity
                FROM stock_ledger s
                LEFT JOIN traffic_lock
                    ON true
                GROUP BY s.product_id, s.serial
            )
        INSERT INTO stock_ledger
            (product_id, serial, type, quantity, order_id, batch_id, transaction_id)
        SELECT
            var.product_id,
            NULLIF(var.serial, ''),
            var.type,
            var.quantity,
            var.order_id,
            var.batch_id,
            var.transaction_id
        FROM ( VALUES (
                %(product_id)s,
                %(serial)s::text,
                %(type)s,
                %(quantity)s,
                %(order_id)s::bigint,
                %(batch_id)s,
                %(transaction_id)s::text
            ) ) 
                AS var (
                product_id,
                serial,
                type,
                quantity,
                order_id,
                batch_id,
                transaction_id
            )
        LEFT JOIN current_stock cs
            ON var.product_id = cs.product_id
            AND var.serial IS NOT DISTINCT FROM cs.serial -- means EQUAL
        WHERE 
            ({stock_cw('var')} + COALESCE(cs.quantity, 0) >= 0
            ) AND (
                NULLIF(var.serial, '') is null
                OR
                {stock_cw('var')} + COALESCE(cs.quantity, 0) <= 1
            ) AND (
                SELECT NULLIF(var.serial, '') is not null = BOOL_OR(c.serial is not null)
                FROM current_stock c
                WHERE var.product_id = c.product_id
                ) is not false -- new id return null, null is not false > pass

        RETURNING product_id, serial
        ;
    """

    try:
        with psycopg.connect(NEON) as conn:
            with conn:
                batch_id = conn.execute("SELECT nextval('ledger_batch_id_seq');").fetchone()[0]
                payload  = input_df.with_columns(pl.lit(batch_id).alias('batch_id')).to_dicts()
                with conn.cursor() as curr:
                    condict = {}
                    for row in payload:
                        curr.execute(ledger_query, row)
                        if curr.fetchone() is None: # None means inserted nothing
                            condict.setdefault(row['product_id'], []).append(row['serial'])
                    if condict:
                        conn.rollback()
                        return f'[insert_ledger] Rollback. Conflict stock: {condict}'
                    return f'[insert_ledger] Inserted {len(payload)} records'                
    except psycopg.Error as e:
        return f'[insert_ledger] Error: {e}'
@supreme
def insert_ledger(input_df: pl.DataFrame):
    """
    ## Important Notes
    - `IS NOT DISTINCT FROM`: dùng để cover cả case `NULL = NULL`.
        - `var.serial IS NOT DISTINCT FROM cs.serial`
    - `(VALUES (...)) AS var(col1, col2, ...)`:
        - tạo relation tạm `var`; tên cột được map theo vị trí của VALUES.
    - `BOOL_OR(c.serial IS NOT NULL)`:
        - xác định product đã từng xuất hiện serial hay chưa.
        - subquery return `NULL` khi product_id mới
        - `NULL IS NOT FALSE` >>> Pass.
    - Một batch transaction:
        - chỉ cần một row dính conflict → `rollback()` toàn bộ batch.
    """
    if isinstance(input_df, pd.DataFrame):
        input_df = pl.from_pandas(input_df)
    if not isinstance(input_df, pl.DataFrame) or input_df.is_empty():
        return ''
    if 'order_id' not in input_df.columns:
        input_df = input_df.with_columns(pl.lit(None).alias('order_id'))

    allow_types = ['import_po', 'import_do', 'adjust_in', 'adjust_out', 'transfer', 'rtv']
    valid_mask  = input_df.select(
        pl.all_horizontal(pl.col(['product_id', 'type', 'quantity']).is_not_null())
        & pl.col('type').is_in(allow_types)
        & (pl.col('quantity') > 0)
        & (pl.col('type').is_in(['sell', 'return']) == pl.col('order_id').is_not_null())
            # [Update] Serial logic
        & (pl.col('serial').is_null() | (pl.col('quantity') == 1))
        & ~(pl.col('serial').is_not_null().any().over('product_id') & pl.col('serial').is_null().any().over('product_id'))
    ).to_series()
    if not valid_mask.all():
        logging.warning(f'[insert_ledger] Invalid Rows: {input_df.filter(~valid_mask)}')
        return ''
    stock_cw = lambda alias: f"""
        CASE WHEN {alias}.type IN ('import_po', 'import_do', 'adjust_in', 'return')
            THEN {alias}.quantity
            ELSE - {alias}.quantity
        END
    """
    query = f"""
        --sql
        WITH
            unnest_payload AS (
            SELECT product_id, NULLIF(serial, '') serial, type, quantity, order_id, batch_id, transaction_id
            FROM unnest(
                %(product_id)s      ::text[],
                %(serial)s          ::text[],
                %(type)s            ::text[],
                %(quantity)s        ::bigint[],
                %(order_id)s        ::bigint[],
                %(batch_id)s        ::bigint[],
                %(transaction_id)s  ::text[]
            ) AS meomeo (product_id, serial, type, quantity, order_id, batch_id, transaction_id)
        ),
            locking_trans AS (
            SELECT pg_advisory_xact_lock(0001)
        ),
            current_stock AS (
            SELECT 
                s.product_id,
                s.serial, 
                SUM({stock_cw('s')}) AS quantity
            FROM stock_ledger s
            JOIN locking_trans l ON true
            WHERE s.product_id IN (
                SELECT product_id FROM unnest_payload
                )
            GROUP BY s.product_id, s.serial
        )
        INSERT INTO stock_ledger
            (product_id, serial, type, quantity, order_id, batch_id, transaction_id)
        SELECT u.product_id, u.serial, u.type, u.quantity, u.order_id, u.batch_id, u.transaction_id
        FROM unnest_payload u
        WHERE (
            ({stock_cw('u')} +
            COALESCE((
                SELECT ct.quantity
                FROM current_stock ct
                WHERE
                    ct.product_id = u.product_id AND
                    ct.serial IS NOT DISTINCT FROM u.serial), 0
                )) >= 0 -- final stock always >= 0
            )
            AND ( -- product level serial consistency check
                (u.serial is null) = COALESCE(
                    (SELECT BOOL_OR(ct.serial is null) FROM current_stock ct WHERE ct.product_id = u.product_id),
                    u.serial is null)
            )
            AND ( -- serial maximum stock = 1 | ignore if non-serial
                (u.serial is null) OR
                COALESCE((SELECT ct.quantity FROM current_stock ct WHERE ct.serial = u.serial), 0) + {stock_cw('u')} <= 1
            )
        RETURNING product_id, serial
    ;
    """

    try:
        with psycopg.connect(NEON) as conn:
            with conn:
                batch_id = conn.execute("SELECT nextval('ledger_batch_id_seq');").fetchone()[0]
                payload  = (
                    input_df.with_columns(pl.lit(batch_id).alias('batch_id'))
                    .select(pl.col(c).implode(maintain_order=True)
                    for c in input_df.columns + ['batch_id']
                ).row(named=True)
                )
                cur = conn.execute(query, payload)
                res = cur.rowcount
                if res != input_df.height:
                    partial_success = cur.fetchall()
                    conn.rollback() #*** Abort ***
                    conflicts = {
                        'product_id': {*payload['product_id']} - {item[0] for item in partial_success},
                        'serial'    : {*payload['serial']}     - {item[1] for item in partial_success},
                    }
                    return f'[insert_ledger] Inserted nothing, conflict on {conflicts}'
        return f'[insert_ledger] Inserted {res} records'
    except psycopg.Error as e:
        return f'[insert_ledger] Error: {e}'
#endregion

#region Checkout | Cancel
def cancel_invoice(order_id: str):
    if not order_id:
        return
    data  = {'order_id': order_id}
    query = """--sql
    WITH 
        update_status AS (
            UPDATE orders
            SET status = 'cancelled'
            WHERE 
                id = %(order_id)s
                AND status = 'completed'
            RETURNING id
        ),
        items AS (
            SELECT s.product_id, s.serial, s.quantity, s.order_id
            FROM stock_ledger s
            JOIN update_status u
                ON s.order_id = u.id
            WHERE s.type = 'sell'
        )
    INSERT INTO stock_ledger
        (product_id, type, serial, quantity, order_id)
    SELECT i.product_id, 'return', i.serial, i.quantity, i.order_id
    FROM items i
    RETURNING order_id
    ;
    """

    try:
        with psycopg.connect(NEON) as conn:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(query, data)
                    res = cur.fetchone()
                    print(f'CANCELED {res}')
                    return res is not None              
    except psycopg.Error as e:
        logging.error(f'[cancel_invoice] {e}')
def check_out(data: dict):
    """
    Xử lý toàn bộ quy trình checkout trong một transaction.

    Flow:
        1. Validate cấu trúc và dữ liệu đầu vào.
        2. Khóa transaction bằng advisory lock để tránh race condition.
        3. Chuyển danh sách item/payment từ Python thành các relation bằng UNNEST.
        4. Tạo order mới và lấy order_id.
        5. Insert các item và payment thuộc order.
        6. Kiểm tra tồn kho và ghi nhận biến động vào stock ledger.
        7. Đối chiếu số item được ghi nhận; nếu thiếu item thì rollback toàn bộ.
        8. Nếu mọi bước thành công, commit transaction.

    Returns:
        '01': Thành công.
        '02': Không đủ tồn kho, rollback.
    """

    #region Guardian
    valid_key   = [
        'type', 'cus_id', 'staff_id', 'inv_disc', 'pay_method', 'pay_amount', 'sku_id', 'sku_price', 'sku_qty', 'sku_disc', 'sku_serial'
        ]
    unpack_data = data.items()
    if not set(data) == set(valid_key):
        raise ValueError('Key meshed up')
    
    if any(not v for k, v in unpack_data if not k in ['inv_disc']):
        raise ValueError('Value meshed up')
    
    if len(data['pay_method']) != len(data['pay_amount']):
        raise ValueError('Payment array length mismatch')
    
    if len({len(v) for k, v in unpack_data if 'sku' in k}) != 1:
        raise ValueError('Item array length mismatch')
    #endregion

    stock_cw  = lambda alias: f"""
        CASE WHEN {alias}.type IN ('import_po', 'import_do', 'adjust_in', 'return')
            THEN {alias}.quantity
            ELSE - {alias}.quantity
        END
    """
    big_query = f"""--sql
    WITH
        lock_traffic AS (
            SELECT pg_advisory_xact_lock(0001)
        ),
        unnest_payment AS (
            SELECT *
            FROM unnest(
                %(pay_method)s  ::text[],
                %(pay_amount)s  ::numeric[]
            ) AS whatever(method, amount)
        ),
        unnest_items AS (
            SELECT *
            FROM unnest(
                %(sku_id)s      ::text[],
                %(sku_qty)s     ::integer[],
                %(sku_price)s   ::numeric[],
                %(sku_disc)s    ::numeric[],
                %(sku_serial)s  ::text[]
            ) AS result_alias(
                product_id, quantity, price, discount, serial
                )
        ),
        new_order AS (
            INSERT INTO orders
                (customer_id, staff_id, discount)
            SELECT %(cus_id)s, %(staff_id)s, %(inv_disc)s
            FROM lock_traffic -- Trigger LOCK
            RETURNING orders.id
        ),
        insert_item AS (
            INSERT INTO item
                (order_id, product_id, serial, quantity, price, discount)
            SELECT o.id, i.product_id, NULLIF(i.serial, ''), i.quantity, i.price, i.discount
            FROM new_order o
            CROSS JOIN unnest_items i
        ),
        insert_payment AS (
            INSERT INTO payment
                (order_id, method, amount)
            SELECT o.id, pay.method, pay.amount
            FROM new_order o
            CROSS JOIN unnest_payment pay
        )

        INSERT INTO stock_ledger
            (product_id, type, serial, quantity, order_id)
        SELECT
            i.product_id, %(type)s, NULLIF(i.serial, ''), i.quantity, o.id
        FROM new_order o
            CROSS JOIN unnest_items i
        WHERE (- i.quantity) + (
            SELECT SUM({stock_cw('st')})
            FROM stock_ledger st
            WHERE
                i.product_id = st.product_id
                AND NULLIF(i.serial, '') IS NOT DISTINCT FROM st.serial
            ) >= 0
        RETURNING order_id, quantity
    ;
    """

    try:
        with psycopg.connect(NEON, row_factory = dict_row) as conn:
            with conn:
                with conn.cursor() as curr:
                    curr.execute(big_query, data)
                    result = curr.fetchall()
                    if len(result) != len(data['sku_id']):
                        conn.rollback()
                        return '02'
                    order_id = result[0]['order_id']
                    return order_id

    except psycopg.Error as e:
        logging.error(f'[check_out] Error: {e}')
        return '02'
#endregion

#region Fetch
def fetch_customer(neon_key = None):
    print('fetch_customer')
    if not neon_key:
        neon_key = NEON
    query = """--sql -- Phải xuống dòng thì query mới hợp lệ
        SELECT * FROM customer;
        """
    try:
        data = psycopg.connect(neon_key, row_factory=dict_row).execute(query).fetchall()
        if not data:
            data = [{'id': '', 'name': '', 'email': ''}]
    except psycopg.Error:
        data = [{'id': '', 'name': '', 'email': ''}]
    return pd.DataFrame(data).convert_dtypes(dtype_backend='pyarrow')
def fetch_inventory(neon_key=None):
    print('fetch_inventory')
    """
    ### Bao gồm
        - EAN
        - ID
        - NAME
        - PRICE
        - QUANTITY
    """
    if neon_key is None:
        neon_key = NEON
    def stock_case_when(key: str='type', val: str='quantity'):
        sdict = {
            'import_po'     : 1,
            'import_do'     : 1,
            'adjust_in'     : 1,
            'adjust_out'    : -1,
            'transfer'      : -1,
            'sell'          : -1,
            'rtv'           : -1,
            'return'        : 1
        }
        return f"CASE {key}\n" + "\n".join([f"WHEN '{k}' THEN {v} * {val}" for k, v in sdict.items()]) + "\nELSE 0 END"

    columns = [
        'ean',
        'id',
        'cat',
        'subcat',
        'name',
        'price',
        'quantity'
    ]
    query   = f"""--sql
        WITH 
        product as (
            SELECT
                p.ean, p.id, p.cat, p.subcat, p.name, pr.price
            FROM product p
            INNER JOIN price pr
                ON p.id = pr.product_id
                AND pr.is_active = true
            ),
        stock as (
            SELECT 
                product_id, -- num + null = null, SUM(num, null) = num
                SUM({stock_case_when('type', 'quantity')}) as quantity
            FROM stock_ledger
            GROUP BY product_id
            )
        SELECT 
            {', '.join(columns[:-1])},
            COALESCE(s.quantity, 0)::bigint as stock -- Tên cột trả về
        FROM product p
        LEFT JOIN stock s 
        ON p.id = s.product_id
        ORDER BY p.id ASC
        ;
        """
    empty   = [{k: None for k in columns}]
    try:
        data = (
            psycopg.connect(neon_key, row_factory=dict_row)
            .execute(query)
            .fetchall()
        )
        if not data:
            data = empty
    except psycopg.Error as e:
        print(e)
        data = empty
    return pd.DataFrame(data).astype({'price': 'int64[pyarrow]'}).convert_dtypes(dtype_backend='pyarrow')
def fetch_invoice(neon_key=None):
    print('fetch_invoice')
    if neon_key is None:
        neon_key = NEON

    query   = """--sql
    WITH ranked_cancelled AS (
        SELECT
            ROW_NUMBER() OVER(PARTITION BY s.order_id ORDER BY s.created_at DESC) AS rn,
            s.order_id,
            s.created_at AS cancelled_at
        FROM stock_ledger s
        WHERE s.type = 'return'
    ),
    cancelled_info AS (
        SELECT
            order_id,
            cancelled_at
        FROM ranked_cancelled
        WHERE rn = 1
    )
    SELECT
        o.id,
        o.status,
        o.customer_id,
        c.name AS customer_name,
        c.email AS customer_email,
        i.product_id,
        i.product_name,
        i.quantity,
        i.price,
        i.discount,
        sn.serial,
        pay.method,
        pay.amount,
        o.created_at
            AT TIME ZONE 'UTC'
            AT TIME ZONE 'Asia/Ho_Chi_Minh'
        AS created_at,
        r.cancelled_at
            AT TIME ZONE 'UTC'
            AT TIME ZONE 'Asia/Ho_Chi_Minh'
        AS cancelled_at
    FROM orders o

    LEFT JOIN customer c
        ON c.id = o.customer_id

    LEFT JOIN cancelled_info r
        ON r.order_id = o.id

    -- Nếu không có LATERAL, sub-query sẽ chạy độc lập và
    -- không thể tham chiếu o.id từ query bên ngoài.
    -- LATERAL cho phép sub-query tham chiếu row hiện tại của orders;
    -- có thể hiểu như sub-query được thực thi riêng cho từng o.id.
    LEFT JOIN LATERAL (
        SELECT
            ARRAY_AGG(i.product_id ORDER BY i.id) AS product_id,
            ARRAY_AGG(p.name      ORDER BY i.id) AS product_name,
            ARRAY_AGG(i.quantity  ORDER BY i.id) AS quantity,
            ARRAY_AGG(i.price     ORDER BY i.id) AS price,
            ARRAY_AGG(i.discount  ORDER BY i.id) AS discount
        FROM item i
        LEFT JOIN product p
            ON p.id = i.product_id
        WHERE i.order_id = o.id
    ) i ON TRUE

    LEFT JOIN LATERAL (
        SELECT
            ARRAY_AGG(pa.method ORDER BY pa.id) AS method,
            ARRAY_AGG(pa.amount ORDER BY pa.id) AS amount
        FROM payment pa
        WHERE pa.order_id = o.id
    ) pay ON TRUE

    LEFT JOIN LATERAL (
        SELECT
            ARRAY_AGG(s.serial ORDER BY s.id) AS serial
        FROM stock_ledger s
        WHERE s.order_id = o.id
            AND s.type = 'sell'
    ) sn ON TRUE
    ;
    """

    try:
        with psycopg.connect(neon_key, row_factory=dict_row) as conn:
            data = conn.execute(query).fetchall()
    except psycopg.Error as e:
        data = []
        print(e)

    return data
def fetch_serial(neon_key=None):
    print('fetch_serial')
    if neon_key is None:
        neon_key = NEON
    query = """
    --sql
    WITH serial_stock AS (
        SELECT
            product_id,
            serial,
            SUM(CASE
                    WHEN type IN ('import_po', 'import_do', 'adjust_in', 'return')
                    THEN quantity
                    ELSE -quantity
                END
            ) AS quantity
        FROM stock_ledger
        WHERE serial IS NOT NULL
        GROUP BY product_id, serial
    )
    SELECT
        s.product_id,
        ARRAY_AGG(s.serial) AS serial_list
    FROM serial_stock AS s
    WHERE s.quantity > 0
    GROUP BY s.product_id
    ;
    """

    try:
        with psycopg.connect(neon_key, row_factory=dict_row) as conn:
            data = conn.execute(query).fetchall()
    except psycopg.Error as e:
        data = []
    if data:
        data = {d['product_id']: d for d in data}
    return data
def fetch_staff(neon_key=None):
    print('fetch_staff')
    if neon_key is None:
        neon_key = NEON
    try:
        with psycopg.connect(neon_key, row_factory=dict_row) as conn:
            data = conn.execute('SELECT * FROM staff').fetchall()
    except psycopg.Error as e:
        data = []
    if data:
        data = {s['id']: s['name'] for s in data}
    return data

def fetch_dashboard(neon_key: str=None):
    if neon_key is None:
        neon_key = NEON
    query = """
    --sql
    SELECT
        o.created_at,
        o.id AS invoice,
        o.staff_id,
        o.discount AS order_disc,
        o.status,
        i.product_id,
        i.serial,
        pd.cat,
        pd.subcat,
        pd.name,
        i.quantity,
        i.price,
        i.discount AS item_discount,
        pm.amount,
        pm.method,
        c.id AS phone,
        c.name,
        c.email
    FROM item i
    JOIN orders o
        ON i.order_id = o.id
    JOIN product pd
        ON i.product_id = pd.id
    JOIN customer c
        ON o.customer_id = c.id
    JOIN LATERAL (
        SELECT
            ARRAY_AGG(p.amount ORDER BY p.id) AS amount,
            ARRAY_AGG(p.method ORDER BY p.id) AS method
        FROM payment p
        WHERE p.order_id = o.id
    ) pm ON true
    ;
    """
    try:
        data = psycopg.connect(neon_key, row_factory=dict_row).execute(query).fetchall()
    except:
        data = []
    return data
def clear_db_cache(include_invoice: bool=True):
    fetch_inventory.clear()
    fetch_dashboard.clear()
    fetch_serial.clear()
    if include_invoice:
        fetch_invoice.clear()
#endregion

fetch_jobs = [
    ('inventory', fetch_inventory),
    ('customer', fetch_customer),
    ('invoice', fetch_invoice),
    ('serial', fetch_serial),
    ('staff', fetch_staff),
]
def init_brief_cache():
    """
    ## Khởi tạo cache (chạy ở app.py)
    """
    return get_sys_brief_cache(fetch_jobs)