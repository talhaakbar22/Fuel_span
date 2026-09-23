(() => {
  const form = document.getElementById("route-form");
  const startInput = document.getElementById("start");
  const finishInput = document.getElementById("finish");
  const submitBtn = document.getElementById("submit-btn");
  const goLabel = submitBtn.querySelector(".go-label");
  const goWait = submitBtn.querySelector(".go-wait");
  const errorEl = document.getElementById("form-error");
  const mapHint = document.getElementById("map-hint");
  const results = document.getElementById("results");
  const stopsList = document.getElementById("stops-list");
  const stopsSub = document.getElementById("stops-sub");

  const map = L.map("map", {
    zoomControl: true,
    attributionControl: true,
  }).setView([39.5, -98.35], 4);

  // Public OSM/Carto tile CDNs block or require keys; Esri World Street Map works without one.
  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    {
      maxZoom: 19,
      attribution:
        "Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom",
    }
  ).addTo(map);

  let routeLayer = null;
  let markerLayer = null;

  function setLoading(on) {
    submitBtn.disabled = on;
    goLabel.hidden = on;
    goWait.hidden = !on;
  }

  function showError(message) {
    errorEl.hidden = !message;
    errorEl.textContent = message || "";
  }

  function formatDuration(seconds) {
    const total = Math.round(Number(seconds) || 0);
    const h = Math.floor(total / 3600);
    const m = Math.round((total % 3600) / 60);
    if (h <= 0) return `${m} min`;
    return `${h} hr ${m} min`;
  }

  function money(n) {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(n);
  }

  function pinIcon(kind, label) {
    return L.divIcon({
      className: `pin pin-${kind}`,
      html: `<span><em>${label}</em></span>`,
      iconSize: [28, 28],
      iconAnchor: [14, 28],
      popupAnchor: [0, -24],
    });
  }

  function clearMapLayers() {
    if (routeLayer) {
      map.removeLayer(routeLayer);
      routeLayer = null;
    }
    if (markerLayer) {
      map.removeLayer(markerLayer);
      markerLayer = null;
    }
  }

  function renderMap(data) {
    clearMapLayers();
    mapHint.classList.add("is-hidden");

    const latLngs = (data.route.geometry.coordinates || []).map(([lng, lat]) => [lat, lng]);
    routeLayer = L.polyline(latLngs, {
      color: "#1f6b5c",
      weight: 5,
      opacity: 0.9,
    }).addTo(map);

    markerLayer = L.layerGroup().addTo(map);

    L.marker([data.start.latitude, data.start.longitude], {
      icon: pinIcon("start", "A"),
    })
      .bindPopup(`<strong>Start</strong><br>${data.start.display_name}`)
      .addTo(markerLayer);

    L.marker([data.finish.latitude, data.finish.longitude], {
      icon: pinIcon("finish", "B"),
    })
      .bindPopup(`<strong>Finish</strong><br>${data.finish.display_name}`)
      .addTo(markerLayer);

    data.fuel_stops.forEach((stop, i) => {
      if (stop.latitude == null || stop.longitude == null) return;
      L.marker([stop.latitude, stop.longitude], {
        icon: pinIcon("fuel", String(i + 1)),
      })
        .bindPopup(
          `<strong>${stop.name}</strong><br>` +
            `${stop.city}, ${stop.state}<br>` +
            `$${Number(stop.price_per_gallon).toFixed(3)}/gal · ${money(stop.cost)}`
        )
        .addTo(markerLayer);
    });

    const bounds = routeLayer.getBounds();
    if (bounds.isValid()) {
      map.fitBounds(bounds, { padding: [36, 36] });
    }
    setTimeout(() => map.invalidateSize(), 50);
  }

  function renderResults(data) {
    results.hidden = false;
    results.classList.add("is-visible");

    document.getElementById("metric-distance").textContent =
      `${Number(data.route.distance_miles).toLocaleString("en-US", { maximumFractionDigits: 1 })} mi`;
    document.getElementById("metric-duration").textContent =
      formatDuration(data.route.duration_seconds);
    document.getElementById("metric-cost").textContent =
      money(data.total_fuel_cost);

    const stops = data.fuel_stops || [];
    if (!stops.length) {
      stopsSub.textContent = "No refuel needed — destination is within vehicle range.";
      stopsList.innerHTML = `<li class="stop-empty">Starting tank covers this trip.</li>`;
      return;
    }

    stopsSub.textContent = `${stops.length} stop${stops.length === 1 ? "" : "s"} · ${Number(data.total_gallons).toFixed(1)} gal purchased on-route`;
    stopsList.innerHTML = stops
      .map(
        (stop, i) => `
      <li class="stop" style="animation-delay:${0.05 * i}s">
        <span class="stop-index">${i + 1}</span>
        <div>
          <p class="stop-name">${stop.name}</p>
          <p class="stop-meta">${stop.city}, ${stop.state} · mile ${Number(stop.miles_along_route).toFixed(0)} · $${Number(stop.price_per_gallon).toFixed(3)}/gal · ${Number(stop.gallons).toFixed(1)} gal</p>
        </div>
        <p class="stop-cost">${money(stop.cost)}</p>
      </li>`
      )
      .join("");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError("");
    setLoading(true);

    const start = startInput.value.trim();
    const finish = finishInput.value.trim();
    const url = `/api/route/?start=${encodeURIComponent(start)}&finish=${encodeURIComponent(finish)}`;

    try {
      const response = await fetch(url);
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.error || "Could not plan this route.");
      }
      renderMap(data);
      renderResults(data);
      results.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      showError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  });

  function attachPlacesAutocomplete(input) {
    const autocomplete = new google.maps.places.Autocomplete(input, {
      componentRestrictions: { country: "us" },
      fields: ["formatted_address", "name"],
      types: ["(cities)"],
    });
    autocomplete.addListener("place_changed", () => {
      const place = autocomplete.getPlace();
      if (place.formatted_address) {
        input.value = place.formatted_address;
      } else if (place.name) {
        input.value = place.name;
      }
    });
  }

  window.initGooglePlaces = () => {
    if (!window.google?.maps?.places) return;
    attachPlacesAutocomplete(startInput);
    attachPlacesAutocomplete(finishInput);
  };

  if (window.google?.maps?.places) {
    window.initGooglePlaces();
  }
})();
