export class ApiError extends Error {
  constructor(public status: number, public reason: string, message: string) {
    super(message);
  }
}
