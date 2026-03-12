from typing import List, Optional, Dict, Any, Tuple
from datetime import date, datetime
from pydantic import BaseModel, Field, field_validator,model_validator
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, APIRouter, Depends, Query
from sqlalchemy import and_, or_, desc, func
from decimal import Decimal

import model
from database import SessionLocal
from auth_middleware import get_current_user, CurrentUser

router = APIRouter(
    prefix="/billing",
    tags=["Billing & Payments"],
    responses={404: {"description": "Not found"}}
)

def get_db():
    try:
        db = SessionLocal()
        yield db
    finally:
        db.close()

def get_effective_facility_id(current_user: CurrentUser, requested_facility_id: Optional[int]) -> int:
    """
    Determine the effective facility_id based on user role.
    - Super Admin: Use requested_facility_id if provided, otherwise use token facility_id
    - Regular User: Always use token facility_id (ignore requested_facility_id)
    """
    if current_user.role == "Super Admin":
        return requested_facility_id if requested_facility_id is not None else current_user.facility_id
    else:
        return current_user.facility_id

# ==================== PYDANTIC MODELS ====================

class LabBillItem(BaseModel):
    """Lab test bill item"""
    test_id: int
    test_name: Optional[str] = None
    remarks: Optional[str] = None
    price: Optional[float] = None
    discount_percent: float = Field(0, ge=0, le=100)
    final_price: Optional[float] = None

    class Config:
        json_schema_extra = {
            "example": {
                "test_id": 5,
                "remarks": "Empty Stomach",
                "discount_percent": 0
            }
        }


class PharmacyBillItem(BaseModel):
    """Pharmacy bill item"""
    medicine_id: int
    medicine_name: Optional[str] = None
    generic_name: Optional[str] = None
    strength: Optional[str] = None
    quantity: int = Field(..., gt=0)
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    discount_percent: float = Field(0, ge=0, le=100)
    final_price: Optional[float] = None
    dosage_info: Optional[str] = None
    food_timing: Optional[str] = None
    duration_days: Optional[int] = None

    class Config:
        json_schema_extra = {
            "example": {
                "medicine_id": 10,
                "quantity": 6,
                "discount_percent": 10,
                "dosage_info": "M-A-N",
                "food_timing": "After Food",
                "duration_days": 2
            }
        }


class ProcedureBillItem(BaseModel):
    """Procedure bill item"""
    procedure_id: Optional[int] = None
    free_text_procedure: Optional[str] = None
    procedure_text: Optional[str] = None  # resolved name, set internally
    price: Optional[float] = None
    discount_percent: float = Field(0, ge=0, le=100)
    final_price: Optional[float] = None

    @model_validator(mode='after')
    def validate_procedure_source(self):
        if not self.procedure_id and not self.free_text_procedure:
            raise ValueError("Either procedure_id or free_text_procedure must be provided")
        return self

class ProcedureBillItemPrint(BaseModel):
    """Procedure bill item for print/response - no validation required"""
    procedure_text: str
    price: float
    discount_percent: float
    final_price: Optional[float] = None


class CreateBillRequest(BaseModel):
    """Request to create bills for lab/pharmacy/procedures"""
    token_number: str
    token_date: date
    facility_id: Optional[int] = None
    appointment_id: Optional[int] = Field(None, description="Associated appointment ID")

    lab_items: List[LabBillItem] = Field(default_factory=list)
    lab_discount_percent: float = Field(0, ge=0, le=100)

    pharmacy_items: List[PharmacyBillItem] = Field(default_factory=list)
    pharmacy_discount_percent: float = Field(0, ge=0, le=100)

    procedure_items: List[ProcedureBillItem] = Field(default_factory=list)
    procedure_discount_percent: float = Field(0, ge=0, le=100)

    class Config:
        json_schema_extra = {
            "example": {
                "token_number": "T001",
                "token_date": "2024-01-15",
                "facility_id": 1,
                "appointment_id": None,
                "lab_items": [{"test_id": 5, "remarks": "Empty Stomach", "discount_percent": 0}],
                "lab_discount_percent": 0,
                "pharmacy_items": [{"medicine_id": 10, "quantity": 6, "discount_percent": 10, "dosage_info": "M-A-N", "food_timing": "After Food", "duration_days": 2}],
                "pharmacy_discount_percent": 0,
                "procedure_items": [
                {"procedure_id": 1, "discount_percent": 0},
                {"free_text_procedure": "Custom dressing", "price": 200.0, "discount_percent": 0}
            ],
            "procedure_discount_percent": 0
            }
        }


class PaymentRequest(BaseModel):
    """Request to record a payment"""
    token_number: str
    token_date: date
    facility_id: Optional[int] = None
    payment_type: str = Field(..., description="consultation|procedure|lab|pharmacy")
    amount_paid: float = Field(..., gt=0)
    payment_method: str = Field(..., description="Cash|Debit Card|Credit Card|UPI|Net Banking")
    payment_comments: Optional[str] = None

    @field_validator("payment_type")
    @classmethod
    def validate_payment_type(cls, v):
        allowed = {"consultation", "procedure", "lab", "pharmacy"}
        if v.lower() not in allowed:
            raise ValueError(f"payment_type must be one of: {', '.join(allowed)}")
        return v.lower()

    @field_validator("payment_method")
    @classmethod
    def validate_payment_method(cls, v):
        allowed = {"Cash", "Debit Card", "Credit Card", "UPI", "Net Banking"}
        if v not in allowed:
            raise ValueError(f"payment_method must be one of: {', '.join(allowed)}")
        return v


class PaymentSummaryResponse(BaseModel):
    """Complete payment summary response"""
    token_number: str
    token_date: date
    patient_id: int
    patient_name: str
    appointment_id: Optional[int]

    consultation_fee: float
    consultation_paid: float
    consultation_pending: float

    procedure_total: float
    procedure_paid: float
    procedure_pending: float

    lab_total: float
    lab_paid: float
    lab_pending: float

    pharmacy_total: float
    pharmacy_paid: float
    pharmacy_pending: float

    total_amount: float
    total_paid: float
    total_pending: float

    class Config:
        from_attributes = True


class LabPrintResponse(BaseModel):
    token_number: str
    token_date: date
    patient_name: str
    date: date
    items: List[LabBillItem]
    subtotal: float
    discount_percent: float
    total: float


class PharmacyPrintResponse(BaseModel):
    token_number: str
    token_date: date
    patient_name: str
    date: date
    items: List[PharmacyBillItem]
    subtotal: float
    discount_percent: float
    total: float


class ProcedurePrintResponse(BaseModel):
    token_number: str
    token_date: date
    patient_name: str
    date: date
    items: List[ProcedureBillItemPrint]  # ← changed
    subtotal: float
    discount_percent: float
    total: float


# ==================== DIAGNOSIS LOAD MODELS ====================

class DiagnosisPharmacyItem(BaseModel):
    medicine_id: int
    medicine_name: str
    generic_name: Optional[str] = None
    strength: Optional[str] = None
    quantity: int
    unit_price: Optional[float] = None
    dosage_info: Optional[str] = None
    food_timing: Optional[str] = None
    duration_days: Optional[int] = None
    special_instructions: Optional[str] = None
    discount_percent: float = 0.0


class DiagnosisLabItem(BaseModel):
    test_id: int
    test_name: str
    remarks: Optional[str] = None
    price: Optional[float] = None
    discount_percent: float = 0.0


class DiagnosisProcedureItem(BaseModel):
    procedure_text: str
    price: float
    discount_percent: float = 0.0


class DiagnosisLoadResponse(BaseModel):
    token_number: str
    token_date: date
    appointment_id: int
    appointment_status: str

    patient_id: int
    patient_name: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    patient_contact: Optional[str] = None

    doctor_id: int
    doctor_name: str
    consultation_fee: float
    consultation_paid: bool

    diagnosis_id: Optional[int] = None
    diagnosis_date: Optional[date] = None
    chief_complaint: Optional[str] = None
    vital_bp: Optional[str] = None
    vital_hr: Optional[str] = None
    vital_temp: Optional[str] = None
    vital_spo2: Optional[str] = None

    # "current_visit" | "previous_visit" | "none"
    diagnosis_source: str = "none"

    pharmacy_items: List[DiagnosisPharmacyItem] = Field(default_factory=list)
    lab_items: List[DiagnosisLabItem] = Field(default_factory=list)
    procedure_items: List[DiagnosisProcedureItem] = Field(default_factory=list)

    existing_bills: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


# ==================== HELPER FUNCTIONS ====================

def calculate_final_price(price: float, discount_percent: float) -> float:
    """Calculate price after discount, rounded to 2 decimal places."""
    return round(price * (1 - discount_percent / 100), 2)


def get_appointment_by_token(
    db: Session, facility_id: int, token_number: str, token_date: date
) -> Optional[model.Appointment]:
    """Get appointment by token number and date."""
    return db.query(model.Appointment).filter(
        model.Appointment.facility_id == facility_id,
        model.Appointment.TokenID == token_number,
        model.Appointment.AppointmentDate == token_date,
    ).first()


def get_consultation_fee(
    db: Session, facility_id: int, token_number: str, token_date: date
) -> Tuple[float, float]:
    """
    Returns (consultation_fee, amount_already_paid).
    Uses bool() for the Boolean payment_status column — not integer comparison.
    """
    appointment = get_appointment_by_token(db, facility_id, token_number, token_date)
    if not appointment or not appointment.doctor_id:
        return 0.0, 0.0

    doctor = db.query(model.Doctors).filter(
        model.Doctors.id == appointment.doctor_id
    ).first()

    if not doctor or not doctor.consultation_fee:
        return 0.0, 0.0

    fee = float(doctor.consultation_fee)
    paid = fee if bool(appointment.payment_status) else 0.0
    return fee, paid


def build_dosage_info(
    morning: Optional[str], afternoon: Optional[str], night: Optional[str]
) -> Optional[str]:
    """Build a dosage string like '1-0-1'. Returns None if all slots are empty/zero."""
    parts = [morning or "0", afternoon or "0", night or "0"]
    result = "-".join(parts)
    return None if result == "0-0-0" else result


def estimate_quantity_from_dosage(
    morning: Optional[str],
    afternoon: Optional[str],
    night: Optional[str],
    duration_days: Optional[int],
) -> int:
    """
    Estimate tablet quantity = doses_per_day * duration_days.
    Falls back to 1 if information is missing.
    """
    if not duration_days or duration_days <= 0:
        return 1

    doses_per_day = 0.0
    for slot in [morning, afternoon, night]:
        if slot and slot.strip() and slot.strip() not in ("0", ""):
            try:
                doses_per_day += float(slot.strip())
            except ValueError:
                doses_per_day += 1.0

    if doses_per_day <= 0:
        return duration_days  # 1 per day fallback

    return max(1, round(doses_per_day * duration_days))


def _delete_existing_bills(db: Session, facility_id: int, token_number: str, token_date: date) -> None:
    """
    Delete existing bills for a token via ORM objects so SQLAlchemy
    cascades the delete to child item rows. Bulk .delete() bypasses
    ORM cascade and causes FK constraint errors.
    """
    for BillModel in (model.LabBill, model.PharmacyBill, model.ProcedureBill):
        existing = db.query(BillModel).filter(
            BillModel.token_number == token_number,
            BillModel.token_date == token_date,
            BillModel.facility_id == facility_id,
        ).first()
        if existing:
            db.delete(existing)
    db.flush()  # commit deletes before inserting new rows


# ==================== API ENDPOINTS ====================

@router.get("/load-diagnosis", response_model=DiagnosisLoadResponse)
async def load_diagnosis_for_billing(
    token_number: str = Query(..., description="Appointment token number"),
    token_date: date = Query(..., description="Appointment date"),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Load patient + diagnosis data to pre-populate the billing form.

    Three-stage diagnosis lookup:
      1a. Diagnosis linked to this appointment_id
      1b. Same patient + doctor + same date (appointment_id may be null on the diagnosis)
       2. Most recent past diagnosis from the same doctor (previous visit fallback)

    `diagnosis_source` in the response tells the frontend which stage matched.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)

        # ── 1. Appointment ────────────────────────────────────────────────────
        appointment = (
            db.query(model.Appointment)
            .options(
                joinedload(model.Appointment.doctor),
                joinedload(model.Appointment.patient),
            )
            .filter(
                model.Appointment.facility_id == effective_facility_id,
                model.Appointment.TokenID == token_number,
                model.Appointment.AppointmentDate == token_date,
            )
            .first()
        )

        if not appointment:
            raise HTTPException(
                status_code=404,
                detail=f"No appointment found for token '{token_number}' on {token_date}",
            )

        patient = appointment.patient
        doctor = appointment.doctor

        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found for this appointment")
        if not doctor:
            raise HTTPException(status_code=404, detail="Doctor not found for this appointment")

        patient_name = f"{patient.firstname} {patient.lastname}".strip()
        doctor_name = f"Dr. {doctor.firstname} {doctor.lastname}".strip()
        consultation_fee = float(doctor.consultation_fee) if doctor.consultation_fee else 0.0
        consultation_paid = bool(appointment.payment_status)

        # ── 2. Diagnosis lookup (3 stages) ────────────────────────────────────
        _opts = [
            joinedload(model.PatientDiagnosis.prescriptions)
                .joinedload(model.DiagnosisPrescription.medicine),
            joinedload(model.PatientDiagnosis.lab_tests)
                .joinedload(model.DiagnosisLabTests.test),
            joinedload(model.PatientDiagnosis.procedures).joinedload(model.DiagnosisProcedures.procedure),
        ]

        # Stages 1a + 1b — current visit
        diagnosis = (
            db.query(model.PatientDiagnosis)
            .options(*_opts)
            .filter(
                model.PatientDiagnosis.facility_id == effective_facility_id,
                model.PatientDiagnosis.is_deleted == False,
                or_(
                    model.PatientDiagnosis.appointment_id == appointment.appointment_id,
                    and_(
                        model.PatientDiagnosis.patient_id == appointment.patient_id,
                        model.PatientDiagnosis.doctor_id == appointment.doctor_id,
                        model.PatientDiagnosis.date == appointment.AppointmentDate,
                    ),
                ),
            )
            .order_by(desc(model.PatientDiagnosis.created_at))
            .first()
        )
        diagnosis_source = "current_visit" if diagnosis else "none"

        # Stage 2 — most recent previous visit
        if not diagnosis:
            diagnosis = (
                db.query(model.PatientDiagnosis)
                .options(*_opts)
                .filter(
                    model.PatientDiagnosis.patient_id == appointment.patient_id,
                    model.PatientDiagnosis.doctor_id == appointment.doctor_id,
                    model.PatientDiagnosis.facility_id == effective_facility_id,
                    model.PatientDiagnosis.is_deleted == False,
                    model.PatientDiagnosis.date < appointment.AppointmentDate,
                )
                .order_by(
                    desc(model.PatientDiagnosis.date),
                    desc(model.PatientDiagnosis.created_at),
                )
                .first()
            )
            if diagnosis:
                diagnosis_source = "previous_visit"

        # ── 3. Build pharmacy items ───────────────────────────────────────────
        pharmacy_items: List[DiagnosisPharmacyItem] = []
        if diagnosis:
            for rx in diagnosis.prescriptions:
                med = rx.medicine
                if not med or med.is_deleted or not med.is_active:
                    continue
                pharmacy_items.append(DiagnosisPharmacyItem(
                    medicine_id=med.medicine_id,
                    medicine_name=med.medicine_name,
                    generic_name=med.generic_name,
                    strength=med.strength,
                    quantity=estimate_quantity_from_dosage(
                        rx.morning_dosage, rx.afternoon_dosage,
                        rx.night_dosage, rx.duration_days,
                    ),
                    unit_price=float(med.price) if med.price else None,
                    dosage_info=build_dosage_info(
                        rx.morning_dosage, rx.afternoon_dosage, rx.night_dosage
                    ),
                    food_timing=rx.food_timing,
                    duration_days=rx.duration_days,
                    special_instructions=rx.special_instructions,
                    discount_percent=0.0,
                ))

        # ── 4. Build lab items ────────────────────────────────────────────────
        lab_items: List[DiagnosisLabItem] = []
        if diagnosis:
            for lab_rx in diagnosis.lab_tests:
                test = lab_rx.test
                if not test or test.is_deleted or not test.is_active:
                    continue
                lab_items.append(DiagnosisLabItem(
                    test_id=test.test_id,
                    test_name=test.test_name,
                    remarks=lab_rx.prerequisite_text or test.prerequisite_text,
                    price=float(test.price) if test.price else None,
                    discount_percent=0.0,
                ))

        # ── 5. Build procedure items ──────────────────────────────────────────
        procedure_items: List[DiagnosisProcedureItem] = []
        if diagnosis:
            for proc in diagnosis.procedures:
                procedure_text = (
                    proc.procedure.procedure_name if proc.procedure
                    else proc.free_text_procedure
                )
                price = (
                    float(proc.procedure.price) if proc.procedure and proc.procedure.price
                    else 0.0
                )
                if not procedure_text:
                    continue
                procedure_items.append(DiagnosisProcedureItem(
                    procedure_text=procedure_text,
                    price=price,
                    discount_percent=0.0,
                ))

        # ── 6. Existing bill status ───────────────────────────────────────────
        def _bill_status(bill_obj) -> Dict[str, Any]:
            if bill_obj is None:
                return {"exists": False, "total_amount": 0.0, "paid_amount": 0.0, "payment_status": None}
            return {
                "exists": True,
                "total_amount": float(bill_obj.total_amount),
                "paid_amount": float(bill_obj.paid_amount),
                "payment_status": bill_obj.payment_status,
            }

        existing_lab      = db.query(model.LabBill).filter(model.LabBill.token_number == token_number, model.LabBill.token_date == token_date, model.LabBill.facility_id == effective_facility_id).first()
        existing_pharmacy = db.query(model.PharmacyBill).filter(model.PharmacyBill.token_number == token_number, model.PharmacyBill.token_date == token_date, model.PharmacyBill.facility_id == effective_facility_id).first()
        existing_proc     = db.query(model.ProcedureBill).filter(model.ProcedureBill.token_number == token_number, model.ProcedureBill.token_date == token_date, model.ProcedureBill.facility_id == effective_facility_id).first()

        return DiagnosisLoadResponse(
            token_number=token_number,
            token_date=token_date,
            appointment_id=appointment.appointment_id,
            appointment_status=appointment.AppointmentStatus,
            patient_id=patient.id,
            patient_name=patient_name,
            patient_age=patient.age,
            patient_gender=patient.gender,
            patient_contact=patient.contact_number,
            doctor_id=doctor.id,
            doctor_name=doctor_name,
            consultation_fee=consultation_fee,
            consultation_paid=consultation_paid,
            diagnosis_id=diagnosis.diagnosis_id if diagnosis else None,
            diagnosis_date=diagnosis.date if diagnosis else None,
            chief_complaint=diagnosis.chief_complaint if diagnosis else None,
            vital_bp=diagnosis.vital_bp if diagnosis else None,
            vital_hr=diagnosis.vital_hr if diagnosis else None,
            vital_temp=diagnosis.vital_temp if diagnosis else None,
            vital_spo2=diagnosis.vital_spo2 if diagnosis else None,
            diagnosis_source=diagnosis_source,
            pharmacy_items=pharmacy_items,
            lab_items=lab_items,
            procedure_items=procedure_items,
            existing_bills={
                "lab": _bill_status(existing_lab),
                "pharmacy": _bill_status(existing_pharmacy),
                "procedure": _bill_status(existing_proc),
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading diagnosis for billing: {str(e)}")


@router.post("/create-bills")
async def create_bills(
    request: CreateBillRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Create bills for lab tests, pharmacy, and procedures.

    Workflow:
      1. GET /load-diagnosis  →  pre-populated items from doctor's diagnosis
      2. Billing staff edits quantities / removes items / sets discounts
      3. POST /create-bills   →  bills saved to DB
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, request.facility_id)

        appointment = get_appointment_by_token(
            db, effective_facility_id, request.token_number, request.token_date
        )
        if not appointment:
            raise HTTPException(
                status_code=404,
                detail=f"Appointment not found for token {request.token_number} on {request.token_date}",
            )

        if request.appointment_id and request.appointment_id != appointment.appointment_id:
            raise HTTPException(status_code=400, detail="Appointment ID mismatch with token")

        patient_id = appointment.patient_id

        # Delete existing bills via ORM so cascade removes child items correctly
        _delete_existing_bills(db, effective_facility_id, request.token_number, request.token_date)

        # ── Lab Bill ──────────────────────────────────────────────────────────
        if request.lab_items:
            lab_subtotal = 0.0
            lab_after_item_discounts = 0.0
            lab_item_data = []

            for item in request.lab_items:
                test = db.query(model.LabMaster).filter(
                    model.LabMaster.test_id == item.test_id,
                    model.LabMaster.facility_id == effective_facility_id,
                    model.LabMaster.is_deleted == False,
                    model.LabMaster.is_active == True,
                ).first()

                if not test:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Lab test ID {item.test_id} not found or inactive",
                    )

                price = item.price if item.price else (float(test.price) if test.price else None)
                if not price:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No price set for test: {test.test_name}",
                    )

                after_item_disc = calculate_final_price(price, item.discount_percent)
                lab_subtotal += price
                lab_after_item_discounts += after_item_disc
                lab_item_data.append({
                    "test_id": item.test_id,
                    "test_name": test.test_name,
                    "remarks": item.remarks,
                    "price": price,
                    "discount_percent": item.discount_percent,
                    "after_item_disc": after_item_disc,
                })

            lab_total_final = calculate_final_price(lab_after_item_discounts, request.lab_discount_percent)
            bill_mult = (lab_total_final / lab_after_item_discounts) if lab_after_item_discounts > 0 else 1.0

            lab_bill = model.LabBill(
                facility_id=effective_facility_id,
                token_number=request.token_number,
                token_date=request.token_date,
                patient_id=patient_id,
                bill_date=date.today(),
                subtotal=lab_subtotal,
                discount_percent=request.lab_discount_percent,
                total_amount=lab_total_final,
                paid_amount=0.0,
                payment_status="Pending",
                created_by=current_user.user_id,
            )
            db.add(lab_bill)
            db.flush()

            for d in lab_item_data:
                db.add(model.LabBillItem(
                    lab_bill_id=lab_bill.lab_bill_id,
                    test_id=d["test_id"],
                    test_name=d["test_name"],
                    remarks=d["remarks"],
                    price=d["price"],
                    discount_percent=d["discount_percent"],
                    final_price=round(d["after_item_disc"] * bill_mult, 2),
                ))

        # ── Pharmacy Bill ─────────────────────────────────────────────────────
        if request.pharmacy_items:
            ph_subtotal = 0.0
            ph_after_item_discounts = 0.0
            ph_item_data = []

            for item in request.pharmacy_items:
                medicine = db.query(model.DrugMaster).filter(
                    model.DrugMaster.medicine_id == item.medicine_id,
                    model.DrugMaster.facility_id == effective_facility_id,
                    model.DrugMaster.is_deleted == False,
                    model.DrugMaster.is_active == True,
                ).first()

                if not medicine:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Medicine ID {item.medicine_id} not found or inactive",
                    )

                unit_price = item.unit_price if item.unit_price else (float(medicine.price) if medicine.price else None)
                if not unit_price:
                    raise HTTPException(
                        status_code=400,
                        detail=f"No price set for medicine: {medicine.medicine_name}",
                    )

                total_price = item.quantity * unit_price
                after_item_disc = calculate_final_price(total_price, item.discount_percent)
                ph_subtotal += total_price
                ph_after_item_discounts += after_item_disc
                ph_item_data.append({
                    "medicine_id": item.medicine_id,
                    "medicine_name": medicine.medicine_name,
                    "generic_name": medicine.generic_name,
                    "strength": medicine.strength,
                    "quantity": item.quantity,
                    "unit_price": unit_price,
                    "total_price": total_price,
                    "discount_percent": item.discount_percent,
                    "after_item_disc": after_item_disc,
                    "dosage_info": item.dosage_info,
                    "food_timing": item.food_timing,
                    "duration_days": item.duration_days,
                })

            ph_total_final = calculate_final_price(ph_after_item_discounts, request.pharmacy_discount_percent)
            bill_mult = (ph_total_final / ph_after_item_discounts) if ph_after_item_discounts > 0 else 1.0

            pharmacy_bill = model.PharmacyBill(
                facility_id=effective_facility_id,
                token_number=request.token_number,
                token_date=request.token_date,
                patient_id=patient_id,
                bill_date=date.today(),
                subtotal=ph_subtotal,
                discount_percent=request.pharmacy_discount_percent,
                total_amount=ph_total_final,
                paid_amount=0.0,
                payment_status="Pending",
                created_by=current_user.user_id,
            )
            db.add(pharmacy_bill)
            db.flush()

            for d in ph_item_data:
                db.add(model.PharmacyBillItem(
                    pharmacy_bill_id=pharmacy_bill.pharmacy_bill_id,
                    medicine_id=d["medicine_id"],
                    medicine_name=d["medicine_name"],
                    generic_name=d["generic_name"],
                    strength=d["strength"],
                    quantity=d["quantity"],
                    unit_price=d["unit_price"],
                    total_price=d["total_price"],
                    discount_percent=d["discount_percent"],
                    final_price=round(d["after_item_disc"] * bill_mult, 2),
                    dosage_info=d["dosage_info"],
                    food_timing=d["food_timing"],
                    duration_days=d["duration_days"],
                ))

        # ── Procedure Bill ────────────────────────────────────────────────────
        if request.procedure_items:
            pr_subtotal = 0.0
            pr_after_item_discounts = 0.0
            pr_item_data = []

            for item in request.procedure_items:
                if item.procedure_id:
                    procedure = db.query(model.ProcedureMaster).filter(
                        model.ProcedureMaster.procedure_id == item.procedure_id,
                        model.ProcedureMaster.facility_id == effective_facility_id,
                        model.ProcedureMaster.is_deleted == False,
                        model.ProcedureMaster.is_active == True,
                    ).first()
                    if not procedure:
                        raise HTTPException(
                            status_code=404,
                            detail=f"Procedure ID {item.procedure_id} not found or inactive",
                        )
                    procedure_text = procedure.procedure_name
                    price = item.price if item.price else (float(procedure.price) if procedure.price else None)
                    if not price:
                        raise HTTPException(
                            status_code=400,
                            detail=f"No price set for procedure: {procedure.procedure_name}",
                        )
                else:
                    procedure_text = item.free_text_procedure
                    price = item.price
                    if not price:
                        raise HTTPException(
                            status_code=400,
                            detail=f"Price is required for free text procedure: {procedure_text}",
                        )

                after_item_disc = calculate_final_price(price, item.discount_percent)
                pr_subtotal += price
                pr_after_item_discounts += after_item_disc
                pr_item_data.append({
                    "procedure_text": procedure_text,
                    "price": price,
                    "discount_percent": item.discount_percent,
                    "after_item_disc": after_item_disc,
                })

            pr_total_final = calculate_final_price(pr_after_item_discounts, request.procedure_discount_percent)
            bill_mult = (pr_total_final / pr_after_item_discounts) if pr_after_item_discounts > 0 else 1.0

            procedure_bill = model.ProcedureBill(
                facility_id=effective_facility_id,
                token_number=request.token_number,
                token_date=request.token_date,
                patient_id=patient_id,
                bill_date=date.today(),
                subtotal=pr_subtotal,
                discount_percent=request.procedure_discount_percent,
                total_amount=pr_total_final,
                paid_amount=0.0,
                payment_status="Pending",
                created_by=current_user.user_id,
            )
            db.add(procedure_bill)
            db.flush()

            for d in pr_item_data:
                db.add(model.ProcedureBillItem(
                    procedure_bill_id=procedure_bill.procedure_bill_id,
                    procedure_text=d["procedure_text"],
                    price=d["price"],
                    discount_percent=d["discount_percent"],
                    final_price=round(d["after_item_disc"] * bill_mult, 2),
                ))

        db.commit()

        return {
            "status_code": 201,
            "message": "Bills created successfully",
            "data": {
                "token_number": request.token_number,
                "token_date": str(request.token_date),
                "lab_items_count": len(request.lab_items),
                "pharmacy_items_count": len(request.pharmacy_items),
                "procedure_items_count": len(request.procedure_items),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error creating bills: {str(e)}")


@router.get("/payment-summary", response_model=PaymentSummaryResponse)
async def get_payment_summary(
    token_number: str = Query(...),
    token_date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get complete payment summary for a token."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        appointment = get_appointment_by_token(db, effective_facility_id, token_number, token_date)

        if not appointment:
            raise HTTPException(
                status_code=404,
                detail=f"Appointment not found for token {token_number} on {token_date}",
            )

        patient = db.query(model.Patients).filter(model.Patients.id == appointment.patient_id).first()
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"

        consultation_fee, consultation_paid = get_consultation_fee(
            db, effective_facility_id, token_number, token_date
        )

        def _amounts(bill) -> Tuple[float, float]:
            if not bill:
                return 0.0, 0.0
            return float(bill.total_amount), float(bill.paid_amount)

        proc_bill = db.query(model.ProcedureBill).filter(model.ProcedureBill.token_number == token_number, model.ProcedureBill.token_date == token_date, model.ProcedureBill.facility_id == effective_facility_id).first()
        lab_bill  = db.query(model.LabBill).filter(model.LabBill.token_number == token_number, model.LabBill.token_date == token_date, model.LabBill.facility_id == effective_facility_id).first()
        ph_bill   = db.query(model.PharmacyBill).filter(model.PharmacyBill.token_number == token_number, model.PharmacyBill.token_date == token_date, model.PharmacyBill.facility_id == effective_facility_id).first()

        procedure_total, procedure_paid = _amounts(proc_bill)
        lab_total, lab_paid             = _amounts(lab_bill)
        pharmacy_total, pharmacy_paid   = _amounts(ph_bill)

        total_amount = consultation_fee + procedure_total + lab_total + pharmacy_total
        total_paid   = consultation_paid + procedure_paid + lab_paid + pharmacy_paid

        return PaymentSummaryResponse(
            token_number=token_number,
            token_date=token_date,
            patient_id=appointment.patient_id,
            patient_name=patient_name,
            appointment_id=appointment.appointment_id,
            consultation_fee=consultation_fee,
            consultation_paid=consultation_paid,
            consultation_pending=consultation_fee - consultation_paid,
            procedure_total=procedure_total,
            procedure_paid=procedure_paid,
            procedure_pending=procedure_total - procedure_paid,
            lab_total=lab_total,
            lab_paid=lab_paid,
            lab_pending=lab_total - lab_paid,
            pharmacy_total=pharmacy_total,
            pharmacy_paid=pharmacy_paid,
            pharmacy_pending=pharmacy_total - pharmacy_paid,
            total_amount=total_amount,
            total_paid=total_paid,
            total_pending=total_amount - total_paid,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting payment summary: {str(e)}")


@router.post("/record-payment")
async def record_payment(
    payment: PaymentRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Record a payment for consultation, procedure, lab, or pharmacy.
    Validates that payment does not exceed the pending amount.
    """
    try:
        effective_facility_id = get_effective_facility_id(current_user, payment.facility_id)
        appointment = get_appointment_by_token(
            db, effective_facility_id, payment.token_number, payment.token_date
        )

        if not appointment:
            raise HTTPException(
                status_code=404,
                detail=f"Appointment not found for token {payment.token_number} on {payment.token_date}",
            )

        payment_type = payment.payment_type  # already lowercased by validator

        if payment_type == "consultation":
            # Consultation: mark appointment as paid (full fee, no partial)
            if bool(appointment.payment_status):
                raise HTTPException(status_code=400, detail="Consultation fee is already paid")
            appointment.payment_status = True
            appointment.payment_method = payment.payment_method
            appointment.payment_comments = payment.payment_comments

            patient = db.query(model.Patients).filter(
                model.Patients.id == appointment.patient_id
            ).first()
            if patient:
                patient.is_paid = True

        else:
            # Lab / pharmacy / procedure — fetch the corresponding bill
            bill_map = {
                "lab":       (model.LabBill,       "lab_bill_id"),
                "pharmacy":  (model.PharmacyBill,  "pharmacy_bill_id"),
                "procedure": (model.ProcedureBill, "procedure_bill_id"),
            }
            BillModel, _ = bill_map[payment_type]

            bill = db.query(BillModel).filter(
                BillModel.token_number == payment.token_number,
                BillModel.token_date   == payment.token_date,
                BillModel.facility_id  == effective_facility_id,
            ).first()

            if not bill:
                raise HTTPException(
                    status_code=404,
                    detail=f"{payment_type.capitalize()} bill not found",
                )

            pending = round(float(bill.total_amount) - float(bill.paid_amount or 0), 2)
            if payment.amount_paid > pending + 0.01:  # 0.01 tolerance for float rounding
                raise HTTPException(
                    status_code=400,
                    detail=f"Amount paid ({payment.amount_paid}) exceeds pending amount ({pending})",
                )

            bill.paid_amount = round(float(bill.paid_amount or 0) + payment.amount_paid, 2)
            bill.payment_status = "Paid" if bill.paid_amount >= float(bill.total_amount) else "Partial"
            bill.payment_method = payment.payment_method
            bill.payment_date   = datetime.now()

        db.commit()

        return {
            "status_code": 200,
            "message": f"Payment recorded successfully for {payment.payment_type}",
            "data": {
                "token_number":   payment.token_number,
                "token_date":     str(payment.token_date),
                "payment_type":   payment.payment_type,
                "amount_paid":    payment.amount_paid,
                "payment_method": payment.payment_method,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error recording payment: {str(e)}")


@router.get("/lab-print", response_model=LabPrintResponse)
async def get_lab_print(
    token_number: str = Query(...),
    token_date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get lab bill for printing."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        lab_bill = (
            db.query(model.LabBill)
            .options(joinedload(model.LabBill.items))
            .filter(
                model.LabBill.token_number == token_number,
                model.LabBill.token_date   == token_date,
                model.LabBill.facility_id  == effective_facility_id,
            )
            .first()
        )
        if not lab_bill:
            raise HTTPException(status_code=404, detail="Lab bill not found")

        patient = db.query(model.Patients).filter(model.Patients.id == lab_bill.patient_id).first()
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"

        items = [
            LabBillItem(
                test_id=i.test_id,
                test_name=i.test_name,
                remarks=i.remarks,
                price=float(i.price),
                discount_percent=float(i.discount_percent),
                final_price=round(float(i.price) * (1 - float(i.discount_percent) / 100), 2),
            )
            for i in lab_bill.items
        ]

        return LabPrintResponse(
            token_number=token_number,
            token_date=token_date,
            patient_name=patient_name,
            date=lab_bill.bill_date,
            items=items,
            subtotal=float(lab_bill.subtotal),
            discount_percent=float(lab_bill.discount_percent),
            total=float(lab_bill.total_amount),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting lab print: {str(e)}")


@router.get("/pharmacy-print", response_model=PharmacyPrintResponse)
async def get_pharmacy_print(
    token_number: str = Query(...),
    token_date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get pharmacy bill for printing."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        pharmacy_bill = (
            db.query(model.PharmacyBill)
            .options(joinedload(model.PharmacyBill.items))
            .filter(
                model.PharmacyBill.token_number == token_number,
                model.PharmacyBill.token_date   == token_date,
                model.PharmacyBill.facility_id  == effective_facility_id,
            )
            .first()
        )
        if not pharmacy_bill:
            raise HTTPException(status_code=404, detail="Pharmacy bill not found")

        patient = db.query(model.Patients).filter(model.Patients.id == pharmacy_bill.patient_id).first()
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"

        items = [
            PharmacyBillItem(
                medicine_id=i.medicine_id,
                medicine_name=i.medicine_name,
                generic_name=i.generic_name,
                strength=i.strength,
                quantity=i.quantity,
                unit_price=float(i.unit_price),
                total_price=float(i.total_price),
                discount_percent=float(i.discount_percent),
                final_price=round(float(i.total_price) * (1 - float(i.discount_percent) / 100), 2),
                dosage_info=i.dosage_info,
                food_timing=i.food_timing,
                duration_days=i.duration_days,
            )
            for i in pharmacy_bill.items
        ]

        return PharmacyPrintResponse(
            token_number=token_number,
            token_date=token_date,
            patient_name=patient_name,
            date=pharmacy_bill.bill_date,
            items=items,
            subtotal=float(pharmacy_bill.subtotal),
            discount_percent=float(pharmacy_bill.discount_percent),
            total=float(pharmacy_bill.total_amount),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting pharmacy print: {str(e)}")


@router.get("/procedure-print", response_model=ProcedurePrintResponse)
async def get_procedure_print(
    token_number: str = Query(...),
    token_date: date = Query(...),
    facility_id: Optional[int] = Query(None),
    current_user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get procedure bill for printing."""
    try:
        effective_facility_id = get_effective_facility_id(current_user, facility_id)
        procedure_bill = (
            db.query(model.ProcedureBill)
            .options(joinedload(model.ProcedureBill.items))
            .filter(
                model.ProcedureBill.token_number == token_number,
                model.ProcedureBill.token_date   == token_date,
                model.ProcedureBill.facility_id  == effective_facility_id,
            )
            .first()
        )
        if not procedure_bill:
            raise HTTPException(status_code=404, detail="Procedure bill not found")

        patient = db.query(model.Patients).filter(model.Patients.id == procedure_bill.patient_id).first()
        patient_name = f"{patient.firstname} {patient.lastname}".strip() if patient else "Unknown"

        items = [
            ProcedureBillItemPrint(
                procedure_text=i.procedure_text,
                price=float(i.price),
                discount_percent=float(i.discount_percent),
                final_price=round(float(i.price) * (1 - float(i.discount_percent) / 100), 2),
            )
            for i in procedure_bill.items
        ]

        return ProcedurePrintResponse(
            token_number=token_number,
            token_date=token_date,
            patient_name=patient_name,
            date=procedure_bill.bill_date,
            items=items,
            subtotal=float(procedure_bill.subtotal),
            discount_percent=float(procedure_bill.discount_percent),
            total=float(procedure_bill.total_amount),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting procedure print: {str(e)}")