fetch('/api/dashboard/stats').then(r => r.json()).then(j => {
  const s = j.data, c = document.querySelectorAll('#statCards strong');
  if (!c.length) return;
  const v = [s.users, s.buses, s.trips, 'LKR ' + Number(s.revenue || 0).toLocaleString(), s.bookings_today, s.active_gps_buses, s.google_maps_status, (s.average_delay_time || 0) + ' min', 'LKR ' + Number(s.fuel_cost_today || 0).toLocaleString(), s.active_trips, s.online_drivers];
  v.forEach((x, i) => { if (c[i]) c[i].textContent = x; });
});
const ctx = document.querySelector('#bookingChart');
if (ctx) new Chart(ctx, { type: 'line', data: { labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'], datasets: [{ data: [42, 58, 47, 76, 69, 92, 84], borderColor: '#14b8a6', backgroundColor: 'rgba(20,184,166,.14)', fill: true, tension: .4, pointBackgroundColor: '#fff' }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: '#8fa79f' } }, y: { grid: { color: 'rgba(255,255,255,.05)' }, ticks: { color: '#8fa79f' } } } } });
