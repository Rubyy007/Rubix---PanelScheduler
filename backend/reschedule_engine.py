import logging
import uuid
from datetime import datetime
from typing import Tuple, List
from backend.models import Booking, BookingStatus, SystemConfig, AuditLog, AuditAction
from backend.sheets_service import SheetsService
from backend.config_manager import ConfigManager
from backend.allocation_engine import allocate_panel
from backend.validation_engine import calculate_duration, validate_booking_rules, ValidationError
from backend.waitlist_engine import process_waitlist_promotions
from backend.audit_logger import create_audit_log_record
from backend.panel_grid_generator import generate_and_update_grid

logger = logging.getLogger("reschedule_engine")

def reschedule_booking(
    booking_id: str,
    new_date: str,
    new_start: str,
    new_end: str,
    notes: str,
    performed_by: str,
    reason: str,
    sheets_service: SheetsService,
    config_manager: ConfigManager
) -> Tuple[Booking, Booking, List[Booking]]:
    """
    Reschedules a booking.
    1. Validates the new booking slot rules.
    2. Marks the old booking as RESCHEDULED and frees its panel slot.
    3. Triggers waitlist promotions on the OLD date (since slots are freed).
    4. Allocates a panel on the NEW date/time (creates a BOOKED or WAITLISTED booking).
    5. Links the new booking to the old via PreviousBookingID.
    6. Saves all changes atomically to Google Sheets and regenerates the PANEL_GRID.
    
    Returns:
        A tuple of (old_booking, new_booking, list_of_promoted_bookings_on_old_date)
    """
    bookings = sheets_service.get_all_bookings()
    config = config_manager.get_config()
    
    # 1. Find the old booking
    old_booking = None
    for b in bookings:
        if b.booking_id == booking_id:
            old_booking = b
            break
            
    if not old_booking:
        raise ValueError(f"Booking with ID {booking_id} not found.")
        
    if old_booking.status in (BookingStatus.CANCELLED, BookingStatus.RESCHEDULED):
        raise ValueError(f"Cannot reschedule booking with status {old_booking.status}.")

    # 2. Run validations for the new request
    # Create a temporary BookingCreate object for validation
    from backend.models import BookingCreate
    temp_create = BookingCreate(
        student_name=old_booking.student_name,
        company=old_booking.company,
        interview_date=new_date,
        start_time=new_start,
        end_time=new_end,
        notes=notes or old_booking.notes
    )
    
    # Run business rule validations
    # Exclude the current old booking from the duplicate check (since we are modifying/moving it)
    other_bookings = [b for b in bookings if b.booking_id != booking_id]
    validate_booking_rules(temp_create, config, other_bookings)

    # 3. Update old booking
    old_status = old_booking.status
    old_panel = old_booking.allocated_panel
    old_date = old_booking.interview_date
    
    old_booking.status = BookingStatus.RESCHEDULED
    old_booking.allocated_panel = None
    old_booking.modified_at = datetime.now().isoformat()
    old_booking.notes = (old_booking.notes or "") + f" [Rescheduled to new booking on {new_date} at {old_booking.modified_at} by {performed_by}]"

    # 4. Trigger waitlist promotion on the OLD date (if the old booking was actively BOOKED)
    promoted_bookings = []
    if old_status == BookingStatus.BOOKED:
        bookings, promotions = process_waitlist_promotions(
            bookings=bookings,
            config=config,
            target_date=old_date
        )
        promoted_bookings = [p[0] for p in promotions]

    # 5. Allocate panel for the NEW booking
    new_duration = calculate_duration(new_start, new_end)
    new_allocated_panel = allocate_panel(
        interview_date=new_date,
        start_time=new_start,
        end_time=new_end,
        config=config,
        existing_bookings=bookings  # This incorporates the waitlist updates and old_booking status release
    )
    
    new_status = BookingStatus.BOOKED if new_allocated_panel else BookingStatus.WAITLISTED
    new_id = f"BK-{uuid.uuid4().hex[:6].upper()}"
    
    new_booking = Booking(
        BookingID=new_id,
        CreatedAt=datetime.now().isoformat(),
        StudentName=old_booking.student_name,
        Company=old_booking.company,
        InterviewDate=new_date,
        StartTime=new_start,
        EndTime=new_end,
        Duration=new_duration,
        AllocatedPanel=new_allocated_panel,
        Status=new_status,
        PreviousBookingID=booking_id,
        ModifiedAt=None,
        Notes=notes or f"Rescheduled from {booking_id}. " + (old_booking.notes or "")
    )
    
    # Add new booking to the memory database list
    bookings.append(new_booking)
    
    # 6. Save everything back to Google Sheets atomically
    sheets_service.save_bookings_batch(bookings)
    
    # 7. Write Audit Logs
    # Audit log for the old booking transition
    audit_old = create_audit_log_record(
        booking_id=booking_id,
        action=AuditAction.RESCHEDULE_BOOKING,
        old_value=f"Status: {old_status}, Panel: {old_panel}",
        new_value=f"Status: RESCHEDULED, LinkedNewBooking: {new_id}",
        performed_by=performed_by,
        reason=reason or "Student/Admin requested reschedule"
    )
    sheets_service.append_audit_log(audit_old)
    
    # Audit log for the new booking creation
    audit_new = create_audit_log_record(
        booking_id=new_id,
        action=AuditAction.CREATE_BOOKING,
        old_value="None",
        new_value=f"Status: {new_status}, Panel: {new_allocated_panel or 'None (WAITLISTED)'}",
        performed_by=performed_by,
        reason=f"Created via rescheduling from booking {booking_id}"
    )
    sheets_service.append_audit_log(audit_new)

    # Audit log for promotions on old date
    for p_booking, orig_status in (promotions if old_status == BookingStatus.BOOKED else []):
        promo_audit = create_audit_log_record(
            booking_id=p_booking.booking_id,
            action=AuditAction.AUTO_PROMOTE,
            old_value=f"Status: {orig_status}, Panel: None",
            new_value=f"Status: {p_booking.status}, Panel: {p_booking.allocated_panel}",
            performed_by="System",
            reason=f"Slot freed by rescheduling booking {booking_id}"
        )
        sheets_service.append_audit_log(promo_audit)

    # 8. Regenerate and update the PANEL_GRID sheet
    try:
        generate_and_update_grid(bookings, config, sheets_service)
    except Exception as ex:
        logger.error(f"Failed to update panel grid layout after reschedule: {ex}")

    return old_booking, new_booking, promoted_bookings
