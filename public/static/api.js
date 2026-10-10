export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const query = params => {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== "" && value != null) search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
};

const API_BASE = (typeof window !== "undefined" && window.__API_BASE__ ? window.__API_BASE__ : "").replace(/\/$/, "");

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}/api${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    let message = data.detail || "The request could not be completed.";
    if (Array.isArray(message)) message = message.map(i => i.msg).join("; ");
    throw new ApiError(message, response.status);
  }
  return data;
}

const post = (path, data = {}) =>
  request(path, { method: "POST", body: JSON.stringify(data) });
const patch = (path, data) =>
  request(path, { method: "PATCH", body: JSON.stringify(data) });

export const api = {
  login: data => post("/auth/login", data),
  logout: () => post("/auth/logout"),
  me: () => request("/auth/me"),
  doctors: () => request("/doctors"),
  dashboard: () => request("/dashboard"),

  patients: () => request("/patients"),
  patient: (id, poll = false) => request(`/patients/${id}${poll ? "?poll=1" : ""}`),
  createPatient: data => post("/patients", data),
  updatePatient: (id, data) => patch(`/patients/${id}`, data),
  addAppointment: (id, data) => post(`/patients/${id}/appointments`, data),

  followUps: params => request(`/follow-ups${query(params)}`),
  followUp: id => request(`/follow-ups/${id}`),
  createFollowUp: data => post("/follow-ups", data),
  updateFollowUp: (id, data) => patch(`/follow-ups/${id}`, data),

  requests: () => request("/reschedule-requests"),
  approve: id => post(`/reschedule-requests/${id}/approve`),
  reject: id => post(`/reschedule-requests/${id}/reject`),

  messages: () => request("/messages"),
  calendar: params => request(`/calendar${query(params)}`),
  activity: () => request("/activity"),

  remindersPreview: data => post("/reminders/preview", data),
  remindersSend: data => post("/reminders/send", data),
};
