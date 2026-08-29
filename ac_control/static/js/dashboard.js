async function updateTemperatures() {
    document.querySelectorAll('[id^="temp-"]').forEach(async (element) => {
        const roomNumber = element.id.split('-')[1];
        try {
            const response = await fetch(`/api/rooms/${roomNumber}/status`);
            if (!response.ok) return;
            const data = await response.json();
            if (data.temperature_f || data.temperature) {
                const temp = data.temperature_f
                    ? parseFloat(data.temperature_f).toFixed(1)
                    : (parseFloat(data.temperature) * 9 / 5 + 32).toFixed(1);
                element.textContent = `${temp}°F`;
            }
            const statusElement = document.getElementById(`status-${roomNumber}`);
            if (!statusElement) return;
            if (data.stale) {
                statusElement.innerHTML = '<span class="badge bg-danger">Stale</span>';
            } else if (data.non_compliant_since) {
                statusElement.innerHTML = `<span class="badge bg-danger">${data.policy_violation_type || 'Non-Compliant'}</span>`;
            } else if (data.window_state === 'opened' && data.ac_state === 'on') {
                statusElement.innerHTML = '<span class="badge bg-warning">Window Open &amp; AC On</span>';
            } else if (data.window_state === 'opened') {
                statusElement.innerHTML = '<span class="badge bg-info">Window Open</span>';
            } else if (data.ac_state === 'on') {
                statusElement.innerHTML = '<span class="badge bg-primary">AC On</span>';
            } else {
                statusElement.innerHTML = '<span class="badge bg-secondary">AC Off</span>';
            }
        } catch (error) {
            console.error(`Error fetching data for room ${roomNumber}:`, error);
        }
    });
}

async function fetchRecentEvents() {
    const roomElement = document.querySelector('[data-room-number]');
    if (!roomElement) return;
    const roomNumber = roomElement.getAttribute('data-room-number');
    try {
        const response = await fetch(`/api/rooms/${roomNumber}/events`);
        if (!response.ok) return;
        const data = await response.json();
        const eventsTable = document.getElementById('eventsTable');
        if (eventsTable && data.events && data.events.length > 0) {
            eventsTable.innerHTML = data.events.map((event) => {
                const temp = (event.temperature_f || (event.temperature * 9 / 5 + 32)).toFixed(1);
                return `<tr>
                    <td>${event.timestamp}</td>
                    <td>${event.window_state}</td>
                    <td>${event.ac_state}</td>
                    <td>${temp}°F</td>
                </tr>`;
            }).join('');
        }
    } catch (error) {
        console.error('Error fetching recent events:', error);
    }
}

setInterval(updateTemperatures, 3000);
updateTemperatures();
setInterval(fetchRecentEvents, 5000);
fetchRecentEvents();
