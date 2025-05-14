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
            if (data && data.temperature) {
                const temp = parseFloat(data.temperature).toFixed(1);
                element.textContent = `${temp}°C`;
                
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
                    <td>${event.temperature.toFixed(1)}°C</td>
                </tr>`;
            });
            eventsTable.innerHTML = newRows;
        }
    } catch (error) {
        console.error('Error fetching recent events:', error);
    }
}

// Update every 5 seconds
setInterval(updateTemperatures, 5000);
updateTemperatures(); // Initial update

// Update events every 10 seconds
setInterval(fetchRecentEvents, 10000);
fetchRecentEvents(); // Initial events fetch
