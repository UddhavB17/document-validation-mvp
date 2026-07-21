export function ErrorMessage({ message }: { message: string }) {
  return <div className="mb-4 rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">{message}</div>;
}

export function InfoMessage({ message }: { message: string }) {
  return <div className="mb-4 rounded border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">{message}</div>;
}

export function LoadingMessage({ message = "Loading..." }: { message?: string }) {
  return <div className="text-sm text-slate-600">{message}</div>;
}
