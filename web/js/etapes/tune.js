// Formules du réglage fin (P8F), copie exacte de app/color_ops.py:tune, pour l'aperçu en direct.
// Aucune dépendance : testé hors navigateur contre la version Python (tests/test_tune_js.py).

export function hueMatrix(deg) {
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), k = 1 / 3, q = Math.sqrt(k);
  return [c + (1 - c) * k, k * (1 - c) - q * s, k * (1 - c) + q * s,
          k * (1 - c) + q * s, c + k * (1 - c), k * (1 - c) - q * s,
          k * (1 - c) - q * s, k * (1 - c) + q * s, c + k * (1 - c)];
}

const TONE_SH = 0.25, TONE_HL = 0.20, CLARTE_SIGMA = 0.012;     // comme app/color_ops.py

export function toneCurve(L, om, hl) {
  L = L < 0 ? 0 : L > 1 ? 1 : L;
  const s1 = L * (1 - L) * (1 - L) * 6.75, s2 = L * L * L * (1 - L) * (256 / 27);
  const v = L + TONE_SH * om * s1 - TONE_HL * hl * s2;
  return v < 0 ? 0 : v > 1 ? 1 : v;
}

export function boxRadius(width) {
  const sig = CLARTE_SIGMA * width, w = Math.sqrt(12 * sig * sig / 3 + 1);
  return Math.max(1, Math.round((w - 1) / 2));
}

// trois passes de moyenne glissante horizontale puis verticale, bords répétés (= color_ops.box_blur3)
export function boxBlur3(src, w, h, r) {
  let a = Float32Array.from(src), b = new Float32Array(src.length);
  const n = 2 * r + 1;
  const pass = (inp, out, len, count, stride, step) => {
    for (let k = 0; k < count; k++) {
      const o = k * stride;
      let acc = 0;
      for (let j = -r; j <= r; j++) acc += inp[o + Math.min(Math.max(j, 0), len - 1) * step];
      for (let i = 0; i < len; i++) {
        out[o + i * step] = acc / n;
        acc += inp[o + Math.min(i + r + 1, len - 1) * step] - inp[o + Math.max(i - r, 0) * step];
      }
    }
  };
  for (let it = 0; it < 3; it++) {
    pass(a, b, w, h, w, 1); [a, b] = [b, a];
    pass(a, b, h, w, 1, w); [a, b] = [b, a];
  }
  return a;
}

export function liveTune(prm, sky, base, stars, out, original, width = 0) {
  const t = +prm.temperature || 0, m = +prm.teinte || 0, rot = +prm.rotation || 0;
  const sat = +prm.saturation || 0, vib = +prm.vibrance || 0, gam = Math.max(+prm.luminosite || 1, 0.05), nb = +prm.noirs || 0;
  const sr = +prm.sat_rouge || 0, sb = +prm.sat_bleu || 0, om = +prm.ombres || 0, hl = +prm.hautes_lumieres || 0, ct = +prm.clarte || 0;
  const prot = prm.proteger_fond !== false, M = rot ? hueMatrix(rot) : null;
  const N = 2048, lut = new Float32Array(N + 1);
  for (let i = 0; i <= N; i++) lut[i] = Math.pow(i / N, 1 / gam);
  const cl = (v) => v < 0 ? 0 : v > 1 ? 1 : v;
  const pw = (v) => { v = cl(v) * N; const i = v | 0; return i >= N ? lut[N] : lut[i] + (lut[i + 1] - lut[i]) * (v - i); };
  const n = base.length / 4;
  const Y = original ? null : new Float32Array(n * 3), W = new Float32Array(n);
  for (let p = 0, i = 0; p < n; p++, i += 4) {
    const r0 = base[i] / 255, g0 = base[i + 1] / 255, b0 = base[i + 2] / 255;
    let w = cl(((r0 + g0 + b0) / 3 - sky) / 0.25); W[p] = w * w * (3 - 2 * w);
    if (original) continue;
    let r = r0 * (1 + 0.12 * t), g = g0 * (1 - 0.10 * m), b = b0 * (1 - 0.12 * t);
    if (M) { const R = M[0] * r + M[1] * g + M[2] * b, G = M[3] * r + M[4] * g + M[5] * b, B = M[6] * r + M[7] * g + M[8] * b; r = R; g = G; b = B; }
    const L = (r + g + b) / 3, mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    const sn = cl((mx - mn) / Math.max(mx, 1e-6));
    let f = (1 + sat) * (1 + vib * (1 - sn));
    if (sr || sb) {
      const ch = Math.max(mx - mn, 1e-6);
      f *= Math.max(1 + sr * cl((r - (g + b) / 2) / ch) + sb * cl(((g + b) / 2 - r) / ch), 0);
    }
    r = pw(L + f * (r - L)); g = pw(L + f * (g - L)); b = pw(L + f * (b - L));
    if (nb) { r = cl((r - nb) / (1 - nb)); g = cl((g - nb) / (1 - nb)); b = cl((b - nb) / (1 - nb)); }
    Y[3 * p] = cl(r); Y[3 * p + 1] = cl(g); Y[3 * p + 2] = cl(b);
  }
  let det = null;
  if (!original && ct) {                      // contraste local : détail de la luminance, objet seul
    const w = width || Math.round(Math.sqrt(n * 1.5)), h = n / w;
    const L2 = new Float32Array(n);
    for (let p = 0; p < n; p++) L2[p] = (Y[3 * p] + Y[3 * p + 1] + Y[3 * p + 2]) / 3;
    const bl = boxBlur3(L2, w, h, boxRadius(w));
    det = new Float32Array(n);
    for (let p = 0; p < n; p++) det[p] = 1.5 * ct * (L2[p] - bl[p]) * W[p];
  }
  for (let p = 0, i = 0; p < n; p++, i += 4) {
    const r0 = base[i] / 255, g0 = base[i + 1] / 255, b0 = base[i + 2] / 255;
    let r = r0, g = g0, b = b0;
    if (!original) {
      r = Y[3 * p]; g = Y[3 * p + 1]; b = Y[3 * p + 2];
      if (det) { r = cl(r + det[p]); g = cl(g + det[p]); b = cl(b + det[p]); }
      if (prot) { const w = W[p]; r = r0 * (1 - w) + r * w; g = g0 * (1 - w) + g * w; b = b0 * (1 - w) + b * w; }
      if (om || hl) {                         // courbe comptée depuis le niveau du ciel (= color_ops.tune)
        const L1 = (r + g + b) / 3;
        if (L1 > sky) {
          const u = cl((L1 - sky) / Math.max(1 - sky, 1e-6)), k = (sky + toneCurve(u, om, hl) * (1 - sky)) / Math.max(L1, 1e-6);
          r = cl(r * k); g = cl(g * k); b = cl(b * k);
        }
      }
    }
    if (stars) {
      r = 1 - (1 - cl(r)) * (1 - stars[i] / 255); g = 1 - (1 - cl(g)) * (1 - stars[i + 1] / 255); b = 1 - (1 - cl(b)) * (1 - stars[i + 2] / 255);
    }
    out[i] = cl(r) * 255 + 0.5; out[i + 1] = cl(g) * 255 + 0.5; out[i + 2] = cl(b) * 255 + 0.5; out[i + 3] = 255;
  }
}

