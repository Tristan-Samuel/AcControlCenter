// Initialize temperature chart
const ctx = document.getElementById('temperatureChart').getContext('2d');
const temperatureChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [{
            label: 'Temperature °F',
            data: [],
            borderColor: 'rgb(75, 192, 192)',
            tension: 0.1
        }]
    },
    options: {
        responsive: true,
        scales: {
            y: {
                beginAtZero: false,
                min: 65,  // Fahrenheit equivalent of ~18°C
                max: 85   // Fahrenheit equivalent of ~30°C
            }
        }
    }
});

let temperatures = [];
let timestamps = [];

// Update chart with real data
async function updateChart() {
    try {
        const roomNumber = document.querySelector('[data-room-number]').dataset.roomNumber;
        const response = await fetch(`/api/temperature/${roomNumber}`);
        const data = await response.json();

        // Add new data point (using Fahrenheit if available)
        const temp = data.temperature_f || (data.temperature * 9/5 + 32);
        temperatures.push(temp);
        timestamps.push(new Date(data.timestamp).toLocaleTimeString());

        // Keep only last 24 points
        if (temperatures.length > 24) {
            temperatures.shift();
            timestamps.shift();
        }

        temperatureChart.data.labels = timestamps;
        temperatureChart.data.datasets[0].data = temperatures;
        temperatureChart.update();

        // Update current temperature display
        document.querySelector('[data-current-temp]').textContent = 
            `${temp.toFixed(1)}°F`;
    } catch (error) {
        console.error('Error updating temperature:', error);
    }
}

// Update more frequently - every 5 seconds
setInterval(updateChart, 5000);
updateChart(); // Initial update

// Add realtime temperature updates
function updateCurrentTemperature() {
    try {
        const tempDisplay = document.querySelector('[data-current-temp]');
        if (!tempDisplay) return;
        
        const roomNumber = document.querySelector('[data-room-number]')?.dataset.roomNumber;
        if (!roomNumber) return;
        
        fetch(`/api/room_status/${roomNumber}`)
            .then(response => response.json())
            .then(data => {
                if (data && data.temperature) {
                    // Convert temperature to Fahrenheit if needed
                    const tempF = data.temperature_f || (data.temperature * 9/5 + 32);
                    // Update current temperature display without updating chart
                    tempDisplay.textContent = `${tempF.toFixed(1)}°F`;
                    
                    // Update room status
                    const statusElement = document.querySelector('.room-status');
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
                    
                    // Update pending action notification if there is one
                    const pendingElement = document.querySelector('.pending-action');
                    if (pendingElement) {
                        if (data.has_pending_event) {
                            const actionTime = new Date(data.pending_event_time);
                            pendingElement.innerHTML = `<div class="alert alert-warning">
                                <strong>Pending Action:</strong> AC will be turned off at ${actionTime.toLocaleTimeString()}
                            </div>`;
                            pendingElement.style.display = 'block';
                        } else {
                            pendingElement.style.display = 'none';
                        }
                    }
                }
            });
    } catch (error) {
        console.error('Error updating current temperature:', error);
    }
}

// Update temperature every 2 seconds (more frequent than chart update)
setInterval(updateCurrentTemperature, 2000);