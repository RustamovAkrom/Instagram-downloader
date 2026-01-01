# app/services/task_manager.py
from concurrent.futures import ThreadPoolExecutor, Future
import threading
import uuid
import logging
from queue import Queue

logger = logging.getLogger("task_manager")
logger.setLevel(logging.INFO)

MAX_WORKERS = 1  # одновременно не больше 3 задач
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
tasks: dict[str, Future] = {}
lock = threading.Lock()

# Очередь задач, если одновременно превышаем MAX_WORKERS
task_queue: Queue[tuple] = Queue()


def _run_task(task_id: str, func, *args, **kwargs):
    """Внутренний метод для запуска и удаления из очереди"""
    try:
        result = func(*args, **kwargs)
        return result
    finally:
        # После завершения проверяем очередь
        if not task_queue.empty():
            next_task_id, next_func, next_args, next_kwargs = task_queue.get()
            logger.info("Starting queued task %s", next_task_id)
            with lock:
                tasks[next_task_id] = executor.submit(_run_task, next_task_id, next_func, *next_args, **next_kwargs)


def submit_task(func, *args, **kwargs) -> str:
    """Добавляем задачу в executor или очередь, если все слоты заняты"""
    task_id = str(uuid.uuid4())
    with lock:
        running = sum(1 for f in tasks.values() if not f.done())
        if running >= MAX_WORKERS:
            # ставим в очередь
            task_queue.put((task_id, func, args, kwargs))
            logger.info("Task %s queued, currently running %d tasks", task_id, running)
            # создаем фиктивный Future, чтобы можно было отслеживать
            from concurrent.futures import Future
            f = Future()
            tasks[task_id] = f
        else:
            tasks[task_id] = executor.submit(_run_task, task_id, func, *args, **kwargs)
            logger.info("Task %s submitted, currently running %d tasks", task_id, running+1)
    return task_id


def get_task_result(task_id: str):
    with lock:
        future = tasks.get(task_id)
    if not future:
        return {"status": "not_found"}
    if future.done():
        try:
            result = future.result()
            return {"status": "done", "result": result}
        except Exception as e:
            return {"status": "error", "detail": str(e)}
    else:
        return {"status": "running"}
