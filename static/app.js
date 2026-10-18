const areas = document.querySelector('#areas');
const empty = document.querySelector('#empty');
const connection = document.querySelector('#connection');
const toast = document.querySelector('#toast');
const state = { sensors: [], status: {} };
let renderedIds = '';
let toastTimer;

const format = value => Number(value).toLocaleString('en-US', { maximumFractionDigits: 1 });

function showError(message) {
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('show'), 4500);
}

async function request(path, options = {}) {
  const prefix = location.pathname.startsWith('/simulator/') ? '/simulator' : '';
  if (prefix && options.method && options.method !== 'GET') {
    const auth = await fetch('/api/auth/me', { credentials: 'same-origin', cache: 'no-store' });
    const session = await auth.json();
    options.headers = { ...options.headers, 'X-CSRF-Token': session.csrf_token || '' };
  }
  const response = await fetch(`${prefix}${path}`, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function makeMeter(sensor) {
  const row = document.createElement('div');
  row.className = 'meter';
  row.dataset.id = sensor.id;

  const heading = document.createElement('div');
  heading.className = 'meter-heading';
  const name = document.createElement('div');
  name.className = 'meter-name';
  name.textContent = sensor.metric;
  const value = document.createElement('output');
  value.className = 'meter-value';
  value.textContent = `${format(sensor.current_value)} ${sensor.unit}`;
  heading.append(name, value);

  const slider = document.createElement('input');
  slider.className = 'meter-slider';
  slider.type = 'range';
  slider.min = String(sensor.min_value);
  slider.max = String(sensor.simulation_max);
  slider.step = '0.1';
  slider.value = String(sensor.current_value);
  slider.setAttribute('aria-label', `${sensor.metric} reading for ${sensor.area}`);

  const scale = document.createElement('div');
  scale.className = 'meter-scale';
  scale.innerHTML = '<span></span><span></span><span></span>';
  row.append(heading, slider, scale);
  updateMeter(row, sensor);
  return row;
}

function updateMeter(row, sensor) {
  const slider = row.querySelector('.meter-slider');
  const scale = row.querySelectorAll('.meter-scale span');
  slider.min = String(sensor.min_value);
  slider.max = String(sensor.simulation_max);
  slider.disabled = !sensor.active;
  row.classList.toggle('disabled', !sensor.active);
  scale[0].textContent = `Min ${format(sensor.min_value)}`;
  scale[1].textContent = `Baseline ${format(sensor.baseline)}`;
  scale[2].textContent = `Max ${format(sensor.max_value)}`;
  if (document.activeElement !== slider && !row.classList.contains('saving')) {
    slider.value = String(sensor.current_value);
    row.querySelector('.meter-value').textContent = `${format(sensor.current_value)} ${sensor.unit}`;
  }
}

function render() {
  const sensors = state.sensors;
  const ids = sensors.map(sensor => sensor.id).join('|');
  if (ids !== renderedIds) {
    areas.replaceChildren();
    const groups = new Map();
    for (const sensor of sensors) {
      if (!groups.has(sensor.area)) groups.set(sensor.area, []);
      groups.get(sensor.area).push(sensor);
    }
    for (const [area, meters] of groups) {
      const section = document.createElement('section');
      section.className = 'area';
      const title = document.createElement('h2');
      title.textContent = area;
      section.append(title);
      const grid = document.createElement('div');
      grid.className = 'meter-grid';
      meters.forEach(sensor => grid.append(makeMeter(sensor)));
      section.append(grid);
      areas.append(section);
    }
    renderedIds = ids;
  } else {
    const byId = new Map(sensors.map(sensor => [sensor.id, sensor]));
    areas.querySelectorAll('.meter').forEach(row => updateMeter(row, byId.get(row.dataset.id)));
  }
  empty.hidden = sensors.length > 0;
  const publishing = state.status.state === 'connected';
  connection.textContent = publishing ? 'Publishing to MQTT' : (state.status.message || 'Waiting for MQTT');
  connection.className = `connection ${publishing ? 'connected' : 'disconnected'}`;
  connection.title = state.status.message || '';
}

async function refresh() {
  try {
    const data = await request('/api/state');
    state.sensors = data.sensors;
    state.status = data.status;
    render();
  } catch (error) {
    connection.textContent = 'Simulator unavailable';
    connection.className = 'connection disconnected';
    showError(error.message);
  }
}

areas.addEventListener('input', event => {
  if (!event.target.matches('.meter-slider')) return;
  const row = event.target.closest('.meter');
  const sensor = state.sensors.find(item => item.id === row.dataset.id);
  row.querySelector('.meter-value').textContent = `${format(event.target.value)} ${sensor.unit}`;
});

areas.addEventListener('change', async event => {
  if (!event.target.matches('.meter-slider')) return;
  const row = event.target.closest('.meter');
  const sensor = state.sensors.find(item => item.id === row.dataset.id);
  const currentValue = Number(event.target.value);
  row.classList.add('saving');
  try {
    await request(`/api/sensors/${encodeURIComponent(sensor.id)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_value: currentValue }),
    });
    sensor.current_value = currentValue;
  } catch (error) {
    showError(error.message);
  } finally {
    row.classList.remove('saving');
    await refresh();
  }
});

refresh();
setInterval(refresh, 2500);
