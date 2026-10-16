
const FIELD_CONFIG = {
  temperature: { key: "t2m", min: -60, max: 45, convert: v => v - 273.15 },
  wind: { key: "wind_speed", min: 0, max: 40, convert: v => v },
  pressure: { key: "sp", min: 870, max: 1080, convert: v => v / 100 },
  rainfall: { key: "tp", min: 0, max: 50, convert: v => v * 1000 },
};

const FIELD_ALIASES = {
  t2m: "temperature", temperature: "temperature",
  wind_speed: "wind", wind: "wind", u10: "wind", v10: "wind",
  sp: "pressure", pressure: "pressure",
  tp: "rainfall", rainfall: "rainfall",
};

const EARTH_CIRCUMFERENCE = 40075016.686;

function normalizeFieldName(name) {
  return FIELD_ALIASES[String(name || "temperature").toLowerCase()] || "temperature";
}

function mercatorX(lon) {
  return (lon + 180) / 360;
}

function mercatorY(lat) {
  const r = Math.max(-85.05112878, Math.min(85.05112878, lat)) * Math.PI / 180;
  return (1 - Math.asinh(Math.tan(r)) / Math.PI) / 2;
}

function flattenGrid(value) {
  if (ArrayBuffer.isView(value)) return Array.from(value);
  if (!Array.isArray(value)) return [];
  return value.flat(Infinity);
}

function findArray(objects, keys) {
  for (const obj of objects) {
    if (!obj || typeof obj !== "object") continue;
    for (const key of keys) {
      const value = obj[key];
      if (Array.isArray(value) || ArrayBuffer.isView(value)) return Array.from(value);
    }
  }
  return null;
}

function extractCoordinates(weather, frame) {
  const sources = [weather, frame, weather?.grid, frame?.grid, weather?.metadata];
  const latitudes = findArray(sources, ["latitudes", "latitude", "lats", "lat"]);
  const longitudes = findArray(sources, ["longitudes", "longitude", "lons", "lon"]);

  if (!latitudes || !longitudes || latitudes.length < 2 || longitudes.length < 2) {
    console.error("[NFD] Missing grid coordinates. Expected latitude/longitude arrays.");
    return null;
  }

  const latOrder = latitudes.map((value, index) => ({ value: Number(value), index }))
    .filter(p => Number.isFinite(p.value))
    .sort((a, b) => b.value - a.value);

  const lonOrder = longitudes.map((value, index) => ({ value: Number(value), index }))
    .filter(p => Number.isFinite(p.value))
    .map(p => ({ ...p, value: ((p.value + 180) % 360 + 360) % 360 - 180 }))
    .sort((a, b) => a.value - b.value);

  if (latOrder.length < 2 || lonOrder.length < 2) return null;

  return {
    latitudes: latOrder.map(p => p.value),
    longitudes: lonOrder.map(p => p.value),
    latOrder: latOrder.map(p => p.index),
    lonOrder: lonOrder.map(p => p.index),
    rows: latOrder.length,
    cols: lonOrder.length,
  };
}

function reorderGrid(values, grid) {
  const { rows, cols, latOrder, lonOrder } = grid;
  if (!values || values.length !== rows * cols) {
    console.error("[NFD] Grid dimensions do not match field data", {
      expected: rows * cols,
      received: values?.length ?? 0,
    });
    return null;
  }

  const result = new Float32Array(rows * cols);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      result[r * cols + c] = Number(values[latOrder[r] * cols + lonOrder[c]]);
    }
  }
  return result;
}

function mercatorMesh(grid) {
  const { rows, cols, latitudes, longitudes } = grid;
  const positions = new Float32Array(rows * cols * 4);
  const indices = new Uint32Array((rows - 1) * (cols - 1) * 6);
  let p = 0;
  let k = 0;

  for (let r = 0; r < rows; r++) {
    const y = mercatorY(latitudes[r]);
    for (let c = 0; c < cols; c++) {
      positions[p++] = mercatorX(longitudes[c]);
      positions[p++] = y;
      positions[p++] = c / (cols - 1);
      positions[p++] = r / (rows - 1);
    }
  }

  for (let r = 0; r < rows - 1; r++) {
    for (let c = 0; c < cols - 1; c++) {
      const a = r * cols + c;
      const b = a + 1;
      const d = a + cols;
      const e = d + 1;
      indices.set([a, d, b, b, d, e], k);
      k += 6;
    }
  }
  return { positions, indices, count: indices.length };
}

function compileShader(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);

  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`Shader compilation failed: ${message}`);
  }
  return shader;
}

function createProgram(gl, vertexSource, fragmentSource) {
  const vertex = compileShader(gl, gl.VERTEX_SHADER, vertexSource);
  const fragment = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource);
  const program = gl.createProgram();
  gl.attachShader(program, vertex);
  gl.attachShader(program, fragment);
  gl.linkProgram(program);
  gl.deleteShader(vertex);
  gl.deleteShader(fragment);

  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`Program linking failed: ${message}`);
  }
  return program;
}

const WEATHER_VERTEX = `#version 300 es
precision highp float;
in vec2 a_pos;
in vec2 a_uv;
uniform mat4 u_matrix;
out vec2 v_uv;
void main() {
  v_uv = a_uv;
  gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
}`;


const WEATHER_FRAGMENT = `#version 300 es
precision highp float;
uniform sampler2D u_field;
uniform float u_alpha;
in vec2 v_uv;
out vec4 fragColor;

vec3 ramp(float t) {
  t = clamp(t, 0.0, 1.0);
  if (t < 0.25) return mix(vec3(0.08,0.12,0.65), vec3(0.0,0.75,0.95), t/0.25);
  if (t < 0.50) return mix(vec3(0.0,0.75,0.95), vec3(0.15,0.8,0.25), (t-0.25)/0.25);
  if (t < 0.75) return mix(vec3(0.15,0.8,0.25), vec3(1.0,0.85,0.05), (t-0.50)/0.25);
  return mix(vec3(1.0,0.85,0.05), vec3(0.85,0.05,0.05), (t-0.75)/0.25);
}

void main() {
  vec4 sampleValue = texture(u_field, v_uv);
  if (sampleValue.a < 0.5) discard;
  float alpha = clamp(u_alpha, 0.0, 1.0);
  fragColor = vec4(ramp(sampleValue.r) * alpha, alpha);
}`;


const PARTICLE_VERTEX = `#version 300 es
precision highp float;
in vec2 a_pos;
uniform mat4 u_matrix;
uniform float u_size;
void main() {
  gl_Position = u_matrix * vec4(a_pos, 0.0, 1.0);
  gl_PointSize = u_size;
}`;

const PARTICLE_FRAGMENT = `#version 300 es
precision highp float;
out vec4 fragColor;
void main() {
  vec2 p = gl_PointCoord - vec2(0.5);
  float d = length(p);
  float alpha = 1.0 - smoothstep(0.12, 0.5, d);
  if (alpha < 0.03) discard;
  fragColor = vec4(0.95 * alpha, 0.98 * alpha, 1.0 * alpha, alpha);
}`;

export default class WebGLWeatherLayer {
  constructor(options = {}) {
    this.id = options.id || "nfd-weather-webgl";
    this.type = "custom";
    this.renderingMode = "2d";
    this.layer = normalizeFieldName(options.layer || "temperature");
    this.alpha = options.alpha ?? 0.62;
    this.showWind = options.showWind ?? true;
    this.particleCount = options.particleCount ?? 1500;
    this.frameIndex = 0;
    this.weather = null;
    this.grid = null;
    this.mesh = null;
    this.ready = false;
    this.map = null;
    this.gl = null;
    this.windU = null;
    this.windV = null;
    this.particles = [];
    this.lastParticleTime = 0;
  }

  onAdd(map, gl) {
    this.map = map;
    this.gl = gl;

    try {
      this.weatherProgram = createProgram(gl, WEATHER_VERTEX, WEATHER_FRAGMENT);
      this.particleProgram = createProgram(gl, PARTICLE_VERTEX, PARTICLE_FRAGMENT);

      this.weatherLocations = {
        matrix: gl.getUniformLocation(this.weatherProgram, "u_matrix"),
        field: gl.getUniformLocation(this.weatherProgram, "u_field"),
        alpha: gl.getUniformLocation(this.weatherProgram, "u_alpha"),
        pos: gl.getAttribLocation(this.weatherProgram, "a_pos"),
        uv: gl.getAttribLocation(this.weatherProgram, "a_uv"),
      };

      this.particleLocations = {
        matrix: gl.getUniformLocation(this.particleProgram, "u_matrix"),
        size: gl.getUniformLocation(this.particleProgram, "u_size"),
        pos: gl.getAttribLocation(this.particleProgram, "a_pos"),
      };

      this.positionBuffer = gl.createBuffer();
      this.indexBuffer = gl.createBuffer();
      this.particleBuffer = gl.createBuffer();
      this.texture = gl.createTexture();

      gl.bindTexture(gl.TEXTURE_2D, this.texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE,
        new Uint8Array([0, 0, 0, 0]));

      this.ready = true;
      if (this.weather) {
        this.uploadMesh();
        this.uploadField();
      }
    } catch (error) {
      this.ready = false;
      console.error("[NFD] WebGL layer initialization failed:", error);
    }
  }

  getFrames() {
    if (Array.isArray(this.weather?.frames)) return this.weather.frames;
    if (Array.isArray(this.weather?.data?.frames)) return this.weather.data.frames;
    if (Array.isArray(this.weather)) return this.weather;
    return this.weather ? [this.weather] : [];
  }

  currentFrame() {
    const frames = this.getFrames();
    return frames[Math.max(0, Math.min(this.frameIndex, frames.length - 1))] || null;
  }

  setState({ weather, layer, frameIndex, showWind, alpha } = {}) {
    const nextLayer = layer ? normalizeFieldName(layer) : this.layer;
    const nextFrameIndex = Number.isInteger(frameIndex) ? Math.max(0, frameIndex) : this.frameIndex;
    const gridChanged = weather !== undefined && weather !== this.weather;
    const fieldChanged = gridChanged || nextLayer !== this.layer || nextFrameIndex !== this.frameIndex;

    
    if (gridChanged) {
      this.weather = weather;
      const frame = this.currentFrame();

      this.grid = weather ? extractCoordinates(weather, frame) : null;
      this.mesh = this.grid ? mercatorMesh(this.grid) : null;

      console.log("[NFD] Mesh properties", {
        keys: Object.keys(this.mesh || {}),
        positionsLength: this.mesh?.positions?.length,
        indicesLength: this.mesh?.indices?.length,
        count: this.mesh?.count,
      });

        console.log("[NFD] Mesh creation", {
          hasWeather: !!weather,
          hasGrid: !!this.grid,
          gridRows: this.grid?.rows,
          gridCols: this.grid?.cols,
          meshType: typeof this.mesh,
          meshKeys: this.mesh ? Object.keys(this.mesh) : null,
          positionsLength: this.mesh?.positions?.length,
          indicesLength: this.mesh?.indices?.length,
          indexCount: this.mesh?.count,
        });

      this.createParticles();
      this.windU = null;
      this.windV = null;
      this.uploadMesh();
    }

    this.layer = nextLayer;
    this.frameIndex = nextFrameIndex;
    if (typeof showWind === "boolean") this.showWind = showWind;
    if (Number.isFinite(alpha)) this.alpha = Math.max(0, Math.min(1, alpha));

    if (fieldChanged && this.ready) {
      this.uploadMesh();
      this.uploadField();
    }
    this.map?.triggerRepaint();
  }

  getField(name) {
    const frame = this.currentFrame();
    const config = FIELD_CONFIG[name];
    if (!frame || !config || !this.grid) return null;

    let raw = frame[config.key] ?? frame.fields?.[config.key] ?? frame.variables?.[config.key];

    if (name === "wind" && raw == null) {
      const u = flattenGrid(frame.u10 ?? frame.fields?.u10 ?? frame.variables?.u10);
      const v = flattenGrid(frame.v10 ?? frame.fields?.v10 ?? frame.variables?.v10);
      if (u.length && u.length === v.length) raw = u.map((value, i) => Math.hypot(Number(value), Number(v[i])));
    }

    const values = flattenGrid(raw);
    const reordered = reorderGrid(values, this.grid);
    if (!reordered) return null;

    const converted = new Float32Array(reordered.length);
    for (let i = 0; i < reordered.length; i++) {
      const value = reordered[i];
      converted[i] = Number.isFinite(value) ? config.convert(value) : NaN;
    }
    return converted;
  }

  uploadMesh() {
  const gl = this.gl;
  if (!this.ready || !this.mesh || !gl) return;

  gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, this.mesh.positions, gl.STATIC_DRAW);

  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.mesh.indices, gl.STATIC_DRAW);
}

  uploadField() {
    const gl = this.gl;
    if (!this.ready || !this.grid || !gl) return;

    const values = this.getField(this.layer);
    if (!values) {
      console.warn("[NFD] Could not load weather field:", this.layer);
      return;
    }

    const config = FIELD_CONFIG[this.layer];
    const rgba = new Uint8Array(values.length * 4);
    let validCount = 0;
    let minValue = Infinity;
    let maxValue = -Infinity;

    for (let i = 0; i < values.length; i++) {
      const value = values[i];
      const offset = i * 4;
      if (!Number.isFinite(value)) {
        rgba[offset + 3] = 0;
        continue;
      }
      const t = Math.max(0, Math.min(1, (value - config.min) / (config.max - config.min)));
      rgba[offset] = Math.round(t * 255);
      rgba[offset + 1] = 0;
      rgba[offset + 2] = 0;
      rgba[offset + 3] = 255;
      minValue = Math.min(minValue, value);
      maxValue = Math.max(maxValue, value);
      validCount++;
    }

    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, this.grid.cols, this.grid.rows, 0,
      gl.RGBA, gl.UNSIGNED_BYTE, rgba);

    this.updateParticleWinds();

    console.info("[NFD] Uploaded weather field", {
      layer: this.layer,
      frameIndex: this.frameIndex,
      dimensions: `${this.grid.rows}x${this.grid.cols}`,
      validCount,
      totalCount: values.length,
      minValue: validCount ? minValue : null,
      maxValue: validCount ? maxValue : null,
      textureError: gl.getError(),
    });
  }

  updateParticleWinds() {
    const frame = this.currentFrame();
    if (!frame || !this.grid) return;

    const u = flattenGrid(frame.u10 ?? frame.fields?.u10 ?? frame.variables?.u10);
    const v = flattenGrid(frame.v10 ?? frame.fields?.v10 ?? frame.variables?.v10);
    this.windU = u.length ? reorderGrid(u, this.grid) : null;
    this.windV = v.length ? reorderGrid(v, this.grid) : null;
  }

  createParticles() {
    this.particles = Array.from({ length: this.particleCount }, () => ({
      x: Math.random(),
      y: 0.05 + Math.random() * 0.9,
    }));
  }

  sampleWind(x, y) {
    if (!this.grid || !this.windU || !this.windV) return null;
    const { rows, cols, latitudes, longitudes } = this.grid;
    const lon = x * 360 - 180;
    const lat = Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180 / Math.PI;

    let row = 0, col = 0, bestLat = Infinity, bestLon = Infinity;
    for (let r = 0; r < rows; r++) {
      const d = Math.abs(latitudes[r] - lat);
      if (d < bestLat) { bestLat = d; row = r; }
    }
    for (let c = 0; c < cols; c++) {
      const d = Math.abs(longitudes[c] - lon);
      if (d < bestLon) { bestLon = d; col = c; }
    }

    const index = row * cols + col;
    const u = this.windU[index], v = this.windV[index];
    return Number.isFinite(u) && Number.isFinite(v) ? { u, v, lat } : null;
  }

  renderParticles(gl, matrix, deltaSeconds) {
    if (!this.showWind || !this.particles.length || !this.windU || !this.windV) return;

    const positions = new Float32Array(this.particles.length * 2);
    const dt = Math.min(deltaSeconds, 0.05);

    for (let i = 0; i < this.particles.length; i++) {
      const p = this.particles[i];
      const wind = this.sampleWind(p.x, p.y);

      if (wind) {
        const cosLat = Math.max(0.15, Math.cos(wind.lat * Math.PI / 180));
        p.x = (p.x + wind.u * dt / (EARTH_CIRCUMFERENCE * cosLat) + 1) % 1;
        p.y = Math.max(0.001, Math.min(0.999,
          p.y - wind.v * dt / (EARTH_CIRCUMFERENCE * cosLat)));
      }

      if (!wind || Math.random() < 0.002) {
        p.x = Math.random();
        p.y = 0.05 + Math.random() * 0.9;
      }

      positions[i * 2] = p.x;
      positions[i * 2 + 1] = p.y;
    }

    gl.useProgram(this.particleProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.particleBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(this.particleLocations.pos);
    gl.vertexAttribPointer(this.particleLocations.pos, 2, gl.FLOAT, false, 0, 0);
    gl.uniformMatrix4fv(this.particleLocations.matrix, false, matrix);
    gl.uniform1f(this.particleLocations.size, 2.0);
    gl.drawArrays(gl.POINTS, 0, this.particles.length);
  }

  
  render(gl, { modelViewProjectionMatrix } = {}) {
    if (!gl || !this.ready || !this.mesh || !this.weather || !modelViewProjectionMatrix) return;
    if (modelViewProjectionMatrix.length !== 16) return;

    const w = this.mesh.positions?.length / 4;
    const count = this.mesh.count;
    if (!w || !count || !this.positionBuffer || !this.indexBuffer || !this.texture) {
      console.error("[NFD] Invalid render resources", {
        vertices: w,
        indexCount: count,
        positionBuffer: !!this.positionBuffer,
        indexBuffer: !!this.indexBuffer,
        texture: !!this.texture,
      });
      return;
    }

    // Check for shader or attribute setup problems.
    const loc = this.weatherLocations;
    if (!loc || loc.pos < 0 || loc.uv < 0 || !this.weatherProgram) {
      console.error("[NFD] Invalid shader locations", {
        locations: loc,
        programReady: !!this.weatherProgram,
      });
      return;
    }

    // Clear old errors so the next error is associated with this draw.
    let error;
    while ((error = gl.getError()) !== gl.NO_ERROR) {
      console.warn("[NFD] Previous WebGL error:", error);
    }

    gl.disable(gl.CULL_FACE);
    gl.disable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendEquation(gl.FUNC_ADD);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

    gl.useProgram(this.weatherProgram);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.positionBuffer);
    gl.enableVertexAttribArray(loc.pos);
    gl.vertexAttribPointer(loc.pos, 2, gl.FLOAT, false, 16, 0);
    gl.enableVertexAttribArray(loc.uv);
    gl.vertexAttribPointer(loc.uv, 2, gl.FLOAT, false, 16, 8);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);

    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.texture);
    gl.uniform1i(loc.field, 0);
    gl.uniform1f(loc.alpha, this.alpha);
    gl.uniformMatrix4fv(loc.matrix, false, modelViewProjectionMatrix);

    const beforeDraw = gl.getError();
    gl.drawElements(gl.TRIANGLES, count, gl.UNSIGNED_INT, 0);
    const afterDraw = gl.getError();

    if (!this._drawLogged) {
      this._drawLogged = true;
      console.log("[NFD] Draw diagnostics", {
        vertices: w,
        indexCount: count,
        positionAttribute: loc.pos,
        uvAttribute: loc.uv,
        matrixLength: modelViewProjectionMatrix.length,
        alpha: this.alpha,
        beforeDraw,
        afterDraw,
        glVersion: gl.getParameter(gl.VERSION),
        maxViewport: gl.getParameter(gl.MAX_VIEWPORT_DIMS),
      });
    }

    const now = performance.now();
    const deltaSeconds = this.lastParticleTime
      ? Math.min((now - this.lastParticleTime) / 1000, 0.05)
      : 0;
    this.lastParticleTime = now;

    this.renderParticles(gl, modelViewProjectionMatrix, deltaSeconds);

    if (this.showWind && this.windU && this.windV) {
      this.map?.triggerRepaint();
    }
  }


  onRemove() {
    const gl = this.gl;
    if (gl) {
      [this.positionBuffer, this.indexBuffer, this.particleBuffer].forEach(buffer => {
        if (buffer) gl.deleteBuffer(buffer);
      });
      if (this.texture) gl.deleteTexture(this.texture);
      if (this.weatherProgram) gl.deleteProgram(this.weatherProgram);
      if (this.particleProgram) gl.deleteProgram(this.particleProgram);
    }

    this.map = null;
    this.gl = null;
    this.ready = false;
    this.mesh = null;
    this.grid = null;
    this.texture = null;
    this.weatherProgram = null;
    this.particleProgram = null;
    this.windU = this.windV = null;
  }
}
