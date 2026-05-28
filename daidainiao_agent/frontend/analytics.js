const ANALYTICS_KEY = "daidainiao-agent-analytics";

function readAnalytics() {
  try {
    return JSON.parse(window.localStorage.getItem(ANALYTICS_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function writeAnalytics(data) {
  try {
    window.localStorage.setItem(ANALYTICS_KEY, JSON.stringify(data));
  } catch {
    // ignore
  }
}

export function trackEvent(name, detail = {}) {
  const data = readAnalytics();
  const bucket = data[name] || { count: 0, last_at: null, samples: [] };
  bucket.count += 1;
  bucket.last_at = new Date().toISOString();
  if (detail && Object.keys(detail).length) {
    bucket.samples = [...(bucket.samples || []), detail].slice(-20);
  }
  data[name] = bucket;
  writeAnalytics(data);
}

export function getAnalyticsSummary() {
  return readAnalytics();
}
