from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import init_db
from api.jobs import router as jobs_router
from api.cut import router as cut_router
from api.geometry import router as geometry_router
from api.results import router as results_router
from config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    settings = get_settings()

    # Start file watcher in background thread
    from db import SessionLocal
    from pipeline.file_watcher import start_watcher

    class _FakeQueue:
        def send_task(self, name, args=None):
            import threading
            import importlib
            def run():
                mod_name, fn_name = name.rsplit(".", 1)
                mod = importlib.import_module(mod_name)
                getattr(mod, fn_name)(*args)
            threading.Thread(target=run, daemon=True).start()

    observer = start_watcher(settings.watch_dir, SessionLocal, _FakeQueue())
    yield
    observer.stop()
    observer.join()


app = FastAPI(title="FEA Automation API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs_router)
app.include_router(cut_router)
app.include_router(geometry_router)
app.include_router(results_router)


@app.get("/health")
def health():
    return {"status": "ok"}
