let allocMap, markers = [], polyline, activeRouteId = null;

window.initAllocMap = function initAllocMap() {
  allocMap = new google.maps.Map(document.querySelector('#allocMap'), {
    center: { lat: 7.8731, lng: 80.7718 },
    zoom: 7,
    gestureHandling: 'greedy',
    styles: [{ elementType: 'geometry', stylers: [{ color: '#0c1a16' }] }, { elementType: 'labels.text.fill', stylers: [{ color: '#8fa79f' }] }, { elementType: 'labels.text.stroke', stylers: [{ color: '#0c1a16' }] }, { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#173028' }] }, { featureType: 'road.highway', elementType: 'geometry', stylers: [{ color: '#1f4a3f' }] }, { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#08120f' }] }, { featureType: 'poi', stylers: [{ visibility: 'off' }] }],
  });
  allocMap.addListener('click', onMapClick);
  const preselect = new URLSearchParams(location.search).get('route_id');
  if (preselect) {
    const chip = document.querySelector(`.route-chip[data-route-id="${preselect}"]`);
    if (chip) chip.click();
  }
};

function clearMap() {
  markers.forEach(m => m.setMap(null));
  markers = [];
  if (polyline) polyline.setMap(null);
}

function renderStops(stops, routeName) {
  const list = document.querySelector('#stopList');
  if (!stops.length) {
    list.innerHTML = `<div class="empty" style="padding:20px"><i class="bi bi-geo-alt"></i><p>No stops yet for <b>${routeName}</b>. Click on the map to add the first one.</p></div>`;
    return;
  }
  list.innerHTML = `<div style="padding:4px 4px 10px"><b>${routeName}</b> · ${stops.length} stop${stops.length > 1 ? 's' : ''}</div>` +
    stops.map((s, i) => `<div class="stop-pin"><span class="num">${i + 1}</span><b>${s.stop_name}</b><small>${s.distance_from_origin_km ? s.distance_from_origin_km + ' km from origin' : ''}</small></div>`).join('');
}

async function loadRoute(routeId, routeName) {
  activeRouteId = routeId;
  clearMap();
  const j = await fetch('/api/routes/' + routeId + '/stops').then(r => r.json());
  const stops = (j.data || []).filter(s => s.latitude && s.longitude);
  renderStops(j.data || [], routeName);
  if (!stops.length) return;
  const path = stops.map(s => ({ lat: Number(s.latitude), lng: Number(s.longitude) }));
  stops.forEach((s, i) => {
    const letter = String.fromCharCode(65 + Math.min(i, 25));
    const isEnd = i === stops.length - 1;
    const fill = i === 0 ? '#22c55e' : isEnd ? '#fb7185' : '#14b8a6';
    const icon = {
      url: 'data:image/svg+xml;charset=UTF-8,' + encodeURIComponent(
        `<svg xmlns="http://www.w3.org/2000/svg" width="34" height="46" viewBox="0 0 34 46"><path d="M17 1 C 8 1 1 8 1 17 c 0 12 16 28 16 28 s 16-16 16-28 C 33 8 26 1 17 1 z" fill="${fill}" stroke="#0f172a" stroke-width="2"/><text x="17" y="22" text-anchor="middle" font-family="Inter, Arial" font-weight="800" font-size="14" fill="#fff">${letter}</text></svg>`),
      scaledSize: new google.maps.Size(34, 46),
      anchor: new google.maps.Point(17, 44),
    };
    const marker = new google.maps.Marker({ position: path[i], map: allocMap, icon, title: s.stop_name });
    markers.push(marker);
  });
  // Snap route to real roads via Directions when we have >=2 stops
  if (path.length >= 2) {
    const ds = new google.maps.DirectionsService();
    const waypoints = path.slice(1, -1).map(p => ({ location: p, stopover: true }));
    ds.route({ origin: path[0], destination: path[path.length - 1], waypoints, travelMode: google.maps.TravelMode.DRIVING }, (res, status) => {
      if (status === 'OK') {
        polyline = new google.maps.Polyline({
          path: res.routes[0].overview_path, geodesic: true, strokeColor: '#14b8a6',
          strokeOpacity: 0.95, strokeWeight: 5, map: allocMap,
        });
      } else {
        polyline = new google.maps.Polyline({ path, geodesic: true, strokeColor: '#14b8a6', strokeOpacity: 0.9, strokeWeight: 4, map: allocMap });
      }
    });
  }
  const bounds = new google.maps.LatLngBounds();
  path.forEach(p => bounds.extend(p));
  allocMap.fitBounds(bounds, 60);
}

async function onMapClick(e) {
  if (!activeRouteId) {
    Swal.fire('Pick a route first', 'Select a route on the left before allocating a stop.', 'info');
    return;
  }
  const lat = e.latLng.lat(), lng = e.latLng.lng();
  let guessedName = 'New stop';
  try {
    const geocoder = new google.maps.Geocoder();
    const res = await geocoder.geocode({ location: { lat, lng } });
    if (res.results && res.results[0]) {
      const locality = res.results[0].address_components.find(c => c.types.includes('locality') || c.types.includes('administrative_area_level_2'));
      guessedName = locality ? locality.long_name : res.results[0].formatted_address.split(',')[0];
    }
  } catch (err) { /* geocoding optional — fall back to manual name */ }

  const { value: stopName, isConfirmed } = await Swal.fire({
    title: 'Allocate this stop',
    input: 'text',
    inputValue: guessedName,
    inputLabel: 'Stop name',
    showCancelButton: true,
    confirmButtonText: 'Allocate stop',
  });
  if (!isConfirmed || !stopName) return;

  document.querySelector('#stopRouteId').value = activeRouteId;
  document.querySelector('#stopName').value = stopName;
  document.querySelector('#stopLat').value = lat;
  document.querySelector('#stopLng').value = lng;
  document.querySelector('#addStopForm').submit();
}

document.querySelectorAll('.route-chip').forEach(chip => {
  chip.addEventListener('click', () => {
    document.querySelectorAll('.route-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    loadRoute(chip.dataset.routeId, chip.dataset.routeName);
  });
});

if (window.google && window.google.maps) window.initAllocMap();
