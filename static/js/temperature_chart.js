// Initialize temperature chart
const ctx = document.getElementById('temperatureChart').getContext('2d');
const temperatureChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: [],
        datasets: [{
            label: 'Temperature °C',
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
                min: 18,
                max: 30
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

        // Add new data point
        temperatures.push(data.temperature);
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
            `${data.temperature.toFixed(1)}°C`;
    } catch (error) {
        console.error('Error updating temperature:', error);
    }
}

// Update every minute
setInterval(updateChart, 60000);
updateChart(); // Initial update