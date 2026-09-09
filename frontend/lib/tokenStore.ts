// Synchronously-updated bearer holder for lib/api.ts.
//
// The hydration race: SessionProvider used to register a new
// `setAuthTokenProvider(() => token)` closure in an effect keyed on token
// state. Child effects run before parent effects, so protected queries
// mounted during hydration read the provider before it was re-registered,
// sent no Authorization header, got 401, and nuked a valid session.
// Reading through this store instead fixes the ordering: writers assign the
// store *before* exposing `authenticated` status, so the getter is correct
// from the first paint with no effect round-trip.

export interface TokenStore {
  getToken: () => string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

export function createTokenStore(): TokenStore {
  let current: string | null = null;
  return {
    getToken: () => current,
    setToken: (token: string) => {
      current = token;
    },
    clearToken: () => {
      current = null;
    },
  };
}
