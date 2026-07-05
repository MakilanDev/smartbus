let gpsTimer;
const tripId = document.querySelector('#tripId').value;
const START_WINDOW_BEFORE_MIN = 720;
const START_WINDOW_AFTER_MIN = 1440;

function updateStartWindow() {
  const startBtn = document.querySelector('#startBtn');
  const note = document.querySelector('#startWindowNote');
  const depRaw = document.querySelector('#departureTime')?.value;
  if (!startBtn || startBtn.dataset.started === 'true') return; // already started/disabled permanently
  if (!depRaw) { if (note) note.textContent = ''; return; }
  const dep = new Date(depRaw);
  const opensAt = new Date(dep.getTime() - START_WINDOW_BEFORE_MIN * 60000);
  const closesAt = new Date(dep.getTime() + START_WINDOW_AFTER_MIN * 60000);
  const now = new Date();
  if (now < opensAt) {
    startBtn.disabled = true;
    if (note) note.textContent = `You can start this trip from ${opensAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} onward.`;
  } else if (now > closesAt) {
    startBtn.disabled = true;
    if (note) note.textContent = 'This trip\u2019s start window has passed — contact dispatch.';
  } else {
    startBtn.disabled = false;
    if (note) note.textContent = 'You can start this trip now.';
  }
}
updateStartWindow();
setInterval(updateStartWindow, 15000);

async function sendLocation() {
  const fallback = { latitude: 7.8731 + (Math.random() - .5) * .04, longitude: 80.7718 + (Math.random() - .5) * .04, speed: 52 };
  const post = d => fetch('/api/driver/location/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ trip_id: tripId, ...d }) });
  if (navigator.geolocation) navigator.geolocation.getCurrentPosition(p => post({ latitude: p.coords.latitude, longitude: p.coords.longitude, speed: p.coords.speed || 0, heading: p.coords.heading || 0 }), () => post(fallback));
  else post(fallback);
}

document.querySelectorAll('.driver-action').forEach(b => b.addEventListener('click', async () => {
  let action = b.dataset.action, data = { trip_id: tripId };
  if (action === 'delay') {
    const r = await Swal.fire({ title: 'Mark a delay', input: 'text', inputLabel: 'What happened?', inputPlaceholder: 'Heavy traffic', showCancelButton: true });
    if (!r.isConfirmed) return;
    data.reason = r.value; data.minutes = 15;
  }
  if (action === 'breakdown') {
    const r = await Swal.fire({ title: 'Report breakdown?', text: 'Dispatch and passengers will be notified.', icon: 'warning', showCancelButton: true });
    if (!r.isConfirmed) return;
  }
  const res = await fetch('/api/trip/' + (action === 'delay' ? 'mark-delay' : action), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const j = await res.json();
  if (res.status === 403) {
    Swal.fire('Not allowed', j.message || 'Only the driver allocated to this trip can do this.', 'error');
    return;
  }
  if (j.ok) {
    document.querySelector('#tripStatus').textContent = action;
    Swal.fire('Updated', 'Trip status is now ' + action + '.', 'success');
    if (action === 'start') {
      document.querySelector('#startTimeText').textContent = new Date(j.data.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      document.querySelectorAll('.start-time-card small')[0].textContent = 'Actual start time';
      const startBtn = document.querySelector('[data-action="start"]');
      startBtn.disabled = true;
      startBtn.dataset.started = 'true';
      document.querySelector('#startWindowNote').textContent = 'Trip started.';
      const trackingStatus = document.querySelector('#trackingStatus');
      if (trackingStatus) trackingStatus.value = 'started';
      sendLocation();
      gpsTimer = setInterval(sendLocation, 10000);
      document.querySelector('#gpsState').innerHTML = '<i class="bi bi-broadcast"></i> Sharing GPS every 10 seconds';
    }
    if (action === 'complete') {
      if (gpsTimer) clearInterval(gpsTimer);
      const trackingStatus = document.querySelector('#trackingStatus');
      if (trackingStatus) trackingStatus.value = 'completed';
    }
  } else {
    Swal.fire('Could not update trip', j.message || 'Please try again.', 'error');
  }
}));
