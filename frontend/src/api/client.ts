import axios from "axios";

// Shared axios instance. The baseURL is RELATIVE on purpose: in development
// Vite proxies /api to the backend on :8000, and in production FastAPI serves
// the built frontend itself — same origin either way, so nothing here has to
// know which of the two it is running in, and CORS never enters the picture.
export const api = axios.create({
  baseURL: "",
});
