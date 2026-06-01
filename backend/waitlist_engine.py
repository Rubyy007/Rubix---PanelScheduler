import logging
from datetime import datetime
from typing import List, Tuple
from backend.models import Booking, BookingStatus, SystemConfig, AuditLog, AuditAction
from backend.allocation_engine import allocate_panel

logger = logging.getLogger("waitlist_engine")

def process_waitlist_promotions(
    bookings: List[Booking],
    config: SystemConfig,
    target_date: str
) -> Tuple[List[Booking], List[Tuple[Booking, str]]]:
    """
    Scans the waitlist for the target_date in FIFO order.
    Attempts to allocate a panel for each waitlisted booking.
    
    Returns:
        A tuple of (updated_bookings_list, list_of_promotions)
        where list_of_promotions is a list of tuples containing (promoted_booking, original_status).
    """
    if not config.auto_promote_waitlist:
        logger.info("Auto-promotion of waitlist is disabled in config.")
        return bookings, []

    # 1. Extract waitlisted bookings for the target date and sort by CreatedAt ascending (FIFO)
    waitlisted = [
        b for b in bookings 
        if b.interview_date == target_date and b.status == BookingStatus.WAITLISTED
    ]
    # Sort waitlist by CreatedAt (oldest first)
    waitlisted.sort(key=lambda x: x.created_at)

    promotions = []
    
    # We do a sequential check. Note that as we promote one booking, it becomes BOOKED,
    # and therefore occupies slots which prevents subsequent waitlist items from taking the same slot.
    # So we must dynamically update our "active bookings" state as we iterate.
    for wl_booking in waitlisted:
        # Check if we can allocate a panel for this waitlist booking now
        allocated_panel = allocate_panel(
            interview_date=wl_booking.interview_date,
            start_time=wl_booking.start_time,
            end_time=wl_booking.end_time,
            config=config,
            existing_bookings=bookings  # This includes the newly promoted bookings in the loop
        )
        
        if allocated_panel:
            # Promote the booking!
            original_status = wl_booking.status
            wl_booking.status = BookingStatus.BOOKED
            wl_booking.allocated_panel = allocated_panel
            wl_booking.modified_at = datetime.now().isoformat()
            wl_booking.notes = (wl_booking.notes or "") + f" [Auto-promoted from waitlist at {wl_booking.modified_at}]"
            
            logger.info(f"Promoted booking {wl_booking.booking_id} for student {wl_booking.student_name} to panel {allocated_panel}")
            promotions.append((wl_booking, original_status))
            
    return bookings, promotions
