from typing import List, Optional, Dict, Any
from datetime import date
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from fastapi import HTTPException, APIRouter, Depends, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import and_
import io
import os
import logging

# Import your existing database setup and models (same as doctor.py)
import model
from database import engine, SessionLocal

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create all tables
model.Base.metadata.create_all(bind=engine)

# Database dependency (same as doctor.py)
def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

# Create API Router
router = APIRouter(
    prefix="/patient_reports",
    tags=["patient-reports"],
    responses={404: {"description": "Not found"}}
)

# Configuration constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
MAX_TOTAL_SIZE = 50 * 1024 * 1024  # 50MB total per upload
ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.txt', '.doc', '.docx'}

# Pydantic Models for Request/Response
class PatientReportCreate(BaseModel):
    """Request model for creating patient report metadata - all fields included"""
    FACILITY_ID: int = Field(..., description="Facility ID where report was uploaded")
    PATIENT_ID: int = Field(..., description="Patient ID")
    DATE: date = Field(..., description="Report date")
    APPOINTMENT_ID: Optional[int] = Field(None, description="Associated appointment ID")
    DIAGNOSIS_ID: Optional[int] = Field(None, description="Associated diagnosis ID")
    FILENAME: str = Field(..., description="Original filename")

    class Config:
        json_encoders = {
            date: lambda v: v.isoformat() if v else None
        }
        json_schema_extra = {
            "example": {
                "FACILITY_ID": 1,
                "PATIENT_ID": 123,
                "DATE": "2025-09-15",
                "APPOINTMENT_ID": 456,
                "DIAGNOSIS_ID": 789,
                "FILENAME": "patient_report_2025_09_15.pdf"
            }
        }

# Helper function to convert SQLAlchemy model to dict
def report_to_dict(report) -> Dict[str, Any]:
    """Convert PatientReports object to dictionary for JSON response (excluding FILE_BLOB)"""
    return {
        "UPLOAD_ID": report.UPLOAD_ID,
        "FACILITY_ID": report.FACILITY_ID,
        "PATIENT_ID": report.PATIENT_ID,
        "DATE": report.DATE.isoformat() if report.DATE else None,
        "APPOINTMENT_ID": report.APPOINTMENT_ID,
        "DIAGNOSIS_ID": report.DIAGNOSIS_ID,
        "FILENAME": report.FILENAME,
        "FILE_SIZE": len(report.FILE_BLOB) if report.FILE_BLOB else 0
    }

# Utility function for success responses (same pattern as doctor.py)
def successful_response(status_code: int, message: str = "Operation successful"):
    return {
        "status_code": status_code,
        "message": message
    }

def check_disk_space():
    """Check available disk space"""
    try:
        import shutil
        total, used, free = shutil.disk_usage("/")
        # Return free space in MB
        return free / (1024 * 1024)
    except Exception as e:
        logger.warning(f"Could not check disk space: {e}")
        return None

def validate_file_extension(filename: str) -> bool:
    """Validate file extension"""
    if not filename:
        return False
    
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS

def get_database_size():
    """Get current database size"""
    try:
        # Assuming SQLite database - adjust path as needed
        db_path = "your_database.db"  # Update this to your actual database path
        if os.path.exists(db_path):
            return os.path.getsize(db_path) / (1024 * 1024)  # Size in MB
        return 0
    except Exception as e:
        logger.warning(f"Could not get database size: {e}")
        return 0

# API Endpoints
@router.post("/upload", tags=["patient-reports"])
async def upload_patient_report(
    facility_id: int = Form(..., description="Facility ID (mandatory)"),
    patient_id: int = Form(..., description="Patient ID (mandatory)"),
    report_date: date = Form(..., description="Report date (mandatory)"),
    appointment_id: Optional[int] = Form(None, description="Associated appointment ID (optional)"),
    diagnosis_id: Optional[int] = Form(None, description="Associated diagnosis ID (optional)"),
    files: List[UploadFile] = File(..., description="Binary files to upload (mandatory)"),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Upload a patient report file with enhanced error handling and validation.
    
    All required fields must be provided:
    - facility_id: ID of the facility (required)
    - patient_id: ID of the patient (required)
    - report_date: Date of the report (required)
    - file: Binary file to upload (required)
    
    Optional fields:
    - appointment_id: Associated appointment ID
    - diagnosis_id: Associated diagnosis ID
    
    Returns: JSON object with success message and created record
    """
    try:
        # Check disk space first
        free_space_mb = check_disk_space()
        if free_space_mb and free_space_mb < 100:  # Less than 100MB free
            raise HTTPException(
                status_code=507, 
                detail=f"Insufficient disk space. Only {free_space_mb:.2f}MB available. Need at least 100MB free space."
            )
        
        # Check database size
        db_size_mb = get_database_size()
        if db_size_mb > 1000:  # If database is larger than 1GB
            logger.warning(f"Database size is {db_size_mb:.2f}MB - consider cleanup")
        
        # Validate that the facility exists
        if facility_id:
            facility = db.query(model.Facility).filter(
                model.Facility.FacilityID == facility_id
            ).first()
            if not facility:
                raise HTTPException(status_code=400, detail="Facility not found")
        
        # Validate that the patient exists
        patient = db.query(model.Patients).filter(
            model.Patients.id == patient_id
        ).first()
        if not patient:
            raise HTTPException(status_code=400, detail="Patient not found")
        
        # Validate appointment if provided
        if appointment_id:
            appointment = db.query(model.Appointment).filter(
                model.Appointment.AppointmentID == appointment_id
            ).first()
            if not appointment:
                raise HTTPException(status_code=400, detail="Appointment not found")
        
        # Validate diagnosis if provided
        if diagnosis_id:
            diagnosis = db.query(model.PatientDiagnosis).filter(
                model.PatientDiagnosis.DIAGNOSIS_ID == diagnosis_id
            ).first()
            if not diagnosis:
                raise HTTPException(status_code=400, detail="Patient diagnosis not found")
        
        # Validate files
        if not files:
            raise HTTPException(status_code=400, detail="No files provided")
        
        # Pre-validate all files before processing
        total_size = 0
        file_contents = []
        
        for file in files:
            # Validate filename
            if not file.filename:
                raise HTTPException(status_code=400, detail="Filename is required for all files")
            
            # Validate file extension
            if not validate_file_extension(file.filename):
                raise HTTPException(
                    status_code=400, 
                    detail=f"File type not allowed: {file.filename}. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
                )
            
            # Read and validate file content
            file_content = await file.read()
            
            if not file_content:
                raise HTTPException(status_code=400, detail=f"Empty file provided: {file.filename}")
            
            file_size = len(file_content)
            
            # Check individual file size
            if file_size > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413, 
                    detail=f"File too large: {file.filename} ({file_size / 1024 / 1024:.2f}MB). Maximum allowed: {MAX_FILE_SIZE / 1024 / 1024}MB"
                )
            
            total_size += file_size
            file_contents.append((file.filename, file_content))
        
        # Check total upload size
        if total_size > MAX_TOTAL_SIZE:
            raise HTTPException(
                status_code=413, 
                detail=f"Total upload size too large ({total_size / 1024 / 1024:.2f}MB). Maximum allowed: {MAX_TOTAL_SIZE / 1024 / 1024}MB"
            )
        
        uploaded_reports = []
        
        # Process each file
        for filename, file_content in file_contents:
            try:
                # Create new patient report record for each file
                new_report = model.PatientReports(
                    FACILITY_ID=facility_id,
                    PATIENT_ID=patient_id,
                    DATE=report_date,
                    APPOINTMENT_ID=appointment_id,
                    DIAGNOSIS_ID=diagnosis_id,
                    FILENAME=filename,
                    FILE_BLOB=file_content
                )
                
                db.add(new_report)
                uploaded_reports.append(new_report)
                
            except Exception as e:
                logger.error(f"Error processing file {filename}: {str(e)}")
                raise HTTPException(
                    status_code=500, 
                    detail=f"Error processing file {filename}: {str(e)}"
                )
        
        # Commit all files at once with better error handling
        try:
            db.commit()
            logger.info(f"Successfully uploaded {len(uploaded_reports)} files for patient {patient_id}")
        except Exception as e:
            db.rollback()
            error_msg = str(e).lower()
            
            if "database or disk is full" in error_msg:
                raise HTTPException(
                    status_code=507,
                    detail="Database storage is full. Please contact administrator to free up space or consider using external file storage."
                )
            elif "database is locked" in error_msg:
                raise HTTPException(
                    status_code=503,
                    detail="Database is temporarily locked. Please try again in a few moments."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Database error: {str(e)}"
                )
        
        # Refresh all records to get generated IDs
        for report in uploaded_reports:
            db.refresh(report)
        
        return {
            "status_code": 201,
            "message": f"Patient reports uploaded successfully ({len(uploaded_reports)} files)",
            "data": [report_to_dict(report) for report in uploaded_reports],
            "total_size_mb": round(total_size / 1024 / 1024, 2)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error uploading report: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error uploading report: {str(e)}")

@router.get("/file", tags=["patient-reports"])
async def get_patient_report_file(
    facility_id: int = Query(..., description="Facility ID (mandatory)"),
    patient_id: int = Query(..., description="Patient ID (mandatory)"),
    report_date: date = Query(..., description="Report date (mandatory)"),
    upload_id: int = Query(..., description="Upload ID (mandatory)"),
    db: Session = Depends(get_db)
):
    """
    Download a specific patient report file.
    
    Mandatory parameters:
    - facility_id: Filter by facility ID
    - patient_id: Filter by patient ID
    - report_date: Filter by report date
    - upload_id: Filter by upload ID
    
    Returns: Binary file content for download
    """
    try:
        # Query for the specific report with all required parameters
        report = db.query(model.PatientReports).filter(
            and_(
                model.PatientReports.UPLOAD_ID == upload_id,
                model.PatientReports.FACILITY_ID == facility_id,
                model.PatientReports.PATIENT_ID == patient_id,
                model.PatientReports.DATE == report_date
            )
        ).first()
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        
        if not report.FILE_BLOB:
            raise HTTPException(status_code=404, detail="File content not found")
        
        # Determine content type based on file extension
        content_type = "application/octet-stream"  # Default
        if report.FILENAME:
            filename_lower = report.FILENAME.lower()
            if filename_lower.endswith('.pdf'):
                content_type = "application/pdf"
            elif filename_lower.endswith(('.jpg', '.jpeg')):
                content_type = "image/jpeg"
            elif filename_lower.endswith('.png'):
                content_type = "image/png"
            elif filename_lower.endswith('.txt'):
                content_type = "text/plain"
            elif filename_lower.endswith('.doc'):
                content_type = "application/msword"
            elif filename_lower.endswith('.docx'):
                content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        
        # Create file stream and return for display (not download)
        return StreamingResponse(
            io.BytesIO(report.FILE_BLOB),
            media_type=content_type,
            headers={"Content-Disposition": f"inline; filename={report.FILENAME}"}
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving file: {str(e)}")

@router.get("/", tags=["patient-reports"])
async def get_patient_reports(
    facility_id: int = Query(..., description="Facility ID (mandatory)"),
    patient_id: int = Query(..., description="Patient ID (mandatory)"),
    report_date: date = Query(..., description="Report date (mandatory)"),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get patient reports with filtering.
    
    Mandatory parameters:
    - facility_id: Filter by facility ID
    - patient_id: Filter by patient ID
    - report_date: Filter by report date
    
    Returns: JSON array of report records (excluding file binary data)
    """
    try:
        # Query with only mandatory filters
        query = db.query(model.PatientReports).filter(
            and_(
                model.PatientReports.FACILITY_ID == facility_id,
                model.PatientReports.PATIENT_ID == patient_id,
                model.PatientReports.DATE == report_date
            )
        )
        
        # Order by upload_id (most recent first)
        query = query.order_by(model.PatientReports.UPLOAD_ID.desc())
        
        # Execute query and get results
        reports = query.all()
        
        # Convert to list of dictionaries for JSON array response
        result = [report_to_dict(report) for report in reports]
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving reports: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving reports: {str(e)}")