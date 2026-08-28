import polars as pl
from typing import Literal
from src.utils import Schema
import polars.selectors as cs
import re
import time
import logging
S = Schema.Sales
K = Schema.Stock


def notebook():
    df = pl.DataFrame()

    df.collect()
    df.collect_schema()
    df.collect_schema().names()

    df.is_empty()
    df.height
    df.width
    df.shape

    df.select()
    df.with_columns()
    df.filter()
    df.rename()
    df.sort()
    df.unique()
    df.concat()
    df.explode()

    pl.all()
    pl.any_horizontal()
    pl.all_horizontal()
    pl.sum_horizontal()
    pl.len()
    pl.lit()

    pl.when()
    pl.then()
    pl.otherwise()

    pl.exclude()
    pl.concat_str()

    pl.col().is_null()
    pl.col().is_not_null()
    pl.col().has_nulls()
    pl.col().null_count()
    pl.col().drop_nulls()
    pl.col().is_duplicated()

    pl.col().cast()
    pl.col().fill_null()

    pl.col().str.strip_chars()
    pl.col().str.to_date()
    pl.col().str.to_time()
    pl.col().str.strftime()

    pl.col().dt.strftime()
    pl.col().dt.week()
    pl.col().dt.truncate()

    pl.col().alias()
    pl.col().name.suffix()

    pl.Config.set_tbl_rows()

    df.to_dicts()
    cs.by_name()
    cs.string()

#endregion

#region Helper
def is_boolean(s: pl.Series) -> bool:
    if s.len() == 0: return False
    if s.dtype == pl.Boolean: return True
    
    # normalize string
    s_str = s.cast(pl.String, strict=False).str.strip_chars().str.to_lowercase()
    
    # Tính toán tỷ lệ khớp (mean)
    valid_mask = s_str.is_in(['true', 'false', 'yes', 'no', '1', '0'])
    x = valid_mask.sum() / s_str.len()
    y = s_str.n_unique()
    
    return (x >= 0.9) and (y <= 2)

def is_datetime(s: pl.Series) -> bool:
    if s.len() == 0: return False
    if s.dtype.is_numeric(): return False
    if s.dtype in [pl.Date, pl.Datetime]: return True
    
    # Tính tỷ lệ cast thành công
    x = s.cast(pl.Datetime, strict=False).drop_nulls().len() / s.len()
    
    # Kiểm tra xem chuỗi có chứa các ký tự phân cách ngày tháng phổ biến không [-/: ]
    y = s.cast(pl.String, strict=False).str.contains(r'[-/: ]').sum() / s.len()
    
    return (x >= 0.9) and (y >= 0.9)

def is_alo(s: pl.Series) -> bool:
    if s.len() == 0: return False
    s_clean = s.drop_nulls().cast(pl.String, strict=False)
    if s_clean.len() == 0: return False
    
    x = s_clean.str.slice(0, 1).is_in(['0', '3', '5', '7', '8', '9']).sum() / s_clean.len()
    y = s_clean.str.replace_all(r'[,\-\s]', '').str.len_chars().mean()
    if s.name == 'id':
        print(x, y)
    if y is None: return False
    return (x >= 0.9) and (9 <= y <= 11)

def is_numeric(s: pl.Series) -> bool:
    if s.len() == 0: return False
    if s.dtype.is_numeric(): return True
    
    # Tính toán tỷ lệ ép kiểu thành công sang Số thực Float64
    x = s.cast(pl.Float64, strict=False).drop_nulls().len() / s.len()
    return x >= 0.9

def is_category(s: pl.Series) -> bool:
    if s.len() == 0: return False
    
    # Kiểm tra xem tỷ lệ số hóa của cột có lớn hơn 80% hay không
    numeric_ratio = s.cast(pl.Float64, strict=False).drop_nulls().len() / s.len()
    if numeric_ratio > 0.8: return False
    
    nunique = s.n_unique()
    return 2 <= nunique <= 33
#endregion

class cleanPipe:
    def __init__(self, df: pl.LazyFrame):
        """
        ## Self là 1 cái balo
        - init: bỏ đồ vào bên trong nó
        - nó giúp chaining các hàm với nhau (chia sẻ chung dữ liệu trong balo)
        """
        self.df = df
        self.book = pl.DataFrame()

    def collect(self):
        return self.df.collect()

    def print_book(self):
        # Ép nó print đầy đủ dòng
        pl.Config.set_tbl_rows(-1)
        print(self.book)

    def recover_money(
        self,
        target: Literal['price', 'revenue'],
        cal_by: Literal['price', 'revenue', 'payment']
        ):
        """
        ### Step 2-utils
        - Khôi phục số liệu thiếu cho Price hoặc Revenue
        - Khôi phục trên những dòng có thể truy ngược bằng 1/3 yếu tố:
        >>> price   = (revenue + disc_Amount) / ((1 - disc_Pct) * qty)
        >>> revenue = (price * qty) * (1 - disc_Pct) - disc_Amount
        >>> sum_horizontal(payment_cols) = revenue
        """
        if target == cal_by:
            raise ValueError('[recover_money] 2 args should not be similar')

        quantity = pl.col(S.qty)
        price    = pl.col(S.price)
        revenue  = pl.col(S.revenue)
        disc_amt = pl.col(S.disc_amt).fill_null(0) # NOTE Quan trọng
        disc_pct = pl.col(S.disc_pct).fill_null(0) # NOTE Nếu không fill thì formula sẽ vô nghĩa
        payment_cols = [S.cash, S.card, S.payoo, S.banking, S.mkt, S.vnpay, S.trade_in]
        payment_sum  = pl.sum_horizontal(payment_cols, ignore_nulls=True)

        target_Expr = {
            'price'     : price,
            'revenue'   : revenue
        }[target]

        cal_by_dict = {
            'price'     : {'ref': price, 'formula': (price * quantity) * (1 - disc_pct) - disc_amt},
            'revenue'   : {'ref': revenue, 'formula': (revenue + disc_amt) / ((1 - disc_pct) * quantity)},
            'payment'   : {'ref': payment_sum, 'formula': (payment_sum + disc_amt) / ((1 - disc_pct) * quantity) if target == 'price' else payment_sum}
        }[cal_by]

        expression = lambda alias: (
            pl.when(
                target_Expr.is_null() & cal_by_dict['ref'].is_not_null() & (cal_by_dict['ref'] > 0))
                .then(cal_by_dict['formula'])
                .otherwise(target_Expr)
                .alias(alias)
                )

        return expression(alias = target)

    def rename_columns(self):
        logging.info('[Pipe] Rename Columns')
        lazy_colnames = self.df.collect_schema().names()
        lazy_renames  = list(S.name_mapping.values())
        names_dict    = dict(zip(lazy_colnames, lazy_renames))
        self.df = self.df.rename(names_dict)
        return self

    def categorizing_columns(self):
        """
        ### Step 1: Chuẩn hóa, phân loại cột, cast-type.
        - 'Ten cot' -> 'ten_cot'
        - self.book: kết quả sau phân loại `pl.dataframe`
        - return `self`
        """

        t0 = time.perf_counter()
        df = self.df
        rules = {
            'date'      : [pl.Date, r'(?:^|_)(?!.*traffic)(?:date|ngay|day|created|updated)(?:_|$)'],
            'time'      : [pl.Time, r'(?:^|_)(?:time|gio|hour|minute|second)(?:_|$)'],
            'price'     : [pl.Float64, r'(?:^|_)(?:price|unit_price|unitprice|đơn_giá|đơn_gia|gia|giá|gia_ban|giá_bán|prc)(?:_|$)'],
            'numeric'   : [pl.Float64, r'(?:^|_)(?:cash|card|vnpay|payoo|trade_in|banking|mkt_promo|cost|qty|quantity|sl|disc|discount|percent|fee|rate|tax|shipping)(?:_|$)'],
            'revenue'   : [pl.Float64, r'(?:^|_)(?<!disc_)(?<!tax_)(?<!fee_)(?<!paid_)(?<!ship_)'
                            r'(?:revenue|total|total_amount|total_revenue|thanh_tien|thanhtien|'
                            r'doanh_thu|doanhthu|tổng_tiền|tong_tien|tongtien|grand_total|subtotal|tt|'
                            r'amount)(?:_|$)'],
            'boolean'   : [pl.Boolean, r'(?:^|_)(?:ins_stt|tg|is_|status|active)(?:_|$)'],
            'category'  : [pl.String, r'(?:^|_)(?:cat|type|category)(?:_|$)'],
            'string'    : [pl.String, r'(?:^|_)(?:ean|inv(?:oice|_no|_number)?|order_id|transaction_id|'
                            r'bill_no|bill_number|ma_hoa_don|serial|sku|upc|code)(?:_|$)'],
            'phone'     : [pl.String, r'(?:^|_)(?:id|phone)(?:_|$)']
        }
        book    = {key: [] for key in rules}
        df      = df.rename(lambda col: col.strip().replace(' ', '_').lower())
        columns = df.collect_schema().names()

        #region Stage 0
        matched = set()
        for kind, [_, regex] in rules.items():
            is_match = re.compile(regex, flags=re.IGNORECASE).match
            for col in columns:
                if not col in matched and is_match(col):
                    book[kind].append(col)
                    matched.add(col)
        pending   = set(columns) - matched
        #endregion

        #region Stage 1
        kind_func = {
            'phone'   : is_alo,
            'date'    : is_datetime,
            'boolean' : is_boolean,
            'numeric' : is_numeric,
            'category': is_category
        }
        if pending:
            samples_df = df.select([ #.impolde() = .agg(list) Pandas (Gom mỗi cột thành 1 List bên trong 1 cell)
                pl.col(col).drop_nulls().head(500).implode().alias(col) 
                for col in pending
            ]).collect()

            for col in pending:
                # Series(List[original_type])[0] -> Series(original_type)
                sample = samples_df.get_column(col)[0]
                if sample.len() == 0:
                    book['string'].append(col)
                    continue
                for kind, func in kind_func.items():
                    if func(sample):
                        book[kind].append(col)
                        break
                else:
                    book['string'].append(col)

        #endregion
        
        #region Execution
        expression = []
        for kind, col_list in book.items():
            if not col_list:
                continue
            # Chỉ Selectors (cs) mới hỗ trợ phép toán giao/hợp tập hợp select cột
            str_cols = cs.by_name(col_list) & cs.string()
            not_str  = cs.by_name(col_list) & (~ cs.string())
            target_dtype = rules[kind][0]

            if df.select(str_cols).collect_schema().names():
                if kind == 'date':
                    expression.append(str_cols.str.strip_chars().str.to_date(strict=False))
                    continue
                if kind == 'time':
                    expression.append(str_cols.str.strip_chars().str.to_time(strict=False))
                    continue
                expression.append(str_cols.str.strip_chars().cast(target_dtype, strict=False))

            if df.select(not_str).collect_schema().names():
                expression.append(not_str.cast(target_dtype, strict=False))
        self.df  = df.with_columns(expression).filter(pl.any_horizontal(pl.all().is_not_null()))

        max_book = max([len(l) for l in book.values()])
        book = {k: l + ['-'] * (max_book - len(l)) for k, l in book.items() if l}
        self.book = pl.DataFrame(book)

        #endregion
        
        t1 = time.perf_counter()
        logging.info(f'[Pipe] Categorize Runtime: {(t1 - t0):.4f}s')
        logging.info(f'[Pipe] Categorize Structure: {self.book}')

        return self

    def validating_data(self):
        """
        ### Step 2: Kiểm tra chất lượng, tự động sửa chữa
        - Lọc bỏ dòng không cứu đc
        - Recover Revenue bằng Payment
        - Dùng Revenue Recover Price
        """
        df          = self.df
        unfixable   = [S.invoice, S.ean, S.qty]
        fixable     = [S.date, S.staff, S.sku, S.cat, S.price ,S.revenue]
        requires    = unfixable + fixable

        #region Guarding
        null_clean  = df.select(pl.all_horizontal(~ pl.col(requires).has_nulls())).collect().item()
        if null_clean:
            logging.info('[Pipe] Validated all clean')
            return self
        #endregion

        #region Validator
        validator = lambda df, stage: df.select([
            (pl.col(requires).null_count() / (length:=pl.len()) - 1).abs().round(4).name.suffix(' val %'),
            length.alias('length'),
            pl.lit(stage).alias('stage')
        ])
        before = validator(df, 'before')
        #endregion
        
        #region Repairment
        filter_expr = []
        filter_expr.append(pl.all_horizontal(pl.col(unfixable).is_not_null()))
        filter_expr.append(pl.col(S.qty) > 0)
        filter_expr.append(pl.col(S.staff).is_not_null())

        revenue_expr = self.recover_money(target='revenue', cal_by='payment')
        price_expr   = self.recover_money(target='price', cal_by='revenue')
        df           = df.filter(filter_expr).with_columns([revenue_expr]).with_columns([price_expr])
        repair       = validator(df, 'repair')
        #endregion

        #region Final Inspection
        df         = df.filter(pl.col(S.revenue).is_not_null() & pl.col(S.price).is_not_null()).sort(by=[S.date, S.invoice], descending=False)
        final      = validator(df, 'final')
        inspection = pl.concat([before, repair, final]).collect()
        logging.info(f'[Pipe] Repair Results: {inspection}')
        #endregion

        self.df = df
        return self

    def add_column(self, name: Literal['week', 'month', 'store_id']):
        DATE = pl.col(S.date)
        choices = {
            'week' : pl.concat_str([DATE.dt.strftime('%y-W'), DATE.dt.week(), DATE.dt.truncate('1w').dt.strftime(' (%d %b)')]),
            'month': DATE.dt.strftime(Schema.Format.month)
        }
        self.df = self.df.with_columns(choices[name].alias(name))
        logging.info(f'[Pipe] Add Column: "{name}"')
        return self

