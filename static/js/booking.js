/* ==========================================
   STUDENT BOOKING PAGE CONTROLLER
   ========================================== */

document.addEventListener("DOMContentLoaded", () => {
    const bookingForm = document.getElementById("bookingForm");
    const today = new Date().toISOString().split('T')[0];
    
    // Set min date of booking to today
    const dateInput = document.getElementById("interview_date");
    if (dateInput) {
        dateInput.min = today;
        // Default date value to today
        dateInput.value = today;
    }

    if (bookingForm) {
        bookingForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            clearAlert("alertContainer");
            
            // Gather inputs
            const name = document.getElementById("student_name").value.trim();
            const company = document.getElementById("company").value.trim();
            const date = document.getElementById("interview_date").value;
            const startTime = document.getElementById("start_time").value;
            const endTime = document.getElementById("end_time").value;
            const notes = document.getElementById("notes").value.trim();
            
            // 1. Basic validation
            if (!name || !company || !date || !startTime || !endTime) {
                showAlert("alertContainer", "All form fields except notes are required.", "error");
                return;
            }
            
            // Time alignment checks
            const startMin = parseInt(startTime.split(":")[1]);
            const endMin = parseInt(endTime.split(":")[1]);
            if (startMin !== 0 && startMin !== 30) {
                showAlert("alertContainer", "Booking start time must align to a 30-minute interval (e.g. 11:00 or 11:30).", "error");
                return;
            }
            if (endMin !== 0 && endMin !== 30) {
                showAlert("alertContainer", "Booking end time must align to a 30-minute interval (e.g. 11:00 or 11:30).", "error");
                return;
            }
            
            const startHour = parseInt(startTime.split(":")[0]);
            const endHour = parseInt(endTime.split(":")[0]);
            const dur = (endHour * 60 + endMin) - (startHour * 60 + startMin);
            if (dur <= 0) {
                showAlert("alertContainer", "Interview end time must be chronologically after the start time.", "error");
                return;
            }
            
            // Construct payload
            const payload = {
                student_name: name,
                company: company,
                interview_date: date,
                start_time: startTime,
                end_time: endTime,
                notes: notes
            };
            
            // Submit payload
            try {
                // Disable button to prevent double-click / browser refresh duplicates
                const submitBtn = bookingForm.querySelector("button[type='submit']");
                submitBtn.disabled = true;
                submitBtn.innerText = "Allocating Panel, Please Wait...";
                
                const response = await fetch(`${API_BASE}/bookings`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify(payload)
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    throw new Error(data.detail || "Failed to book interview panel.");
                }
                
                // Success feedback
                if (data.Status === "BOOKED") {
                    showAlert(
                        "alertContainer", 
                        `Awesome! Booking is <strong>CONFIRMED</strong>. Allocated to <strong>${data.AllocatedPanel}</strong> from ${data.StartTime} to ${data.EndTime} on ${data.InterviewDate}. (ID: ${data.BookingID})`, 
                        "success"
                    );
                    bookingForm.reset();
                    if (dateInput) dateInput.value = today;
                } else if (data.Status === "WAITLISTED") {
                    showAlert(
                        "alertContainer", 
                        `Panels are currently occupied. You have been added to the <strong>WAITLIST</strong> for ${data.StartTime} - ${data.EndTime} on ${data.InterviewDate}. You will be promoted if a panel frees up! (ID: ${data.BookingID})`, 
                        "success"
                    );
                    bookingForm.reset();
                    if (dateInput) dateInput.value = today;
                }
                
            } catch (err) {
                showAlert("alertContainer", err.message, "error");
            } finally {
                // Re-enable button
                const submitBtn = bookingForm.querySelector("button[type='submit']");
                submitBtn.disabled = false;
                submitBtn.innerText = "Submit Booking Request";
            }
        });
    }
});
