import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from backend.models import Booking, BookingStatus, SystemConfig
from backend.sheets_service import SheetsService
from backend.validation_engine import get_all_slots, parse_time

logger = logging.getLogger("panel_grid_generator")

def generate_grid_for_date(
    bookings: List[Booking],
    config: SystemConfig,
    date_str: str
) -> Tuple[List[str], List[List[str]]]:
    """
    Generates a visual timetable grid for a specific date.
    
    Returns:
        A tuple of (headers, rows)
        headers: ['Time', 'Panel-1', 'Panel-2', 'Panel-3', ...]
        rows: [['09:00', 'Jancy', '', ''], ['09:30', '####', '', ''], ...]
    """
    # 1. Gather all panel names from config
    panels = list(config.panel_enabled_flags.keys())
    panels.sort() # Keep sequential: Panel-1, Panel-2, Panel-3
    
    headers = ["Time"] + panels

    # 2. Generate time slots
    start_dt = parse_time(config.working_hours_start)
    end_dt = parse_time(config.working_hours_end)
    
    time_slots: List[str] = []
    curr = start_dt
    while curr < end_dt:
        time_slots.append(curr.strftime("%H:%M"))
        curr += timedelta(minutes=config.slot_duration)

    # 3. Filter bookings for this date and check occupied ranges
    # Only active bookings on the grid: BOOKED, COMPLETED, NO_SHOW
    active_statuses = (BookingStatus.BOOKED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW)
    date_bookings = [
        b for b in bookings 
        if b.interview_date == date_str and b.status in active_statuses
    ]

    # Map: panel -> slot_time -> (student_name or "####")
    grid_map: Dict[str, Dict[str, str]] = {panel: {} for panel in panels}

    for b in date_bookings:
        if not b.allocated_panel or b.allocated_panel not in grid_map:
            continue
            
        b_slots = get_all_slots(b.start_time, b.end_time, config.slot_duration)
        if not b_slots:
            continue
            
        # First slot gets student name
        first_slot = b_slots[0]
        grid_map[b.allocated_panel][first_slot] = b.student_name
        
        # Continuation slots get "####"
        for cont_slot in b_slots[1:]:
            grid_map[b.allocated_panel][cont_slot] = "####"

    # 4. Construct final rows
    rows: List[List[str]] = []
    for slot in time_slots:
        row = [slot]
        for panel in panels:
            cell_value = grid_map[panel].get(slot, "")
            row.append(cell_value)
        rows.append(row)

    return headers, rows


def generate_and_update_grid(
    bookings: List[Booking],
    config: SystemConfig,
    sheets_service: SheetsService,
    date_str: Optional[str] = None
) -> bool:
    """
    Determines the most relevant date, generates the grid, and updates the PANEL_GRID worksheet.
    If no date_str is provided, uses the date of the most recent active booking.
    """
    if not date_str:
        # Find the date of the most recent booking, or fall back to today's date
        active_bookings = [
            b for b in bookings 
            if b.status in (BookingStatus.BOOKED, BookingStatus.COMPLETED, BookingStatus.NO_SHOW)
        ]
        if active_bookings:
            # Sort by CreatedAt descending to find the latest
            active_bookings.sort(key=lambda x: x.created_at, reverse=True)
            date_str = active_bookings[0].interview_date
        else:
            # Current standard date in YYYY-MM-DD
            date_str = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"Regenerating PANEL_GRID sheet for date: {date_str}")
    headers, rows = generate_grid_for_date(bookings, config, date_str)
    
    # Prepend a row indicating the date of this grid for Google Sheets users
    visual_rows = [[f"DATE: {date_str}"] + [""] * (len(headers) - 1)]
    visual_rows.append(headers)
    visual_rows.extend(rows)
    
    # We write headers + rows to sheets
    # Note: to match the exact headers structure of PANEL_GRID, let's keep it clean
    # The first row can just be the standard headers, but let's make it the clean Grid headers.
    # The user example: Time | Panel-1 | Panel-2 | Panel-3
    return sheets_service.update_panel_grid_sheet(headers, rows)
