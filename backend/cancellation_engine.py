import logging
from datetime import datetime
from typing import List, Tuple
from backend.models import Booking, BookingStatus, SystemConfig, AuditLog, AuditAction
from backend.sheets_service import SheetsService
from backend.config_manager import ConfigManager
from backend.waitlist_engine import process_waitlist_promotions
from backend.audit_logger import create_audit_log_record
from backend.panel_grid_generator import generate_and_update_grid

logger = logging.getLogger("cancellation_engine")

def cancel_booking(
    booking_id: str,
    performed_by: str,
    reason: str,
    sheets_service: SheetsService,
    config_manager: ConfigManager
) -> Tuple[Booking, List[Booking]]:
    """
    Cancels an existing booking. Status changes to CANCELLED.
    If the cancelled booking was BOOKED, triggers waitlist promotions for that day.
    Saves updates atomically and updates the PANEL_GRID.
    
    Returns:
        A tuple of (cancelled_booking, list_of_promoted_bookings)
    """
    bookings = sheets_service.get_all_bookings()
    config = config_manager.get_config()
    
    # 1. Find the booking
    target_booking = None
    for b in bookings:
        if b.booking_id == booking_id:
            target_booking = b
            break
            
    if not target_booking:
        raise ValueError(f"Booking with ID {booking_id} not found.")
        
    if target_booking.status == BookingStatus.CANCELLED:
        raise ValueError("Booking is already CANCELLED.")

    # 2. Update booking status
    old_status = target_booking.status
    old_panel = target_booking.allocated_panel
    target_booking.status = BookingStatus.CANCELLED
    target_booking.allocated_panel = None
    target_booking.modified_at = datetime.now().isoformat()
    if reason:
        target_booking.notes = (target_booking.notes or "") + f" [Cancelled: {reason} at {target_booking.modified_at} by {performed_by}]"
    else:
        target_booking.notes = (target_booking.notes or "") + f" [Cancelled at {target_booking.modified_at} by {performed_by}]"
        
    # Keep track of promoted bookings
    promoted_bookings = []
    
    # 3. Trigger waitlist promotion if the cancelled booking was BOOKED
    if old_status == BookingStatus.BOOKED:
        bookings, promotions = process_waitlist_promotions(
            bookings=bookings,
            config=config,
            target_date=target_booking.interview_date
        )
        promoted_bookings = [p[0] for p in promotions]

    # 4. Save bookings back to Google Sheets (Atomic batch overwrite)
    sheets_service.save_bookings_batch(bookings)
    
    # 5. Log the cancellation audit event
    old_val_str = f"Status: {old_status}, Panel: {old_panel}"
    new_val_str = "Status: CANCELLED, Panel: None"
    
    cancel_audit = create_audit_log_record(
        booking_id=booking_id,
        action=AuditAction.CANCEL_BOOKING,
        old_value=old_val_str,
        new_value=new_val_str,
        performed_by=performed_by,
        reason=reason or "Student cancelled / Admin cancel request"
    )
    sheets_service.append_audit_log(cancel_audit)
    
    # Log any promotions
    for p_booking, orig_status in (promotions if old_status == BookingStatus.BOOKED else []):
        promo_audit = create_audit_log_record(
            booking_id=p_booking.booking_id,
            action=AuditAction.AUTO_PROMOTE,
            old_value=f"Status: {orig_status}, Panel: None",
            new_value=f"Status: {p_booking.status}, Panel: {p_booking.allocated_panel}",
            performed_by="System",
            reason=f"Slot freed by cancellation of booking {booking_id}"
        )
        sheets_service.append_audit_log(promo_audit)

    # 6. Regenerate and update the PANEL_GRID sheet
    try:
        generate_and_update_grid(bookings, config, sheets_service)
    except Exception as ex:
        logger.error(f"Failed to update panel grid layout after cancellation: {ex}")

    return target_booking, promoted_bookings
