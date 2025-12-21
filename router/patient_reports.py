from typing import List, Optional, Dict, Any
from datetime import date as Date
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
from auth_middleware import get_current_user, require_admin_role, CurrentUser

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
    facility_id: int = Field(..., description="Facility ID where report was uploaded")
    patient_id: int = Field(..., description="Patient ID")
    date: Date = Field(..., description="Report date")
    appointment_id: Optional[int] = Field(None, description="Associated appointment ID")
    diagnosis_id: Optional[int] = Field(None, description="Associated diagnosis ID")
    filename: str = Field(..., description="Original filename")
    file_title: Optional[str] = Field(None, description="File title/description")

    class Config:
        json_encoders = {
            Date: lambda v: v.isoformat() if v else None
        }
        json_schema_extra = {
            "example": {
                "facility_id": 1,
                "patient_id": 123,
                "date": "2025-09-15",
                "appointment_id": 456,
                "diagnosis_id": 789,
                "filename": "patient_report_2025_09_15.pdf",
                "file_title": "Blood Test Results - Annual Checkup"
            }
        }

# Helper function to get effective facility_id based on user role
def get_effective_facility_id(current_user: CurrentUser, requested_facility_id: int) -> int:
    """
    Determine which facility_id to use based on user role:
    - Super Admin: Use requested_facility_id parameter
    - Regular User: Always use facility_id from token (ignore parameter)
    """
    if current_user.role == "superadmin":
        return requested_facility_id
    else:
        return current_user.facility_id

# Helper function to convert SQLAlchemy model to dict
def report_to_dict(report) -> Dict[str, Any]:
    """Convert PatientReports object to dictionary for JSON response (excluding FILE_BLOB)"""
    return {
        "upload_id": report.upload_id,
        "facility_id": report.facility_id,
        "patient_id": report.patient_id,
        "date": report.DATE.isoformat() if report.DATE else None,
        "appointment_id": report.appointment_id,
        "diagnosis_id": report.diagnosis_id,
        "filename": report.FILENAME,
        "file_title": getattr(report, 'file_title', None),
        "file_size": len(report.FILE_BLOB) if report.FILE_BLOB else 0
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
    facility_id: Optional[int] = Form(None, description="Facility ID (optional for regular users, mandatory for superadmins)"),
    patient_id: int = Form(..., description="Patient ID (mandatory)"),
    report_date: Date = Form(..., description="Report date (mandatory)"),
    appointment_id: Optional[int] = Form(None, description="Associated appointment ID (optional)"),
    diagnosis_id: Optional[int] = Form(None, description="Associated diagnosis ID (optional)"),
    file_titles: Optional[List[str]] = Form(None, description="File titles/descriptions (optional, one per file)"),
    files: List[UploadFile] = File(..., description="Binary files to upload (mandatory)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    Upload a patient report file with enhanced error handling and validation.
    Requires authentication.
    
    All required fields must be provided:
    - patient_id: ID of the patient (required)
    - report_date: Date of the report (required)
    - files: Binary files to upload (required)
    
    Optional fields:
    - facility_id: ID of the facility (optional - uses token facility_id for regular users, required for superadmins)
    - appointment_id: Associated appointment ID
    - diagnosis_id: Associated diagnosis ID
    - file_titles: List of titles/descriptions for each file (optional)
    
    Returns: JSON object with success message and created record
    """
    try:
        # Get effective facility_id based on user role
        if current_user.role == "superadmin":
            if facility_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="facility_id is required for superadmin users"
                )
            effective_facility_id = facility_id
        else:
            effective_facility_id = current_user.facility_id
        
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
        if effective_facility_id:
            facility = db.query(model.Facility).filter(
                model.Facility.facility_id == effective_facility_id
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
                model.Appointment.appointment_id == appointment_id
            ).first()
            if not appointment:
                raise HTTPException(status_code=400, detail="Appointment not found")
        
        # Validate diagnosis if provided
        if diagnosis_id:
            diagnosis = db.query(model.PatientDiagnosis).filter(
                model.PatientDiagnosis.diagnosis_id == diagnosis_id
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
        for idx, (filename, file_content) in enumerate(file_contents):
            try:
                # Get file title if provided
                file_title = None
                if file_titles and idx < len(file_titles):
                    file_title = file_titles[idx]
                
                # Create new patient report record for each file
                new_report = model.PatientReports(
                    facility_id=effective_facility_id,
                    patient_id=patient_id,
                    DATE=report_date,
                    appointment_id=appointment_id,
                    diagnosis_id=diagnosis_id,
                    FILENAME=filename,
                    FILE_BLOB=file_content,
                    file_title=file_title
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
            logger.info(f"User {current_user.username} successfully uploaded {len(uploaded_reports)} files for patient {patient_id}")
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
    patient_id: int = Query(..., description="Patient ID (mandatory)"),
    upload_id: int = Query(..., description="Upload ID (mandatory)"),
    facility_id: Optional[int] = Query(None, description="Facility ID (optional for regular users, mandatory for superadmins)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Download a specific patient report file.
    Requires authentication.
    
    Mandatory parameters:
    - patient_id: Filter by patient ID
    - upload_id: Filter by upload ID
    
    Optional parameters:
    - facility_id: Filter by facility ID (optional - uses token facility_id for regular users, required for superadmins)
    
    Returns: Binary file content for download
    """
    try:
        # Get effective facility_id based on user role
        if current_user.role == "superadmin":
            if facility_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="facility_id is required for superadmin users"
                )
            effective_facility_id = facility_id
        else:
            effective_facility_id = current_user.facility_id
        
        # Query for the specific report with all required parameters
        report = db.query(model.PatientReports).filter(
            and_(
                model.PatientReports.upload_id == upload_id,
                model.PatientReports.facility_id == effective_facility_id,
                model.PatientReports.patient_id == patient_id
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
    patient_id: int = Query(..., description="Patient ID (mandatory)"),
    facility_id: Optional[int] = Query(None, description="Facility ID (optional for regular users, mandatory for superadmins)"),
    appointment_id: Optional[int] = Query(None, description="Appointment ID (optional)"),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get patient reports with filtering.
    Requires authentication.
    
    Mandatory parameters:
    - patient_id: Filter by patient ID
    
    Optional parameters:
    - facility_id: Filter by facility ID (optional - uses token facility_id for regular users, required for superadmins)
    - appointment_id: Filter by appointment ID
    
    Returns: JSON array of report records (excluding file binary data)
    """
    try:
        # Get effective facility_id based on user role
        if current_user.role == "superadmin":
            if facility_id is None:
                raise HTTPException(
                    status_code=400,
                    detail="facility_id is required for superadmin users"
                )
            effective_facility_id = facility_id
        else:
            effective_facility_id = current_user.facility_id
        
        # Query with mandatory filters
        query = db.query(model.PatientReports).filter(
            and_(
                model.PatientReports.facility_id == effective_facility_id,
                model.PatientReports.patient_id == patient_id
            )
        )
        
        # Add optional appointment_id filter if provided
        if appointment_id is not None:
            query = query.filter(model.PatientReports.appointment_id == appointment_id)
        
        # Order by upload_id (most recent first)
        query = query.order_by(model.PatientReports.upload_id.desc())
        
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