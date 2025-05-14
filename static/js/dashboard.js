// Update room temperatures periodically
async function updateTemperatures() {
    document.querySelectorAll('[id^="temp-"]').forEach(async element => {
        const roomNumber = element.id.split('-')[1];
        
        try {
            // Fetch actual temperature from the API
            const response = await fetch(`/api/room_status/${roomNumber}`);
            if (!response.ok) {
                console.error(`Failed to fetch status for room ${roomNumber}: ${response.status}`);
                return;
            }
            
            const data = await response.json();
            
            // Update temperature display
            if (data && (data.temperature_f || data.temperature)) {
                const temp = data.temperature_f ? parseFloat(data.temperature_f).toFixed(1) : 
                    (parseFloat(data.temperature) * 9/5 + 32).toFixed(1);
                element.textContent = `${temp}°F`;
                
                // Update status based on temperature and other factors
                const statusElement = document.getElementById(`status-${roomNumber}`);
                
                if (data.non_compliant_since) {
                    // Room is in non-compliant state
                    statusElement.innerHTML = `<span class="badge bg-danger">${data.policy_violation_type || 'Non-Compliant'}</span>`;
                } else if (data.window_state === 'opened' && data.ac_state === 'on') {
                    // Window open with AC on
                    statusElement.innerHTML = '<span class="badge bg-warning">Window Open & AC On</span>';
                } else if (data.window_state === 'opened') {
                    // Window open
                    statusElement.innerHTML = '<span class="badge bg-info">Window Open</span>';
                } else if (data.ac_state === 'on') {
                    // AC on
                    statusElement.innerHTML = '<span class="badge bg-primary">AC On</span>';
                } else {
                    // AC off state
                    statusElement.innerHTML = '<span class="badge bg-secondary">AC Off</span>';
                }
            }
        } catch (error) {
            console.error(`Error fetching data for room ${roomNumber}:`, error);
        }
    });
}

// Function to fetch and update recent events
async function fetchRecentEvents() {
    const roomElement = document.querySelector('[data-room-number]');
    if (!roomElement) return; // Not on room dashboard page
    
    const roomNumber = roomElement.getAttribute('data-room-number');
    try {
        // Fetch latest events for this room
        const response = await fetch(`/api/recent_events/${roomNumber}`);
        if (!response.ok) {
            console.error('Failed to fetch recent events:', response.status);
            return;
        }
        
        const data = await response.json();
        const eventsTable = document.getElementById('eventsTable');
        
        if (eventsTable && data.events && data.events.length > 0) {
            let newRows = '';
            // Create table rows for each event
            data.events.forEach(event => {
                newRows += `
                <tr>
                    <td>${event.timestamp}</td>
                    <td>${event.window_state}</td>
                    <td>${event.ac_state}</td>
                    <td>${(event.temperature_f || (event.temperature * 9/5 + 32)).toFixed(1)}°F</td>
                </tr>`;
            });
            eventsTable.innerHTML = newRows;
        }
    } catch (error) {
        console.error('Error fetching recent events:', error);
    }
}

// Update more frequently
setInterval(updateTemperatures, 3000); // Every 3 seconds
updateTemperatures(); // Initial update

// Update events more frequently
setInterval(fetchRecentEvents, 5000); // Every 5 seconds
fetchRecentEvents(); // Initial events fetch

// Add realtime update for admin dashboard
function updateAllRoomStatus() {
    // Only run on admin dashboard
    if (document.getElementById('admin-dashboard')) {
        document.querySelectorAll('.room-card').forEach(async card => {
            const roomNumber = card.getAttribute('data-room-id');
            if (!roomNumber) return;
            
            try {
                const response = await fetch(`/api/room_status/${roomNumber}`);
                if (!response.ok) return;
                
                const data = await response.json();
                
                // Update room status
                const statusElement = card.querySelector('.room-status');
                if (statusElement) {
                    if (data.non_compliant_since) {
                        statusElement.innerHTML = `<span class="badge bg-danger">${data.policy_violation_type || 'Non-Compliant'}</span>`;
                    } else if (data.window_state === 'opened' && data.ac_state === 'on') {
                        statusElement.innerHTML = '<span class="badge bg-warning">Window Open & AC On</span>';
                    } else if (data.window_state === 'opened') {
                        statusElement.innerHTML = '<span class="badge bg-info">Window Open</span>';
                    } else if (data.ac_state === 'on') {
                        statusElement.innerHTML = '<span class="badge bg-primary">AC On</span>';
                    } else {
                        statusElement.innerHTML = '<span class="badge bg-secondary">AC Off</span>';
                    }
                }
                
                // Update temperature
                const tempElement = card.querySelector('.room-temperature');
                if (tempElement && (data.temperature_f || data.temperature)) {
                    const temp = data.temperature_f ? parseFloat(data.temperature_f).toFixed(1) : 
                        (parseFloat(data.temperature) * 9/5 + 32).toFixed(1);
                    tempElement.textContent = `${temp}°F`;
                }
            } catch (error) {
                console.error(`Error updating status for room ${roomNumber}:`, error);
            }
        });
    }
}

// Update admin dashboard every 3 seconds
setInterval(updateAllRoomStatus, 3000);
updateAllRoomStatus(); // Initial update
