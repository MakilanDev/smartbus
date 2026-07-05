/* SmartBus live tracking — Uber/PickMe-style map.
 *
 * Features:
 *   • Stops rendered as labeled pins (A, B, C … Z) along the route.
 *   • Route drawn via Google Directions, following real roads through stops.
 *   • Bus marker is a custom SVG that rotates to the heading of travel and
 *     animates smoothly between GPS pings (no teleporting).
 *   • Progress stops in the side panel light up as the bus passes them.
 *   • Uses async Google Maps loader with an initMap callback so the script
 *     never runs before the SDK is ready.
 */

(function () {
  let mapObj,
      busMarker,
      directionsRenderer,
      directionsService,
      statusTimer,
      positionTimer,
      routePath = [],
      stopsData = [],
      stopMarkers = [],
      animRAF = null,
      lastPos = null;

  const SRI_LANKA_CENTER = { lat: 7.8731, lng: 80.7718 };
  const BUS_SVG = "M -18 -8 L 18 -8 A 4 4 0 0 1 22 -4 L 22 8 A 4 4 0 0 1 18 12 L -18 12 A 4 4 0 0 1 -22 8 L -22 -4 A 4 4 0 0 1 -18 -8 Z M -14 -4 L 14 -4 L 14 4 L -14 4 Z";

  function $(id) { return document.querySelector('#' + id); }
  function readInput(id) { const el = $(id); return el ? el.value.trim() : ''; }

  function getOriginDest() {
    const originLat = parseFloat(readInput('originLat'));
    const originLng = parseFloat(readInput('originLng'));
    const destLat = parseFloat(readInput('destLat'));
    const destLng = parseFloat(readInput('destLng'));
    const originName = readInput('originName');
    const destName = readInput('destName');
    const hasCoords = !isNaN(originLat) && !isNaN(originLng) && !isNaN(destLat) && !isNaN(destLng);
    return {
      origin: hasCoords ? { lat: originLat, lng: originLng } : (originName || null),
      dest: hasCoords ? { lat: destLat, lng: destLng } : (destName || null),
      hasCoords,
    };
  }

  function loadStops() {
    const el = document.querySelector('#waypointsData');
    stopsData = [];
    if (!el) return;
    try {
      const middle = JSON.parse(el.textContent || '[]');
      // Include origin and destination if we have coords, so the pins show A..Z
      const originLat = parseFloat(readInput('originLat'));
      const originLng = parseFloat(readInput('originLng'));
      const destLat = parseFloat(readInput('destLat'));
      const destLng = parseFloat(readInput('destLng'));
      const originName = readInput('originName') || 'Start';
      const destName = readInput('destName') || 'Destination';
      if (!isNaN(originLat)) stopsData.push({ stop_name: originName, latitude: originLat, longitude: originLng });
      middle.forEach(s => {
        if (s.latitude && s.longitude) stopsData.push(s);
      });
      if (!isNaN(destLat)) stopsData.push({ stop_name: destName, latitude: destLat, longitude: destLng });
    } catch (e) { /* keep empty */ }
  }

  function setOverlay(which) {
    const waiting = document.querySelector('#waitingOverlay');
    const completed = document.querySelector('#completedOverlay');
    const liveBadge = document.querySelector('#liveBadge');
    if (waiting) waiting.style.display = which === 'waiting' ? 'flex' : 'none';
    if (completed) completed.style.display = which === 'completed' ? 'flex' : 'none';
    if (liveBadge) liveBadge.style.display = which === null ? 'inline-flex' : 'none';
  }

  function stopPinIcon(index, total, isPassed) {
    const letter = String.fromCharCode(65 + Math.min(index, 25));
    const isStart = index === 0;
    const isEnd = index === total - 1;
    const fill = isStart ? '#22c55e' : isEnd ? '#fb7185' : (isPassed ? '#14b8a6' : '#f8fafc');
    const stroke = isStart ? '#052e1a' : isEnd ? '#3f0a15' : '#0f172a';
    const textColor = (isStart || isEnd) ? '#fff' : '#0f172a';
    return {
      url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="34" height="46" viewBox="0 0 34 46">
          <defs><filter id="s" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="2" stdDeviation="1.5" flood-opacity="0.4"/></filter></defs>
          <path filter="url(#s)" d="M17 1 C 8 1 1 8 1 17 c 0 12 16 28 16 28 s 16-16 16-28 C 33 8 26 1 17 1 z" fill="${fill}" stroke="${stroke}" stroke-width="2"/>
          <text x="17" y="22" text-anchor="middle" font-family="Inter, Arial" font-weight="800" font-size="14" fill="${textColor}">${letter}</text>
        </svg>`),
      scaledSize: new google.maps.Size(34, 46),
      anchor: new google.maps.Point(17, 44),
    };
  }

  function busIcon(heading) {
      // Uber/PickMe-style bus marker: white chip with a rotating heading arrow.
      // The 🚌 emoji is rendered via the Marker `label` (SVG <text> can't render
      // emoji reliably across browsers when embedded as a data: URL).
      const rot = heading || 0;
      const svg = "<svg xmlns='http://www.w3.org/2000/svg' width='64' height='72' viewBox='0 0 64 72'>"
        + "<defs><filter id='sh' x='-20%' y='-20%' width='140%' height='140%'><feDropShadow dx='0' dy='3' stdDeviation='2.5' flood-opacity='0.35'/></filter></defs>"
        + "<g transform='translate(32 34) rotate(" + rot + ")'><path d='M0 -30 L11 -15 L-11 -15 Z' fill='#f59e0b' stroke='#78350f' stroke-width='1.5'/></g>"
        + "<circle cx='32' cy='34' r='22' fill='#ffffff' stroke='#f59e0b' stroke-width='3' filter='url(#sh)'/>"
        + "</svg>";
      return {
        url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(svg),
        scaledSize: new google.maps.Size(64, 72),
        anchor: new google.maps.Point(32, 34),
        labelOrigin: new google.maps.Point(32, 36),
      };
    }

  const BUS_LABEL = {
    text: String.fromCodePoint(0x1F68C),
    fontSize: '26px',
    fontWeight: '400',
    className: 'bus-marker-label',
  };


  function renderStopMarkers() {
    stopMarkers.forEach(m => m.setMap(null));
    stopMarkers = [];
    stopsData.forEach((s, i) => {
      const marker = new google.maps.Marker({
        position: { lat: Number(s.latitude), lng: Number(s.longitude) },
        map: mapObj,
        icon: stopPinIcon(i, stopsData.length, false),
        title: s.stop_name,
        zIndex: 10 + i,
      });
      stopMarkers.push(marker);
    });
  }

  function drawRoute(cb) {
    const { origin, dest, hasCoords } = getOriginDest();
    if (!origin || !dest) return;
    const waypoints = stopsData.slice(1, -1).map(s => ({
      location: { lat: Number(s.latitude), lng: Number(s.longitude) },
      stopover: true,
    }));
    directionsService = directionsService || new google.maps.DirectionsService();
    directionsRenderer = new google.maps.DirectionsRenderer({
      map: mapObj,
      suppressMarkers: true,
      preserveViewport: false,
      polylineOptions: {
        strokeColor: '#14b8a6',
        strokeOpacity: 0.95,
        strokeWeight: 6,
        icons: [{
          icon: { path: 'M 0,-1 0,1', strokeOpacity: 0.6, scale: 3, strokeColor: '#5eead4' },
          offset: '0', repeat: '18px'
        }],
      },
    });
    directionsService.route(
      { origin, destination: dest, waypoints, travelMode: google.maps.TravelMode.DRIVING },
      (result, status) => {
        if (status === 'OK') {
          directionsRenderer.setDirections(result);
          routePath = [];
          result.routes[0].legs.forEach(l => l.steps.forEach(st => {
            st.path.forEach(pt => routePath.push({ lat: pt.lat(), lng: pt.lng() }));
          }));
          const remainingSeconds = result.routes[0].legs.reduce((s, l) => s + (l.duration?.value || 0), 0);
          const etaEl = $('etaText');
          if (etaEl && remainingSeconds) etaEl.textContent = Math.round(remainingSeconds / 60) + ' min to destination';
          if (cb) cb();
        } else if (hasCoords) {
          routePath = [{ lat: origin.lat, lng: origin.lng }, { lat: dest.lat, lng: dest.lng }];
          new google.maps.Polyline({ path: routePath, strokeColor: '#14b8a6', strokeOpacity: 0.9, strokeWeight: 5, map: mapObj });
          if (cb) cb();
        }
      }
    );

    busMarker = new google.maps.Marker({
      position: hasCoords ? origin : SRI_LANKA_CENTER,
      map: mapObj,
      icon: busIcon(0),
      label: BUS_LABEL,
      zIndex: 999,
    });
  }

  function bearing(a, b) {
    const toRad = d => d * Math.PI / 180;
    const toDeg = r => r * 180 / Math.PI;
    const y = Math.sin(toRad(b.lng - a.lng)) * Math.cos(toRad(b.lat));
    const x = Math.cos(toRad(a.lat)) * Math.sin(toRad(b.lat)) -
              Math.sin(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.cos(toRad(b.lng - a.lng));
    return (toDeg(Math.atan2(y, x)) + 360) % 360;
  }

  function animateBusTo(target) {
    if (!busMarker) return;
    if (animRAF) cancelAnimationFrame(animRAF);
    const start = busMarker.getPosition();
    if (!start) { busMarker.setPosition(target); return; }
    const from = { lat: start.lat(), lng: start.lng() };
    const heading = bearing(from, target);
    busMarker.setIcon(busIcon(heading));
    const t0 = performance.now();
    const dur = 1400;
    function step(now) {
      const k = Math.min(1, (now - t0) / dur);
      const lat = from.lat + (target.lat - from.lat) * k;
      const lng = from.lng + (target.lng - from.lng) * k;
      busMarker.setPosition({ lat, lng });
      if (k < 1) animRAF = requestAnimationFrame(step);
    }
    animRAF = requestAnimationFrame(step);
    updateProgressStops(target);
  }

  function distMeters(a, b) {
    const R = 6371000;
    const toRad = d => d * Math.PI / 180;
    const dLat = toRad(b.lat - a.lat);
    const dLng = toRad(b.lng - a.lng);
    const s = Math.sin(dLat/2)**2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng/2)**2;
    return R * 2 * Math.atan2(Math.sqrt(s), Math.sqrt(1-s));
  }

  function updateProgressStops(busPos) {
    if (!stopsData.length) return;
    // A stop is "passed" if the bus is closer to any later stop or the current
    // one is within 800m.
    let passedIdx = -1;
    for (let i = 0; i < stopsData.length; i++) {
      const s = { lat: Number(stopsData[i].latitude), lng: Number(stopsData[i].longitude) };
      if (distMeters(busPos, s) < 800) passedIdx = Math.max(passedIdx, i);
    }
    // Also mark all stops before whichever is nearest as passed.
    let nearest = 0, nearestD = Infinity;
    stopsData.forEach((s, i) => {
      const d = distMeters(busPos, { lat: Number(s.latitude), lng: Number(s.longitude) });
      if (d < nearestD) { nearestD = d; nearest = i; }
    });
    passedIdx = Math.max(passedIdx, nearest - 1);

    document.querySelectorAll('.progress-stops > div').forEach((el, i) => {
      el.classList.remove('done', 'active');
      const state = el.querySelector('.stop-state');
      if (i < passedIdx) { el.classList.add('done'); if (state) state.textContent = 'Passed'; }
      else if (i === passedIdx || i === nearest) { el.classList.add('active'); if (state) state.textContent = 'Approaching'; }
      else if (state) state.textContent = 'Upcoming';
    });
    stopMarkers.forEach((m, i) => m.setIcon(stopPinIcon(i, stopsData.length, i <= passedIdx)));
  }

  window.initMap = function initMap() {
    const el = document.querySelector('#map');
    if (!el) return;

    loadStops();
    const { origin, hasCoords } = getOriginDest();
    const center = hasCoords ? origin : SRI_LANKA_CENTER;

    mapObj = new google.maps.Map(el, {
      center,
      zoom: hasCoords ? 8 : 7,
      gestureHandling: 'greedy',
      disableDefaultUI: true,
      zoomControl: true,
      styles: [
        { elementType: 'geometry', stylers: [{ color: '#0c1a16' }] },
        { elementType: 'labels.text.fill', stylers: [{ color: '#8fa79f' }] },
        { elementType: 'labels.text.stroke', stylers: [{ color: '#0c1a16' }] },
        { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#173028' }] },
        { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#1f4a3f' }] },
        { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#06120f' }] },
        { featureType: 'poi', stylers: [{ visibility: 'off' }] },
      ],
    });

    const isFleetMode = readInput('adminMode') === 'true' && !readInput('tripId');
    if (isFleetMode) {
      updateFleet();
      setInterval(updateFleet, 10000);
      const picker = document.querySelector('#adminTripPicker');
      if (picker) {
        refreshTripPicker();
        setInterval(refreshTripPicker, 15000);
        picker.addEventListener('change', () => {
          if (picker.value) window.location.href = '/live-tracking?trip_id=' + picker.value;
        });
      }
      return;
    }

    renderStopMarkers();
    // Fit map to all stops so passengers see the whole route from the start.
    if (stopsData.length >= 2) {
      const b = new google.maps.LatLngBounds();
      stopsData.forEach(s => b.extend({ lat: Number(s.latitude), lng: Number(s.longitude) }));
      mapObj.fitBounds(b, 60);
    }

    const status = readInput('trackingStatus');
    handleStatus(status, true);
    statusTimer = setInterval(pollStatus, 6000);
  };

  function handleStatus(status) {
    if (status === 'started' || status === 'delayed') {
      setOverlay(null);
      const badge = $('onTimeBadge');
      if (badge) badge.textContent = status === 'delayed' ? 'Delayed' : 'On time';
      if (!busMarker) drawRoute();
      if (!positionTimer) {
        updatePosition();
        positionTimer = setInterval(updatePosition, 5000);
      }
    } else if (status === 'completed' || status === 'cancelled' || status === 'breakdown') {
      setOverlay('completed');
      clearInterval(statusTimer);
      clearInterval(positionTimer);
    } else {
      setOverlay('waiting');
    }
  }

  async function pollStatus() {
    const id = $('tripId')?.value;
    if (!id) return;
    try {
      const r = await fetch('/api/trip/status/' + id);
      const j = await r.json();
      if (j.ok) handleStatus(j.data.status);
    } catch (e) { /* transient */ }
  }

  async function updatePosition() {
    const id = $('tripId')?.value;
    if (!id || !busMarker) return;
    try {
      const r = await fetch('/api/trip/location/' + id);
      const j = await r.json();
      if (j.ok && j.data && j.data.has_position && j.data.latitude && j.data.longitude) {
        const target = { lat: Number(j.data.latitude), lng: Number(j.data.longitude) };
        animateBusTo(target);
        lastPos = target;
      }
      if (j.ok && j.data && j.data.status && j.data.status !== readInput('trackingStatus')) {
        $('trackingStatus').value = j.data.status;
        handleStatus(j.data.status);
      }
    } catch (e) { /* keep last known */ }
  }

  async function refreshTripPicker() {
    const picker = document.querySelector('#adminTripPicker');
    if (!picker) return;
    try {
      const r = await fetch('/api/admin/active-trips');
      const j = await r.json();
      if (!j.ok) return;
      const noActive = document.querySelector('#noActiveFleet');
      if (!j.data.length) {
        picker.innerHTML = '<option value="">No active trips</option>';
        if (noActive) noActive.style.display = 'flex';
        return;
      }
      if (noActive) noActive.style.display = 'none';
      picker.innerHTML = '<option value="">Select a trip to follow…</option>' +
        j.data.map(t => `<option value="${t.trip_id}">${t.bus} · ${t.route_label}${t.status === 'delayed' ? ' (delayed)' : ''}</option>`).join('');
    } catch (e) { /* keep list */ }
  }

  async function updateFleet() {
    try {
      const r = await fetch('/api/admin/all-bus-locations');
      const j = await r.json();
      if (!j.ok) return;
      (window._fleetMarkers || []).forEach(m => m.setMap(null));
      window._fleetMarkers = j.data.map(row =>
        new google.maps.Marker({
          position: { lat: Number(row.latitude), lng: Number(row.longitude) },
          map: mapObj,
          icon: busIcon(row.heading || 0),
          label: BUS_LABEL,
          title: `${row.bus || ''} · ${row.route_label || ''}`,
        })
      );
      const noActive = document.querySelector('#noActiveFleet');
      if (noActive) noActive.style.display = j.data.length ? 'none' : 'flex';
    } catch (e) { /* keep last */ }
  }

  // If Google Maps is already loaded (e.g. cached), run initMap now.
  if (window.google && window.google.maps) window.initMap();
})();
