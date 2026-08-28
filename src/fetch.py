from concurrent.futures import ThreadPoolExecutor
from googleapiclient.discovery import build
from google.oauth2 import service_account
import google.auth.transport.requests
from datetime import datetime
from io import BytesIO
import streamlit as st
import polars as pl
import threading
import zoneinfo
import logging
import time
from .utils import Drive
from .clean import cleanPipe
logging.getLogger('googleapiclient.discovery_cache').setLevel(logging.ERROR)
SECRET_KEY = st.secrets['gcs_connections']
SS = st.session_state


#region Connections
@st.cache_resource
def cached_http_session():
    """
    ## Khởi tạo đường ống tới Google API (Thread-safe).

    Mục đích:
    ---------
    Thay vì để mỗi lần build service, worker phải tạo đường ống mới từ đầu và đập bỏ khi fetch xong.
    Hàm này sẽ tạo 1 đường ống ổn định đầu tiên và cached vào RAM.
    Hàm get_connections sẽ dùng build thêm nhánh trực tiếp từ ống chính, tiết kiệm thời gian và tài nguyên.

    Return:
    -------
    google.auth.transport.requests.Request: 
        Một HTTP session object đã được cấu hình sẵn để làm cổng vận chuyển dữ liệu cho Google API Client.
    """
    return google.auth.transport.requests.Request()

def get_google_connections(key = SECRET_KEY):
    """
    ## Khởi tạo và cấu hình các dịch vụ kết nối (Google Drive & Sheets) cho từng luồng.

    Mục đích:
    ---------
    Sử dụng đường ống chính đã Cached và build thêm các nhánh (v3, v4) để fetch data về máy.
    Sử dụng .refresh(cached_session) để verify token của cred còn hạn hay không.
    Nếu cred check với ống thấy token expired thì sẽ dùng ống để xin API cấp lại token (rất nhanh).
    Trả về:
    -------
    dict:
        - 'drive' : googleapiclient.discovery.Resource (Drive API v3 Client)
        - 'sheets': googleapiclient.discovery.Resource (Sheets API v4 Client)

    """
    scopes = [
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    
    base_credentials = service_account.Credentials.from_service_account_info(key)
    credentials = base_credentials.with_scopes(scopes)
    
    cached_session = cached_http_session()
    credentials.refresh(cached_session)
    
    drive_service = build('drive', 'v3', credentials=credentials)
    sheets_service = build('sheets', 'v4', credentials=credentials)
    
    return {
        'drive': drive_service,
        'sheets': sheets_service
    }

@st.fragment()
def get_drive_trigger(
    service = None,
    file_id = None
) -> None:
    if service is None:
        service = get_google_connections()['drive']
    if file_id is None:
        file_id = Drive.sales_id
    if 'fetch_trigger' not in SS:
        logging.info('[Trigger] First Run')
        SS.fetch_trigger  = 'First Run'
        SS.block_button   = False

    if SS.get('trigger_status') is True:
        SS.trigger_status = 'Pending'
        st.toast('Syncing..', icon=':material/sync:')
    elif SS.get('trigger_status') is False:
        SS.trigger_status = 'Pending'
        st.toast('No updates available', icon=':material/sync_alt:')

    def trigger_clicked():
        SS.block_button   = True

    st.sidebar.button(
        label    = ':orange[:material/cloud_sync: **Pull Trigger**]',
        type     = 'secondary',
        width    = 'stretch',
        on_click = trigger_clicked,
        disabled = SS.block_button
    )
    if SS.block_button:
        SS.block_button   = False
        SS.trigger_status = False
        try:
            meta = service.files().get(fileId=file_id, fields='modifiedTime').execute()
            utc_str = meta.get('modifiedTime')

            if not utc_str:
                logging.error('[Trigger] Empty String')
                st.rerun(scope='fragment')

            normalize_dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
            modified_time = normalize_dt.astimezone(zoneinfo.ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%H:%M:%S %d/%m/%Y')
            
            if modified_time != SS.fetch_trigger:
                logging.info(f'[Trigger] Re-Run {SS.get("fetch_trigger")}')
                SS.fetch_trigger  = modified_time
                SS.trigger_status = True
                st.rerun(scope='app')

        except Exception as e:
            logging.error(f'[Trigger] Failed: {e}')
        # Nếu try-pass nhưng mà trigger không đổi hoặc dính except -> rerun để mở khóa nút
        st.rerun(scope='fragment')
#endregion


#region Fetch
def polars_worker(
    folder_id: str,
    file_name: str,
    ):
    try:
        # không thể bỏ connections ra hàm ngoài, mỗi worker cần có service riêng
        connections = get_google_connections()
        thread_service = connections['drive']
        query = f"'{folder_id}' in parents and name = '{file_name}' and trashed = false"
        file_infos = thread_service.files().list(q=query, fields="files(id)").execute()
        files = file_infos.get('files', [])
        
        if not files:
            return file_name, None

        file_id = files[0]['id']
        media_content = thread_service.files().get_media(fileId=file_id).execute()
        ext = file_name.split('.')[-1].lower()

        if file_name == Drive.sales_name:
            df = cleanPipe(pl.scan_csv(media_content))
            df = (
                df.rename_columns()
                .categorizing_columns()
                .validating_data()
                .add_column('week')
                .add_column('month')
                ).collect()
            return file_name, df

        if ext in ['xlsx', 'xls']:
            df = pl.read_excel(media_content, drop_empty_rows=True)
        elif ext == 'csv':
            df = pl.read_csv(media_content)
        elif ext == 'parquet':
            df = pl.read_parquet(media_content)
        elif ext == 'pkl':
            df = BytesIO(media_content)
        else:
            df = None
        return file_name, df

    except Exception:
        print('[polars_worker] Errors')
        return file_name, None

@st.cache_resource(show_spinner='Fetching data from Google Drive...')
def fetch_from_drive(trigger: str  = None) -> dict[str, pl.DataFrame]:
    """
    ## Truyền `trigger` = Auth Data Bundle
    ## Blank = Demo Data Bundle
    ### Hàm đọc toàn bộ files yêu cầu từ Drive và Cached RAM.
    ### Chạy lần đầu ở app.py, các page khác khi gọi hàm sẽ không cần fetch lại.
    """
    pl.Config.set_tbl_cols(-1)
    if trigger is None:
        return
    folder_id = Drive.folder_id
    file_list = Drive.file_list
    if isinstance(file_list, str):
        file_list = [file_list]
    with ThreadPoolExecutor(max_workers = (X:=len(file_list)) ) as executor:
        results = executor.map(polars_worker, [folder_id] * X, file_list)
    return {file_name: df for file_name, df in results if df is not None}
#endregion


def read_mockup():
    print('read_mockup')
    return pl.read_parquet('data/demo_sales_bundle_2.parquet')

