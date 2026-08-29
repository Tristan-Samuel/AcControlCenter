const canvas = document.getElementById('temperatureChart');
if (canvas) {
    const ctx = canvas.getContext('2d');
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
                y: { beginAtZero: false, min: 60, max: 90 }
            }
        }
    });

    const temperatures = [];
    const timestamps = [];

    async function updateChart() {
        try {
            const roomNumber = document.querySelector('[data-room-number]')?.dataset.roomNumber;
            if (!roomNumber) return;
            const response = await fetch(`/api/rooms/${roomNumber}/temperature`);
            if (!response.ok) return;
            const data = await response.json();
            const temp = data.temperature_f || (data.temperature * 9 / 5 + 32);
            temperatures.push(temp);
            timestamps.push(new Date().toLocaleTimeString());
            if (temperatures.length > 24) {
                temperatures.shift();
                timestamps.shift();
            }
            temperatureChart.data.labels = timestamps;
            temperatureChart.data.datasets[0].data = temperatures;
            temperatureChart.update();
            const display = document.querySelector('[data-current-temp]');
            if (display) display.textContent = `${Number(temp).toFixed(1)}°F`;
        } catch (error) {
            console.error('Error updating temperature:', error);
        }
    }

    setInterval(updateChart, 5000);
    updateChart();
}
