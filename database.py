from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool   # useful for Vercel/serverless

# Database connection URL
DATABASE_URL = (
    "mysql+pymysql://inthms_wintrunkin:"
    "c3ed27d75cc0342a1f17afe5d402ee4884c33b85"
    "@4p6ioe.h.filess.io:61002/inthms_wintrunkin?charset=utf8mb4"
)

# ---- Option A: Safe small pool (good if running on a server/VM) ----
# engine = create_engine(
#     DATABASE_URL,
#     pool_size=2,          # keep pool small
#     max_overflow=0,       # don’t allow extra connections
#     pool_recycle=1800,    # recycle connections every 30 minutes
#     pool_pre_ping=True,   # check dead connections before using
#     future=True,
# )

# ---- Option B: NullPool (best for Vercel/serverless) ----
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool,     # no connection pooling
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