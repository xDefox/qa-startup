// ============================================================
// History Page — Chart.js Score History
// Extracted from history.html for CSP compliance
// ============================================================

(function () {
  const canvas = document.getElementById('scoreChart');
  if (!canvas) return;

  // Data is injected via data attributes
  const labels = JSON.parse(canvas.dataset.labels || '[]');
  const data = JSON.parse(canvas.dataset.data || '[]');

  if (!labels.length || !data.length) return;

  if (typeof Chart === 'undefined') {
    console.warn('Chart.js not loaded');
    return;
  }

  new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: {
      labels: labels,
      datasets: [{
        label: 'Оценка',
        data: data,
        borderColor: '#2563eb',
        backgroundColor: 'rgba(37, 99, 235, 0.1)',
        fill: true,
        tension: 0.3,
        pointRadius: 4,
        pointHoverRadius: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (ctx) { return ctx.parsed.y + '/100'; }
          }
        }
      },
      scales: {
        x: {
          ticks: { maxRotation: 45, autoSkip: true, maxTicksLimit: 8 }
        },
        y: {
          min: 0,
          max: 100,
          ticks: { callback: function (v) { return v; } }
        }
      }
    }
  });
})();