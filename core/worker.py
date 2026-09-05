# region Note
# DEFAULT_WORKERS = max(1, (os.cpu_count() or 8) // 2)
# #region Setup
# #! những dòng không nằm bên trong func mà đc import vào streamlit thì chỉ chạy đúng 1 lần
# # _global_Q - Tạo 1 hàng đợi (Dùng chung cả app)
# _global_Q = queue.Queue()

# # _pool_started - 1 flag global (dùng chung cho mọi user/session)
# _pool_started = False

# # _lock - 1 cái flag đặc biệt, hiểu nôm na như transacton lock ở DB, muốn thông qua thì phải chờ tới lượt
# # có thể dùng để khóa mọi tác vụ, không nhất thiết phải liên quan tới thread, nhưng sinh ra để phục vụ threading
# _lock = threading.Lock()
# #endregion

# explain = """
# - Thread là 1 đơn vị thực thi, đại diện cho 1 luồng chạy code
# - Queue là 1 hàng đợi chứa các job lần lượt

# Queue: [job_A(filter), job_B(adv_utils), job_C(filter), job_D(period), job_E(filter), job_F(adv_utils)]

# Worker1 rảnh → lấy job_A → chạy filter
# Worker2 rảnh → lấy job_B → chạy adv_utils
# Worker3 rảnh → lấy job_C → chạy filter
# Worker4 rảnh → lấy job_D → chạy period
# Worker1 xong job_A, rảnh lại → lấy job_E → chạy filter
# Worker2 xong job_B, rảnh lại → lấy job_F → chạy adv_utils

# - Pool là 1 khái niệm (bể chứa các thread) không phải là 1 object
# """
# def _worker_loop():
#     """
#     Hàm này chính là target đc giao của 1 Thread
#     được gọi 1 lần và cứ thế chạy đến khi app dừng (vì có while True)
#     - func chính là hàm Polars đc gọi
#     - while True: Giữ thread luôn sống trong 1 vòng lặp, nếu không thì nó sẽ biến mất khi xong việc
#     - .get() là hàm có cơ chế wait, mỗi vòng lặp while chỉ là vòng đời của 1 job
#         _global_Q.get() sẽ đợi cho tới khi có job và xử lý xong nó mới chạy xuống dưới và kết thúc vòng lặp
#     """
#     while True: # Làm xong việc thì quay lại bàn đợi tiếp, cấm bỏ về sớm
#         func, args, kwargs, result_q = _global_Q.get() # (*) DỪNG Ở ĐÂY, có thể vài giây/vài giờ không chạy tiếp
#         try:
#             result = func(*args, **kwargs)
#             result_q.put(("ok", result))
#         except Exception as e:
#             result_q.put(("error", e))
# def ensure_started(n_workers = DEFAULT_WORKERS):
#     """
#     Hàm sẽ đc gọi mỗi khi rerun nhưng chỉ chạy đúng 1 lần đầu tiên
#     - **with _lock: Là 1 cái flag đặc biệt, kiểu hiện màu đỏ khi nhà vệ sinh đang có người bên trong
#         không thể có 2 người pass cùng 1 lúc, mục đích để tránh race condition tạo ra nhiều hơn 4 thread
#     - loop qua 4 lần, khởi động 4 thread chạy xuyên suốt App process
#     - daemon = True : tự ngắt thread khi App shutdown, nếu không thì nó sẽ chạy mãi
#     - t.start() : Khởi động thread
#     - _pool_started = True : Bật flag (ghi đè biến global)
#     """
#     global _pool_started
#     with _lock:
#         if not _pool_started:
#             for i in range(n_workers):
#                 t = threading.Thread(
#                     target = _worker_loop,
#                     daemon = True,
#                     name   = f"Supreme-Worker-{i}",
#                 )
#                 t.start()
#             _pool_started = True
# def run_on_worker(func, *args, **kwargs):
#     """
#     - Khởi động pool
#     - result_q: tạo queue mới mỗi lần để chứa kết quả từ worker
#     - _global_Q: Cầu nối giữa worker và result_q
#     - Worker nào rảnh sẽ nhận job từ _global_Q, xử lý và trả về result_q
#     """
#     ensure_started()
#     result_q = queue.Queue()
#     _global_Q.put((func, args, kwargs, result_q))
#     status, payload = result_q.get() # Auto wait result
#     if status == "error":
#         raise payload
#     return payload
# def supreme(func):
#     """Dán lên hàm Polars thuần (không chứa st.*) để nó tự động chạy qua pool worker."""
#     @functools.wraps(func)
#     def wrapper(*args, **kwargs):
#         return run_on_worker(func, *args, **kwargs)
#     return wrapper
#endregion

import os
import sys
import queue
import threading
import functools

_pool_lock_  = threading.Lock()
_cache_lock_ = threading.Lock()

class supreme_pool:
    n_worker = max(1, (os.cpu_count() or 8) // 2)
    def __init__(self):
        self.global_Q   = queue.Queue()
        self.is_running = threading.Event()
        self.is_running.set()
        for n in range(supreme_pool.n_worker):
            threading.Thread(
                target=self._worker_loop, daemon=True, name=f'Supreme-Worker-{n:02d}'
            ).start()

    def _worker_loop(self):
        """
        Edge-case: Nếu get(timeout) > result_q không đc unpack 
            > "previous_loop_result_q is not None" > previous_loop_result_q.put((False, e))
        - Put error vào queue của vòng lặp trước
        - Solved: Cho result_q = None vào bên trong loop
        """
        ### result_q = None
        while self.is_running.is_set():
            result_q = None
            try:
                func, arg, kwarg, result_q = self.global_Q.get(timeout=5)
                result_q.put((True, func(*arg, **kwarg)))
            except queue.Empty:
                continue
            except Exception as e:
                if result_q is not None:
                    result_q.put((False, e))

    def _abort(self):
        self.is_running.clear()

    def _run_on_worker(self, func, *arg, **kwarg):
        result_q = queue.Queue()
        self.global_Q.put((func, arg, kwarg, result_q))
        status, payload = result_q.get()
        if status:
            return payload
        raise payload

def get_sys_pool() -> supreme_pool:
    with _pool_lock_:
        if not hasattr(sys, '_supreme_pool'):
            sys._supreme_pool = supreme_pool()
        return sys._supreme_pool

def supreme(func):
    @functools.wraps(func)
    def _wrap(*arg, **kwarg):
        return get_sys_pool()._run_on_worker(func, *arg, **kwarg)
    return _wrap


class brief_cache:

    def __init__(self, fetch_jobs: list):
        self.pocket     = {}
        self.lock       = threading.Lock()
        self.fetch_jobs = fetch_jobs
        self.first_fetch()

        # self.refetch  = threading.Event()
        # self.refetch.clear()
        # threading.Thread(
        #     target = self.auto_refetch,
        #     daemon = True,
        #     name   = 'Briefcache_auto_refetch'
        # ).start()

    def put(self, key, val):
        with self.lock:
            self.pocket[key] = val

    def get(self, key):
        with self.lock:
            return self.pocket.get(key, None)

    def clear(self, *keys):
        """
        >>> fetch_jobs = [
            ('inventory', fetch_inventory),
            ('customer', fetch_customer),
            ('invoice', fetch_invoice),
            ('serial', fetch_serial),
            ('staff', fetch_staff),
        ]
        ## New lesson: lock 1 lần toàn bộ != lock nhiều lần 1 hàm
        - Chỉ cần gọi lock ở những vị trí cần chặn race / conflict
        - Toàn bộ process dùng chung 1 `self.lock` cho mọi user/session
        - Mục đích cơ bản là để tại 1 thời điểm chỉ có 1 user đc chạy khối code bọc trong lock
        """
        listed_jobs = self.fetch_jobs
        pending_job = []
        done_batch  = {}

        if not keys:
            # Không clear cache để tránh cache rỗng
            keys = [j[0] for j in listed_jobs]

        for k, job in listed_jobs:
            if not k in keys:
                continue
            res_q = queue.Queue()
            get_sys_pool().global_Q.put((job, (), {}, res_q))
            pending_job.append((k, res_q))

        for key, res_q in pending_job:
            status, res = res_q.get()
            if status:
                done_batch[key] = res

        with self.lock: # Atomic action (update 1 loạt)
            self.pocket.update(done_batch)

    def check(self, key):
        with self.lock:
            return key in self.pocket

    def first_fetch(self):
        pending = []
        # Gọi worker liên tục theo batch 1 lượt
        for key, func in self.fetch_jobs:
            result_q = queue.Queue()
            # Tuyệt đối không gọi thẳng supreme_pool()
            get_sys_pool().global_Q.put((func, (), {}, result_q))
            pending.append((key, result_q))
        # Cầm giỏ để chờ kết quả
        for key, result_q in pending:
            status, data = result_q.get()
            if status:
                self.put(key, data)

    def auto_refetch(self):
        while True:
            try:
                self.refetch.wait()
                print('[Briefcache_auto_refetch] Run')
                pending = []
                # Loop 1: request liên tiếp
                for key, func in self.fetch_jobs:
                    res_q = queue.Queue()
                    if not key in self.pocket:
                        # Tuyệt đối không gọi thẳng supreme_pool()
                        get_sys_pool().global_Q.put((func, (), {}, res_q))
                        pending.append((key, res_q))
                # Loop 2: job nào xong trước thì nhận và cất vào pocket trước
                for key, res_q in pending:
                    status, data = res_q.get()
                    if status:
                        self.put(key, data)
                self.refetch.clear()

            except Exception as e:
                print('[Briefcache_auto_refetch] Error:', e)
                self.refetch.clear()

def get_sys_brief_cache(fetch_jobs=None):
    with _cache_lock_:
        if not hasattr(sys, '_brief_cache'):
            if fetch_jobs is None:
                raise ValueError('fetch_jobs must be given at start up')
            sys._brief_cache = brief_cache(fetch_jobs)
        return sys._brief_cache
