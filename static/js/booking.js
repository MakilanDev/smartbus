const scheduleId = document.querySelector('#scheduleId').value;
const map = document.querySelector('#seatMap');
const chosen = new Set();
const chosenLabels = new Map(); // seat id -> seat_no, for the summary panel
let fare = Number(document.querySelector('#fareValue').value) || 0;
const leftCols = Number(document.querySelector('#leftCols').value) || 2;
let currentBookingId = null;

const originSelect = document.querySelector('#originStop');
const destSelect = document.querySelector('#destStop');

function drawSummary() {
  document.querySelector('#selectedNames').textContent = [...chosen].map(id => chosenLabels.get(id) || id).join(', ') || 'None';
  document.querySelector('#total').textContent = 'LKR ' + (chosen.size * fare).toLocaleString();
  document.querySelector('#bookBtn').disabled = !chosen.size;
}

async function refreshFare() {
  if (!originSelect || !destSelect) return;
  const params = new URLSearchParams({ origin_stop_id: originSelect.value, destination_stop_id: destSelect.value });
  try {
    const j = await fetch('/api/fare/' + scheduleId + '?' + params).then(r => r.json());
    if (j.ok) {
      fare = j.data.fare;
      document.querySelector('#legFare').textContent = 'LKR ' + Math.round(fare).toLocaleString();
      const legText = originSelect.options[originSelect.selectedIndex].text + ' → ' + destSelect.options[destSelect.selectedIndex].text;
      document.querySelector('#legText').textContent = legText;
      document.querySelector('#routeLabel').textContent = legText;
      drawSummary();
    }
  } catch (e) { /* keep full fare on failure */ }
}

if (originSelect && destSelect) {
  originSelect.addEventListener('change', refreshFare);
  destSelect.addEventListener('change', refreshFare);
  document.querySelector('#swapStops')?.addEventListener('click', () => {
    const a = originSelect.value; originSelect.value = destSelect.value; destSelect.value = a;
    refreshFare();
  });
}

fetch('/api/seats/' + scheduleId).then(r => r.json()).then(j => {
  map.innerHTML = j.data.map(s => {
    chosenLabels.set(s.id, s.seat_no);
    // Real AC-bus feel: leave a visual aisle gap after the left block of seats
    // (e.g. after column 2 in a 2+2 layout) instead of a plain uniform grid.
    const isAisleEdge = s.column_no && s.column_no === leftCols;
    const style = isAisleEdge ? 'margin-right:26px' : '';
    const seatType = s.seat_type || 'normal';
    const typeClass = seatType !== 'normal' ? ' ' + seatType : '';
    const label = seatType === 'female' ? `<small>Female</small>${s.seat_no}` : s.seat_no;
    const disabled = s.status !== 'available';
    return `<button class="seat ${s.status}${typeClass}" data-id="${s.id}" data-seat-type="${seatType}" data-seat-no="${s.seat_no}" style="${style}" ${disabled ? 'disabled' : ''}>${label}</button>`;
  }).join('');
  map.addEventListener('click', async e => {
    const btn = e.target.closest('.seat');
    if (!btn || btn.disabled) return;
    const id = btn.dataset.id;
    const isSelecting = !chosen.has(id);
    if (isSelecting && btn.dataset.seatType === 'female') {
      const r = await Swal.fire({
        title: 'Ladies-only seat',
        text: `Seat ${btn.dataset.seatNo} is reserved for female passengers. Continue selecting it?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, select it',
      });
      if (!r.isConfirmed) return;
    }
    if (chosen.has(id)) chosen.delete(id); else chosen.add(id);
    btn.classList.toggle('selected');
    drawSummary();
  });
});

document.querySelector('#bookBtn').addEventListener('click', async () => {
  const payload = { schedule_id: scheduleId, seat_ids: [...chosen] };
  if (originSelect && destSelect) {
    payload.origin_stop_id = originSelect.value;
    payload.destination_stop_id = destSelect.value;
  }
  const b = await fetch('/api/bookings/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.json());
  if (!b.ok) { Swal.fire('Seat unavailable', b.message, 'error'); return; }
  currentBookingId = b.data.id;
  document.querySelector('#payAmount').textContent = 'LKR ' + Number(b.data.total_amount).toLocaleString();
  new bootstrap.Modal('#paymentModal').show();
});

// --- Dummy card form: formats input and does basic client-side validation
// only. No card network is ever contacted; /api/payment/test always marks
// the booking paid in test mode. ---
const cardNumber = document.querySelector('#cardNumber');
cardNumber.addEventListener('input', () => {
  cardNumber.value = cardNumber.value.replace(/\D/g, '').slice(0, 16).replace(/(.{4})/g, '$1 ').trim();
});
const cardExpiry = document.querySelector('#cardExpiry');
cardExpiry.addEventListener('input', () => {
  let v = cardExpiry.value.replace(/\D/g, '').slice(0, 4);
  if (v.length > 2) v = v.slice(0, 2) + '/' + v.slice(2);
  cardExpiry.value = v;
});
document.querySelector('#cardCvv').addEventListener('input', e => {
  e.target.value = e.target.value.replace(/\D/g, '').slice(0, 4);
});

document.querySelector('#paymentForm').addEventListener('submit', async e => {
  e.preventDefault();
  const errorEl = document.querySelector('#cardError');
  errorEl.textContent = '';
  const digits = cardNumber.value.replace(/\s/g, '');
  const [mm, yy] = (cardExpiry.value || '').split('/');
  if (digits.length < 12) { errorEl.textContent = 'Enter a valid card number.'; return; }
  if (!mm || !yy || Number(mm) < 1 || Number(mm) > 12) { errorEl.textContent = 'Enter a valid expiry date.'; return; }
  if (document.querySelector('#cardCvv').value.length < 3) { errorEl.textContent = 'Enter a valid CVV.'; return; }

  const payBtn = document.querySelector('#payBtn');
  payBtn.disabled = true;
  payBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Processing…';

  try {
    const p = await fetch('/api/payment/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ booking_id: currentBookingId }),
    }).then(r => r.json());

    bootstrap.Modal.getInstance(document.querySelector('#paymentModal'))?.hide();

    if (p.ok) {
      Swal.fire({
        title: 'Payment successful!',
        html: `Your bill and live tracking link have also been sent to your email.<br><br>
               <a href="${p.data.ticket}" target="_blank" class="btn-primary-xl" style="text-decoration:none;display:inline-block;margin:6px">Download bill (PDF)</a>
               ${p.data.tracking ? `<a href="${p.data.tracking}" class="btn-primary-xl" style="text-decoration:none;display:inline-block;margin:6px">Track your bus</a>` : ''}`,
        icon: 'success',
        confirmButtonText: 'Done',
      });
    } else {
      Swal.fire('Payment failed', p.message || 'Please try again.', 'error');
    }
  } finally {
    payBtn.disabled = false;
    payBtn.innerHTML = '<i class="bi bi-lock-fill"></i> Pay now';
  }
});
