// Update room temperatures periodically
function updateTemperatures() {
    document.querySelectorAll('[id^="temp-"]').forEach(element => {
        // Mock temperature data for demo
        const temp = (20 + Math.random() * 8).toFixed(1);
        element.textContent = `${temp}°C`;
        
        // Update status based on temperature
        const roomNumber = element.id.split('-')[1];
        const statusElement = document.getElementById(`status-${roomNumber}`);
        if (parseFloat(temp) > 26) {
            statusElement.innerHTML = '<span class="badge bg-danger">High Temp</span>';
        } else if (parseFloat(temp) < 22) {
            statusElement.innerHTML = '<span class="badge bg-info">Low Temp</span>';
        } else {
            statusElement.innerHTML = '<span class="badge bg-success">Normal</span>';
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
