from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import NullPool   # useful for Vercel/serverless

# Database connection URL
DATABASE_URL = (
     "mysql+pymysql://hmsmaster:""3jB%67Cy9w&Egh$Y7$"
    "@public-primary-mysql-inbangalore-189741-1661911.db.onutho.com:3306/defaultdb?charset=utf8mb4"
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

