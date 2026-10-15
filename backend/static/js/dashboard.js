/* ============================================================
   Smart Traffic Incident Review Dashboard – JavaScript
   PC122 Project • Group 36
   ============================================================ */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Health check poll
  const apiStatusEl = document.getElementById('api-status');
  async function checkApiHealth() {
    try {
      const res = await fetch('/health');
      if (res.ok) {
        const data = await res.json();
        apiStatusEl.textContent = `🟢 API Online (v${data.version})`;
        apiStatusEl.style.color = 'var(--color-success)';
      } else {
        apiStatusEl.textContent = '🟡 Degraded';
        apiStatusEl.style.color = 'var(--color-warning)';
      }
    } catch {
      apiStatusEl.textContent = '🔴 Offline';
      apiStatusEl.style.color = 'var(--color-danger)';
    }
  }
  checkApiHealth();
  setInterval(checkApiHealth, 6000);

  // 2. Seed Demo Vehicles
  const seedBtn = document.getElementById('seed-demo-btn');
  seedBtn.addEventListener('click', async () => {
    seedBtn.disabled = true;
    seedBtn.textContent = 'Seeding…';
    try {
      const res = await fetch('/api/v1/vehicles/seed-demo', { method: 'POST' });
      const data = await res.json();
      alert(data.message || 'Demo student vehicles seeded successfully!');
      window.location.reload();
    } catch (err) {
      alert(`Error seeding demo data: ${err.message}`);
    } finally {
      seedBtn.disabled = false;
      seedBtn.textContent = '🌱 Seed Demo Vehicles';
    }
  });

  // 3. Register Vehicle Form
  const regForm = document.getElementById('register-vehicle-form');
  const regFeedback = document.getElementById('reg-feedback');
  regForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    regFeedback.textContent = 'Saving vehicle…';
    regFeedback.style.color = 'var(--color-accent)';

    const payload = {
      student_id: document.getElementById('reg-sid').value.trim(),
      student_name: document.getElementById('reg-name').value.trim(),
      email: document.getElementById('reg-email').value.trim(),
      plate_number: document.getElementById('reg-plate').value.trim().toUpperCase(),
      department: document.getElementById('reg-dept').value.trim() || null,
      phone: document.getElementById('reg-phone').value.trim() || null,
    };

    try {
      const res = await fetch('/api/v1/vehicles/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        regFeedback.textContent = `✅ Registered ${payload.plate_number} for ${payload.student_name}!`;
        regFeedback.style.color = 'var(--color-success)';
        regForm.reset();
        setTimeout(() => window.location.reload(), 1200);
      } else {
        const err = await res.json();
        regFeedback.textContent = `❌ ${err.detail || 'Registration failed'}`;
        regFeedback.style.color = 'var(--color-danger)';
      }
    } catch (err) {
      regFeedback.textContent = `❌ Error: ${err.message}`;
      regFeedback.style.color = 'var(--color-danger)';
    }
  });

  // 4. Simulate Sensor Event & Upload
  const simForm = document.getElementById('simulate-form');
  const simBtn = document.getElementById('simulate-btn');
  const simContainer = document.getElementById('sim-result-container');
  const simResult = document.getElementById('sim-result');
  const simPreview = document.getElementById('sim-preview');

  simForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('image-input');
    const plateInput = document.getElementById('test-plate-input');
    const sensorInput = document.getElementById('sensor-data-input');

    if (!fileInput.files.length) return;

    simBtn.disabled = true;
    simBtn.textContent = 'Processing Event & Running OCR…';
    simContainer.style.display = 'block';
    simResult.textContent = 'Registering event...\nUploading frame...\nExtracting license plate characters...\nMatching vehicle database...';
    simPreview.innerHTML = '';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    if (plateInput.value.trim()) {
      formData.append('test_plate', plateInput.value.trim().toUpperCase());
    }
    if (sensorInput.value.trim()) {
      formData.append('sensor_info', sensorInput.value.trim());
    }

    try {
      const res = await fetch('/api/v1/events/simulate', {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      if (res.ok) {
        simResult.textContent = JSON.stringify(data, null, 2);
        if (data.images && data.images.length > 0) {
          const img = data.images[0];
          simPreview.innerHTML = `
            <p style="font-size: 0.8rem; color: var(--color-muted); margin-bottom: 4px;">Annotated Capture Proof:</p>
            <img src="${img.annotated_path || img.image_path}" alt="Capture Proof" />
          `;
        }
        setTimeout(() => window.location.reload(), 2500);
      } else {
        simResult.textContent = `Error: ${data.detail || 'Simulation failed'}`;
        simResult.style.color = 'var(--color-danger)';
      }
    } catch (err) {
      simResult.textContent = `Error: ${err.message}`;
      simResult.style.color = 'var(--color-danger)';
    } finally {
      simBtn.disabled = false;
      simBtn.textContent = 'Submit Event & Process Frame';
    }
  });

  // 5. Human Review Actions (Confirm / Reject)
  document.querySelectorAll('.review-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const eventId = btn.dataset.eventId;
      const action = btn.dataset.action;
      const recognizedPlate = btn.dataset.plate || '';

      let confirmedPlate = recognizedPlate;
      if (action === 'confirm') {
        const input = prompt(
          `Confirm incident for event ${eventId}.\nVerify or correct the vehicle plate:`,
          recognizedPlate || 'GJ01AB1234'
        );
        if (input === null) return; // User cancelled
        confirmedPlate = input.trim().toUpperCase();
        if (!confirmedPlate) {
          alert('Plate number cannot be empty when confirming.');
          return;
        }
      } else {
        if (!confirm(`Are you sure you want to dismiss event ${eventId}?`)) return;
      }

      btn.disabled = true;
      btn.textContent = '…';

      try {
        const res = await fetch(`/api/v1/events/${eventId}/review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: action,
            confirmed_plate: confirmedPlate,
            reviewer_name: 'Campus Review Officer',
            notes: action === 'confirm' ? 'Confirmed by officer on dashboard' : 'Dismissed as false positive',
          }),
        });

        if (res.ok) {
          window.location.reload();
        } else {
          const err = await res.json();
          alert(`Review failed: ${err.detail || 'Unknown error'}`);
          btn.disabled = false;
          btn.textContent = action === 'confirm' ? 'Confirm' : 'Reject';
        }
      } catch (err) {
        alert(`Network error: ${err.message}`);
        btn.disabled = false;
        btn.textContent = action === 'confirm' ? 'Confirm' : 'Reject';
      }
    });
  });
});
