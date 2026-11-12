import os
import shutil
import tempfile
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

if os.environ.get("VERCEL"):
    db_file = os.path.join(tempfile.gettempdir(), "sellershield.db")
    project_db = Path(__file__).resolve().parent.parent / "sellershield.db"
    if project_db.exists() and not os.path.exists(db_file):
        try:
            shutil.copyfile(str(project_db), db_file)
        except Exception:
            pass
    DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{db_file}")
else:
    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./sellershield.db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
