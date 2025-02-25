// Initialize temperature chart
const ctx = document.getElementById('temperatureChart').getContext('2d');
const temperatureChart = new Chart(ctx, {
    type: 'line',
    data: {
        labels: Array.from({length: 24}, (_, i) => `${i}:00`),
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

// Update chart with mock data
function updateChart() {
    const newData = Array.from({length: 24}, () => 20 + Math.random() * 8);
    temperatureChart.data.datasets[0].data = newData;
    temperatureChart.update();
}

// Update every 5 minutes
setInterval(updateChart, 300000);
updateChart(); // Initial update
