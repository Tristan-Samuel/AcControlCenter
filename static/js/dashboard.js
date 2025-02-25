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

// Update every 5 seconds
setInterval(updateTemperatures, 5000);
updateTemperatures(); // Initial update
