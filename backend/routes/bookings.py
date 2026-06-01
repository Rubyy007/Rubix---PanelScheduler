import uuid
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from backend.models import Booking, BookingCreate, BookingReschedule, BookingStatus, AuditLog, AuditAction
from backend.sheets_service import SheetsService, SHEET_TRANSACTION_LOCK
from backend.config_manager import ConfigManager
from backend.validation_engine import validate_booking_rules, ValidationError, calculate_duration
from backend.allocation_engine import allocate_panel
from backend.waitlist_engine import process_waitlist_promotions
from backend.cancellation_engine import cancel_booking
from backend.reschedule_engine import reschedule_booking
from backend.audit_logger import create_audit_log_record
from backend.panel_grid_generator import generate_and_update_grid

router = APIRouter(prefix="/bookings", tags=["bookings"])
logger = logging.getLogger("routes.bookings")

# Dependency injection helpers
def get_sheets_service() -> SheetsService:
    service = SheetsService()
    if not service.spreadsheet:
        service.connect_spreadsheet()
    return service

def get_config_manager(sheets_service: SheetsService = Depends(get_sheets_service)) -> ConfigManager:
    return ConfigManager(sheets_service)


# --- ADDITIONAL REQUEST SCHEMAS ---

class UpdateBookingPayload(BaseModel):
    student_name: Optional[str] = Field(None, min_length=2)
    company: Optional[str] = Field(None, min_length=1)
    notes: Optional[str] = None
    performed_by: str = Field("Admin", min_length=2)


class ActionPayload(BaseModel):
    performed_by: str = Field("Admin", min_length=2)
    reason: Optional[str] = Field("", description="Reason for the action")


class ReschedulePayload(BaseModel):
    interview_date: str = Field(..., description="YYYY-MM-DD")
    start_time: str = Field(..., description="HH:MM")
    end_time: str = Field(..., description="HH:MM")
    notes: Optional[str] = ""
    performed_by: str = Field("Student", min_length=2)
    reason: str = Field(..., min_length=3, description="Reason for rescheduling")


# --- ROUTE HANDLERS ---

@router.post("", response_model=Booking, status_code=status.HTTP_201_CREATED)
async def create_new_booking(
    payload: BookingCreate,
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    Creates a new booking submission.
    Runs validations, checks panel availability sequentially, and assigns a slot or waitlists the student.
    Uses a global async mutex lock to prevent concurrent double-booking race conditions.
    """
    async with SHEET_TRANSACTION_LOCK:
        try:
            # 1. Fetch current bookings and configurations
            bookings = sheets_service.get_all_bookings()
            config = config_manager.get_config()
            
            # 2. Run validations
            validate_booking_rules(payload, config, bookings)
            
            # 3. Attempt to allocate a panel
            allocated_panel = allocate_panel(
                interview_date=payload.interview_date,
                start_time=payload.start_time,
                end_time=payload.end_time,
                config=config,
                existing_bookings=bookings
            )
            
            booking_status = BookingStatus.BOOKED if allocated_panel else BookingStatus.WAITLISTED
            booking_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
            duration = calculate_duration(payload.start_time, payload.end_time)
            
            # 4. Construct Booking model
            new_booking = Booking(
                BookingID=booking_id,
                CreatedAt=datetime.now().isoformat(),
                StudentName=payload.student_name,
                Company=payload.company,
                InterviewDate=payload.interview_date,
                StartTime=payload.start_time,
                EndTime=payload.end_time,
                Duration=duration,
                AllocatedPanel=allocated_panel,
                Status=booking_status,
                PreviousBookingID=None,
                ModifiedAt=None,
                Notes=payload.notes or ""
            )
            
            bookings.append(new_booking)
            
            # 5. Save all bookings to sheets database
            success = sheets_service.save_bookings_batch(bookings)
            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to commit booking to Google Sheets database."
                )
                
            # 6. Log audit event
            audit_rec = create_audit_log_record(
                booking_id=booking_id,
                action=AuditAction.CREATE_BOOKING,
                old_value="None",
                new_value=f"Status: {booking_status}, Panel: {allocated_panel or 'None (WAITLISTED)'}",
                performed_by=payload.student_name,
                reason="Initial student mock booking submission."
            )
            sheets_service.append_audit_log(audit_rec)
            
            # 7. Update PANEL_GRID sheet
            generate_and_update_grid(bookings, config, sheets_service, payload.interview_date)
            
            return new_booking

        except ValidationError as val_err:
            logger.warning(f"Booking validation failed: {val_err.message}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=val_err.message)
        except Exception as err:
            logger.error(f"Unexpected error in create_booking: {err}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(err))


@router.get("", response_model=List[Booking])
async def get_bookings(
    date: Optional[str] = Query(None, description="Filter bookings by YYYY-MM-DD"),
    status_filter: Optional[BookingStatus] = Query(None, description="Filter by Booking Status"),
    sheets_service: SheetsService = Depends(get_sheets_service)
):
    """Fetch all bookings with optional date and status filters."""
    bookings = sheets_service.get_all_bookings()
    if date:
        bookings = [b for b in bookings if b.interview_date == date]
    if status_filter:
        bookings = [b for b in bookings if b.status == status_filter]
    return bookings


@router.get("/{booking_id}", response_model=Booking)
async def get_booking_by_id(
    booking_id: str,
    sheets_service: SheetsService = Depends(get_sheets_service)
):
    """Get detailed information of a single booking by ID."""
    bookings = sheets_service.get_all_bookings()
    for b in bookings:
        if b.booking_id == booking_id:
            return b
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Booking with ID {booking_id} not found."
    )


@router.put("/{booking_id}", response_model=Booking)
async def update_booking_metadata(
    booking_id: str,
    payload: UpdateBookingPayload,
    sheets_service: SheetsService = Depends(get_sheets_service)
):
    """
    Updates a booking's non-scheduling metadata (StudentName, Company, Notes).
    Allows edits without altering date/time allocation.
    """
    async with SHEET_TRANSACTION_LOCK:
        bookings = sheets_service.get_all_bookings()
        
        target_booking = None
        for b in bookings:
            if b.booking_id == booking_id:
                target_booking = b
                break
                
        if not target_booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Booking with ID {booking_id} not found."
            )
            
        old_val_str = f"Name: {target_booking.student_name}, Company: {target_booking.company}, Notes: {target_booking.notes}"
        
        # Modify fields
        if payload.student_name is not None:
            target_booking.student_name = payload.student_name
        if payload.company is not None:
            target_booking.company = payload.company
        if payload.notes is not None:
            target_booking.notes = payload.notes
            
        target_booking.modified_at = datetime.now().isoformat()
        
        new_val_str = f"Name: {target_booking.student_name}, Company: {target_booking.company}, Notes: {target_booking.notes}"
        
        # Save to Google Sheets
        sheets_service.save_bookings_batch(bookings)
        
        # Audit Log
        audit_log = create_audit_log_record(
            booking_id=booking_id,
            action=AuditAction.RESCHEDULE_BOOKING,  # Re-used for update
            old_value=old_val_str,
            new_value=new_val_str,
            performed_by=payload.performed_by,
            reason="Admin updated booking metadata details."
        )
        sheets_service.append_audit_log(audit_log)
        
        return target_booking


@router.delete("/{booking_id}", response_model=Booking)
async def delete_or_cancel_booking(
    booking_id: str,
    performed_by: str = Query("Student", description="Who performed the cancellation"),
    reason: str = Query("", description="Reason for cancellation"),
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    Cancels a booking by changing its status to CANCELLED (never deletes the row).
    Frees up panel slots and automatically promotes the oldest matching waitlisted booking if enabled.
    """
    async with SHEET_TRANSACTION_LOCK:
        try:
            cancelled, _ = cancel_booking(
                booking_id=booking_id,
                performed_by=performed_by,
                reason=reason,
                sheets_service=sheets_service,
                config_manager=config_manager
            )
            return cancelled
        except ValueError as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))
        except Exception as e:
            logger.error(f"Error cancelling booking {booking_id}: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{booking_id}/reschedule", response_model=Booking)
async def reschedule_existing_booking(
    booking_id: str,
    payload: ReschedulePayload,
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """
    Reschedules an existing active booking.
    Old booking status -> RESCHEDULED.
    New booking created with status BOOKED (or WAITLISTED if no panels free).
    Links both via PreviousBookingID to preserve chronological tracking.
    """
    async with SHEET_TRANSACTION_LOCK:
        try:
            old, new, promoted = reschedule_booking(
                booking_id=booking_id,
                new_date=payload.interview_date,
                new_start=payload.start_time,
                new_end=payload.end_time,
                notes=payload.notes,
                performed_by=payload.performed_by,
                reason=payload.reason,
                sheets_service=sheets_service,
                config_manager=config_manager
            )
            return new
        except ValueError as val_err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(val_err))
        except ValidationError as business_err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=business_err.message)
        except Exception as e:
            logger.error(f"Error rescheduling booking {booking_id}: {e}", exc_info=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/{booking_id}/complete", response_model=Booking)
async def mark_booking_completed(
    booking_id: str,
    payload: ActionPayload,
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """Marks a BOOKED booking as COMPLETED and logs the action."""
    async with SHEET_TRANSACTION_LOCK:
        bookings = sheets_service.get_all_bookings()
        
        target_booking = None
        for b in bookings:
            if b.booking_id == booking_id:
                target_booking = b
                break
                
        if not target_booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Booking with ID {booking_id} not found."
            )
            
        if target_booking.status != BookingStatus.BOOKED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only BOOKED bookings can be marked as COMPLETED. Current status: {target_booking.status}"
            )
            
        old_status = target_booking.status
        target_booking.status = BookingStatus.COMPLETED
        target_booking.modified_at = datetime.now().isoformat()
        target_booking.notes = (target_booking.notes or "") + f" [Completed at {target_booking.modified_at} by {payload.performed_by}]"
        
        sheets_service.save_bookings_batch(bookings)
        
        audit_log = create_audit_log_record(
            booking_id=booking_id,
            action=AuditAction.COMPLETE_BOOKING,
            old_value=f"Status: {old_status}",
            new_value="Status: COMPLETED",
            performed_by=payload.performed_by,
            reason=payload.reason or "Interview successfully finished."
        )
        sheets_service.append_audit_log(audit_log)
        
        # Regenerate Panel Grid sheet
        generate_and_update_grid(bookings, config_manager.get_config(), sheets_service, target_booking.interview_date)
        
        return target_booking


@router.post("/{booking_id}/noshow", response_model=Booking)
async def mark_booking_noshow(
    booking_id: str,
    payload: ActionPayload,
    sheets_service: SheetsService = Depends(get_sheets_service),
    config_manager: ConfigManager = Depends(get_config_manager)
):
    """Marks a BOOKED booking as NO_SHOW (student failed to appear) and logs the action."""
    async with SHEET_TRANSACTION_LOCK:
        bookings = sheets_service.get_all_bookings()
        
        target_booking = None
        for b in bookings:
            if b.booking_id == booking_id:
                target_booking = b
                break
                
        if not target_booking:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Booking with ID {booking_id} not found."
            )
            
        if target_booking.status != BookingStatus.BOOKED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only BOOKED bookings can be marked as NO_SHOW. Current status: {target_booking.status}"
            )
            
        old_status = target_booking.status
        target_booking.status = BookingStatus.NO_SHOW
        target_booking.modified_at = datetime.now().isoformat()
        target_booking.notes = (target_booking.notes or "") + f" [No show marked at {target_booking.modified_at} by {payload.performed_by}]"
        
        sheets_service.save_bookings_batch(bookings)
        
        audit_log = create_audit_log_record(
            booking_id=booking_id,
            action=AuditAction.NOSHOW_BOOKING,
            old_value=f"Status: {old_status}",
            new_value="Status: NO_SHOW",
            performed_by=payload.performed_by,
            reason=payload.reason or "Student did not attend scheduled session."
        )
        sheets_service.append_audit_log(audit_log)
        
        # Regenerate Panel Grid sheet
        generate_and_update_grid(bookings, config_manager.get_config(), sheets_service, target_booking.interview_date)
        
        return target_booking
