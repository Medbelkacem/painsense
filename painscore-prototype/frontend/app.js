const STREAMS = ['A', 'B', 'C'];

const COLOURS = { A: '#7c6cf0', B: '#38b2ac', C: '#e08b3e' };

const LAYER_ROWS = [
  ['base', 'base'],
  ['statistical', 'statistical'],
  ['ml', 'ML'],
  ['composite', 'composite'],
  ['final', 'after C'],
];

const ABLATION_LABELS = {
  without_base: 'without layer 1 · clinical base',
  without_statistical: 'without layer 2 · statistical',
  without_ml: 'without layer 3 · ML importance',
  without_attenuation: 'without layer 4 · attenuation',
};

const SCENARIO_LABELS = {
  rest: 'rest',
  pain: 'pain',
  exercise: 'exercise',
  anxiety: 'anxiety',
  sedated: 'sedated',
  sensor_failure: 'sensor failure',
};

const CONTEXT_LABELS = {
  conscious_ward: 'conscious — ward',
  conscious_er: 'conscious — emergency',
  unconscious_sedated: 'unconscious — sedated',
};

const THERAPY_LABELS = {
  therapy_tens: 'TENS',
  therapy_vibration: 'vibration',
  therapy_thermotherapy: 'thermotherapy',
  therapy_photobiomodulation: 'photobiomodulation',
};

const OBSERVATION_LABELS = {
  heart_rate_up: 'heart rate up',
  gsr_up: 'skin conductance up',
  respiration_up: 'respiration up',
  moving: 'body motion',
  guarding: 'EMG guarding',
  pain_face: 'pain facial features',
};

const WEIGHT_SCALE = 0.6;
const HISTORY = 90;

const find = (id) => document.getElementById(id);

const parts = {
  link: find('link'),
  security: find('security'),
  scenarios: find('scenarios'),
  level: find('level'),
  levelValue: find('levelValue'),
  context: find('context'),
  role: find('role'),
  camera: find('camera'),
  therapy: find('therapy'),
  withheld: find('withheld'),
  status: find('status'),
  confidenceValue: find('confidenceValue'),
  confidenceBar: find('confidenceBar'),
  showReport: find('showReport'),
  reportNote: find('reportNote'),
  gaugeFused: find('gaugeFused'),
  streamGrid: find('streamGrid'),
  weightGrid: find('weightGrid'),
  alertPanel: find('alertPanel'),
  alertText: find('alertText'),
  observations: find('observations'),
  timeline: find('timeline'),
  resultsTable: find('resultsTable'),
  securityDetail: find('securityDetail'),
  verify: find('verify'),
  verdict: find('verdict'),
};

const control = { role: 'nurse', scenario: 'rest', level: 6, context: 'conscious_ward' };

let setup = null;
let socket = null;
let cards = {};
let rows = {};
let liveAudit = null;
const trail = [];

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function prepare(canvas, width, height) {
  const ratio = window.devicePixelRatio || 1;
  if (width === null) {
    canvas.style.width = '100%';
    canvas.style.height = height + 'px';
    width = canvas.clientWidth || 600;
  } else {
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
  }
  const pixelWidth = Math.round(width * ratio);
  const pixelHeight = Math.round(height * ratio);
  if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
  if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function arc(ctx, centreX, centreY, radius, fraction, colour, thickness) {
  const start = Math.PI * (5 / 6);
  const sweep = Math.PI * (4 / 3);
  ctx.lineCap = 'round';
  ctx.lineWidth = thickness;
  ctx.strokeStyle = '#1d232c';
  ctx.beginPath();
  ctx.arc(centreX, centreY, radius, start, start + sweep);
  ctx.stroke();
  if (fraction <= 0) return;
  ctx.strokeStyle = colour;
  ctx.beginPath();
  ctx.arc(centreX, centreY, radius, start, start + sweep * Math.min(fraction, 1));
  ctx.stroke();
}

function drawFused(score, status) {
  const { ctx, width, height } = prepare(parts.gaugeFused, 260, 190);
  const centreX = width / 2;
  const centreY = height * 0.68;
  const radius = 86;
  const insufficient = status && status !== 'OK';
  arc(ctx, centreX, centreY, radius, score === null ? 0 : score / 10, '#4ea8de', 15);

  const start = Math.PI * (5 / 6);
  const sweep = Math.PI * (4 / 3);
  ctx.fillStyle = '#5f6b7b';
  ctx.font = '10px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (let step = 0; step <= 10; step += 2) {
    const angle = start + sweep * (step / 10);
    ctx.fillText(
      String(step),
      centreX + Math.cos(angle) * (radius + 17),
      centreY + Math.sin(angle) * (radius + 17)
    );
  }

  if (insufficient) {
    ctx.fillStyle = '#e2574c';
    ctx.font = '600 15px system-ui, sans-serif';
    ctx.fillText('INSUFFICIENT', centreX, centreY - 8);
    ctx.fillText('SIGNAL', centreX, centreY + 11);
    return;
  }
  ctx.fillStyle = '#e6ebf2';
  ctx.font = '600 44px system-ui, sans-serif';
  ctx.fillText(score === null ? '—' : score.toFixed(1), centreX, centreY - 4);
  ctx.fillStyle = '#8e9aab';
  ctx.font = '11px system-ui, sans-serif';
  ctx.fillText('estimated pain / 10', centreX, centreY + 27);
}

function drawStream(canvas, score, colour) {
  const { ctx, width, height } = prepare(canvas, 150, 96);
  const centreX = width / 2;
  const centreY = height * 0.78;
  arc(ctx, centreX, centreY, 54, score === null ? 0 : score / 10, colour, 10);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#e6ebf2';
  ctx.font = '600 24px system-ui, sans-serif';
  ctx.fillText(score === null ? '—' : score.toFixed(1), centreX, centreY - 6);
}

function lampClass(quality) {
  if (quality === null || quality === undefined) return 'lamp';
  if (quality >= 0.7) return 'lamp good';
  if (quality >= 0.35) return 'lamp warn';
  return 'lamp bad';
}

function buildStreams(names) {
  parts.streamGrid.textContent = '';
  cards = {};
  STREAMS.forEach((stream) => {
    const card = element('div', 'stream');
    const head = element('header');
    head.append(element('h3', null, `${stream} · ${names[stream]}`));
    const right = element('span', 'label', '—');
    const lamp = element('span', 'lamp');
    right.append(lamp);
    head.append(right);
    const canvas = element('canvas');
    const quality = element('div', 'meta');
    quality.append(element('span', null, 'quality'), element('span', null, '—'));
    const raw = element('div');
    const reason = element('div', 'reason');
    card.append(head, canvas, quality, raw, reason);
    parts.streamGrid.append(card);
    cards[stream] = {
      canvas,
      lamp,
      contribution: right,
      quality: quality.lastChild,
      raw,
      reason,
    };
  });
}

function buildWeights(names) {
  parts.weightGrid.textContent = '';
  rows = {};
  STREAMS.forEach((stream) => {
    const row = element('div', 'weight-row');
    const name = element('div', 'name');
    const total = element('b', null, '—');
    name.append(element('span', null, `${stream} · ${names[stream]}`), total);
    row.append(name);
    const bars = {};
    LAYER_ROWS.forEach(([key, label]) => {
      const line = element('div', 'layer');
      const track = element('div', 'track');
      const fill = element('i');
      fill.style.background = COLOURS[stream];
      track.append(fill);
      const value = element('span', null, '—');
      line.append(element('span', null, label), track, value);
      row.append(line);
      bars[key] = { fill, value };
    });
    parts.weightGrid.append(row);
    rows[stream] = { total, bars };
  });
}

function buildScenarios(names) {
  parts.scenarios.textContent = '';
  names.forEach((name) => {
    const button = element('button', null, SCENARIO_LABELS[name] || name);
    button.dataset.scenario = name;
    button.addEventListener('click', () => {
      control.scenario = name;
      send();
    });
    parts.scenarios.append(button);
  });
}

function buildContexts(names, current) {
  parts.context.textContent = '';
  names.forEach((name) => {
    const option = element('option', null, CONTEXT_LABELS[name] || name);
    option.value = name;
    parts.context.append(option);
  });
  parts.context.value = current;
  control.context = current;
}

function describeSecurity(status) {
  parts.securityDetail.textContent = '';
  const list = element('dl');
  const add = (term, value) => {
    list.append(element('dt', null, term), element('dd', null, value));
  };
  add('provider', status.provider);
  add('key exchange', status.kem);
  add('data cipher', status.cipher);
  add('signature', status.signature);
  add('encapsulation', `${status.handshake.encapsulation_bytes} bytes`);
  const entries = element('dd', null, `${status.audit_entries}`);
  list.append(element('dt', null, 'audit chain'), entries);
  liveAudit = entries;
  add('consent register', `${status.consented_subjects.length} pseudonymised subjects`);
  parts.securityDetail.append(list);

  const alignment = element('dl');
  Object.entries(status.compliance).forEach(([term, text]) => {
    alignment.append(element('dt', null, term), element('dd', null, text));
  });
  parts.securityDetail.append(element('p', 'hint spaced', 'Alignment with Law No. 18-07'), alignment);

  parts.security.textContent = `${status.kem} · ${status.signature}`;
  parts.security.className = status.post_quantum ? 'badge quantum' : 'badge classical';
  if (status.warning) {
    const strip = element('div', 'warning-strip', status.warning);
    document.querySelector('main').prepend(strip);
  }
}

function robustnessTable(robustness) {
  const table = element('table');
  const head = element('tr');
  ['subgroup', 'windows', 'A', 'B', 'C', 'simple avg', 'fusion', 'refused'].forEach((title) => {
    head.append(element('th', null, title));
  });
  table.append(head);
  Object.entries(robustness).forEach(([name, entry]) => {
    if (entry.hybrid_fusion === undefined) return;
    const row = element('tr', name === 'all test windows' ? 'highlight' : null);
    row.append(element('td', null, name));
    row.append(element('td', null, String(entry.windows)));
    STREAMS.forEach((stream) => row.append(element('td', null, entry[stream].toFixed(2))));
    row.append(element('td', null, entry.simple_average.toFixed(2)));
    const fused = element('td', entry.hybrid_fusion <= entry.simple_average ? 'delta better' : 'delta worse');
    fused.textContent = entry.hybrid_fusion.toFixed(2);
    row.append(fused);
    row.append(element('td', null, String(entry.insufficient_signal)));
    table.append(row);
  });
  table.append(
    element(
      'caption',
      null,
      'Mean absolute error by signal condition, measured on the windows every estimator could score. ' +
        'Refused counts the windows where the remaining weight fell under the floor and the fusion returned ' +
        'INSUFFICIENT SIGNAL instead of a number.'
    )
  );
  return table;
}

function renderResults(results) {
  if (!results) {
    parts.resultsTable.textContent = 'no evaluation yet — run python ai/train.py';
    return;
  }
  const table = element('table');
  const head = element('tr');
  ['estimator', 'MAE', 'RMSE', 'pearson r', 'Δ MAE'].forEach((title) => {
    head.append(element('th', null, title));
  });
  table.append(head);

  const line = (label, entry, delta, highlight) => {
    const row = element('tr', highlight ? 'highlight' : null);
    row.append(element('td', null, label));
    row.append(element('td', null, entry.mae.toFixed(3)));
    row.append(element('td', null, entry.rmse.toFixed(3)));
    row.append(element('td', null, entry.pearson_r.toFixed(3)));
    if (delta === null || delta === undefined) {
      row.append(element('td', null, '—'));
    } else {
      const cell = element('td', `delta ${delta > 0 ? 'worse' : 'better'}`);
      cell.textContent = `${delta > 0 ? '+' : ''}${delta.toFixed(3)}`;
      row.append(cell);
    }
    table.append(row);
  };

  STREAMS.forEach((stream) => {
    line(`stream ${stream} · ${results.streams[stream].name}`, results.streams[stream], null);
  });
  line('simple average', results.simple_average, null);
  line('4-layer hybrid fusion', results.hybrid_fusion, null, true);
  Object.entries(results.ablations).forEach(([key, entry]) => {
    line(ABLATION_LABELS[key] || key, entry, entry.mae_delta);
  });
  line('patient self-report (NRS)', results.self_report_reference, null);

  const caption = element(
    'caption',
    null,
    `Patient-wise split: ${results.split.train_patients} train / ${results.split.test_patients} held-out patients, ` +
      `${results.windows.evaluated} of ${results.windows.test_windows} test windows scored, ` +
      `${results.windows.insufficient_signal} returned INSUFFICIENT SIGNAL. Point estimator ${results.split.model}. ` +
      `Δ MAE is measured against the full fusion, so a positive number means removing that layer made the estimate worse. ` +
      `The self-report row is the reference only and never reaches the model.`
  );
  table.append(caption);
  parts.resultsTable.textContent = '';
  parts.resultsTable.append(table);
  if (results.robustness) {
    parts.resultsTable.append(element('h2', null, 'Robustness by signal condition'));
    parts.resultsTable.append(robustnessTable(results.robustness));
  }
}

function renderTherapy(flags) {
  parts.therapy.textContent = '';
  Object.entries(THERAPY_LABELS).forEach(([key, label]) => {
    parts.therapy.append(element('span', flags[key] ? 'tag on' : 'tag', label));
  });
}

function renderObservations(observations) {
  parts.observations.textContent = '';
  if (!observations) return;
  Object.entries(OBSERVATION_LABELS).forEach(([key, label]) => {
    parts.observations.append(element('span', observations[key] ? 'tag on' : 'tag', label));
  });
}

function renderWeights(quality) {
  STREAMS.forEach((stream) => {
    const row = rows[stream];
    if (!quality) {
      row.total.textContent = '—';
      LAYER_ROWS.forEach(([key]) => {
        row.bars[key].fill.style.width = '0%';
        row.bars[key].value.textContent = '—';
      });
      return;
    }
    row.total.textContent = quality.weights.final[stream].toFixed(3);
    LAYER_ROWS.forEach(([key]) => {
      const weight = quality.weights[key][stream];
      row.bars[key].fill.style.width = `${Math.min(weight / WEIGHT_SCALE, 1) * 100}%`;
      row.bars[key].value.textContent = weight.toFixed(3);
    });
  });
}

function renderStreams(frame) {
  const estimate = frame.estimate;
  const quality = frame.quality;
  STREAMS.forEach((stream) => {
    const card = cards[stream];
    const score = estimate ? estimate.stream_scores[stream] : null;
    drawStream(card.canvas, score, COLOURS[stream]);

    const level = quality ? quality.signal_quality[stream] : null;
    card.lamp.className = lampClass(level);
    card.quality.textContent = level === null ? '—' : level.toFixed(2);

    if (estimate) {
      const entry = estimate.contributing_signals.find((item) => item.stream === stream);
      card.contribution.textContent = entry ? entry.label : '—';
    } else {
      card.contribution.textContent = 'restricted';
    }
    card.contribution.append(card.lamp);

    card.raw.textContent = '';
    if (frame.raw) {
      frame.raw[stream].forEach((item) => {
        const line = element('div', 'meta');
        line.append(element('span', null, item.label), element('span', null, item.value));
        card.raw.append(line);
      });
    }

    const reasons = quality ? quality.attenuation_reasons[stream] : [];
    const coefficient = quality ? quality.attenuation[stream] : null;
    if (reasons && reasons.length) {
      card.reason.textContent = `${reasons.join(', ')} → C = ${coefficient.toFixed(2)}`;
    } else if (coefficient !== null && coefficient < 0.7) {
      card.reason.textContent = `quality limited → C = ${coefficient.toFixed(2)}`;
    } else {
      card.reason.textContent = '';
    }
  });
}

function drawTimeline() {
  const { ctx, width, height } = prepare(parts.timeline, null, 240);
  const left = 34;
  const right = width - 10;
  const top = 14;
  const bottom = height - 22;
  const span = Math.max(right - left, 1);
  const slots = Math.max(Math.min(trail.length, HISTORY), 20);
  const place = (index) => right - (span * (trail.length - 1 - index)) / Math.max(slots - 1, 1);
  const height10 = (value) => bottom - ((bottom - top) * value) / 10;

  ctx.strokeStyle = '#232b36';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#5f6b7b';
  ctx.font = '10px system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let step = 0; step <= 10; step += 2) {
    const y = Math.round(height10(step)) + 0.5;
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
    ctx.fillText(String(step), left - 7, y);
  }

  const series = (key, colour, thickness, dashed) => {
    ctx.strokeStyle = colour;
    ctx.lineWidth = thickness;
    ctx.setLineDash(dashed ? [4, 3] : []);
    let drawing = false;
    ctx.beginPath();
    trail.forEach((point, index) => {
      const value = point[key];
      if (value === null || value === undefined) {
        drawing = false;
        return;
      }
      const x = place(index);
      const y = height10(value);
      if (drawing) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
      drawing = true;
    });
    ctx.stroke();
    ctx.setLineDash([]);
  };

  series('truth', '#55606f', 1.5, false);
  if (parts.showReport.checked) series('nrs', '#b58ce0', 1.5, true);
  series('gps', '#4ea8de', 2, false);

  ctx.fillStyle = '#e2574c';
  trail.forEach((point, index) => {
    if (point.gps === null) ctx.fillRect(place(index) - 1.5, bottom + 4, 3, 5);
  });
}

function renderFrame(frame) {
  const estimate = frame.estimate;
  const score = estimate && estimate.estimated_pain !== null ? estimate.estimated_pain : null;

  drawFused(score, estimate ? estimate.status : 'restricted');

  if (!estimate) {
    parts.status.textContent = `role ${frame.role} may not read pain estimates`;
    parts.status.className = 'status insufficient';
    parts.confidenceValue.textContent = '—';
    parts.confidenceBar.style.width = '0%';
    parts.alertText.textContent = 'confounder analysis is part of the estimate and withheld for this role';
    parts.alertPanel.className = 'panel alert';
    renderObservations(null);
  } else if (estimate.status !== 'OK') {
    parts.status.textContent = `${setup.insufficient} · remaining weight below the floor`;
    parts.status.className = 'status insufficient';
    parts.confidenceValue.textContent = `${estimate.confidence.toFixed(1)}%`;
    parts.confidenceBar.style.width = `${estimate.confidence}%`;
    parts.alertText.textContent = estimate.confounder_alert;
    parts.alertPanel.className = 'panel alert';
    renderObservations(estimate.observations);
  } else {
    const reported = frame.self_report;
    const comparison =
      reported === null
        ? 'no self-report for a sedated subject'
        : `patient self-report ${reported}/10, kept for comparison only`;
    parts.status.textContent = `${SCENARIO_LABELS[frame.scenario] || frame.scenario} · ${
      CONTEXT_LABELS[frame.clinical_context] || frame.clinical_context
    } · ${comparison}`;
    parts.status.className = 'status';
    parts.confidenceValue.textContent = `${estimate.confidence.toFixed(1)}%`;
    parts.confidenceBar.style.width = `${estimate.confidence}%`;
    parts.alertText.textContent = estimate.confounder_alert;
    parts.alertPanel.className = `panel alert ${estimate.confounder_class}`;
    renderObservations(estimate.observations);
  }

  renderStreams(frame);
  renderWeights(frame.quality);
  renderTherapy(frame.therapy);

  const camera = frame.camera;
  const pulse = camera.rppg_bpm ? `, rPPG ${camera.rppg_bpm} bpm` : '';
  parts.camera.textContent = `camera ${camera.state} · ${camera.detail || 'stream C simulated'}${pulse}`;

  const notes = [];
  if (frame.notice) notes.push(frame.notice);
  if (frame.withheld.length) notes.push(`withheld from role ${frame.role}: ${frame.withheld.join(', ')}`);
  notes.push(`patch link ${frame.patch_link.state} · ${frame.patch_link.detail || 'simulated'}`);
  notes.push(`record sealed, ${frame.sealed_bytes} bytes · chain entry ${frame.audit_index} · ${frame.audit_hash}`);
  parts.withheld.textContent = notes.join(' — ');

  if (liveAudit) liveAudit.textContent = `${frame.audit_index + 1} entries, head ${frame.audit_hash}`;

  Array.from(parts.scenarios.children).forEach((button) => {
    button.className = button.dataset.scenario === frame.scenario ? 'active' : '';
  });
  if (parts.context.value !== frame.clinical_context) parts.context.value = frame.clinical_context;

  trail.push({
    gps: score,
    nrs: frame.self_report,
    truth: frame.ground_truth,
  });
  while (trail.length > HISTORY) trail.shift();
  drawTimeline();
}

function send() {
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(control));
}

function greet(message) {
  setup = message;
  buildScenarios(message.scenarios);
  buildContexts(message.contexts, message.context);
  buildStreams(message.stream_names);
  buildWeights(message.stream_names);
  describeSecurity(message.security);
  renderResults(message.results);
  parts.reportNote.textContent =
    `Self-report is recorded beside the estimate for comparison only and is never a model input. ` +
    `Layer mixing ${message.layer_mix.base} base / ${message.layer_mix.statistical} statistical / ${message.layer_mix.ml} ML.`;
  control.scenario = 'rest';
  send();
}

function connect() {
  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  socket = new WebSocket(`${scheme}://${location.host}/ws`);
  socket.addEventListener('open', () => {
    parts.link.textContent = 'live';
    parts.link.className = 'badge live';
  });
  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    if (message.type === 'hello') greet(message);
    else renderFrame(message);
  });
  socket.addEventListener('close', () => {
    parts.link.textContent = 'offline';
    parts.link.className = 'badge offline';
    setTimeout(connect, 2000);
  });
  socket.addEventListener('error', () => socket.close());
}

parts.level.addEventListener('input', () => {
  control.level = Number(parts.level.value);
  parts.levelValue.textContent = parts.level.value;
  send();
});

parts.context.addEventListener('change', () => {
  control.context = parts.context.value;
  send();
});

parts.role.addEventListener('change', () => {
  control.role = parts.role.value;
  send();
});

parts.showReport.addEventListener('change', drawTimeline);

parts.verify.addEventListener('click', async () => {
  parts.verdict.textContent = 'verifying …';
  parts.verdict.className = '';
  try {
    const answer = await fetch(`/api/verify?role=${encodeURIComponent(control.role)}`, { method: 'POST' });
    const body = await answer.json();
    if (!answer.ok) {
      parts.verdict.textContent = body.detail;
      parts.verdict.className = 'broken';
      return;
    }
    parts.verdict.textContent = body.verified
      ? `chain intact · ${body.message}`
      : `chain broken · ${body.message}`;
    parts.verdict.className = body.verified ? 'ok' : 'broken';
  } catch (problem) {
    parts.verdict.textContent = `verification unreachable (${problem.message})`;
    parts.verdict.className = 'broken';
  }
});

window.addEventListener('resize', () => {
  if (trail.length) drawTimeline();
});

parts.levelValue.textContent = parts.level.value;
control.level = Number(parts.level.value);
control.role = parts.role.value;
drawFused(null, 'OK');
drawTimeline();
connect();
