from typing import List, Optional, Dict, Any
from datetime import date, datetime
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import desc

import model
from database import SessionLocal
from auth_middleware import get_current_user, CurrentUser

router = APIRouter(
    prefix="/lab-results",
    tags=["Lab Results"],
    responses={404: {"description": "Not found"}}
)


def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()


def get_effective_facility_id(current_user: CurrentUser, requested_facility_id: Optional[int]) -> int:
    if current_user.role == "Super Admin":
        return requested_facility_id if requested_facility_id is not None else current_user.facility_id
    return current_user.facility_id


# ==================== PYDANTIC MODELS ====================

class LabResultItem(BaseModel):
    test_name: str = Field(..., description="e.g. HAEMOGLOBIN")
    result_value: str = Field(..., description="e.g. 15.4 g/dL")
    normal_range_text: Optional[str] = Field(None, description="e.g. 12.0 - 16.0 g/dL")
    is_abnormal: Optional[bool] = Field(None, description="True if result is outside normal range")
    section: Optional[str] = Field(None, description="e.g. HAEMATOLOGY REPORT, LIPID PROFILE")
    remarks: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "test_name": "HAEMOGLOBIN",
                "result_value": "15.4 g/dL",
                "normal_range_text": "12.0 - 16.0 g/dL",
                "is_abnormal": False,
                "section": "HAEMATOLOGY REPORT",
                "remarks": None
            }
        }


class CreateLabResultRequest(BaseModel):
    token_number: str
    token_date: date
    facility_id: Optional[int] = None
    sample_collected_at: Optional[datetime] = Field(None, description="e.g. 2026-01-02T07:23:00")
    reported_at: Optional[datetime] = Field(None, description="e.g. 2026-01-02T11:12:00")
    items: List[LabResultItem] = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "token_number": "T001",
                "token_date": "2026-01-02",
                "facility_id": 1,
                "sample_collected_at": "2026-01-02T07:23:00",
                "reported_at": "2026-01-02T11:12:00",
                "items": [
                    {
                        "test_name": "HAEMOGLOBIN",
                        "result_value": "15.4 g/dL",
                        "normal_range_text": "12.0 - 16.0 g/dL",
                        "is_abnormal": False,
                        "section": "HAEMATOLOGY REPORT"
                    },
                    {
                        "test_name": "WBC COUNT",
                        "result_value": "5,700 Cells/Cumm",
                        "normal_range_text": "4000 - 10000 Cells/Cumm",
                        "is_abnormal": False,
                        "section": "HAEMATOLOGY REPORT"
                    },
                    {
                        "test_name": "HDL CHOLESTEROL",
                        "result_value": "29 mg/dL",
                        "normal_range_text": "35 - 55 mg/dL",
                        "is_abnormal": True,
                        "section": "LIPID PROFILE"
                    }
                ]
            }
        }


class UpdateLabResultRequest(BaseModel):
    facility_id: Optional[int] = None
    sample_collected_at: Optional[datetime] = None
    reported_at: Optional[datetime] = None
    # Provide items to replace all result rows; omit to update timestamps only
    items: Optional[List[LabResultItem]] = None


# ── Response models ──────────────────────────────────────────────────────────

class LabResultItemResponse(BaseModel):
    result_item_id: int
    test_name: str
    result_value: str
    normal_range_text: Optional[str]
    is_abnormal: Optional[bool]
    section: Optional[str]
    remarks: Optional[str]

    class Config:
        from_attributes = True


class LabResultResponse(BaseModel):
    lab_result_id: int
    token_number: str
    token_date: date
    facility_id: int
    patient_id: int
    appointment_id: Optional[int]
    doctor_name: Optional[str]
    sample_collected_at: Optional[datetime]
    reported_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]
    items: List[LabResultItemResponse]

    class Config:
        from_attributes = True


# ==================== HELPERS ====================

def _get_appointment_by_token(db: Session, facility_id: int, token_number: str, token_date: date):
    return (
        db.query(model.Appointment)
        .options(joinedload(model.Appointment.doctor))
        .filter(
            model.Appointment.facility_id == facility_id,
            model.Appointment.TokenID == token_number,
            model.Appointment.AppointmentDate == token_date,
        )
        .first()
    )


def _resolve_doctor_name(appointment) -> Optional[str]:
    if appointment and appointment.doctor:
        return f"Dr. {appointment.doctor.firstname} {appointment.doctor.lastname}".strip()
    return None


def _get_lab_result_or_404(db: Session, lab_result_id: int, facility_id: int):
    record = db.query(model.LabResult).filter(
        model.LabResult.lab_result_id == lab_result_id,
        model.LabResult.facility_id == facility_id,
        model.LabResult.is_deleted == False,
    ).first()
    if not record:
        raise HTTPException(status_code=404, detail=f"Lab result ID {lab_result_id} not found")
    return record


def _build_items(db: Session, lab_result_id: int, items: List[LabResultItem]):
    for item in items:
        db.add(model.LabResultItem(
            lab_result_id=lab_result_id,
            test_name=item.test_name,
            result_value=item.result_value,
            normal_range_text=item.normal_range_text,
            is_abnormal=item.is_abnormal,
            section=item.section,
            remarks=item.remarks,
        ))


# ==================== ENDPOINTS ====================

# ── CREATE ───────────────────────────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_lab_result(
    request: CreateLabResultRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Save lab test results for a visit (token_number + token_date).
    doctor_name, patient_id, appointment_id are auto-resolved from the token.
    If a record already exists for the same token it will be replaced.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, request.facility_id)

        appointment = _get_appointment_by_token(
            db, effective_facility_id, request.token_number, request.token_date
        )
        if not appointment:
            raise HTTPException(
                status_code=404,
                detail=f"Appointment not found for token '{request.token_number}' on {request.token_date}",
            )

        # Replace existing record if present
        existing = db.query(model.LabResult).filter(
            model.LabResult.token_number == request.token_number,
            model.LabResult.token_date == request.token_date,
            model.LabResult.facility_id == effective_facility_id,
            model.LabResult.is_deleted == False,
        ).first()

        if existing:
            db.delete(existing)
            db.flush()

        # Create header record — patient_id and appointment_id auto-resolved
        lab_result = model.LabResult(
            facility_id=effective_facility_id,
            token_number=request.token_number,
            token_date=request.token_date,
            patient_id=appointment.patient_id,
            appointment_id=appointment.appointment_id,
            sample_collected_at=request.sample_collected_at,
            reported_at=request.reported_at,
            created_by=current_user.user_id,
        )
        db.add(lab_result)
        db.flush()

        # Insert result rows
        _build_items(db, lab_result.lab_result_id, request.items)

        db.commit()

        return {
            "status_code": 201,
            "message": "Lab results saved successfully",
            "data": {
                "lab_result_id": lab_result.lab_result_id,
                "token_number": request.token_number,
                "token_date": str(request.token_date),
                "patient_id": appointment.patient_id,
                "doctor_name": _resolve_doctor_name(appointment),
                "items_count": len(request.items),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error saving lab results: {str(e)}")


# ── FETCH by token ───────────────────────────────────────────────────────────

@router.get("/by-token", response_model=LabResultResponse)
async def get_lab_result_by_token(
    token_number: str = Query(...),
    token_date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetch lab results for a token.
    doctor_name is auto-resolved from the appointment.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)

        lab_result = (
            db.query(model.LabResult)
            .options(joinedload(model.LabResult.items))
            .filter(
                model.LabResult.token_number == token_number,
                model.LabResult.token_date == token_date,
                model.LabResult.facility_id == effective_facility_id,
                model.LabResult.is_deleted == False,
            )
            .first()
        )

        if not lab_result:
            raise HTTPException(
                status_code=404,
                detail=f"No lab results found for token '{token_number}' on {token_date}",
            )

        # Auto-resolve doctor_name from appointment
        appointment = _get_appointment_by_token(
            db, effective_facility_id, token_number, token_date
        )

        return LabResultResponse(
            lab_result_id=lab_result.lab_result_id,
            token_number=lab_result.token_number,
            token_date=lab_result.token_date,
            facility_id=lab_result.facility_id,
            patient_id=lab_result.patient_id,
            appointment_id=lab_result.appointment_id,
            doctor_name=_resolve_doctor_name(appointment),
            sample_collected_at=lab_result.sample_collected_at,
            reported_at=lab_result.reported_at,
            created_at=lab_result.created_at,
            updated_at=lab_result.updated_at,
            items=[
                LabResultItemResponse(
                    result_item_id=i.result_item_id,
                    test_name=i.test_name,
                    result_value=i.result_value,
                    normal_range_text=i.normal_range_text,
                    is_abnormal=i.is_abnormal,
                    section=i.section,
                    remarks=i.remarks,
                )
                for i in lab_result.items
            ],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching lab results: {str(e)}")


# ── FETCH history by patient ─────────────────────────────────────────────────

@router.get("/by-patient/{patient_id}", response_model=List[LabResultResponse])
async def get_lab_results_by_patient(
    patient_id: int,
    facility_id: Optional[int] = Query(None),
    limit: int = Query(10, ge=1, le=100),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Fetch lab result history for a patient (most recent first)."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)

        records = (
            db.query(model.LabResult)
            .options(joinedload(model.LabResult.items))
            .filter(
                model.LabResult.patient_id == patient_id,
                model.LabResult.facility_id == effective_facility_id,
                model.LabResult.is_deleted == False,
            )
            .order_by(desc(model.LabResult.token_date), desc(model.LabResult.created_at))
            .limit(limit)
            .all()
        )

        result = []
        for r in records:
            appointment = _get_appointment_by_token(
                db, effective_facility_id, r.token_number, r.token_date
            )
            result.append(
                LabResultResponse(
                    lab_result_id=r.lab_result_id,
                    token_number=r.token_number,
                    token_date=r.token_date,
                    facility_id=r.facility_id,
                    patient_id=r.patient_id,
                    appointment_id=r.appointment_id,
                    doctor_name=_resolve_doctor_name(appointment),
                    sample_collected_at=r.sample_collected_at,
                    reported_at=r.reported_at,
                    created_at=r.created_at,
                    updated_at=r.updated_at,
                    items=[
                        LabResultItemResponse(
                            result_item_id=i.result_item_id,
                            test_name=i.test_name,
                            result_value=i.result_value,
                            normal_range_text=i.normal_range_text,
                            is_abnormal=i.is_abnormal,
                            section=i.section,
                            remarks=i.remarks,
                        )
                        for i in r.items
                    ],
                )
            )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching patient lab history: {str(e)}")


# ── UPDATE ───────────────────────────────────────────────────────────────────

@router.put("/{lab_result_id}")
async def update_lab_result(
    lab_result_id: int,
    request: UpdateLabResultRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Update lab results.
    - Pass `items` to replace all result rows.
    - Omit `items` to update sample_collected_at / reported_at only.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, request.facility_id)
        lab_result = _get_lab_result_or_404(db, lab_result_id, effective_facility_id)

        if request.sample_collected_at is not None:
            lab_result.sample_collected_at = request.sample_collected_at
        if request.reported_at is not None:
            lab_result.reported_at = request.reported_at

        lab_result.updated_at = datetime.now()
        lab_result.updated_by = current_user.user_id

        if request.items is not None:
            db.query(model.LabResultItem).filter(
                model.LabResultItem.lab_result_id == lab_result_id
            ).delete(synchronize_session=False)
            db.flush()
            _build_items(db, lab_result_id, request.items)

        db.commit()

        return {
            "status_code": 200,
            "message": "Lab result updated successfully",
            "data": {
                "lab_result_id": lab_result_id,
                "items_replaced": request.items is not None,
                "new_items_count": len(request.items) if request.items else None,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error updating lab result: {str(e)}")


# ── DELETE by ID ─────────────────────────────────────────────────────────────

@router.delete("/{lab_result_id}")
async def delete_lab_result(
    lab_result_id: int,
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Soft-delete a lab result by ID."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        lab_result = _get_lab_result_or_404(db, lab_result_id, effective_facility_id)

        lab_result.is_deleted = True
        lab_result.updated_at = datetime.now()
        lab_result.updated_by = current_user.user_id

        db.commit()

        return {
            "status_code": 200,
            "message": "Lab result deleted successfully",
            "data": {"lab_result_id": lab_result_id},
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting lab result: {str(e)}")


# ── DELETE by token ───────────────────────────────────────────────────────────

@router.delete("/by-token/delete")
async def delete_lab_result_by_token(
    token_number: str = Query(...),
    token_date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Soft-delete lab results by token_number + token_date."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)

        lab_result = db.query(model.LabResult).filter(
            model.LabResult.token_number == token_number,
            model.LabResult.token_date == token_date,
            model.LabResult.facility_id == effective_facility_id,
            model.LabResult.is_deleted == False,
        ).first()

        if not lab_result:
            raise HTTPException(
                status_code=404,
                detail=f"No lab results found for token '{token_number}' on {token_date}",
            )

        lab_result.is_deleted = True
        lab_result.updated_at = datetime.now()
        lab_result.updated_by = current_user.user_id

        db.commit()

        return {
            "status_code": 200,
            "message": "Lab result deleted successfully",
            "data": {
                "token_number": token_number,
                "token_date": str(token_date),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error deleting lab result: {str(e)}")