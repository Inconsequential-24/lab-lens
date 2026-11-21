// Sign-in state. The Google ID token is kept in memory only (never localStorage).
// Real Google Identity Services wiring is not part of this build: without VITE_GOOGLE_CLIENT_ID
// the UI shows a placeholder button; in mock mode a fake token signs in a demo user.
import { useSyncExternalStore } from "react";

export const GOOGLE_CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) ?? "";
const MOCK = import.meta.env.VITE_MOCK === "1";

let token: string | null = MOCK && sessionStorage.getItem("mock_signed_in") === "1" ? "mock-token" : null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function getToken() { return token; }
export const canSignIn = MOCK; // only the mock sign-in works today
export function signIn() {
  if (!MOCK) return;
  token = "mock-token";
  sessionStorage.setItem("mock_signed_in", "1");
  emit();
}
export function signOut() {
  token = null;
  sessionStorage.removeItem("mock_signed_in");
  emit();
}
export function useSignedIn() {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => token !== null);
}
