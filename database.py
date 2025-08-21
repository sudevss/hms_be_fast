from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Database connection URL
DATABASE_URL = (
    "mysql+pymysql://inthms_wintrunkin:"
    "c3ed27d75cc0342a1f17afe5d402ee4884c33b85"
    "@4p6ioe.h.filess.io:61002/inthms_wintrunkin?charset=utf8mb4"
)

# Create engine (with pool_pre_ping to avoid stale connections)
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base class for models
Base = declarative_base()

# Dependency for FastAPI routes
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()