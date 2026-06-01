from typing import List, Optional
from backend.models import Booking, BookingStatus, SystemConfig
from backend.validation_engine import get_all_slots, parse_time

def get_occupied_slots_by_panel(
    interview_date: str,
    existing_bookings: List[Booking]
) -> dict[str, List[str]]:
    """
    Returns a mapping of panel name to a list of occupied 30-minute start times.
    Only considers active bookings (BOOKED, RESCHEDULED, COMPLETED) on the given date.
    """
    occupied = {}
    for b in existing_bookings:
        if b.interview_date == interview_date and b.status in (
            BookingStatus.BOOKED,
            BookingStatus.COMPLETED
        ):
            if b.allocated_panel:
                if b.allocated_panel not in occupied:
                    occupied[b.allocated_panel] = []
                # Get all 30-min slot starts for this booking
                slots = get_all_slots(b.start_time, b.end_time)
                occupied[b.allocated_panel].extend(slots)
    return occupied


def allocate_panel(
    interview_date: str,
    start_time: str,
    end_time: str,
    config: SystemConfig,
    existing_bookings: List[Booking]
) -> Optional[str]:
    """
    Finds the first available enabled panel that is completely free for the booking duration.
    Checks in sequential order: Panel-1, Panel-2, Panel-3, etc.
    Returns the panel name if allocated, or None if no panels are available (Waitlist).
    """
    # 1. Get requested slots
    requested_slots = get_all_slots(start_time, end_time)
    
    # 2. Get enabled panels sorted in alphabetical/sequential order
    # Example: {"Panel-1": true, "Panel-2": true, "Panel-3": true}
    enabled_panels = [
        panel for panel, enabled in config.panel_enabled_flags.items() if enabled
    ]
    # Sort them to guarantee sequence order: Panel-1, Panel-2, Panel-3
    enabled_panels.sort()
    
    # 3. Get currently occupied slots for each panel on this date
    occupied_slots = get_occupied_slots_by_panel(interview_date, existing_bookings)
    
    # 4. Check each enabled panel sequentially
    for panel in enabled_panels:
        panel_occupied = occupied_slots.get(panel, [])
        
        # Check if there is any overlap
        overlap = False
        for slot in requested_slots:
            if slot in panel_occupied:
                overlap = True
                break
                
        if not overlap:
            # Found a free panel!
            return panel
            
    # All panels are full/occupied -> Needs to go to waitlist
    return None
