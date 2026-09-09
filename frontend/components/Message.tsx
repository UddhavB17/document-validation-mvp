export function ErrorMessage({ message }: { message: string }) {
  return (
    <div className="message message--danger" role="alert">
      <MessageIcon kind="danger" />
      <span>{message}</span>
    </div>
  );
}

export function InfoMessage({ message }: { message: string }) {
  return (
    <div className="message message--info" role="status">
      <MessageIcon kind="info" />
      <span>{message}</span>
    </div>
  );
}

export function LoadingMessage({ message = "Loading..." }: { message?: string }) {
  return (
    <div className="message message--loading" role="status" aria-live="polite">
      <span className="message__indicator" aria-hidden="true" />
      <span>{message}</span>
    </div>
  );
}

function MessageIcon({ kind }: { kind: "danger" | "info" }) {
  return (
    <svg className="message__icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
      {kind === "danger" ? (
        <>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.3 3.6 2.9 16.4A2 2 0 0 0 4.6 19.4h14.8a2 2 0 0 0 1.7-3L13.7 3.6a2 2 0 0 0-3.4 0Z" />
        </>
      ) : (
        <>
          <circle cx="12" cy="12" r="8.5" />
          <path strokeLinecap="round" d="M12 10.5v5m0-8h.01" />
        </>
      )}
    </svg>
  );
}
