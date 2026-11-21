export class ApiError extends Error {
  // `body` keeps the full error JSON (e.g. 409 `saved_on` / `overlaps`).
  constructor(public status: number, public reason: string, message: string, public body?: unknown) {
    super(message);
  }
}
